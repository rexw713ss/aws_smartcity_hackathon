import React, { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CopilotResponse,
  DataLimitations,
  DatasetCatalogItem,
  RegistrationBasis,
} from '../lib/copilot'
import {
  formatEntityLabel,
  formatLabel,
  formatQuality,
  localizedStatus,
} from '../lib/format'
import { useI18n } from '../lib/i18n'
import SourceCandidates from './SourceCandidates'
import { useDashboardMotion } from './MotionProvider'

/** Reader-facing name for the population a metric counts. The caveat text
 * itself comes from the backend note, so this is only a short label. */
/** The backend's own audit of how far the evidence can be trusted: how old each
 * source is, how much of the city it covers, and which population it counts.
 * Every figure here is computed by the backend from the evidence it used. */
function Limitations({ limitations }: { limitations: DataLimitations }) {
  const { language, t } = useI18n()
  const basisLabels: Record<RegistrationBasis, string> = {
    registered_household: t('basisRegistered'), resident: t('basisResident'), unknown: t('basisUnknown'),
  }
  const { freshness, coverage, notes } = limitations
  if (!freshness.length && !coverage && !notes.length) return null
  return (
    <details className="turn-detail data-limits">
      <summary>{t('dataLimitations')}</summary>

      <p className="limit-basis">{basisLabels[limitations.registration_basis]}</p>

      {freshness.length ? (
        <ul className="limit-sources">
          {freshness.map(item => (
            <li key={item.citation_id}>
              <code>{item.citation_id}</code> {formatLabel(item.dataset_id)} @ {item.dataset_version}
              <span className="limit-age">
                {item.age_days === 0 ? t('publishedToday') : t('publishedDaysAgo', { count: item.age_days })}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {coverage ? (
        <p className="limit-coverage">
          {t('coverage', { observed: coverage.observed_entity_count, expected: coverage.expected_entity_count })}
          {coverage.missing_entity_names.length
            ? ` ${t('noEvidenceFor', { names: coverage.missing_entity_names.join(', ') })}`
            : ` ${t('noGaps')}`}
          {coverage.unmapped_entity_ids.length
            ? ` ${t('outsideDistricts', { names: coverage.unmapped_entity_ids.map(formatEntityLabel).join(', ') })}`
            : ''}
        </p>
      ) : null}

      {notes.length ? (
        <ul>
          {notes.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      ) : null}
    </details>
  )
}

function CitedAnswer({
  response,
  text,
  onCitation,
}: {
  response: CopilotResponse
  /** The part of the answer revealed so far; the whole answer once typed. */
  text: string
  onCitation: (citationId: string) => void
}) {
  const { t } = useI18n()
  const citations = new Map(
    response.citations.map((citation, index) => [citation.citation_id, { citation, number: index + 1 }]),
  )
  const citedText = (text: string, keyPrefix: string) =>
    text.split(/(\[data-\d+\])/g).map((part, index) => {
        const match = /^\[(data-\d+)\]$/.exec(part)
        const source = match ? citations.get(match[1]) : undefined
        if (!source) return <React.Fragment key={`${keyPrefix}-${index}`}>{part}</React.Fragment>
        return (
          <sup className="inline-citation" key={`${keyPrefix}-${source.citation.citation_id}-${index}`}>
            <button
              type="button"
              onClick={() => onCitation(source.citation.citation_id)}
              aria-label={t('showSource', { number: source.number, name: formatLabel(source.citation.dataset_id) })}
              title={`${formatLabel(source.citation.dataset_id)} · ${source.citation.dataset_version}`}
            >
              [{source.number}]
            </button>
          </sup>
        )
      })
  const blocks = text.trim().split(/\n{2,}/)

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
  | { kind: 'answer'; id: string; response: CopilotResponse }
  | { kind: 'error'; id: string; text: string }

/** Reveal the answer a character at a time, the way the assistant would speak
 * it. Only the newest turn types; re-reading an older one is not a performance,
 * and a reader who asked for reduced motion gets the finished text at once. */
function useTypedLength(text: string, live: boolean): number {
  const { reducedMotion } = useDashboardMotion()
  const animate = live && !reducedMotion
  const [count, setCount] = useState(() => (animate ? 0 : text.length))

  useEffect(() => {
    if (!animate) {
      setCount(text.length)
      return
    }
    setCount(0)
    let frame = 0
    let started: number | null = null
    const step = (now: number) => {
      if (started === null) started = now
      // ~55 characters a second: quick enough to follow, slow enough to see.
      const shown = Math.min(text.length, Math.round((now - started) / 18))
      setCount(shown)
      if (shown < text.length) frame = window.requestAnimationFrame(step)
    }
    frame = window.requestAnimationFrame(step)
    return () => window.cancelAnimationFrame(frame)
  }, [text, animate])

  return count
}

function Answer({
  response,
  live,
  onCitation,
  onTyped,
  onGrow,
}: {
  response: CopilotResponse
  live: boolean
  onCitation: (citationId: string) => void
  onTyped: () => void
  onGrow: () => void
}) {
  const { language, t } = useI18n()
  const status = localizedStatus(language, response.status)
  const typed = useTypedLength(response.answer, live)
  const done = typed >= response.answer.length

  // The pane follows the text as it appears, and the caveats that land when it
  // finishes are the last thing that moves.
  useEffect(() => { onGrow() }, [typed, done, onGrow])
  useEffect(() => { if (done) onTyped() }, [done, onTyped])

  return (
    <div className="turn answer" data-status={response.status} data-typing={done ? undefined : 'true'}>
      <span className={`status-pill tone-${status.tone}`}>{status.label}</span>
      {/* Citation tokens become controlled buttons; all other model text remains escaped text. */}
      <CitedAnswer response={response} text={response.answer.slice(0, typed)} onCitation={onCitation} />
      {done ? <p className="status-detail">{status.detail}</p> : null}

      {/* The caveats belong to a finished statement, so they arrive with the
          last character rather than sitting under a half-typed sentence. */}
      {done && response.assumptions.length ? (
        <details className="turn-detail">
          <summary>{t('assumptions')} ({response.assumptions.length})</summary>
          <ul>
            {response.assumptions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </details>
      ) : null}

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

      {done && response.limitations ? <Limitations limitations={response.limitations} /> : null}

      {done && response.status === 'answered' && !response.citations.length ? (
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
  onAcquire,
  acquiring,
  onGrow,
}: {
  response: CopilotResponse
  live: boolean
  onCitation: (citationId: string) => void
  onAcquire: (candidateId: string, submittedBy: string) => Promise<string>
  acquiring: boolean
  onGrow: () => void
}) {
  const { t } = useI18n()
  const { reducedMotion } = useDashboardMotion()
  const staged = live && !reducedMotion
  const [answered, setAnswered] = useState(!staged)
  const [asked, setAsked] = useState(!staged)
  const asks = response.source_candidates.length > 0

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
          <SourceCandidates
            candidates={response.source_candidates}
            onAcquire={onAcquire}
            busy={acquiring}
          />
        </div>
      ) : null}
    </>
  )
}

const thinkingKeys = [
  'thinkingReading', 'thinkingRetrieving', 'thinkingComputing', 'thinkingChecking',
] as const

/** A spinner and a line that moves through what the backend is actually doing:
 * reading the catalog, retrieving, calculating, checking the evidence. */
function Thinking() {
  const { t } = useI18n()
  const { reducedMotion } = useDashboardMotion()
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (reducedMotion) return
    const timer = window.setInterval(
      () => setStep(value => (value + 1) % thinkingKeys.length),
      2200,
    )
    return () => window.clearInterval(timer)
  }, [reducedMotion])

  return (
    <div className="turn pending">
      <span className="spinner" aria-hidden="true" />
      {/* One stable announcement; the cycling line is decoration. */}
      <span className="sr-only" aria-live="polite">{t('pending')}</span>
      <span className="thinking-label" aria-hidden="true">{t(thinkingKeys[step])}</span>
    </div>
  )
}

export default function ChatPanel({
  turns,
  pending,
  suggestions,
  datasets,
  catalogLoading,
  draft,
  onDraft,
  onSubmit,
  onCancel,
  onCitation,
  onAcquire,
  acquiring,
}: {
  turns: Turn[]
  pending: boolean
  suggestions: string[]
  datasets: DatasetCatalogItem[]
  catalogLoading: boolean
  draft: string
  onDraft: (value: string) => void
  onSubmit: (question: string) => void
  onCancel: () => void
  onCitation: (citationId: string) => void
  onAcquire: (candidateId: string, submittedBy: string) => Promise<string>
  acquiring: boolean
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
      <div className="chat-scroll" ref={scroller}>
        {turns.length === 0 ? (
          <div className="chat-intro">
            <h2>{t('introTitle')}</h2>
            <p>{t('intro')}</p>
            <section className="dataset-guide" aria-label={t('availableDatasets')}>
              <header>
                <h3>{t('availableDatasets')}</h3>
                <span>{t('publishedOnly')}</span>
              </header>
              {catalogLoading ? (
                <p>{t('loadingCatalog')}</p>
              ) : datasets.length ? (
                <ul>
                  {datasets.map(item => (
                    <li key={item.datasetId}>
                      <div>
                        <strong>{formatLabel(item.datasetId)}</strong>
                        <span>{formatLabel(item.topic)}</span>
                      </div>
                      <p>
                        {t('breakdowns')}: {item.grain.map(formatLabel).join(' · ')}
                      </p>
                      <small>{t('quality')} {formatQuality(item.qualityScore, language)}</small>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>{t('noDatasets')}</p>
              )}
            </section>
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
          </div>
        ) : (
          turns.map(turn =>
            turn.kind === 'question' ? (
              <div className="turn question" key={turn.id}>
                <p>{turn.text}</p>
              </div>
            ) : turn.kind === 'answer' ? (
              <AnswerTurn
                key={turn.id}
                response={turn.response}
                // Only the newest answer performs; the rest are already said.
                live={turn.id === turns[turns.length - 1]?.id}
                onCitation={onCitation}
                onAcquire={onAcquire}
                acquiring={acquiring}
                onGrow={stickToBottom}
              />
            ) : (
              <div className="turn error" key={turn.id} role="alert">
                <p>{turn.text}</p>
              </div>
            ),
          )
        )}

        {pending ? <Thinking /> : null}
      </div>

      <form
        className="composer"
        onSubmit={event => {
          event.preventDefault()
          send()
        }}
      >
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
