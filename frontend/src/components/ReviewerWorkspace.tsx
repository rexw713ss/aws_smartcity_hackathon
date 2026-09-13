import React, { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  CopilotClient,
  IngestionJob,
  MappingAnalysis,
  MappingSamplePreview,
} from '../lib/copilot'
import { formatLabel, formatQuality } from '../lib/format'
import { useI18n } from '../lib/i18n'

const defaultReviewerIdentity = 'steward@newtaipei.gov.tw'

function Confidence({ value }: { value: number }) {
  const { language, t } = useI18n()
  const tone = value >= 0.95 ? 'high' : value >= 0.75 ? 'medium' : 'low'
  return (
    <span className={`confidence-badge confidence-${tone}`}>
      {t('reviewConfidence')} {formatQuality(value, language)}
    </span>
  )
}

function canonicalText(values: Record<string, string | number | boolean | null>): string {
  const entries = Object.entries(values)
  if (!entries.length) return '—'
  return entries.map(([key, value]) => `${formatLabel(key)}: ${String(value ?? '—')}`).join(' · ')
}

export default function ReviewerWorkspace({
  client,
  jobId,
  writeToken,
  setWriteToken,
  tokenRequired,
  onClose,
  onPublished,
}: {
  client: CopilotClient
  jobId: string
  writeToken: string
  setWriteToken: (value: string) => void
  tokenRequired: boolean
  onClose: () => void
  onPublished: () => void | Promise<void>
}) {
  const { language, t } = useI18n()
  const [job, setJob] = useState<IngestionJob | null>(null)
  const [mapping, setMapping] = useState<MappingAnalysis | null>(null)
  const [preview, setPreview] = useState<MappingSamplePreview[]>([])
  const [reviewerIdentity, setReviewerIdentity] = useState(defaultReviewerIdentity)
  const [comment, setComment] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (signal: AbortSignal) => {
    const nextJob = await client.ingestionJob(jobId, signal)
    if (nextJob.status === 'awaiting_approval') {
      const [nextMapping, nextPreview] = await Promise.all([
        client.mappingAnalysis(jobId, signal),
        client.mappingPreview(jobId, signal),
      ])
      setMapping(nextMapping)
      setPreview(nextPreview)
    }
    // Commit the status only after its reviewer data is ready. Otherwise the
    // polling effect cleans up on the status change and can abort these reads.
    setJob(nextJob)
  }, [client, jobId])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    load(controller.signal)
      .catch(cause => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : t('reviewLoadFailed'))
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [load, language])

  useEffect(() => {
    if (!job || !['pending', 'running'].includes(job.status)) return
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      void load(controller.signal).catch(() => undefined)
    }, 1_500)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [job, load])

  const profileByName = useMemo(
    () => new Map(mapping?.profile.columns.map(column => [column.name, column]) ?? []),
    [mapping],
  )
  const previewBySource = useMemo(
    () => new Map(preview.map(item => [item.sourceColumn, item])),
    [preview],
  )
  const issues = mapping ? [
    ...mapping.profile.warnings.map(item => ({ ...item, blocking: false })),
    ...mapping.proposal.warnings.map(message => ({ code: 'MAPPING_WARNING', message, severity: 'warning', field: null, blocking: false })),
    ...mapping.validation.issues,
  ] : []
  const canApprove = job?.status === 'awaiting_approval' && !!mapping?.validation.valid &&
    !mapping.validation.issues.some(issue => issue.blocking) &&
    !!reviewerIdentity.trim() &&
    (!tokenRequired || !!writeToken.trim())
  const outcomeLabel = job?.status === 'published' ? t('outcomePublished') :
    job?.status === 'rejected' ? t('outcomeRejected') :
      job?.status === 'quarantined' ? t('outcomeQuarantined') :
        job?.status === 'failed' ? t('outcomeFailed') : formatLabel(job?.status ?? '')

  const decide = async (decision: 'approve' | 'reject') => {
    setBusy(decision)
    setError(null)
    const controller = new AbortController()
    try {
      const settled = await client.decideIngestion(
        jobId, decision, reviewerIdentity.trim(), comment.trim(), writeToken, controller.signal,
      )
      setJob(settled)
      if (settled.status === 'published') await onPublished()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('reviewDecisionFailed'))
    } finally {
      setBusy(null)
    }
  }

  return (
    <main className="review-workspace" id="review">
      <header className="review-head">
        <div>
          <span className="review-kicker">{t('reviewKicker')}</span>
          <h1>{t('reviewTitle')}</h1>
          <p>{t('reviewSubtitle')}</p>
        </div>
        <button type="button" className="ghost" onClick={onClose}>{t('backToAssistant')}</button>
      </header>

      {loading ? <p className="review-loading">{t('reviewLoading')}</p> : null}
      {error ? <p className="review-error" role="alert">{error}</p> : null}

      {job ? (
        <section className="review-job-bar" aria-label={t('reviewJob')}>
          <div><span>{t('reviewJob')}</span><code>{job.jobId}</code></div>
          <div><span>{t('reviewStatus')}</span><strong>{formatLabel(job.status)}</strong></div>
          <div><span>{t('reviewDataset')}</span><strong>{job.datasetId ? formatLabel(job.datasetId) : '—'}</strong></div>
          {job.qualityScore !== null ? <Confidence value={job.qualityScore} /> : null}
        </section>
      ) : null}

      {mapping ? (
        <>
          <section className="review-summary">
            <article><span>{t('reviewFile')}</span><strong>{mapping.profile.file_name}</strong><small>{mapping.profile.file_format.toUpperCase()}</small></article>
            <article><span>{t('reviewRows')}</span><strong>{mapping.profile.row_count.toLocaleString()}</strong><small>{t('reviewColumns', { count: mapping.profile.column_count })}</small></article>
            <article><span>{t('reviewTopic')}</span><strong>{formatLabel(mapping.proposal.topic)}</strong><small>{formatLabel(mapping.proposal.dataset_role)}</small></article>
            <article><span>{t('reviewGrain')}</span><strong>{mapping.proposal.grain.dimensions.length}</strong><small>{mapping.proposal.grain.dimensions.map(formatLabel).join(' · ')}</small></article>
          </section>

          <section className="review-section">
            <div className="review-section-head">
              <div><h2>{t('mappingTitle')}</h2><p>{t('mappingSubtitle')}</p></div>
              <Confidence value={mapping.proposal.overall_confidence} />
            </div>
            <div className="mapping-table-wrap">
              <table className="mapping-table">
                <thead><tr><th>{t('mappingSource')}</th><th>{t('mappingTarget')}</th><th>{t('mappingTransform')}</th><th>{t('mappingConfidence')}</th></tr></thead>
                <tbody>
                  {mapping.proposal.columns.map(item => (
                    <tr key={`${item.source_column}-${item.target_field}`}>
                      <td><strong>{item.source_column}</strong><small>{formatLabel(profileByName.get(item.source_column)?.inferred_type ?? '')}</small></td>
                      <td><code>{item.target_field}</code></td>
                      <td>{formatLabel(item.transformation)}</td>
                      <td><Confidence value={item.confidence} /></td>
                    </tr>
                  ))}
                  {mapping.proposal.metrics.map(item => (
                    <tr key={`${item.source_column}-${item.metric_code}`}>
                      <td><strong>{item.source_column}</strong><small>{t('mappingMetric')}</small></td>
                      <td><code>{item.metric_code}</code></td>
                      <td>{formatLabel(item.aggregation_method)} · {item.unit_code ?? t('mappingUnitMissing')}</td>
                      <td><Confidence value={item.confidence} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="review-section">
            <div className="review-section-head"><div><h2>{t('previewTitle')}</h2><p>{t('previewSubtitle')}</p></div></div>
            <div className="preview-grid">
              {mapping.proposal.columns.map(item => {
                const samples = previewBySource.get(item.source_column)?.samples ?? []
                return (
                  <article className="preview-card" key={item.source_column}>
                    <header><strong>{item.source_column}</strong><span>→</span><code>{item.target_field}</code></header>
                    {samples.length ? samples.map((sample, index) => (
                      <div className="preview-row" key={`${sample.source}-${index}`}>
                        <span>{sample.source}</span>
                        <i aria-hidden="true">→</i>
                        <strong className={sample.error ? 'preview-invalid' : undefined}>
                          {sample.error ?? canonicalText(sample.canonical)}
                        </strong>
                      </div>
                    )) : <p>{t('previewNone')}</p>}
                  </article>
                )
              })}
            </div>
          </section>

          <section className="review-section review-validation">
            <div className="review-section-head">
              <div><h2>{t('validationTitle')}</h2><p>{mapping.validation.valid ? t('validationPassed') : t('validationBlocked')}</p></div>
              <span className={`validation-badge ${mapping.validation.valid ? 'is-valid' : 'is-blocked'}`}>
                {mapping.validation.valid ? t('valid') : t('blocked')}
              </span>
            </div>
            {issues.length ? <ul>{issues.map((issue, index) => (
              <li key={`${issue.code}-${index}`} className={issue.blocking ? 'is-blocking' : undefined}>
                <strong>{formatLabel(issue.code)}</strong><span>{issue.message}</span>
              </li>
            ))}</ul> : <p className="review-clean">{t('validationClean')}</p>}
          </section>

          {job?.status === 'awaiting_approval' ? (
            <section className="review-decision">
              <div><h2>{t('decisionTitle')}</h2><p>{t('decisionSubtitle')}</p></div>
              <label><span>{t('reviewerIdentity')}</span><input type="email" value={reviewerIdentity} onChange={event => setReviewerIdentity(event.target.value)} autoComplete="email" required /></label>
              {tokenRequired ? (
                <label><span>{t('reviewToken')}</span><input type="password" value={writeToken} onChange={event => setWriteToken(event.target.value)} autoComplete="off" /></label>
              ) : null}
              <label className="review-note"><span>{t('reviewNote')}</span><textarea value={comment} onChange={event => setComment(event.target.value)} maxLength={2000} rows={3} placeholder={t('reviewNotePlaceholder')} /></label>
              <div className="review-actions">
                <button type="button" className="primary" disabled={!canApprove || !!busy} onClick={() => void decide('approve')}>
                  {busy === 'approve' ? t('working') : t('approvePublish')}
                </button>
                <button type="button" className="ghost danger" disabled={!!busy || !reviewerIdentity.trim() || (tokenRequired && !writeToken.trim())} onClick={() => void decide('reject')}>
                  {busy === 'reject' ? t('working') : t('rejectDataset')}
                </button>
              </div>
            </section>
          ) : null}
        </>
      ) : null}

      {job && !['pending', 'running', 'awaiting_approval'].includes(job.status) ? (
        <section className={`review-outcome outcome-${job.status}`} role="status">
          <strong>{outcomeLabel}</strong>
          <p>{job.status === 'published' ? t('publishedNext') : t('rejectedNext')}</p>
          <button type="button" className="primary" onClick={onClose}>{t('backToAssistant')}</button>
        </section>
      ) : null}
    </main>
  )
}
