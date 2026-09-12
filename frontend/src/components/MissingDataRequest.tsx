import React, { useId, useRef, useState } from 'react'
import type { CopilotResponse, IntakeOptions, IntakeStart, SourceCandidate } from '../lib/copilot'
import { formatLabel } from '../lib/format'
import { useI18n, type MessageKey } from '../lib/i18n'

/** Everything the chat needs to act on a missing-data request. */
export type DataIntake = {
  acquire: (candidateId: string, submittedBy: string) => Promise<string>
  acquireLink: (url: string, submittedBy: string, topicHint: string | null) => Promise<IntakeStart>
  upload: (file: File, submittedBy: string, topicHint: string | null) => Promise<IntakeStart>
  options: IntakeOptions | null
}

type Gap = { key: string; title: string; detail: string | null; metrics: string[] }

// The public copilot has no signed-in reviewer identity. Keep the required
// workflow audit field internal instead of asking the reader to invent one.
const submittedBy = 'youth-compass-web'
const uploadAccept = '.csv,.tsv,.json,.jsonl,.ndjson,.xlsx,.xlsm'
const gapTitles: Record<string, MessageKey> = {
  housing: 'gapHousing',
  transport: 'gapTransport',
  public_services: 'gapPublicServices',
}

/** The gaps the backend itself reported: the impact chain's missing capacity
 * links first, otherwise the catalog requirement it could not satisfy. */
function gapsOf(response: CopilotResponse, t: (key: MessageKey) => string): Gap[] {
  const impact = response.impact_analysis?.data_gaps ?? []
  if (impact.length) {
    return impact.map(gap => ({
      key: gap.domain,
      title: gapTitles[gap.domain] ? t(gapTitles[gap.domain]) : formatLabel(gap.domain),
      detail: gap.reason,
      metrics: gap.required_metrics,
    }))
  }
  const requirement = response.data_requirement
  if (!requirement || (!requirement.metric_codes.length && !requirement.topic_terms.length)) return []
  return [{
    key: 'requirement',
    title: requirement.topic_terms.length
      ? requirement.topic_terms.map(formatLabel).join(' · ')
      : t('neededMetrics'),
    detail: requirement.time_expression ? `${t('neededPeriod')}: ${requirement.time_expression}` : null,
    metrics: requirement.metric_codes,
  }]
}

/** True when an answer stopped for lack of data and can say what it lacks. */
export function requestsData(response: CopilotResponse): boolean {
  if (response.status !== 'acquisition_required' && response.status !== 'insufficient_data') return false
  return response.source_candidates.length > 0 ||
    (response.impact_analysis?.data_gaps.length ?? 0) > 0 ||
    !!response.data_requirement?.metric_codes.length ||
    !!response.data_requirement?.topic_terms.length
}

const megabytes = (bytes: number) => `${Math.round(bytes / (1024 * 1024))} MB`
const fileSize = (bytes: number) => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : megabytes(bytes)

function SourceCard({ candidate }: { candidate: SourceCandidate }) {
  const { t } = useI18n()
  let host = candidate.download_url
  try { host = new URL(candidate.download_url).hostname } catch { /* keep the raw value */ }
  return (
    <div className="source-card">
      <strong>{candidate.title}</strong>
      <span className="candidate-meta">
        {candidate.publisher} · {candidate.source_format.toUpperCase()} · {host}
      </span>
      <span className="candidate-meta">
        {candidate.period_start || candidate.period_end
          ? `${candidate.period_start ?? '—'} – ${candidate.period_end ?? '—'}`
          : t('periodNotStated')}
        {candidate.license ? ` · ${candidate.license}` : ` · ${t('licenceNotStated')}`}
      </span>
    </div>
  )
}

/** The assistant's turn when it cannot answer: what is missing, what it proposes
 * to fetch, and how the reader can supply the data instead.
 *
 * Every path ends in the same approval-gated ingestion workflow. Accepting a
 * suggestion submits a configured candidate id, never a URL; a pasted link is
 * fetched by the backend only from approved official hosts. */
export default function MissingDataRequest({ response, intake }: {
  response: CopilotResponse
  intake: DataIntake
}) {
  const { t } = useI18n()
  const ids = useId()
  const gaps = gapsOf(response, t)
  const candidates = response.source_candidates
  const topicHint = response.impact_analysis?.data_gaps[0]?.domain ??
    response.data_requirement?.topic_terms[0] ?? null

  const [selected, setSelected] = useState(candidates[0]?.candidate_id ?? '')
  const [rejected, setRejected] = useState(false)
  const [showOwnData, setShowOwnData] = useState(false)
  const [mode, setMode] = useState<'upload' | 'link'>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [link, setLink] = useState('')
  const [busy, setBusy] = useState<'accept' | 'upload' | 'link' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ name: string; job: string } | null>(null)
  const ownData = useRef<HTMLElement>(null)

  const chosen = candidates.find(item => item.candidate_id === selected) ?? candidates[0]
  const maxBytes = intake.options?.maxUploadBytes ?? 25 * 1024 * 1024
  const linkHosts = intake.options?.linkHosts ?? []

  const run = async (kind: 'accept' | 'upload' | 'link', action: () => Promise<{ name: string; job: string }>) => {
    setBusy(kind)
    setError(null)
    try {
      setDone(await action())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('submissionFailed'))
    } finally {
      setBusy(null)
    }
  }

  const accept = () => chosen && run('accept', async () => ({
    name: chosen.title,
    job: await intake.acquire(chosen.candidate_id, submittedBy),
  }))

  const reject = () => {
    setRejected(true)
    setError(null)
  }

  const toggleOwnData = () => {
    setShowOwnData(current => !current)
    setError(null)
    if (!showOwnData) {
      window.requestAnimationFrame(() => ownData.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
    }
  }

  const submitUpload = (event: React.FormEvent) => {
    event.preventDefault()
    if (!file) return
    if (file.size > maxBytes) {
      setError(t('fileTooLarge', { size: megabytes(maxBytes) }))
      return
    }
    void run('upload', async () => {
      const started = await intake.upload(file, submittedBy, topicHint)
      return { name: started.file_name ?? file.name, job: started.job_id }
    })
  }

  const submitLink = (event: React.FormEvent) => {
    event.preventDefault()
    const url = link.trim()
    if (!/^https:\/\/\S+$/i.test(url)) {
      setError(t('linkInvalid'))
      return
    }
    void run('link', async () => {
      const started = await intake.acquireLink(url, submittedBy, topicHint)
      return { name: started.file_name ?? url, job: started.job_id }
    })
  }

  return (
    <section className="data-request" aria-label={t('missingTitle')}>
      <header>
        <h4>{t('missingTitle')}</h4>
        <p>{t('missingIntro')}</p>
      </header>

      {gaps.length ? (
        <ul className="gap-list">
          {gaps.map(gap => (
            <li key={gap.key}>
              <strong>{gap.title}</strong>
              {gap.detail ? <p>{gap.detail}</p> : null}
              {gap.metrics.length ? (
                <div className="gap-metrics" aria-label={t('neededMetrics')}>
                  {gap.metrics.map(metric => <span key={metric}>{formatLabel(metric)}</span>)}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {done ? (
        <p className="intake-done" role="status">
          {t('intakeDone', { name: done.name, job: done.job })}
        </p>
      ) : (
        <>
          <section className="request-step" ref={ownData}>
            <h5>{t('recommendTitle')}</h5>
            {!candidates.length ? (
              <p className="request-note">{t('recommendNone')}</p>
            ) : rejected ? (
              <p className="request-note">{t('rejected')}</p>
            ) : (
              <>
                <p className="request-lead">{t('recommendLead')}</p>
                {chosen ? <SourceCard candidate={chosen} /> : null}
                {candidates.length > 1 ? (
                  <details className="other-sources">
                    <summary>{t('otherSources', { count: candidates.length - 1 })}</summary>
                    <ul>
                      {candidates.map(candidate => (
                        <li key={candidate.candidate_id}>
                          <label>
                            <input
                              type="radio"
                              name={`${ids}-candidate`}
                              value={candidate.candidate_id}
                              checked={selected === candidate.candidate_id}
                              onChange={() => setSelected(candidate.candidate_id)}
                              disabled={!!busy}
                            />
                            <span>{candidate.title}</span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
                <p className="request-note">{t('recommendProcess')}</p>
              </>
            )}

            <div className="request-actions">
              {chosen && !rejected ? (
                <>
                  <button type="button" className="primary" onClick={accept} disabled={!!busy}>
                    {busy === 'accept' ? t('working') : t('accept')}
                  </button>
                  <button type="button" className="ghost" onClick={reject} disabled={!!busy}>
                    {t('reject')}
                  </button>
                </>
              ) : null}
              <button
                type="button"
                className="ghost"
                onClick={toggleOwnData}
                disabled={!!busy}
                aria-expanded={showOwnData}
                aria-controls={`${ids}-own-data`}
              >
                {t('provideOwn')}
              </button>
            </div>

            {showOwnData ? (
              <div className="own-data-panel" id={`${ids}-own-data`}>
                <h5>{t('ownTitle')}</h5>
                <div className="intake-modes" role="tablist" aria-label={t('ownTitle')}>
                  {(['upload', 'link'] as const).map(item => (
                    <button
                      key={item}
                      type="button"
                      role="tab"
                      aria-selected={mode === item}
                      className={mode === item ? 'is-active' : undefined}
                      onClick={() => { setMode(item); setError(null) }}
                    >
                      {item === 'upload' ? t('uploadTab') : t('linkTab')}
                    </button>
                  ))}
                </div>

                {mode === 'upload' ? (
                  <form className="intake-form" onSubmit={submitUpload}>
                    <label className="file-pick">
                      <input
                        type="file"
                        accept={uploadAccept}
                        onChange={event => { setFile(event.target.files?.[0] ?? null); setError(null) }}
                        disabled={!!busy}
                      />
                      <span>{file ? `${file.name} · ${fileSize(file.size)}` : t('chooseFile', { size: megabytes(maxBytes) })}</span>
                    </label>
                    <button type="submit" className="primary" disabled={!!busy || !file}>
                      {busy === 'upload' ? t('working') : t('uploadSubmit')}
                    </button>
                  </form>
                ) : linkHosts.length ? (
                  <form className="intake-form" onSubmit={submitLink}>
                    <input
                      type="url"
                      inputMode="url"
                      value={link}
                      onChange={event => { setLink(event.target.value); setError(null) }}
                      placeholder={`https://${linkHosts[0]}/…`}
                      aria-label={t('linkTab')}
                      maxLength={2000}
                      disabled={!!busy}
                    />
                    <button type="submit" className="primary" disabled={!!busy || !link.trim()}>
                      {busy === 'link' ? t('working') : t('linkSubmit')}
                    </button>
                    <p className="request-note">{t('linkHosts', { hosts: linkHosts.join(', ') })}</p>
                  </form>
                ) : (
                  <p className="request-note">{t('linkDisabled')}</p>
                )}
              </div>
            ) : null}
          </section>

          {error ? <p className="request-error" role="alert">{error}</p> : null}
        </>
      )}
    </section>
  )
}
