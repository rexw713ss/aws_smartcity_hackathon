import React, { useMemo, useState } from 'react'
import { DISTRICTS } from '../lib/districts'
import type {
  ScenarioOperation,
  YouthPopulationScenarioRequest,
  YouthPopulationScenarioResult,
} from '../lib/copilot'
import { formatNumber } from '../lib/format'

type Runner = (
  request: YouthPopulationScenarioRequest,
  signal: AbortSignal,
) => Promise<YouthPopulationScenarioResult>

const signed = (value: number) => `${value > 0 ? '+' : ''}${formatNumber(value)}`
const percent = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(1)}%`

type ProjectionOperation = Extract<ScenarioOperation,
  | 'annual_net_migration'
  | 'retention_rate_change'
  | 'match_city_retention'
  | 'match_top_quartile_retention'
>

type DraftAdjustment = {
  id: number
  districtId: string
  operation: ProjectionOperation
  value: string
}

const benchmarkOperations = new Set<ProjectionOperation>([
  'match_city_retention',
  'match_top_quartile_retention',
])

let adjustmentSequence = 1
const newAdjustment = (): DraftAdjustment => ({
  id: adjustmentSequence++,
  districtId: '14',
  operation: 'match_top_quartile_retention',
  value: '0',
})

const operationHelp: Record<ProjectionOperation, string> = {
  match_top_quartile_retention: 'Raise this district to at least the observed 75th-percentile rate across all 29 districts.',
  match_city_retention: 'Raise this district to at least the observed median rate across all 29 districts.',
  retention_rate_change: 'Change the district’s annual cohort transition rate by percentage points.',
  annual_net_migration: 'Add a recurring annual youth inflow or outflow through the target year.',
}

export default function WhatIfPanel({ run }: { run: Runner }) {
  const [adjustments, setAdjustments] = useState<DraftAdjustment[]>(() => [newAdjustment()])
  const [targetYear, setTargetYear] = useState('2030')
  const [result, setResult] = useState<YouthPopulationScenarioResult | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const changed = useMemo(
    () => result?.rows.filter(row => row.absolute_delta !== 0) ?? [],
    [result],
  )

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const parsed = adjustments.map(item => ({ ...item, numeric: Number(item.value) }))
    if (parsed.some(item => !benchmarkOperations.has(item.operation) && !Number.isFinite(item.numeric))) {
      setError('Enter a finite scenario value.')
      return
    }
    const controller = new AbortController()
    setPending(true)
    setError(null)
    try {
      setResult(await run({
        balanceMode: 'open',
        targetYear: Number(targetYear),
        adjustments: parsed.map(item => ({
          districtId: item.districtId,
          operation: item.operation,
          value: benchmarkOperations.has(item.operation) ? 0 : item.numeric,
        })),
      }, controller.signal))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The scenario could not be calculated.')
    } finally {
      setPending(false)
    }
  }

  const update = (id: number, change: Partial<DraftAdjustment>) => {
    setAdjustments(current => current.map(item => item.id === id ? { ...item, ...change } : item))
  }

  const loadExample = (kind: 'benchmark' | 'combined') => {
    setTargetYear('2030')
    if (kind === 'benchmark') {
      setAdjustments([newAdjustment()])
      return
    }
    setAdjustments([
      newAdjustment(),
      { ...newAdjustment(), districtId: '14', operation: 'annual_net_migration', value: '300' },
    ])
  }

  return (
    <div className="what-if">
      <section className="scenario-intro">
        <span className="scenario-kicker">Observed cohorts → future scenario</span>
        <h3>What changes the youth population by {targetYear}?</h3>
        <p>
          Age today’s residents forward, apply each district’s recent cohort-retention pattern,
          then test a different retention or migration path. This is a transparent scenario,
          not a causal policy prediction.
        </p>
      </section>

      <form className="scenario-form scenario-builder" onSubmit={submit}>
        <header className="scenario-builder-head">
          <label>
            Projection target
            <select value={targetYear} onChange={event => setTargetYear(event.target.value)}>
              {Array.from({ length: 10 }, (_, index) => 2027 + index).map(year => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
          </label>
          <div className="scenario-examples" aria-label="Scenario examples">
            <button type="button" className="ghost" onClick={() => loadExample('benchmark')}>
              Example: top-quartile retention
            </button>
            <button type="button" className="ghost" onClick={() => loadExample('combined')}>
              Example: retention + migration
            </button>
          </div>
        </header>

        <ol className="scenario-adjustments">
          {adjustments.map((item, index) => {
            const benchmark = benchmarkOperations.has(item.operation)
            return (
              <li key={item.id} className={`scenario-adjustment${benchmark ? ' is-benchmark' : ''}`}>
                <span className="scenario-step">{String(index + 1).padStart(2, '0')}</span>
                <label>
                  Assumption
                  <select
                    value={item.operation}
                    onChange={event => update(item.id, { operation: event.target.value as ProjectionOperation })}
                  >
                    <option value="match_top_quartile_retention">Reach top-quartile retention</option>
                    <option value="match_city_retention">Reach city-median retention</option>
                    <option value="retention_rate_change">Change annual retention rate</option>
                    <option value="annual_net_migration">Annual net youth migration</option>
                  </select>
                </label>
                <label>
                  District
                  <select value={item.districtId} onChange={event => update(item.id, { districtId: event.target.value })}>
                    {DISTRICTS.map(district => (
                      <option key={district.code} value={district.code}>
                        {district.english} · {district.name}
                      </option>
                    ))}
                  </select>
                </label>
                {benchmark ? (
                  <div className="scenario-derived-value">
                    <span>Data-derived value</span>
                    <p>{operationHelp[item.operation]}</p>
                  </div>
                ) : (
                  <label>
                    {item.operation === 'retention_rate_change' ? 'Percentage points / year' : 'People / year'}
                    <input
                      type="number"
                      step={item.operation === 'retention_rate_change' ? '0.1' : '1'}
                      value={item.value}
                      onChange={event => update(item.id, { value: event.target.value })}
                    />
                  </label>
                )}
                <button
                  type="button"
                  className="scenario-remove"
                  disabled={adjustments.length === 1}
                  onClick={() => setAdjustments(current => current.filter(candidate => candidate.id !== item.id))}
                  aria-label={`Remove assumption ${index + 1}`}
                >
                  Remove
                </button>
              </li>
            )
          })}
        </ol>

        <footer className="scenario-builder-actions">
          <button
            type="button"
            className="ghost"
            disabled={adjustments.length >= 20}
            onClick={() => setAdjustments(current => [...current, newAdjustment()])}
          >
            + Add assumption
          </button>
          <span>{adjustments.length} assumption{adjustments.length === 1 ? '' : 's'} · annual cohort model</span>
          <button type="submit" className="primary" disabled={pending}>
            {pending ? 'Projecting…' : 'Run projection'}
          </button>
        </footer>
      </form>

      {error ? <p className="scenario-error" role="alert">{error}</p> : null}

      {result ? (
        <>
          <section className="scenario-summary" aria-label="Scenario totals">
            <div><span>Observed</span><strong>{result.observed_period}</strong></div>
            <div><span>Target</span><strong>{result.target_year}</strong></div>
            <div><span>Baseline projection</span><strong>{formatNumber(result.baseline_total)}</strong></div>
            <div><span>Scenario projection</span><strong>{formatNumber(result.scenario_total)}</strong></div>
            <div><span>Difference</span><strong>{signed(result.total_delta)}</strong></div>
          </section>

          <section className="scenario-results scenario-trajectory">
            <header>
              <div>
                <h3>City-wide trajectory</h3>
                <p>Same observed cohorts, two explicit paths. Values are registered residents aged 18–35.</p>
              </div>
              <span className="scenario-badge">Derived projection</span>
            </header>
            <div className="table-scroll">
              <table className="spec-table">
                <thead><tr><th>Year</th><th className="numeric">Baseline</th><th className="numeric">Scenario</th><th className="numeric">Difference</th></tr></thead>
                <tbody>
                  {result.trajectory.map(point => (
                    <tr key={point.year}>
                      <td>{point.year}</td>
                      <td className="numeric">{formatNumber(point.baseline_value)}</td>
                      <td className="numeric">{formatNumber(point.scenario_value)}</td>
                      <td className="numeric" data-sign={point.absolute_delta < 0 ? 'negative' : 'positive'}>{signed(point.absolute_delta)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="scenario-results">
            <header>
              <div>
                <h3>District impact at {result.target_year}</h3>
                <p>{changed.length} district{changed.length === 1 ? '' : 's'} differ from the historical-retention baseline.</p>
              </div>
              <span className="scenario-badge">Scenario assumption</span>
            </header>
            <div className="table-scroll">
              <table className="spec-table">
                <thead>
                  <tr>
                    <th>District</th><th className="numeric">Historical rate</th>
                    <th className="numeric">Scenario rate</th><th className="numeric">Baseline</th>
                    <th className="numeric">Scenario</th><th className="numeric">Difference</th>
                    <th className="numeric">Rank</th>
                  </tr>
                </thead>
                <tbody>
                  {changed.map(row => (
                    <tr key={row.district_code}>
                      <td>{row.district_name}</td>
                      <td className="numeric">{percent(row.historical_retention_rate)}</td>
                      <td className="numeric">{percent(row.scenario_retention_rate)}</td>
                      <td className="numeric">{formatNumber(row.baseline_value)}</td>
                      <td className="numeric">{formatNumber(row.scenario_value)}</td>
                      <td className="numeric" data-sign={row.absolute_delta < 0 ? 'negative' : 'positive'}>{signed(row.absolute_delta)}</td>
                      <td className="numeric">{row.baseline_rank} → {row.scenario_rank}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="scenario-evidence">
            <h3>What is measured, derived, and assumed</h3>
            <ul>
              {result.evidence.map(item => (
                <li key={`${item.kind}-${item.label}`}>
                  <span data-kind={item.kind}>{item.kind.replace('_', ' ')}</span>
                  <div>
                    <strong>{item.label}</strong><p>{item.detail}</p>
                    {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">Official source</a> : null}
                  </div>
                </li>
              ))}
            </ul>
            {result.warnings.map(warning => <p className="scenario-warning" key={warning}>{warning}</p>)}
          </section>
        </>
      ) : null}
    </div>
  )
}
