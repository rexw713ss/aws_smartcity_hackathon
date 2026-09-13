import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ChatPanel, { type TopicSwitchPrompt, type Turn } from './components/ChatPanel'
import type { DataIntake, RetryRequest } from './components/MissingDataRequest'
import InsightPanel from './components/InsightPanel'
import MotionProvider from './components/MotionProvider'
import ReviewerWorkspace from './components/ReviewerWorkspace'
import {
  createCopilotClient,
  type CopilotStage,
  type CopilotResponse,
  type DatasetCatalogItem,
  type DistrictOverview,
  type IntakeOptions,
  type ToolCapability,
} from './lib/copilot'
import useNarrowLayout from './lib/useNarrowLayout'
import { I18nProvider, translate, type Language } from './lib/i18n'

// deploy_site.py injects the Function URL at publish time, so one immutable
// frontend build can target each environment without rebuilding.
const apiBase = window.YOUTH_COMPASS_API_BASE ??
  (import.meta.env.VITE_COPILOT_API_BASE as string | undefined) ?? '/api/v1'
const requestTimeoutMs = 90_000
const selectableTopics = ['education', 'employment', 'population', 'others']

const topicAliases: Record<string, string[]> = {
  population: ['population', 'residents', 'dân số', 'dân cư', '人口', '青年人口'],
  employment: ['employment', 'unemployment', 'jobs', 'việc làm', 'thất nghiệp', '就業', '失業'],
  education: ['education', 'schooling', 'học vấn', 'giáo dục', '教育', '學歷'],
  marriage: ['marriage', 'marital status', 'hôn nhân', '婚姻'],
  migration: ['migration', 'immigration', 'di cư', 'nhập cư', '遷徙', '遷入', '遷出'],
  income: ['income', 'earnings', 'thu nhập', '所得', '收入'],
  household_registration: ['household registration', 'hộ khẩu', '戶籍'],
  birth_events: ['births', 'fertility', 'sinh con', 'tỷ lệ sinh', '出生', '生育'],
}

const topicLabel = (topic: string) => topic.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase())
const folded = (value: string) => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase()
const escaped = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function mentionsAlias(question: string, alias: string): number {
  const needle = folded(alias)
  if (/[^\x00-\x7F]/.test(needle)) return question.indexOf(needle)
  const match = new RegExp(`(^|[^a-z0-9])${escaped(needle)}(?=$|[^a-z0-9])`).exec(question)
  return match ? match.index + match[1].length : -1
}

function topicsMentionedBy(question: string, topics: string[]): string[] {
  const haystack = folded(question)
  const found: { topic: string; position: number }[] = []
  for (const topic of topics) {
    let firstPosition = -1
    for (const alias of [topic.replace(/_/g, ' '), ...(topicAliases[topic] ?? [])]) {
      const position = mentionsAlias(haystack, alias)
      if (position >= 0 && (firstPosition < 0 || position < firstPosition)) firstPosition = position
    }
    if (firstPosition >= 0) found.push({ topic, position: firstPosition })
  }
  return found.sort((left, right) => left.position - right.position).map(item => item.topic)
}

function suggestionsFor(topic: string, language: Language, grain: string[]): string[] {
  const label = topicLabel(topic)
  const suggestions = language === 'zh-TW'
    ? [`概覽${label}`, `查看${label}的時間趨勢`, `比較各行政區的${label}`]
    : [`Give me an overview of ${label}`, `Show the ${label} trend over time`, `Compare ${label} across districts`]
  if (grain.some(field => field.toLocaleLowerCase().includes('gender'))) {
    suggestions.push(language === 'zh-TW' ? `按性別比較${label}` : `Compare ${label} by gender`)
  }
  return suggestions
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
  const [insightHistory, setInsightHistory] = useState<{
    id: string
    question: string
    topic: string | null
    response: CopilotResponse
  }[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [streamStage, setStreamStage] = useState<CopilotStage | null>(null)
  const [intakeOptions, setIntakeOptions] = useState<IntakeOptions | null>(null)
  const [writeToken, setWriteToken] = useState('')
  const [activeReviewJob, setActiveReviewJob] = useState<string | null>(() => {
    const jobId = new URLSearchParams(window.location.search).get('review')
    return jobId && /^[-a-zA-Z0-9_]{1,200}$/.test(jobId) ? jobId : null
  })
  const [capabilities, setCapabilities] = useState<ToolCapability[]>([])
  const [datasets, setDatasets] = useState<DatasetCatalogItem[]>([])
  const [catalogLoading, setCatalogLoading] = useState(true)
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null)
  const [topicSwitch, setTopicSwitch] = useState<TopicSwitchPrompt | null>(null)
  const [conversationKey, setConversationKey] = useState(0)
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
  const previousLanguage = useRef(language)
  const insightHistoryRef = useRef(insightHistory)
  const retryAfterPublish = useRef<{ jobId: string; request: RetryRequest } | null>(null)
  const publishedReviewJob = useRef<string | null>(null)

  const client = useMemo(() => {
    try {
      return createCopilotClient(apiBase)
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    document.documentElement.lang = language
    document.title = language === 'zh-TW' ? '新北青策 · 決策助理' : 'New Taipei Youth Policy · Decision Assistant'
    try { localStorage.setItem('youth-compass-language', language) } catch { /* Private storage can be unavailable. */ }
  }, [language])

  useEffect(() => { insightHistoryRef.current = insightHistory }, [insightHistory])

  useEffect(() => {
    if (previousLanguage.current === language) return
    previousLanguage.current = language
    const snapshot = insightHistoryRef.current
    if (!client || !snapshot.length) return

    latest.current += 1
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller
    const activeId = snapshot.find(item => item.response === response)?.id ?? snapshot[snapshot.length - 1]?.id
    setPending(true)
    setStreamStage('planning')

    void (async () => {
      try {
        let localizedSession: string | undefined
        const localized = [] as typeof snapshot
        for (const item of snapshot) {
          const translated = await client.query({
            question: item.question,
            topicHint: item.topic ?? undefined,
            responseLanguage: language,
            minQualityScore: 0.7,
            sessionId: localizedSession,
          }, controller.signal)
          localizedSession = translated.session_id ?? undefined
          localized.push({ ...item, response: translated })
        }
        if (controller.signal.aborted) return
        insightHistoryRef.current = localized
        setInsightHistory(localized)
        const byId = new Map(localized.map(item => [item.id, item.response]))
        setTurns(current => current.map(turn => (
          turn.kind === 'answer' && byId.has(turn.id)
            ? { ...turn, response: byId.get(turn.id)! }
            : turn
        )))
        setResponse(byId.get(activeId ?? '') ?? localized[localized.length - 1]?.response ?? null)
        sessionId.current = localizedSession ?? null
      } catch (cause) {
        if (!controller.signal.aborted) console.error('language refresh failed', cause)
      } finally {
        if (inFlight.current === controller) {
          inFlight.current = null
          setPending(false)
          setStreamStage(null)
        }
      }
    })()
    return () => controller.abort()
  }, [client, language])

  useEffect(() => {
    if (!client) {
      setCatalogLoading(false)
      return
    }
    const controller = new AbortController()
    client
      .intakeOptions(controller.signal)
      .then(setIntakeOptions)
      .catch(cause => {
        // Upload still works without this; only the link hint is lost.
        if (!controller.signal.aborted) console.error('intake options request failed', cause)
      })
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
  const topics = selectableTopics
  const suggestions = useMemo(() => {
    if (!selectedTopic || selectedTopic === 'others') return []
    const dataset = publishedDatasets.find(item => item.topic === selectedTopic)
    return suggestionsFor(selectedTopic, language, dataset?.grain ?? [])
  }, [publishedDatasets, language, selectedTopic])

  useEffect(() => () => inFlight.current?.abort(), [])

  useEffect(() => {
    const url = new URL(window.location.href)
    if (activeReviewJob) url.searchParams.set('review', activeReviewJob)
    else url.searchParams.delete('review')
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
  }, [activeReviewJob])

  const executeQuestion = useCallback(
    async (question: string, topic: string | null) => {
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
      setStreamStage('planning')
      setMobileView('chat')
      setCitationFocus(null)
      const answerId = nextId()

      try {
        const result = await client.queryStream(
          {
            question,
            topicHint: topic ?? undefined,
            responseLanguage: language,
            // The public UI should not silently select barely-passing evidence.
            // The API still supports an explicit lower threshold for reviewer workflows.
            minQualityScore: 0.7,
            sessionId: sessionId.current ?? undefined,
          },
          controller.signal,
          text => {
            if (ticket !== latest.current) return
            setTurns(current => {
              const exists = current.some(turn => turn.id === answerId)
              if (!exists) return [...current, { kind: 'streaming', id: answerId, text }]
              return current.map(turn => turn.id === answerId
                ? { kind: 'streaming' as const, id: answerId, text }
                : turn)
            })
          },
          stage => {
            if (ticket === latest.current) setStreamStage(stage)
          },
        )
        if (ticket !== latest.current) return
        sessionId.current = result.session_id
        setResponse(result)
        setInsightHistory(current => [...current, { id: answerId, question, topic, response: result }])
        setTurns(current => {
          const final = {
            kind: 'answer' as const,
            id: answerId,
            response: result,
            retry: { question, topic },
          }
          return current.some(turn => turn.id === answerId)
            ? current.map(turn => turn.id === answerId ? final : turn)
            : [...current, final]
        })
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
        if (ticket === latest.current) {
          setPending(false)
          setStreamStage(null)
        }
        if (inFlight.current === controller) inFlight.current = null
      }
    },
    [client, language],
  )

  const ask = useCallback((question: string) => {
    const focusedTopic = selectedTopic === 'others' ? null : selectedTopic
    const requestedTopics = topicsMentionedBy(question, topics.filter(topic => topic !== 'others'))
    const requestedTopic = requestedTopics.find(topic => topic !== focusedTopic) ?? null
    if (focusedTopic && requestedTopic) {
      setTopicSwitch({ question, from: focusedTopic, to: requestedTopic })
      return
    }
    const initialTopic = requestedTopics[0] ?? null
    if (!focusedTopic && initialTopic) setSelectedTopic(initialTopic)
    void executeQuestion(question, focusedTopic ?? initialTopic)
  }, [executeQuestion, selectedTopic, topics])

  const acceptTopicSwitch = useCallback(() => {
    if (!topicSwitch) return
    const request = topicSwitch
    setSelectedTopic(request.to)
    setTopicSwitch(null)
    void executeQuestion(request.question, request.to)
  }, [executeQuestion, topicSwitch])

  // Accepting a suggestion, uploading a file, and pasting a link all enter the
  // same approval-gated workflow; none of them publishes anything.
  const intake = useMemo<DataIntake>(() => {
    const unavailable = () => Promise.reject(new Error(t('configInvalid')))
    if (!client) return {
      acquire: unavailable, acquireLink: unavailable, upload: unavailable, options: null,
      openReview: setActiveReviewJob, writeToken, setWriteToken,
    }
    return {
      acquire: async (candidateId, submittedBy, token) => {
        const result = await client.acquire(
          candidateId, submittedBy, token, new AbortController().signal,
        )
        return result.ingestion_job_id
      },
      acquireLink: async (url, submittedBy, topicHint, token) => {
        const result = await client.acquireLink(
          url, submittedBy, topicHint, token, new AbortController().signal,
        )
        return result
      },
      upload: async (file, submittedBy, topicHint, token) => {
        const result = await client.uploadDataset(
          file, submittedBy, topicHint, token, new AbortController().signal,
        )
        return result
      },
      options: intakeOptions,
      openReview: (jobId, retry) => {
        retryAfterPublish.current = { jobId, request: retry }
        publishedReviewJob.current = null
        setActiveReviewJob(jobId)
      },
      writeToken,
      setWriteToken,
    }
  }, [client, intakeOptions, language, writeToken])

  const refreshCatalog = useCallback(async () => {
    if (!client) return
    const controller = new AbortController()
    try {
      setDatasets(await client.datasets(controller.signal))
    } catch {
      // The approved version is durable; a later catalog refresh can recover.
    }
  }, [client])

  const publishedReview = useCallback(async () => {
    await refreshCatalog()
    publishedReviewJob.current = activeReviewJob
  }, [activeReviewJob, refreshCatalog])

  const closeReview = useCallback(() => {
    const jobId = activeReviewJob
    setActiveReviewJob(null)
    if (!jobId || publishedReviewJob.current !== jobId) return
    const pendingRetry = retryAfterPublish.current
    publishedReviewJob.current = null
    retryAfterPublish.current = null
    if (pendingRetry?.jobId === jobId) {
      void executeQuestion(pendingRetry.request.question, pendingRetry.request.topic)
    }
  }, [activeReviewJob, executeQuestion])

  const cancel = useCallback(() => {
    latest.current += 1
    inFlight.current?.abort()
    inFlight.current = null
    setPending(false)
    setStreamStage(null)
  }, [])

  const newConversation = useCallback(() => {
    latest.current += 1
    inFlight.current?.abort()
    inFlight.current = null
    sessionId.current = null
    insightHistoryRef.current = []
    retryAfterPublish.current = null
    publishedReviewJob.current = null
    setTurns([])
    setResponse(null)
    setInsightHistory([])
    setDraft('')
    setPending(false)
    setStreamStage(null)
    setSelectedTopic(null)
    setTopicSwitch(null)
    setCitationFocus(null)
    setMobileView('chat')
    setConversationKey(current => current + 1)
  }, [])

  const showCitation = useCallback((citationId: string, sourceResponse?: CopilotResponse) => {
    if (sourceResponse) setResponse(sourceResponse)
    setCitationFocus({ citationId, requestId: ++citationRequest.current })
    setMobileView('insight')
  }, [])

  const exploreDistrict = useCallback(async (districtCode: string): Promise<DistrictOverview> => {
    if (!client) throw new Error(t('configInvalid'))
    setMobileView('insight')
    const controller = new AbortController()
    // The forecast is optional context: a district without one still gets its overview.
    const [overview, forecast] = await Promise.all([
      client.districtOverview(districtCode, controller.signal),
      client.districtForecast(districtCode, controller.signal).catch(() => null),
    ])
    return { ...overview, forecast }
  }, [client])

  return (
    <I18nProvider language={language}>
    <MotionProvider>
      <div className="app-shell">
        <a className="skip-link" href="#chat">{t('skip')}</a>
        <header className="app-bar">
          <div className="brand">
            <img className="brand-logo" src="/ntpc-logo.png" alt="" aria-hidden="true" />
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
              <select value={language} onChange={event => setLanguage(event.target.value as Language)} aria-label={t('language')} disabled={pending}>
                <option value="zh-TW">{t('traditionalChinese')}</option>
                <option value="en">{t('english')}</option>
              </select>
            </label>
          </div>
        </header>

        {activeReviewJob && client ? (
          <ReviewerWorkspace
            client={client}
            jobId={activeReviewJob}
            writeToken={writeToken}
            setWriteToken={setWriteToken}
            tokenRequired={!!intakeOptions?.writeTokenRequired}
            onClose={closeReview}
            onPublished={publishedReview}
          />
        ) : (
        <>
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
              stage={streamStage}
              suggestions={suggestions}
              topics={topics}
              selectedTopic={selectedTopic}
              onSelectTopic={topic => {
                setSelectedTopic(topic)
                setTopicSwitch(null)
              }}
              topicSwitch={topicSwitch}
              onAcceptTopicSwitch={acceptTopicSwitch}
              onRejectTopicSwitch={() => setTopicSwitch(null)}
              catalogLoading={catalogLoading}
              draft={draft}
              onDraft={setDraft}
              onSubmit={ask}
              onCancel={cancel}
              onNewConversation={newConversation}
              onCitation={showCitation}
              intake={intake}
            />
          ) : null}
          {!narrow || mobileView === 'insight' ? (
            <InsightPanel
              key={conversationKey}
              response={response}
              history={insightHistory}
              pending={pending}
              onExploreDistrict={exploreDistrict}
              citationFocus={citationFocus}
              onCitation={showCitation}
            />
          ) : null}
        </main>
        </>
        )}
      </div>
    </MotionProvider>
    </I18nProvider>
  )
}
