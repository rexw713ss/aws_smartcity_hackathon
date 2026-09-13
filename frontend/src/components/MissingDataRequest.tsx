import React, { useId, useRef, useState } from 'react'
import type { CopilotResponse, IntakeOptions, IntakeStart, SourceCandidate, WebCitation } from '../lib/copilot'
import { formatLabel } from '../lib/format'
import { useI18n, type MessageKey } from '../lib/i18n'

/** Everything the chat needs to act on a missing-data request. */
export type DataIntake = {
  acquire: (candidateId: string, submittedBy: string, writeToken: string) => Promise<string>
  acquireLink: (url: string, submittedBy: string, topicHint: string | null, writeToken: string) => Promise<IntakeStart>
  upload: (file: File, submittedBy: string, topicHint: string | null, writeToken: string) => Promise<IntakeStart>
  openReview: (jobId: string, retry: RetryRequest) => void
  options: IntakeOptions | null
  writeToken: string
  setWriteToken: (value: string) => void
}

export type RetryRequest = { question: string; topic: string | null }

type Gap = { key: string; title: string; detail: string | null; metrics: string[] }

// The public copilot has no signed-in reviewer identity. Keep the required
// workflow audit field internal instead of asking the reader to invent one.
const submittedBy = 'youth-compass-web'
const uploadAccept = '.csv,.tsv,.json,.jsonl,.ndjson,.xlsx,.xlsm'
const gapTitles: Record<string, MessageKey> = {
  housing: 'gapHousing',
  public_services: 'gapPublicServices',
}

/** The gaps the backend itself reported: the impact chain's missing capacity
 * links first, otherwise the catalog requirement it could not satisfy. */
const zhLabels: Record<string, string> = {
  education: '教育', employment: '就業', population: '人口',
  employment_count: '就業人數', unemployment_count: '失業人數',
  unemployment_rate: '失業率', population_count: '人口數',
}

function gapsOf(
  response: CopilotResponse,
  t: (key: MessageKey) => string,
  language: string,
): Gap[] {
  const label = (value: string) => language === 'zh-TW' && zhLabels[value]
    ? zhLabels[value]
    : formatLabel(value)
  const impact = response.impact_analysis?.data_gaps ?? []
  if (impact.length) {
    return impact.map(gap => ({
      key: gap.domain,
      title: gapTitles[gap.domain] ? t(gapTitles[gap.domain]) : label(gap.domain),
      detail: gap.reason,
      metrics: gap.required_metrics,
    }))
  }
  const requirement = response.data_requirement
  if (!requirement || (!requirement.metric_codes.length && !requirement.topic_terms.length)) return []
  return [{
    key: 'requirement',
    title: requirement.topic_terms.length
      ? requirement.topic_terms.map(label).join(' · ')
      : t('neededMetrics'),
    detail: requirement.time_expression ? `${t('neededPeriod')}: ${requirement.time_expression}` : null,
    metrics: requirement.metric_codes.map(label),
  }]
}

/** True when an answer stopped for lack of data and can say what it lacks. */
export function requestsData(response: CopilotResponse): boolean {
  if (response.status !== 'acquisition_required' && response.status !== 'insufficient_data') return false
  return response.source_candidates.length > 0 ||
    response.web_citations.length > 0 ||
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
      <span className="candidate-fit">{t('sourceReady')}</span>
    </div>
  )
}

function WebSourceCard({ source }: { source: WebCitation }) {
  const { language, t } = useI18n()
  let host = source.url
  try { host = new URL(source.url).hostname } catch { /* keep the validated URL */ }
  return (
    <div className="source-card web-source-card">
      <strong>
        <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
      </strong>
      <span className="candidate-meta">{host} · {t('webSuggestion')}</span>
      <span className="candidate-fit">{t('sourceFoundBySearch')}</span>
    </div>
  )
}

/** The assistant's turn when it cannot answer: what is missing, what it proposes
 * to fetch, and how the reader can supply the data instead.
 *
 * Every path ends in the same approval-gated ingestion workflow. Configured
 * suggestions submit their candidate id; discovered or pasted links are fetched
 * by the backend only from approved official hosts. */
export default function MissingDataRequest({ response, intake, retry }: {
  response: CopilotResponse
  intake: DataIntake
  retry: RetryRequest
}) {
  const { language, t } = useI18n()
  const ids = useId()
  const gaps = gapsOf(response, t, language)
  const candidates = response.source_candidates
  const webSources = response.web_citations
  const sourceCount = candidates.length + webSources.length
  const requestedTopics = response.impact_analysis?.data_gaps.length
    ? response.impact_analysis.data_gaps.map(gap => gap.domain)
    : response.data_requirement?.topic_terms ?? []
  // A multi-topic gap cannot tell us which subject an uploaded file contains.
  // Forcing the first topic here previously published employment_demo.csv as
  // population and displaced the valid population version. Let mapping infer
  // the file's topic; the reviewer still sees it before approval.
  const topicHint = requestedTopics.length === 1 ? requestedTopics[0] : null

  const [selected, setSelected] = useState(
    candidates[0] ? `candidate:${candidates[0].candidate_id}` :
      webSources[0] ? `web:${webSources[0].citation_id}` : '',
  )
  const [rejected, setRejected] = useState(false)
  const [showOwnData, setShowOwnData] = useState(false)
  const [mode, setMode] = useState<'upload' | 'link'>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [link, setLink] = useState('')
  const [busy, setBusy] = useState<'accept' | 'upload' | 'link' | null>(null)
  const [progressStage, setProgressStage] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ name: string; job: string } | null>(null)
  const ownData = useRef<HTMLElement>(null)

  const chosen = candidates.find(item => `candidate:${item.candidate_id}` === selected)
  const chosenWeb = webSources.find(item => `web:${item.citation_id}` === selected)
  const maxBytes = intake.options?.maxUploadBytes ?? 25 * 1024 * 1024
  const linkHosts = intake.options?.linkHosts ?? []
  const tokenMissing = !!intake.options?.writeTokenRequired && !intake.writeToken.trim()

  const progressKeys: MessageKey[] = [
    'intakeDownloading',
    'intakeInspecting',
    'intakeMapping',
    'intakeQuality',
    'intakeReviewReady',
  ]
  const run = async (kind: 'accept' | 'upload' | 'link', action: () => Promise<{ name: string; job: string }>) => {
    setBusy(kind)
    setError(null)
    setProgressStage(0)
    let shownStage = 0
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
    const timer = window.setInterval(() => {
      shownStage = Math.min(shownStage + 1, progressKeys.length - 2)
      setProgressStage(shownStage)
    }, reducedMotion ? 50 : 650)
    try {
      const completed = await action()
      window.clearInterval(timer)
      for (let stage = shownStage + 1; stage < progressKeys.length; stage += 1) {
        setProgressStage(stage)
        await new Promise(resolve => window.setTimeout(resolve, reducedMotion ? 0 : 280))
      }
      setDone(completed)
      await new Promise(resolve => window.setTimeout(resolve, reducedMotion ? 0 : 450))
      intake.openReview(completed.job, retry)
    } catch (cause) {
      window.clearInterval(timer)
      setError(cause instanceof Error ? cause.message : t('submissionFailed'))
      setProgressStage(null)
    } finally {
      setBusy(null)
    }
  }

  const accept = () => {
    if (chosen) {
      void run('accept', async () => ({
        name: chosen.title,
        job: await intake.acquire(chosen.candidate_id, submittedBy, intake.writeToken),
      }))
    }
    else if (chosenWeb) {
      void run('accept', async () => {
        const started = await intake.acquireLink(
          chosenWeb.url, submittedBy, topicHint, intake.writeToken,
        )
        return { name: chosenWeb.title, job: started.job_id }
      })
    }
  }

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
      const started = await intake.upload(file, submittedBy, topicHint, intake.writeToken)
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
      const started = await intake.acquireLink(url, submittedBy, topicHint, intake.writeToken)
      return { name: started.file_name ?? url, job: started.job_id }
    })
  }

  return (
    <section className="data-request" aria-label={t('missingTitle')}>
      <header>
        <h4>{t('missingTitle')}</h4>
      </header>

      {gaps.length ? (
        <p className="gap-summary">
          <span>{t('neededData')}</span>{' '}
          {gaps.map(gap => gap.title).join(' · ')}
        </p>
      ) : null}

      {intake.options?.writeTokenRequired && !done ? (
        <label className="review-token-field">
          <span>{t('reviewToken')}</span>
          <input
            type="password"
            value={intake.writeToken}
            onChange={event => intake.setWriteToken(event.target.value)}
            autoComplete="off"
            disabled={!!busy}
            placeholder={t('reviewTokenPlaceholder')}
          />
          <small>{t('reviewTokenHelp')}</small>
        </label>
      ) : null}

      {done ? (
        <p className="intake-done" role="status">
          {t('intakeDone', { name: done.name, job: done.job })}
        </p>
      ) : (
        <>
          <section className="request-step" ref={ownData}>
            <h5>{t('sourceMatch')}</h5>
            {!sourceCount ? (
              <p className="request-note">{t('recommendNone')}</p>
            ) : rejected ? (
              <p className="request-note">{t('rejected')}</p>
            ) : (
              <>
                {chosen ? <SourceCard candidate={chosen} /> : null}
                {chosenWeb ? <WebSourceCard source={chosenWeb} /> : null}
                {sourceCount > 1 ? (
                  <details className="other-sources">
                    <summary>{t('otherSources', { count: sourceCount - 1 })}</summary>
                    <ul>
                      {candidates.map(candidate => (
                        <li key={candidate.candidate_id}>
                          <label>
                            <input
                              type="radio"
                              name={`${ids}-candidate`}
                              value={`candidate:${candidate.candidate_id}`}
                              checked={selected === `candidate:${candidate.candidate_id}`}
                              onChange={() => setSelected(`candidate:${candidate.candidate_id}`)}
                              disabled={!!busy}
                            />
                            <span>{candidate.title}</span>
                          </label>
                        </li>
                      ))}
                      {webSources.map(source => (
                        <li key={source.citation_id}>
                          <label>
                            <input
                              type="radio"
                              name={`${ids}-candidate`}
                              value={`web:${source.citation_id}`}
                              checked={selected === `web:${source.citation_id}`}
                              onChange={() => setSelected(`web:${source.citation_id}`)}
                              disabled={!!busy}
                            />
                            <span>{source.title}</span>
                          </label>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </>
            )}

            {busy && progressStage !== null ? (
              <ol className="intake-progress" aria-live="polite">
                {progressKeys.map((key, index) => (
                  <li
                    key={key}
                    data-state={index < progressStage ? 'done' : index === progressStage ? 'active' : 'waiting'}
                  >
                    <i aria-hidden="true" />
                    <span>{t(key)}</span>
                  </li>
                ))}
              </ol>
            ) : null}

            <div className="request-actions">
              {(chosen || chosenWeb) && !rejected ? (
                <>
                  <button type="button" className="primary" onClick={accept} disabled={!!busy || tokenMissing}>
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
                    <button type="submit" className="primary" disabled={!!busy || !file || tokenMissing}>
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
                    <button type="submit" className="primary" disabled={!!busy || !link.trim() || tokenMissing}>
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
