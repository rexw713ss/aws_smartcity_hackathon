import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ChatPanel, { Turn } from './components/ChatPanel'
import InsightPanel from './components/InsightPanel'
import MotionProvider from './components/MotionProvider'
import { createCopilotClient, type CopilotResponse, type ToolCapability } from './lib/copilot'
import useNarrowLayout from './lib/useNarrowLayout'

const apiBase = (import.meta.env.VITE_COPILOT_API_BASE as string | undefined) ?? '/api/v1'
const requestTimeoutMs = 30_000

// Phrasings the offline DeterministicQueryDecomposer actually routes; see
// evals/agent-routing.jsonl. With the Bedrock decomposer enabled, paraphrases
// route too, but these chips must work in the offline demo path as well.
const suggestions = [
  'Compare population trend from 2023 to 2025',
  'Where should I buy a home?',
  'Where should we place an EV charging station?',
  'Which youth datasets are published in the catalog?',
]

let turnSequence = 0
const nextId = (): string => `turn-${++turnSequence}`

export default function App() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [response, setResponse] = useState<CopilotResponse | null>(null)
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [acquiring, setAcquiring] = useState(false)
  const [capabilities, setCapabilities] = useState<ToolCapability[]>([])
  const [mobileView, setMobileView] = useState<'chat' | 'insight'>('chat')
  const narrow = useNarrowLayout()
  // Ventriloc is a light system; dark is a derived opt-in, not the default.
  const [darkMode, setDarkMode] = useState(() => {
    try {
      return localStorage.getItem('youth-compass-theme') === 'dark'
    } catch {
      return false
    }
  })

  const inFlight = useRef<AbortController | null>(null)
  // Only the newest request may write state; a late reply cannot replace a newer answer.
  const latest = useRef(0)

  const client = useMemo(() => {
    try {
      return createCopilotClient(apiBase)
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode)
    try {
      localStorage.setItem('youth-compass-theme', darkMode ? 'dark' : 'light')
    } catch { /* Private storage can be unavailable. */ }
  }, [darkMode])

  useEffect(() => {
    if (!client) return
    const controller = new AbortController()
    client
      .capabilities(controller.signal)
      .then(setCapabilities)
      .catch(cause => {
        setCapabilities([])
        // Swallowing this hid a real contract mismatch; surface it instead.
        if (!controller.signal.aborted) console.error('capabilities request failed', cause)
      })
    return () => controller.abort()
  }, [client])

  useEffect(() => () => inFlight.current?.abort(), [])

  const ask = useCallback(
    async (question: string) => {
      if (!client) {
        setTurns(current => [
          ...current,
          { kind: 'error', id: nextId(), text: 'VITE_COPILOT_API_BASE is invalid. Check the frontend environment settings.' },
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

      try {
        const result = await client.query({ question }, controller.signal)
        if (ticket !== latest.current) return
        setResponse(result)
        setTurns(current => [...current, { kind: 'answer', id: nextId(), response: result }])
        if (result.visualizations.length) setMobileView('insight')
      } catch (cause) {
        if (ticket !== latest.current) return
        if (controller.signal.aborted) {
          // A user cancel needs no error turn; a timeout does.
          if (!cause || (cause as Error).name === 'AbortError') {
            setTurns(current => [...current, { kind: 'error', id: nextId(), text: 'The request was cancelled or timed out after 30 seconds.' }])
          }
          return
        }
        setTurns(current => [
          ...current,
          { kind: 'error', id: nextId(), text: cause instanceof Error ? cause.message : 'An unexpected error occurred.' },
        ])
      } finally {
        window.clearTimeout(timer)
        if (ticket === latest.current) setPending(false)
        if (inFlight.current === controller) inFlight.current = null
      }
    },
    [client],
  )

  const acquire = useCallback(
    async (candidateId: string, submittedBy: string): Promise<string> => {
      if (!client) throw new Error('The frontend API configuration is invalid.')
      const controller = new AbortController()
      setAcquiring(true)
      try {
        const started = await client.acquire(candidateId, submittedBy, controller.signal)
        return started.ingestion_job_id
      } finally {
        setAcquiring(false)
      }
    },
    [client],
  )

  const cancel = useCallback(() => {
    latest.current += 1
    inFlight.current?.abort()
    inFlight.current = null
    setPending(false)
  }, [])

  return (
    <MotionProvider>
      <div className="app-shell">
        <a className="skip-link" href="#chat">Skip to conversation</a>
        <header className="app-bar">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true" />
            <span>
              <strong>Youth Compass</strong>
              <em>New Taipei · decision assistant</em>
            </span>
          </div>
          <div className="app-bar-actions">
            {capabilities.length ? (
              <details className="capability-menu">
                <summary>Tools ({capabilities.length})</summary>
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
            <button
              type="button"
              className="ghost"
              aria-pressed={darkMode}
              onClick={() => setDarkMode(value => !value)}
            >
              {darkMode ? 'Light' : 'Dark'}
            </button>
          </div>
        </header>

        {narrow ? (
        <nav className="mobile-switch" aria-label="Switch view">
          <button type="button" className={mobileView === 'chat' ? 'is-active' : undefined} onClick={() => setMobileView('chat')}>
            Conversation
          </button>
          <button type="button" className={mobileView === 'insight' ? 'is-active' : undefined} onClick={() => setMobileView('insight')}>
            Charts & evidence
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
              draft={draft}
              onDraft={setDraft}
              onSubmit={ask}
              onCancel={cancel}
            />
          ) : null}
          {!narrow || mobileView === 'insight' ? (
            <InsightPanel
              response={response}
              pending={pending}
              onAcquire={acquire}
              acquiring={acquiring}
              onAsk={ask}
            />
          ) : null}
        </main>
      </div>
    </MotionProvider>
  )
}
