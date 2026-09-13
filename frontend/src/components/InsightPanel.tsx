import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { CopilotResponse, DistrictOverview as DistrictOverviewData, VisualizationSpec } from '../lib/copilot'
import { districtHighlights } from '../lib/districtHighlights'
import type { District } from '../lib/districts'
import { districtLabel, formatLabel, formatPeriod, formatProseYears, formatQuality, formatTimestamp } from '../lib/format'
import ChartView from './ChartView'
import DistrictMap from './DistrictMap'
import DistrictOverview from './DistrictOverview'
import { useI18n } from '../lib/i18n'

type Tab = 'map' | 'charts' | 'evidence' | 'trace'

function VisualizationCard({
  spec,
  response,
  onCitation,
}: {
  spec: VisualizationSpec
  response: CopilotResponse
  onCitation: (citationId: string) => void
}) {
  const { language, t } = useI18n()
  const years = (text: string) => formatProseYears(text, language)
  const citations = new Map<string, { number: number; label: string; url: string | null }>([
    ...response.citations.map((citation, index) => [
      citation.citation_id,
      {
        number: index + 1,
        label: formatLabel(citation.dataset_id),
        url: null,
      },
    ] as const),
    ...response.web_citations.map((citation, index) => [
      citation.citation_id,
      {
        number: response.citations.length + index + 1,
        label: citation.title,
        url: citation.url,
      },
    ] as const),
  ])
  return (
    <figure className="viz-card" data-viz-id={spec.visualization_id} data-viz-type={spec.type}>
      <figcaption>
        {/* The headline is the finding; the title names the subject. A reader
            who only skims the answer should still leave with the finding. */}
        {spec.headline ? <h3 className="viz-headline">{years(spec.headline)}</h3> : <h3>{years(spec.title)}</h3>}
        {spec.headline ? <p className="viz-subject">{years(spec.title)}</p> : null}
        {spec.description ? <p>{years(spec.description)}</p> : null}
      </figcaption>
      <ChartView spec={spec} />
      <footer>
        <span className={spec.truncated ? 'viz-flag' : undefined}>
          {t('showingRows', { count: spec.rows.length })}
          {spec.citation_ids.length ? <>{' '}{t('fromSources')}{' '}</> : null}
          {spec.citation_ids.map(id => {
            const citation = citations.get(id)
            if (!citation) return null
            return citation.url ? (
              <sup className="inline-citation" key={id}>
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noreferrer"
                  aria-label={t('openWebSource', { number: citation.number, name: citation.label })}
                  title={citation.label}
                >
                  [{citation.number}]
                </a>
              </sup>
            ) : (
              <sup className="inline-citation" key={id}>
                <button
                  type="button"
                  onClick={() => onCitation(id)}
                  aria-label={t('showSource', { number: citation.number, name: citation.label })}
                  title={citation.label}
                >
                  [{citation.number}]
                </button>
              </sup>
            )
          })}
        </span>
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
  history,
  pending,
  onExploreDistrict,
  citationFocus,
  onCitation,
}: {
  response: CopilotResponse | null
  history: { id: string; question: string; response: CopilotResponse }[]
  pending: boolean
  onExploreDistrict: (districtCode: string) => Promise<DistrictOverviewData>
  citationFocus: { citationId: string; requestId: number } | null
  onCitation: (citationId: string, sourceResponse?: CopilotResponse) => void
}) {
  const { language, t } = useI18n()
  const [tab, setTab] = useState<Tab>('map')
  const [chartHistoryId, setChartHistoryId] = useState<string | null>(null)
  const [selectedDistricts, setSelectedDistricts] = useState<string[]>([])
  const [overviews, setOverviews] = useState<DistrictOverviewData[]>([])
  // The district, not its name: the label follows the language picker.
  const [overviewDistricts, setOverviewDistricts] = useState<District[]>([])
  const [overviewPending, setOverviewPending] = useState(false)
  const [overviewError, setOverviewError] = useState<string | null>(null)
  const overviewRequest = useRef(0)
  const evidenceRefs = useRef(new Map<string, HTMLLIElement>())
  const highlights = useMemo(() => districtHighlights(response), [response])
  const chartHistoryItem = history.find(item => item.id === chartHistoryId) ?? history[history.length - 1]
  const chartResponse = chartHistoryItem?.response ?? response
  // A choropleth is the map's own spec. Showing it again as a table here would
  // print the same figures twice, so the Charts tab lists everything else.
  const charts = useMemo(
    () => chartResponse?.visualizations.filter(spec => spec.type !== 'choropleth') ?? [],
    [chartResponse],
  )

  useEffect(() => {
    const latestItem = history[history.length - 1]
    if (latestItem) setChartHistoryId(latestItem.id)
  }, [history])

  // The map is the primary spatial overview. Other views open only after an
  // explicit chart, district-overview, citation, or trace action.
  useEffect(() => {
    if (response) {
      setOverviews([])
      setOverviewDistricts([])
      setSelectedDistricts([])
      setOverviewError(null)
      setTab('map')
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
  const displayedResponse = tab === 'charts' ? chartResponse : response

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'map', label: t('map'), count: highlights.byCode.size },
    { id: 'charts', label: t('charts'), count: overviews.length ? 3 : charts.length },
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
        {displayedResponse ? (
          <p className="panel-stamp">{t('generated')} {formatTimestamp(displayedResponse.generated_at, language)}</p>
        ) : null}
      </header>

      <div
        className={`panel-body${tab === 'map' ? ' is-map' : ''}`}
        id={`panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
      >
        {pending && !response ? <div className="panel-loading" aria-live="polite">{t('calculating')}</div> : null}

        {tab === 'charts' ? (
          <>
          {history.length ? (
            <div className="chart-history-tabs" role="tablist" aria-label={t('chartHistory')}>
              {history.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={item.id === chartHistoryItem?.id}
                  className={item.id === chartHistoryItem?.id ? 'is-active' : undefined}
                  title={item.question}
                  onClick={() => {
                    setChartHistoryId(item.id)
                    setOverviews([])
                    setOverviewDistricts([])
                    setOverviewError(null)
                  }}
                >
                  <span className="chart-history-number" aria-hidden="true">{index + 1}</span>
                  <span className="chart-history-label">{item.question}</span>
                </button>
              ))}
            </div>
          ) : null}
          {overviewPending ? (
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
                <VisualizationCard
                  key={spec.visualization_id}
                  spec={spec}
                  response={chartResponse!}
                  onCitation={citationId => onCitation(citationId, chartResponse ?? undefined)}
                />
              ))}
            </>
          ) : (
            !pending && (
              <Empty
                title={t('noCharts')}
                detail={
                  chartResponse
                    ? t('noChartsAnswer')
                    : t('noChartsPrompt')
                }
              />
            )
          )}
          </>
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
                                    {row.period ? formatPeriod(row.period, language) : (row.observed_at ? formatTimestamp(row.observed_at, language) : t('snapshot'))}
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
