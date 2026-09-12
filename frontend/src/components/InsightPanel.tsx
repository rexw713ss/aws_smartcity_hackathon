import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { CopilotResponse, DistrictOverview as DistrictOverviewData, ImpactAnalysis, VisualizationSpec } from '../lib/copilot'
import { districtHighlights } from '../lib/districtHighlights'
import type { District } from '../lib/districts'
import { districtLabel, formatLabel, formatQuality, formatTimestamp } from '../lib/format'
import ChartView from './ChartView'
import DistrictMap from './DistrictMap'
import DistrictOverview from './DistrictOverview'
import { useI18n } from '../lib/i18n'

type Tab = 'charts' | 'map' | 'impact' | 'evidence' | 'trace'

function ImpactChain({ analysis }: { analysis: ImpactAnalysis }) {
  const { t } = useI18n()
  return (
    <section className="impact-chain">
      <header>
        <span>{t('impactChain')}</span>
        <h3>{analysis.district_name} · {analysis.target_year}</h3>
        <p>{t('confidence')}: {analysis.confidence}</p>
      </header>
      <ol>
        {analysis.findings.map((finding, index) => (
          <li key={`${finding.stage}-${index}`} data-state="complete">
            <span>{String(index + 1).padStart(2, '0')}</span>
            <div>
              <strong>{formatLabel(finding.stage)}</strong>
              <p>{finding.label}</p>
              {finding.baseline_value !== null && finding.scenario_value !== null ? (
                <em>
                  {finding.baseline_value.toLocaleString()} → {finding.scenario_value.toLocaleString()}
                  {finding.absolute_delta !== null ? ` (${finding.absolute_delta > 0 ? '+' : ''}${finding.absolute_delta.toLocaleString()} ${finding.unit})` : ''}
                </em>
              ) : null}
            </div>
          </li>
        ))}
        {analysis.data_gaps.map((gap, index) => (
          <li key={gap.domain} data-state="blocked">
            <span>{String(analysis.findings.length + index + 1).padStart(2, '0')}</span>
            <div>
              <strong>{formatLabel(gap.domain)} {t('capacity')}</strong>
              <p>{gap.reason}</p>
              <small>{t('needs')}: {gap.required_metrics.map(formatLabel).join(' · ')}</small>
            </div>
          </li>
        ))}
        <li data-state={analysis.recommendations.length ? 'complete' : 'withheld'}>
          <span>{String(analysis.findings.length + analysis.data_gaps.length + 1).padStart(2, '0')}</span>
          <div>
            <strong>{t('recommendation')}</strong>
            {analysis.recommendations.length ? analysis.recommendations.map(item => (
              <p key={`${item.priority}-${item.domain}`}>{item.priority}. {item.action} — {item.rationale}</p>
            )) : <p>{t('withheld')}</p>}
          </div>
        </li>
      </ol>
    </section>
  )
}

function VisualizationCard({ spec }: { spec: VisualizationSpec }) {
  const { t } = useI18n()
  return (
    <figure className="viz-card" data-viz-id={spec.visualization_id} data-viz-type={spec.type}>
      <figcaption>
        <h3>{spec.title}</h3>
        {spec.description ? <p>{spec.description}</p> : null}
      </figcaption>
      <ChartView spec={spec} />
      <footer>
        {spec.truncated ? (
          <span
            className="viz-flag"
            title={t('showingRows', { count: spec.rows.length })}
          >
            {t('showingRows', { count: spec.rows.length })}
          </span>
        ) : null}
        {spec.citation_ids.length ? (
          <span className="viz-cites">
            {t('cited')}
            {spec.citation_ids.map(id => (
              <code key={id}>{id}</code>
            ))}
          </span>
        ) : null}
      </footer>
    </figure>
  )
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="panel-empty">
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  )
}

export default function InsightPanel({
  response,
  pending,
  onExploreDistrict,
  citationFocus,
}: {
  response: CopilotResponse | null
  pending: boolean
  onExploreDistrict: (districtCode: string) => Promise<DistrictOverviewData>
  citationFocus: { citationId: string; requestId: number } | null
}) {
  const { language, t } = useI18n()
  const [tab, setTab] = useState<Tab>('charts')
  const [selectedDistricts, setSelectedDistricts] = useState<string[]>([])
  const [overviews, setOverviews] = useState<DistrictOverviewData[]>([])
  // The district, not its name: the label follows the language picker.
  const [overviewDistricts, setOverviewDistricts] = useState<District[]>([])
  const [overviewPending, setOverviewPending] = useState(false)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const overviewRequest = useRef(0)
  const evidenceRefs = useRef(new Map<string, HTMLLIElement>())
  const highlights = useMemo(() => districtHighlights(response), [response])
  // A choropleth is the map's own spec. Showing it again as a table here would
  // print the same figures twice, so the Charts tab lists everything else.
  const charts = useMemo(
    () => response?.visualizations.filter(spec => spec.type !== 'choropleth') ?? [],
    [response],
  )

  // A new answer always returns the reader to the charts it produced.
  useEffect(() => {
    if (response) {
      setOverviews([])
      setOverviewDistricts([])
      setSelectedDistricts([])
      setOverviewError(null)
      setTab(response.impact_analysis ? 'impact' : 'charts')
    }
  }, [response])

  const exploreDistricts = async (districts: District[]) => {
    if (!districts.length) return
    const ticket = ++overviewRequest.current
    setTab('charts')
    setOverviews([])
    setOverviewDistricts(districts)
    setOverviewError(null)
    setOverviewPending(true)
    try {
      const results = await Promise.all(districts.map(district => onExploreDistrict(district.code)))
      if (ticket === overviewRequest.current) setOverviews(results)
    } catch (cause) {
      if (ticket === overviewRequest.current) {
        setOverviewError(cause instanceof Error ? cause.message : t('overviewUnavailable'))
      }
    } finally {
      if (ticket === overviewRequest.current) setOverviewPending(false)
    }
  }

  useEffect(() => {
    if (citationFocus) setTab('evidence')
  }, [citationFocus])

  useEffect(() => {
    if (tab !== 'evidence' || !citationFocus) return
    const frame = window.requestAnimationFrame(() => {
      const source = evidenceRefs.current.get(citationFocus.citationId)
      source?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      source?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [tab, citationFocus])

  const overviewNames = overviewDistricts.map(district => districtLabel(district, language))
  const overviewName = overviewNames.join(language === 'zh-TW' ? '、' : ', ')

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'charts', label: t('charts'), count: overviews.length ? 3 : charts.length },
    { id: 'map', label: t('map'), count: highlights.byCode.size },
    { id: 'impact', label: t('impact'), count: response?.impact_analysis ? 1 : 0 },
    { id: 'evidence', label: t('evidence'), count: (response?.citations.length ?? 0) + (response?.web_citations.length ?? 0) },
    { id: 'trace', label: t('trace'), count: response?.tool_trace.length ?? 0 },
  ]

  return (
    <section className="insight-panel" aria-label={t('supportingInsight')}>
      <header className="panel-head">
        <div className="panel-tabs" role="tablist" aria-label={t('insightViews')}>
          {tabs.map(item => (
            <button
              key={item.id}
              role="tab"
              type="button"
              id={`tab-${item.id}`}
              aria-selected={tab === item.id}
              aria-controls={`panel-${item.id}`}
              className={tab === item.id ? 'is-active' : undefined}
              onClick={() => setTab(item.id)}
            >
              {item.label}
              {item.count ? <span className="tab-count">{item.count}</span> : null}
            </button>
          ))}
        </div>
        {response ? (
          <p className="panel-stamp">{t('generated')} {formatTimestamp(response.generated_at, language)}</p>
        ) : null}
      </header>

      <div className="panel-body" id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {pending && !response ? <div className="panel-loading" aria-live="polite">{t('calculating')}</div> : null}

        {tab === 'charts' ? (
          overviewPending ? (
            <div className="panel-loading" aria-live="polite">{t('loadingOverview', { name: overviewName })}</div>
          ) : overviewError ? (
            <Empty title={t('overviewUnavailable')} detail={overviewError} />
          ) : overviews.length ? (
            <DistrictOverview
              entries={overviews.map((overview, index) => ({ overview, displayName: overviewNames[index] ?? overview.districtName ?? overview.districtCode }))}
            />
          ) : charts.length ? (
            <>
              {charts.map(spec => (
                <VisualizationCard key={spec.visualization_id} spec={spec} />
              ))}
              <p className="panel-note">{t('chartNote')}</p>
            </>
          ) : (
            !pending && (
              <Empty
                title={t('noCharts')}
                detail={
                  response
                    ? t('noChartsAnswer')
                    : t('noChartsPrompt')
                }
              />
            )
          )
        ) : null}

        {tab === 'map' ? (
          <DistrictMap
            highlights={highlights}
            coverage={response?.limitations?.coverage ?? null}
            selected={selectedDistricts}
            onSelect={setSelectedDistricts}
            onExplore={exploreDistricts}
          />
        ) : null}

        {tab === 'impact' ? (
          response?.impact_analysis
            ? <ImpactChain analysis={response.impact_analysis} />
            : !pending && <Empty title={t('noImpact')} detail={t('noImpactDetail')} />
        ) : null}

        {tab === 'evidence' ? (
          response && (response.citations.length || response.web_citations.length) ? (
            <>
            {response.citations.length ? <ul className="evidence-list">
              {response.citations.map((citation, index) => (
                <li
                  key={citation.citation_id}
                  ref={element => {
                    if (element) evidenceRefs.current.set(citation.citation_id, element)
                    else evidenceRefs.current.delete(citation.citation_id)
                  }}
                  tabIndex={-1}
                  className={citationFocus?.citationId === citation.citation_id ? 'is-focused' : undefined}
                  data-citation-id={citation.citation_id}
                >
                  <code aria-label={`Source ${index + 1}`}>[{index + 1}]</code>
                  <div>
                    <strong>{formatLabel(citation.dataset_id)}</strong>
                    <span className="evidence-meta">
                      {t('version')} {citation.dataset_version} · {t('quality').toLowerCase()} {formatQuality(citation.quality_score, language)} · {t('retrieved')}{' '}
                      {formatTimestamp(citation.retrieved_at, language)}
                    </span>
                    <details
                      className="evidence-excerpt"
                      open={citationFocus?.citationId === citation.citation_id || undefined}
                    >
                      <summary>
                        {citation.excerpt.length
                          ? `${t('dataUsed')} · ${t('relevantRows', { count: citation.excerpt.length })}`
                          : t('dataUsed')}
                      </summary>
                      {citation.excerpt.length ? (
                        <div className="evidence-table-scroll">
                          <p>{t('excerptHelp')}</p>
                          <table className="evidence-table">
                            <thead>
                              <tr>
                                <th>{t('location')}</th>
                                <th>{t('field')}</th>
                                <th>{t('observed')}</th>
                                <th>{t('value')}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {citation.excerpt.map((row, rowIndex) => (
                                <tr key={`${row.entity_id}-${row.metric_code}-${row.period ?? row.observed_at ?? 'snapshot'}-${rowIndex}`}>
                                  <td>
                                    {row.entity_name}
                                    <code>{row.entity_id}</code>
                                  </td>
                                  <td>
                                    {row.metric_name}
                                    <code>{row.metric_code}</code>
                                  </td>
                                  <td>
                                    {row.period ?? (row.observed_at ? formatTimestamp(row.observed_at, language) : t('snapshot'))}
                                  </td>
                                  <td className="numeric">{row.value.toLocaleString()}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p className="evidence-unavailable">{t('noExcerpt')}</p>
                      )}
                    </details>
                  </div>
                </li>
              ))}
            </ul> : null}
            {response.web_citations.length ? (
              <ul className="evidence-list web-evidence-list">
                {response.web_citations.map((citation, index) => (
                  <li key={citation.citation_id} data-citation-id={citation.citation_id}>
                    <code aria-label={`Source ${response.citations.length + index + 1}`}>[{response.citations.length + index + 1}]</code>
                    <div>
                      <strong><a href={citation.url} target="_blank" rel="noreferrer">{citation.title}</a></strong>
                      {citation.published_at ? <span className="evidence-meta">{t('published')} {formatTimestamp(citation.published_at, language)}</span> : null}
                      {citation.snippet ? <p className="web-evidence-snippet">{citation.snippet}</p> : null}
                      <a className="web-evidence-link" href={citation.url} target="_blank" rel="noreferrer">{t('openWebResult')}</a>
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}
            </>
          ) : (
            !pending && <Empty title={t('noCitations')} detail={t('noCitationsDetail')} />
          )
        ) : null}

        {tab === 'trace' ? (
          response?.tool_trace.length ? (
            <ol className="trace-list">
              {response.tool_trace.map((step, index) => (
                <li key={`${step.tool}-${index}`} data-outcome={step.outcome}>
                  <span className="trace-tool">{formatLabel(step.tool)}</span>
                  <span className="trace-outcome">{formatLabel(step.outcome)}</span>
                  <p>{step.summary}</p>
                </li>
              ))}
            </ol>
          ) : (
            !pending && <Empty title={t('noTrace')} detail={t('noTraceDetail')} />
          )
        ) : null}
      </div>
    </section>
  )
}
