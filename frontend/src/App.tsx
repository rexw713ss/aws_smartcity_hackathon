import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ChatPanel, { Turn } from './components/ChatPanel'
import InsightPanel from './components/InsightPanel'
import MotionProvider from './components/MotionProvider'
import {
  createCopilotClient,
  type CopilotResponse,
  type DatasetCatalogItem,
  type DistrictOverview,
  type ToolCapability,
} from './lib/copilot'
import useNarrowLayout from './lib/useNarrowLayout'
import { I18nProvider, translate, type Language } from './lib/i18n'

const apiBase = (import.meta.env.VITE_COPILOT_API_BASE as string | undefined) ?? '/api/v1'
const requestTimeoutMs = 30_000

// Phrasings the offline DeterministicQueryDecomposer actually routes; see
// evals/agent-routing.jsonl. With the Bedrock decomposer enabled, paraphrases
// route too, but these chips must work in the offline demo path as well.
const baseSuggestions: Record<Language, string[]> = {
  'zh-TW': [
    '如果 2030 年前林口新增 2,000 名青年人口，應投資哪些基礎設施？',
    '比較 2023 至 2025 年的人口趨勢',
    '哪個行政區最適合青年居住？',
    '電動車充電站應設置在哪裡？',
    '資料目錄中有哪些已發布的青年資料集？',
  ],
  en: [
    'If 2,000 young people move to Linkou before 2030, what infrastructure should we invest in?',
    'Compare population trend from 2023 to 2025',
    'Which district is best suited for young people to live in?',
    'Where should we place an EV charging station?',
    'Which youth datasets are published in the catalog?',
  ],
}

let turnSequence = 0
const nextId = (): string => `turn-${++turnSequence}`

export default function App() {
  const [language, setLanguage] = useState<Language>(() => {
    try { return localStorage.getItem('youth-compass-language') === 'en' ? 'en' : 'zh-TW' }
    catch { return 'zh-TW' }
  })
  const t = (key: Parameters<typeof translate>[1], replacements?: Parameters<typeof translate>[2]) => translate(language, key, replacements)
  const [turns, setTurns] = useState<Turn[]>([])
  const [response, setResponse] = useState<CopilotResponse | null>(null)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [acquiring, setAcquiring] = useState(false)
  const [capabilities, setCapabilities] = useState<ToolCapability[]>([])
  const [datasets, setDatasets] = useState<DatasetCatalogItem[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [mobileView, setMobileView] = useState<'chat' | 'insight'>('chat')
  const [citationFocus, setCitationFocus] = useState<{
    citationId: string
    requestId: number
  } | null>(null)
  const narrow = useNarrowLayout()

  const inFlight = useRef<AbortController | null>(null)
  // Only the newest request may write state; a late reply cannot replace a newer answer.
  const latest = useRef(0)
  // The backend stores only bounded structured scope under this opaque ID.
  const sessionId = useRef<string | null>(null)
  const citationRequest = useRef(0)

  const client = useMemo(() => {
    try {
      return createCopilotClient(apiBase)
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    document.documentElement.lang = language
    document.title = language === 'zh-TW' ? '新北青年政策羅盤 · 決策助理' : 'Youth Compass · Decision Assistant'
    try { localStorage.setItem('youth-compass-language', language) } catch { /* Private storage can be unavailable. */ }
  }, [language])

  useEffect(() => {
    if (!client) {
      setCatalogLoading(false)
      return
    }
    const controller = new AbortController()
    client
      .capabilities(controller.signal)
      .then(setCapabilities)
      .catch(cause => {
        setCapabilities([])
        // Swallowing this hid a real contract mismatch; surface it instead.
        if (!controller.signal.aborted) console.error('capabilities request failed', cause)
      })
    client
      .datasets(controller.signal)
      .then(setDatasets)
      .catch(cause => {
        setDatasets([])
        if (!controller.signal.aborted) console.error('dataset catalog request failed', cause)
      })
      .finally(() => {
        if (!controller.signal.aborted) setCatalogLoading(false)
      })
    return () => controller.abort()
  }, [client])

  const publishedDatasets = useMemo(
    () => datasets.filter(item => item.status === 'published'),
    [datasets],
  )
  const suggestions = useMemo(() => {
    const topicPrompts = publishedDatasets
      .map(item => item.topic.replace(/_/g, ' '))
      .filter((topic, index, topics) => topics.indexOf(topic) === index)
      .flatMap(topic => [
        `What published data is available for ${topic}?`,
        `Compare ${topic} trends by district`,
      ])
    return [...baseSuggestions[language], ...topicPrompts].filter(
      (item, index, items) => items.indexOf(item) === index,
    ).slice(0, 8)
  }, [publishedDatasets, language])

  useEffect(() => () => inFlight.current?.abort(), [])

  const ask = useCallback(
    async (question: string) => {
      if (!client) {
        setTurns(current => [
          ...current,
          { kind: 'error', id: nextId(), text: t('configInvalid') },
        ])
        return
      }
      inFlight.current?.abort()
      const controller = new AbortController()
      inFlight.current = controller
      const ticket = ++latest.current
      const timer = window.setTimeout(() => controller.abort(), requestTimeoutMs)

      setTurns(current => [...current, { kind: 'question', id: nextId(), text: question }])
      setDraft('')
      setPending(true)
      setMobileView('chat')
      setCitationFocus(null)

      try {
        const result = await client.query(
          {
            question,
            // The public UI should not silently select barely-passing evidence.
            // The API still supports an explicit lower threshold for reviewer workflows.
            minQualityScore: 0.7,
            sessionId: sessionId.current ?? undefined,
          },
          controller.signal,
        )
        if (ticket !== latest.current) return
        sessionId.current = result.session_id
        setResponse(result)
        setTurns(current => [...current, { kind: 'answer', id: nextId(), response: result }])
        if (result.visualizations.length) setMobileView('insight')
      } catch (cause) {
        if (ticket !== latest.current) return
        if (controller.signal.aborted) {
          // A user cancel needs no error turn; a timeout does.
          if (!cause || (cause as Error).name === 'AbortError') {
            setTurns(current => [...current, { kind: 'error', id: nextId(), text: t('timeout') }])
          }
          return
        }
        setTurns(current => [
          ...current,
          { kind: 'error', id: nextId(), text: cause instanceof Error ? cause.message : t('unexpected') },
        ])
      } finally {
        window.clearTimeout(timer)
        if (ticket === latest.current) setPending(false)
        if (inFlight.current === controller) inFlight.current = null
      }
    },
    [client, language],
  )

  const acquire = useCallback(
    async (candidateId: string, submittedBy: string): Promise<string> => {
      if (!client) throw new Error(t('configInvalid'))
      const controller = new AbortController()
      setAcquiring(true)
      try {
        const started = await client.acquire(candidateId, submittedBy, controller.signal)
        return started.ingestion_job_id
      } finally {
        setAcquiring(false)
      }
    },
    [client, language],
  )

  const cancel = useCallback(() => {
    latest.current += 1
    inFlight.current?.abort()
    inFlight.current = null
    setPending(false)
  }, [])

  const showCitation = useCallback((citationId: string) => {
    setCitationFocus({ citationId, requestId: ++citationRequest.current })
    setMobileView('insight')
  }, [])

  const exploreDistrict = useCallback(async (districtCode: string): Promise<DistrictOverview> => {
    if (!client) throw new Error(t('configInvalid'))
    setMobileView('insight')
    const controller = new AbortController()
    return client.districtOverview(districtCode, controller.signal)
  }, [client])

  return (
    <I18nProvider language={language}>
    <MotionProvider>
      <div className="app-shell">
        <a className="skip-link" href="#chat">{t('skip')}</a>
        <header className="app-bar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <span>
              <strong>{t('brand')}</strong>
              <em>{t('tagline')}</em>
            </span>
          </div>
          <div className="app-bar-actions">
            {capabilities.length ? (
              <details className="capability-menu">
                <summary>{t('tools')} ({capabilities.length})</summary>
                <ul>
                  {capabilities.map(item => (
                    <li key={`${item.name}-${item.operation}`}>
                      <code>{item.name}</code>
                      <span>{item.description}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
            <label className="language-picker">
              <span className="sr-only">{t('language')}</span>
              <select value={language} onChange={event => setLanguage(event.target.value as Language)} aria-label={t('language')}>
                <option value="zh-TW">{t('traditionalChinese')}</option>
                <option value="en">{t('english')}</option>
              </select>
            </label>
          </div>
        </header>

        {narrow ? (
        <nav className="mobile-switch" aria-label={t('switchView')}>
          <button type="button" className={mobileView === 'chat' ? 'is-active' : undefined} onClick={() => setMobileView('chat')}>
            {t('conversation')}
          </button>
          <button type="button" className={mobileView === 'insight' ? 'is-active' : undefined} onClick={() => setMobileView('insight')}>
            {t('chartsEvidence')}
            {response?.visualizations.length ? <span className="tab-count">{response.visualizations.length}</span> : null}
          </button>
        </nav>
        ) : null}

        <main className="workspace" data-mobile-view={mobileView} id="chat">
          {/* Narrow viewports unmount the inactive pane: a display:none pane would
              mount its charts at 0x0, which Recharts cannot lay out. */}
          {!narrow || mobileView === 'chat' ? (
            <ChatPanel
              turns={turns}
              pending={pending}
              suggestions={suggestions}
              datasets={publishedDatasets}
              catalogLoading={catalogLoading}
              draft={draft}
              onDraft={setDraft}
              onSubmit={ask}
              onCancel={cancel}
              onCitation={showCitation}
              onAcquire={acquire}
              acquiring={acquiring}
            />
          ) : null}
          {!narrow || mobileView === 'insight' ? (
            <InsightPanel
              response={response}
              pending={pending}
              onExploreDistrict={exploreDistrict}
              citationFocus={citationFocus}
            />
          ) : null}
        </main>
      </div>
    </MotionProvider>
    </I18nProvider>
  )
}
