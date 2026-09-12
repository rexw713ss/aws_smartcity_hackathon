import React, { useState } from 'react'
import type { SourceCandidate } from '../lib/copilot'
import { useI18n } from '../lib/i18n'

const hostOf = (url: string): string => {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

/** The assistant's own turn in the conversation: it asks for the one thing it
 * is missing, in the thread where the question was asked.
 *
 * The reviewer submits a configured candidateId, never a URL. Nothing is
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
  const { t } = useI18n()
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
      setError(cause instanceof Error ? cause.message : t('submissionFailed'))
    }
  }

  return (
    <section className="acquire" aria-label={t('sourceCandidatesLabel')}>
      <header>
        <p className="acquire-ask">{t('askForSource')}</p>
        <p>{t('sourceCandidatesIntro')}</p>
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
                      : t('periodNotStated')}
                    {candidate.license ? ` · ${candidate.license}` : ` · ${t('licenceNotStated')}`}
                  </span>
                  <code>{candidate.candidate_id}</code>
                </span>
              </label>
            </li>
          ))}
        </ul>

        {started ? (
          <p className="acquire-done" role="status">
            {t('submitted', { candidate: started.candidateId, job: started.jobId })}
          </p>
        ) : (
          <div className="acquire-actions">
            <label className="acquire-field">
              {t('reviewerIdentity')}
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
              {busy ? t('submitting') : t('submitSource')}
            </button>
          </div>
        )}
        {error ? <p className="acquire-error" role="alert">{error}</p> : null}
      </form>
    </section>
  )
}
