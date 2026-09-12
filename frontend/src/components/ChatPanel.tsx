import React, { useEffect, useRef } from 'react'
import type { CopilotResponse } from '../lib/copilot'
import { statusDetail, statusLabels } from '../lib/format'

export type Turn =
  | { kind: 'question'; id: string; text: string }
  | { kind: 'answer'; id: string; response: CopilotResponse }
  | { kind: 'error'; id: string; text: string }

function Answer({ response }: { response: CopilotResponse }) {
  const status = statusLabels[response.status]
  return (
    <div className="turn answer" data-status={response.status}>
      <span className={`status-pill tone-${status.tone}`}>{status.label}</span>
      {/* Plain text only. A model-authored string is never treated as markup. */}
      <p className="answer-text">{response.answer}</p>
      <p className="status-detail">{statusDetail[response.status]}</p>

      {response.assumptions.length ? (
        <details className="turn-detail">
          <summary>Assumptions ({response.assumptions.length})</summary>
          <ul>
            {response.assumptions.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {response.warnings.length ? (
        <div className="turn-warnings" role="note">
          <strong>Limitations</strong>
          <ul>
            {response.warnings.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {response.status === 'answered' && !response.citations.length ? (
        <p className="turn-flag">This answer carries no citation. Confirm with the backend before acting on it.</p>
      ) : null}
    </div>
  )
}

export default function ChatPanel({
  turns,
  pending,
  suggestions,
  draft,
  onDraft,
  onSubmit,
  onCancel,
}: {
  turns: Turn[]
  pending: boolean
  suggestions: string[]
  draft: string
  onDraft: (value: string) => void
  onSubmit: (question: string) => void
  onCancel: () => void
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const element = scroller.current
    if (element) element.scrollTop = element.scrollHeight
  }, [turns.length, pending])

  const send = () => {
    const question = draft.trim()
    if (!question || pending) return
    onSubmit(question)
  }

  return (
    <section className="chat-panel" aria-label="Policy decision assistant">
      <div className="chat-scroll" ref={scroller}>
        {turns.length === 0 ? (
          <div className="chat-intro">
            <h2>New Taipei Youth Compass</h2>
            <p>
              Every answer is drawn from approved, published datasets. The system performs retrieval,
              filtering, and calculation; the language model only interprets the question and states the
              result. It cannot invent a figure, pick a dataset, or write a query.
            </p>
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
              <Answer key={turn.id} response={turn.response} />
            ) : (
              <div className="turn error" key={turn.id} role="alert">
                <p>{turn.text}</p>
              </div>
            ),
          )
        )}

        {pending ? (
          <div className="turn pending" aria-live="polite">
            <span className="dots" aria-hidden="true"><i /><i /><i /></span>
            Retrieving published data and calculating…
          </div>
        ) : null}
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
          placeholder="e.g. Compare the youth population trend by district from 2023 to 2025"
          aria-label="Question"
        />
        <div className="composer-actions">
          <span className="composer-hint">Enter to send · Shift+Enter for a new line</span>
          {pending ? (
            <button type="button" className="ghost" onClick={onCancel}>
              Cancel
            </button>
          ) : (
            <button type="submit" className="primary" disabled={!draft.trim()}>
              Send
            </button>
          )}
        </div>
      </form>
    </section>
  )
}
