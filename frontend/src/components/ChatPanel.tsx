import React, { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CopilotResponse,
  CopilotStage,
  EvidenceCitation,
  WebCitation,
} from '../lib/copilot'
import {
  formatLabel,
  formatProseYears,
  localizedStatus,
} from '../lib/format'
import { useI18n } from '../lib/i18n'
import MissingDataRequest, { requestsData, type DataIntake, type RetryRequest } from './MissingDataRequest'
import { useDashboardMotion } from './MotionProvider'

function CitedAnswer({
  response,
  text,
  onCitation,
}: {
  response: CopilotResponse
  /** The part of the answer revealed so far; the whole answer once typed. */
  text: string
  onCitation: (citationId: string, sourceResponse?: CopilotResponse) => void
}) {
  const { language, t } = useI18n()
  type CitationTarget =
    | { kind: 'data'; citation: EvidenceCitation; number: number }
    | { kind: 'web'; citation: WebCitation; number: number }
  const citations = new Map<string, CitationTarget>([
    ...response.citations.map((citation, index) => [citation.citation_id, { kind: 'data' as const, citation, number: index + 1 }] as const),
    ...response.web_citations.map((citation, index) => [citation.citation_id, { kind: 'web' as const, citation, number: response.citations.length + index + 1 }] as const),
  ])
  const citedText = (text: string, keyPrefix: string) =>
    text.split(/(\[(?:data|web)-\d+\])/g).map((part, index) => {
        const match = /^\[((?:data|web)-\d+)\]$/.exec(part)
        const source = match ? citations.get(match[1]) : undefined
        if (!source) return <React.Fragment key={`${keyPrefix}-${index}`}>{part}</React.Fragment>
        if (source.kind === 'web') {
          return (
            <sup className="inline-citation" key={`${keyPrefix}-${source.citation.citation_id}-${index}`}>
              <a href={source.citation.url} target="_blank" rel="noreferrer"
                aria-label={t('openWebSource', { number: source.number, name: source.citation.title })}
                title={source.citation.title}>[{source.number}]</a>
            </sup>
          )
        }
        return (
          <sup className="inline-citation" key={`${keyPrefix}-${source.citation.citation_id}-${index}`}>
            <button
              type="button"
              onClick={() => onCitation(source.citation.citation_id, response)}
              aria-label={t('showSource', { number: source.number, name: formatLabel(source.citation.dataset_id) })}
              title={`${formatLabel(source.citation.dataset_id)} · ${source.citation.dataset_version}`}
            >
              [{source.number}]
            </button>
          </sup>
        )
      })
  const blocks = formatProseYears(text, language).trim().split(/\n{2,}/)

  return (
    <div className="answer-text">
      {blocks.map((block, blockIndex) => {
        const lines = block.split('\n').filter(Boolean)
        if (lines.length && lines.every(line => line.startsWith('- '))) {
          return (
            <ul key={blockIndex}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>{citedText(line.slice(2), `${blockIndex}-${lineIndex}`)}</li>
              ))}
            </ul>
          )
        }
        return <p key={blockIndex}>{citedText(block, String(blockIndex))}</p>
      })}
    </div>
  )
}

export type Turn =
  | { kind: 'question'; id: string; text: string }
  | { kind: 'streaming'; id: string; text: string }
  | { kind: 'answer'; id: string; response: CopilotResponse; retry: RetryRequest }
  | { kind: 'error'; id: string; text: string }

export type TopicSwitchPrompt = { question: string; from: string; to: string }

function Answer({
  response,
  live,
  onCitation,
  onTyped,
  onGrow,
}: {
  response: CopilotResponse
  live: boolean
  onCitation: (citationId: string, sourceResponse?: CopilotResponse) => void
  onTyped: () => void
  onGrow: () => void
}) {
  const { language, t } = useI18n()
  const status = localizedStatus(language, response.status)
  // The network stream already revealed this answer. Never replay a simulated
  // typewriter animation after the validated final envelope arrives.
  void live
  const typed = response.answer.length
  const done = true

  // The pane follows the text as it appears, and the caveats that land when it
  // finishes are the last thing that moves.
  useEffect(() => { onGrow() }, [typed, done, onGrow])
  useEffect(() => { if (done) onTyped() }, [done, onTyped])

  return (
    <div className="turn answer" data-status={response.status} data-typing={done ? undefined : 'true'}>
      {/* Citation tokens become controlled buttons; all other model text remains escaped text. */}
      <CitedAnswer response={response} text={response.answer.slice(0, typed)} onCitation={onCitation} />
      {done ? <p className="status-detail">{status.detail}</p> : null}

      {/* The caveats belong to a finished statement, so they arrive with the
          last character rather than sitting under a half-typed sentence. */}
      {done && response.warnings.length ? (
        <div className="turn-warnings" role="note">
          <strong>{t('limitations')}</strong>
          <ul>
            {response.warnings.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {done && response.assumptions.length ? (
        <details className="turn-detail answer-assumptions">
          <summary>{t('assumptions')} ({response.assumptions.length})</summary>
          <ul>
            {response.assumptions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {done && response.status === 'answered' && !response.citations.length && !response.web_citations.length ? (
        <p className="turn-flag">{t('noCitationWarning')}</p>
      ) : null}
    </div>
  )
}

/** One answer, and — when the assistant is missing data — the request it makes
 * back to the reader as a turn of its own.
 *
 * Missing data is a question, so it is asked in the thread rather than in the
 * insight pane the reader may never open. It waits for the answer to finish and
 * for the stage direction that says what the assistant did in between, so the
 * exchange reads as two turns instead of one wall of text.
 */
function AnswerTurn({
  response,
  live,
  onCitation,
  intake,
  retry,
  onGrow,
}: {
  response: CopilotResponse
  live: boolean
  onCitation: (citationId: string, sourceResponse?: CopilotResponse) => void
  intake: DataIntake
  retry: RetryRequest
  onGrow: () => void
}) {
  const { t } = useI18n()
  const { reducedMotion } = useDashboardMotion()
  const staged = live && !reducedMotion
  const [answered, setAnswered] = useState(!staged)
  const [asked, setAsked] = useState(!staged)
  const asks = requestsData(response)

  useEffect(() => {
    if (!asks || !answered || asked) return
    const timer = window.setTimeout(() => setAsked(true), 900)
    return () => window.clearTimeout(timer)
  }, [asks, answered, asked])

  useEffect(() => { onGrow() }, [answered, asked, onGrow])

  const onTyped = useCallback(() => setAnswered(true), [])

  return (
    <>
      <Answer
        response={response}
        live={live}
        onCitation={onCitation}
        onTyped={onTyped}
        onGrow={onGrow}
      />
      {asks && answered ? (
        <p className="turn-aside">{t('asideSourceSearch')}</p>
      ) : null}
      {asks && asked ? (
        <div className="turn answer follow-up">
          <MissingDataRequest response={response} intake={intake} retry={retry} />
        </div>
      ) : null}
    </>
  )
}

const stageKeys: Record<CopilotStage, 'stagePlanning' | 'stageRouting' | 'stageRetrieval' | 'stageAnalysis' | 'stageComposing'> = {
  planning: 'stagePlanning',
  routing: 'stageRouting',
  retrieval: 'stageRetrieval',
  analysis: 'stageAnalysis',
  composing: 'stageComposing',
}

/** A spinner labelled with the stage the backend is actually executing. */
function Thinking({ stage }: { stage: CopilotStage | null }) {
  const { t } = useI18n()

  return (
    <div className="turn pending" data-stage={stage ?? 'waiting'}>
      <span className="agent-orbit" aria-hidden="true">
        <span className="agent-core" />
        <span className="agent-satellite" />
      </span>
      {/* One stable announcement; the cycling line is decoration. */}
      <span className="sr-only" aria-live="polite">{t('pending')}</span>
      <span className="thinking-copy" aria-hidden="true">
        <span className="thinking-label" key={stage ?? 'waiting'}>
          {t(stage ? stageKeys[stage] : 'pending')}
        </span>
        <span className="activity-lines">
          <i /><i /><i />
        </span>
      </span>
    </div>
  )
}

export default function ChatPanel({
  turns,
  pending,
  stage,
  suggestions,
  topics,
  selectedTopic,
  onSelectTopic,
  topicSwitch,
  onAcceptTopicSwitch,
  onRejectTopicSwitch,
  catalogLoading,
  draft,
  onDraft,
  onSubmit,
  onCancel,
  onNewConversation,
  onCitation,
  intake,
}: {
  turns: Turn[]
  pending: boolean
  stage: CopilotStage | null
  suggestions: string[]
  topics: string[]
  selectedTopic: string | null
  onSelectTopic: (topic: string | null) => void
  topicSwitch: TopicSwitchPrompt | null
  onAcceptTopicSwitch: () => void
  onRejectTopicSwitch: () => void
  catalogLoading: boolean
  draft: string
  onDraft: (value: string) => void
  onSubmit: (question: string) => void
  onCancel: () => void
  onNewConversation: () => void
  onCitation: (citationId: string, sourceResponse?: CopilotResponse) => void
  intake: DataIntake
}) {
  const { language, t } = useI18n()
  const scroller = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)

  // Typing, the stage direction, and the follow-up each grow the thread, so the
  // pane is pinned to the bottom by whatever moved rather than by turn count.
  const stickToBottom = useCallback(() => {
    const element = scroller.current
    if (element) element.scrollTop = element.scrollHeight
  }, [])

  useEffect(() => { stickToBottom() }, [turns.length, pending, stickToBottom])

  const send = () => {
    const question = draft.trim()
    if (!question || pending) return
    onSubmit(question)
  }

  return (
    <section className="chat-panel" aria-label={t('assistantLabel')}>
      <header className="chat-toolbar">
        <button type="button" className="ghost" onClick={onNewConversation} disabled={!turns.length && !draft.trim()}>
          <span aria-hidden="true">＋</span>
          {t('newConversation')}
        </button>
      </header>
      <div className="chat-scroll" ref={scroller}>
        {turns.length === 0 ? (
          <div className="chat-intro">
            <h2>{t('introTitle')}</h2>
            <p>{t('intro')}</p>
            <section className="topic-guide" aria-label={t('topic')}>
              <h3>{catalogLoading ? t('loadingCatalog') : t('selectTopic')}</h3>
              <div className="topic-options" role="radiogroup" aria-label={t('topic')}>
                {topics.map(topic => (
                  <button
                    key={topic}
                    type="button"
                    role="radio"
                    aria-checked={selectedTopic === topic}
                    className={selectedTopic === topic ? 'is-selected' : undefined}
                    onClick={() => onSelectTopic(topic)}
                    disabled={catalogLoading}
                  >
                    {topic === 'others' ? t('otherTopics') : formatLabel(topic)}
                  </button>
                ))}
              </div>
            </section>
            {selectedTopic ? (
              <section className="topic-suggestions" aria-label={t('tryAsking')}>
                <h3 className="suggestion-heading">{t('tryAsking')}</h3>
                <ul className="suggestion-list">
                  {suggestions.map(item => (
                    <li key={item}>
                      <button type="button" onClick={() => onSubmit(item)} disabled={pending}>
                        {item}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        ) : (
          turns.map(turn =>
            turn.kind === 'question' ? (
              <div className="turn question" key={turn.id}>
                <p>{turn.text}</p>
              </div>
            ) : turn.kind === 'streaming' ? (
              <div className="turn answer streaming-answer" key={turn.id} aria-live="polite">
                <div className="answer-text"><p>{formatProseYears(turn.text, language)}</p></div>
              </div>
            ) : turn.kind === 'answer' ? (
              <AnswerTurn
                key={turn.id}
                response={turn.response}
                // Only the newest answer performs; the rest are already said.
                live={turn.id === turns[turns.length - 1]?.id}
                onCitation={onCitation}
                intake={intake}
                retry={turn.retry}
                onGrow={stickToBottom}
              />
            ) : (
              <div className="turn error" key={turn.id} role="alert">
                <p>{turn.text}</p>
              </div>
            ),
          )
        )}

        {topicSwitch ? (
          <div className="turn topic-switch" role="alert">
            <p>{t('confirmTopicSwitch', {
              from: formatLabel(topicSwitch.from),
              to: formatLabel(topicSwitch.to),
            })}</p>
            <div>
              <button type="button" className="primary" onClick={onAcceptTopicSwitch}>{t('switchTopic')}</button>
              <button type="button" className="ghost" onClick={onRejectTopicSwitch}>{t('keepTopic')}</button>
            </div>
          </div>
        ) : null}

        {pending && turns[turns.length - 1]?.kind !== 'streaming' ? <Thinking stage={stage} /> : null}
      </div>

      <form
        className="composer"
        onSubmit={event => {
          event.preventDefault()
          send()
        }}
      >
        {turns.length ? (
          <label className="composer-topic" htmlFor="composer-topic">
            <span>{t('topic')}</span>
            <select
              id="composer-topic"
              value={selectedTopic ?? ''}
              onChange={event => onSelectTopic(event.target.value || null)}
              disabled={pending || catalogLoading}
            >
              <option value="">{t('selectTopic')}</option>
              {topics.map(topic => (
                <option key={topic} value={topic}>
                  {topic === 'others' ? t('otherTopics') : formatLabel(topic)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <textarea
          ref={composer}
          value={draft}
          onChange={event => onDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              send()
            }
          }}
          rows={2}
          maxLength={2000}
          placeholder={t('questionPlaceholder')}
          aria-label={t('question')}
        />
        <div className="composer-actions">
          <span className="composer-hint">{t('composerHint')}</span>
          {pending ? (
            <button type="button" className="ghost" onClick={onCancel}>
              {t('cancel')}
            </button>
          ) : (
            <button type="submit" className="primary" disabled={!draft.trim()}>
              {t('send')}
            </button>
          )}
        </div>
      </form>
    </section>
  )
}
