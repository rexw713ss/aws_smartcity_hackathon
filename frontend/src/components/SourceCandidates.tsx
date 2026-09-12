import React, { useState } from 'react'
import type { SourceCandidate } from '../lib/copilot'

const hostOf = (url: string): string => {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

/** The reviewer submits a configured candidateId, never a URL. Nothing is
 * fetched or published from here: the snapshot enters the approval-gated
 * ingestion workflow and still needs mapping and quality review. */
export default function SourceCandidates({
  candidates,
  onAcquire,
  busy,
}: {
  candidates: SourceCandidate[]
  onAcquire: (candidateId: string, submittedBy: string) => Promise<string>
  busy: boolean
}) {
  const [selected, setSelected] = useState<string>(candidates[0]?.candidate_id ?? '')
  const [reviewer, setReviewer] = useState('')
  const [started, setStarted] = useState<{ jobId: string; candidateId: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      const jobId = await onAcquire(selected, reviewer.trim())
      setStarted({ jobId, candidateId: selected })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Submission failed. Try again.')
    }
  }

  return (
    <section className="acquire" aria-label="Available source candidates">
      <header>
        <h3>Source candidates</h3>
        <p>
          The catalog is missing the data this question needs. These sources are pre-configured in the
          connector allowlist. A submitted snapshot goes through exactly the same mapping, quality, and
          approval steps as a manual upload.
        </p>
      </header>

      <form onSubmit={submit}>
        <ul className="candidate-list">
          {candidates.map(candidate => (
            <li key={candidate.candidate_id}>
              <label>
                <input
                  type="radio"
                  name="candidate"
                  value={candidate.candidate_id}
                  checked={selected === candidate.candidate_id}
                  onChange={() => setSelected(candidate.candidate_id)}
                  disabled={busy || !!started}
                />
                <span className="candidate-body">
                  <strong>{candidate.title}</strong>
                  <span className="candidate-meta">
                    {candidate.publisher} · {candidate.source_format.toUpperCase()} · {hostOf(candidate.download_url)}
                  </span>
                  <span className="candidate-meta">
                    {candidate.period_start || candidate.period_end
                      ? `${candidate.period_start ?? '—'} to ${candidate.period_end ?? '—'}`
                      : 'Period not stated'}
                    {candidate.license ? ` · ${candidate.license}` : ' · licence not stated'}
                  </span>
                  <code>{candidate.candidate_id}</code>
                </span>
              </label>
            </li>
          ))}
        </ul>

        {started ? (
          <p className="acquire-done" role="status">
            Submitted <code>{started.candidateId}</code>. Ingestion job <code>{started.jobId}</code> is
            awaiting approval. Review the field mapping and quality report before approving publication.
          </p>
        ) : (
          <div className="acquire-actions">
            <label className="acquire-field">
              Reviewer identity
              <input
                type="text"
                value={reviewer}
                onChange={event => setReviewer(event.target.value)}
                placeholder="reviewer@example.gov.tw"
                autoComplete="off"
                maxLength={256}
                required
                disabled={busy}
              />
            </label>
            <button type="submit" className="primary" disabled={busy || !selected || !reviewer.trim()}>
              {busy ? 'Submitting…' : 'Fetch snapshot and submit for review'}
            </button>
          </div>
        )}
        {error ? <p className="acquire-error" role="alert">{error}</p> : null}
      </form>
    </section>
  )
}
