import React, { useEffect, useMemo, useState } from 'react'
import type { CopilotResponse, VisualizationSpec } from '../lib/copilot'
import { districtHighlights } from '../lib/districtHighlights'
import { formatQuality, formatTimestamp } from '../lib/format'
import ChartView from './ChartView'
import DistrictMap from './DistrictMap'
import SourceCandidates from './SourceCandidates'

type Tab = 'charts' | 'map' | 'evidence' | 'trace'

function VisualizationCard({ spec }: { spec: VisualizationSpec }) {
  return (
    <figure className="viz-card" data-viz-id={spec.visualization_id} data-viz-type={spec.type}>
      <figcaption>
        <h3>{spec.title}</h3>
        {spec.description ? <p>{spec.description}</p> : null}
      </figcaption>
      <ChartView spec={spec} />
      <footer>
        {spec.truncated ? (
          <span className="viz-flag" title="The backend truncated this at 200 rows; the chart is not the full dataset.">
            Truncated to {spec.rows.length} rows
          </span>
        ) : null}
        {spec.citation_ids.length ? (
          <span className="viz-cites">
            Cited
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
  onAcquire,
  acquiring,
  onAsk,
}: {
  response: CopilotResponse | null
  pending: boolean
  onAcquire: (candidateId: string, submittedBy: string) => Promise<string>
  acquiring: boolean
  onAsk: (question: string) => void
}) {
  const [tab, setTab] = useState<Tab>('charts')
  const [selectedDistrict, setSelectedDistrict] = useState<string | null>(null)
  const highlights = useMemo(() => districtHighlights(response), [response])

  // A new answer always returns the reader to the charts it produced.
  useEffect(() => {
    if (response) setTab('charts')
  }, [response])

  const tabs: { id: Tab; label: string; count: number }[] = [
    { id: 'charts', label: 'Charts', count: response?.visualizations.length ?? 0 },
    { id: 'map', label: 'Map', count: highlights.byCode.size },
    { id: 'evidence', label: 'Evidence', count: response?.citations.length ?? 0 },
    { id: 'trace', label: 'Trace', count: response?.tool_trace.length ?? 0 },
  ]

  return (
    <section className="insight-panel" aria-label="Supporting insight">
      <header className="panel-head">
        <div className="panel-tabs" role="tablist" aria-label="Insight views">
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
          <p className="panel-stamp">Generated {formatTimestamp(response.generated_at)}</p>
        ) : null}
      </header>

      <div className="panel-body" id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {pending && !response ? <div className="panel-loading" aria-live="polite">Calculating from published data…</div> : null}

        {tab === 'charts' ? (
          response?.visualizations.length ? (
            <>
              {response.visualizations.map(spec => (
                <VisualizationCard key={spec.visualization_id} spec={spec} />
              ))}
              <p className="panel-note">
                The backend decides the chart type, the fields, and every value. This panel only draws
                them; it never recalculates a ranking, a change, or a percentage.
              </p>
            </>
          ) : (
            !pending && (
              <Empty
                title="No charts yet"
                detail={
                  response
                    ? 'This answer produced no visualization. Insufficient-evidence and unsupported answers deliberately return none.'
                    : 'Ask a question on the left. Charts and tables returned by the backend appear here.'
                }
              />
            )
          )
        ) : null}

        {tab === 'map' ? (
          <DistrictMap
            highlights={highlights}
            selected={selectedDistrict}
            onSelect={setSelectedDistrict}
            onAsk={onAsk}
          />
        ) : null}

        {tab === 'evidence' ? (
          response?.citations.length ? (
            <ul className="evidence-list">
              {response.citations.map(citation => (
                <li key={citation.citation_id}>
                  <code>{citation.citation_id}</code>
                  <div>
                    <strong>{citation.dataset_id}</strong>
                    <span className="evidence-meta">
                      Version {citation.dataset_version} · quality {formatQuality(citation.quality_score)} · retrieved{' '}
                      {formatTimestamp(citation.retrieved_at)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            !pending && <Empty title="No citations" detail="Citations appear only when an answer is drawn from published datasets." />
          )
        ) : null}

        {tab === 'trace' ? (
          response?.tool_trace.length ? (
            <ol className="trace-list">
              {response.tool_trace.map((step, index) => (
                <li key={`${step.tool}-${index}`} data-outcome={step.outcome}>
                  <span className="trace-tool">{step.tool}</span>
                  <span className="trace-outcome">{step.outcome}</span>
                  <p>{step.summary}</p>
                </li>
              ))}
            </ol>
          ) : (
            !pending && <Empty title="No trace" detail="This lists the tools the system actually called and what each returned." />
          )
        ) : null}

        {response?.source_candidates.length ? (
          <SourceCandidates candidates={response.source_candidates} onAcquire={onAcquire} busy={acquiring} />
        ) : null}
      </div>
    </section>
  )
}
