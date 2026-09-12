import React from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DistrictOverview as DistrictOverviewData } from '../lib/copilot'
import { colorFor, compactFor, formatNumber, formatUnit, orderedColorFor } from '../lib/format'
import { useI18n } from '../lib/i18n'
import ChartMotion from './ChartMotion'

const tick = { fill: 'var(--chart-muted)', fontSize: 11 }

function OverviewTip({ active, payload, label, unit }: any) {
  const { language, t } = useI18n()
  if (!active || !payload?.length) return null
  const item = payload[0]
  return (
    <div className="mono-tooltip">
      <p>{label ?? item.payload?.label}</p>
      <span className="tooltip-row">
        <i className="tooltip-swatch" style={{ background: item.color ?? item.payload?.fill }} />
        {item.name}
        <strong>{formatNumber(Number(item.value), language)}</strong>
      </span>
      {item.payload?.sharePercent !== undefined ? (
        <span className="tooltip-unit">{t('shareOfYouth', { value: item.payload.sharePercent })}</span>
      ) : unit ? <span className="tooltip-unit">{formatUnit(unit, language)}</span> : null}
    </div>
  )
}

function SingleDistrictOverview({ overview, displayName }: {
  overview: DistrictOverviewData
  displayName: string
}) {
  const { language, t } = useI18n()
  const compact = compactFor(language)
  // The data-direction attribute stays a stable English token so the CSS hook
  // does not change with the language picker.
  const direction = overview.absoluteChange === null
    ? 'no prior period'
    : overview.absoluteChange > 0
      ? 'increasing'
      : overview.absoluteChange < 0
        ? 'decreasing'
        : 'stable'
  const directionLabel = {
    'no prior period': t('noPrior'), increasing: t('increasing'),
    decreasing: t('decreasing'), stable: t('stable'),
  }[direction]
  const leadingAge = overview.ageDistribution.reduce<(typeof overview.ageDistribution)[number] | null>(
    (leader, item) => !leader || item.value > leader.value ? item : leader,
    null,
  )

  return (
    <section className="district-overview" aria-label={t('youthOverviewOf', { name: displayName })}>
      <header className="overview-title">
        <div>
          <span>{t('districtOverview')}</span>
          <h2>{displayName}{overview.districtName === displayName ? null : <small>{overview.districtName}</small>}</h2>
        </div>
        <p>{t('latestPeriod')} · {overview.period}</p>
      </header>

      <div className="overview-kpis">
        <div>
          <span>{t('youthPopulation')}</span>
          <strong>{formatNumber(overview.total, language)}</strong>
          <small>{formatUnit(overview.unitCode, language)} · {t('ages')}</small>
        </div>
        <div data-direction={direction}>
          <span>{t('latestMovement')}</span>
          <strong>{overview.percentChange === null ? '—' : `${overview.percentChange > 0 ? '+' : ''}${overview.percentChange}%`}</strong>
          <small>{directionLabel}{overview.previousPeriod ? ` ${t('versus')} ${overview.previousPeriod}` : ''}</small>
        </div>
        <div>
          <span>{t('largestAge')}</span>
          <strong>{leadingAge?.label ?? '—'}</strong>
          <small>{leadingAge ? t('districtYouthShare', { value: leadingAge.sharePercent }) : t('notAvailable')}</small>
        </div>
      </div>

      <figure className="viz-card overview-trend" data-overview-chart="trend">
        <figcaption>
          <h3>{t('populationTrend')}</h3>
          <p>{t('recentPeriods', { count: overview.trend.length })}</p>
        </figcaption>
        <div className="mono-chart" style={{ height: 280 }}>
          <ChartMotion motionKey={`${overview.districtCode}-trend-${overview.period}`} direction="horizontal">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={overview.trend} margin={{ top: 12, right: 20, bottom: 22, left: 4 }}>
                <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 3" vertical={false} />
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={tick} minTickGap={24} dy={6} />
                <YAxis axisLine={false} tickLine={false} tick={tick} width={56} domain={['auto', 'auto']} tickFormatter={value => compact.format(Number(value))} />
                <Tooltip content={<OverviewTip unit={overview.unitCode} />} cursor={{ stroke: 'var(--chart-cursor)', strokeDasharray: '3 3' }} />
                <Line dataKey="value" name={t('youthPopulation')} type="monotone" stroke="var(--chart-primary)" strokeWidth={2} dot={{ r: 2, strokeWidth: 0, fill: 'var(--chart-primary)' }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartMotion>
        </div>
      </figure>

      <div className="overview-demographics">
        <figure className="viz-card" data-overview-chart="age">
          <figcaption>
            <h3>{t('shareByAge')}</h3>
            <p>{t('shareByAgeDetail')}</p>
          </figcaption>
          <div className="donut-layout">
            <div className="mono-chart donut-chart">
              <ChartMotion motionKey={`${overview.districtCode}-age-${overview.period}`} direction="ring">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={overview.ageDistribution} dataKey="value" nameKey="label" innerRadius="58%" outerRadius="84%" paddingAngle={1} isAnimationActive={false}>
                      {overview.ageDistribution.map((item, index) => <Cell key={item.key} fill={orderedColorFor(index)} />)}
                    </Pie>
                    <Tooltip content={<OverviewTip unit={overview.unitCode} />} />
                  </PieChart>
                </ResponsiveContainer>
              </ChartMotion>
              <div className="donut-center"><strong>18–35</strong><span>{t('years')}</span></div>
            </div>
            <ul className="donut-legend">
              {overview.ageDistribution.map((item, index) => (
                <li key={item.key}>
                  <i style={{ background: orderedColorFor(index) }} />
                  <span>{t('agesOf', { label: item.label })}</span>
                  <strong>{item.sharePercent}%</strong>
                  <small>{formatNumber(item.value, language)}</small>
                </li>
              ))}
            </ul>
          </div>
        </figure>

        <figure className="viz-card" data-overview-chart="gender">
          <figcaption>
            <h3>{t('genderDistribution')}</h3>
            <p>{t('genderRegistration', { period: overview.period })}</p>
          </figcaption>
          <div className="mono-chart" style={{ height: 270 }}>
            <ChartMotion motionKey={`${overview.districtCode}-gender-${overview.period}`} direction="horizontal">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={overview.genderDistribution} layout="vertical" margin={{ top: 8, right: 52, bottom: 18, left: 4 }}>
                  <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 3" horizontal={false} />
                  <XAxis type="number" axisLine={false} tickLine={false} tick={tick} tickFormatter={value => compact.format(Number(value))} />
                  <YAxis type="category" dataKey="label" axisLine={false} tickLine={false} tick={tick} width={58} />
                  <Tooltip content={<OverviewTip unit={overview.unitCode} />} cursor={{ fill: 'var(--chart-hover)' }} />
                  <Bar dataKey="value" name={t('youthPopulation')} barSize={16} isAnimationActive={false}>
                    {overview.genderDistribution.map((item, index) => (
                      <Cell key={item.key} fill={colorFor(index)} />
                    ))}
                    <LabelList dataKey="sharePercent" position="right" fill="var(--chart-muted)" fontSize={10} formatter={(value: number) => `${value}%`} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartMotion>
          </div>
        </figure>
      </div>

      <p className="panel-note">{t('overviewFooter', {
        dataset: overview.datasetId,
        version: overview.datasetVersion,
        quality: Math.round(overview.qualityScore * 100),
        scope: overview.populationScope.replace(/_/g, ' '),
      })}</p>
    </section>
  )
}

type OverviewEntry = { overview: DistrictOverviewData; displayName: string }

function MultiOverviewTip({ active, payload, label, unit, percent = false }: any) {
  const { language } = useI18n()
  if (!active || !payload?.length) return null
  // The tooltip ranking belongs to the hovered period, not the latest-period
  // order used by the cards and end labels.
  const rankedPayload = [...payload].sort((left: any, right: any) => {
    const difference = Number(right.value) - Number(left.value)
    return difference || String(left.name).localeCompare(String(right.name))
  })
  return (
    <div className="mono-tooltip">
      <p>{label}</p>
      {rankedPayload.map((item: any, index: number) => (
        <span className="tooltip-row" key={item.dataKey}>
          <b className="tooltip-rank">{index + 1}</b>
          <i className="tooltip-swatch" style={{ background: item.color }} />
          {item.name}
          <strong>{percent
            ? `${Number(item.value) > 0 ? '+' : ''}${Number(item.value).toFixed(2)}%`
            : formatNumber(Number(item.value), language)}</strong>
        </span>
      ))}
      {!percent ? <span className="tooltip-unit">{formatUnit(unit, language)}</span> : null}
    </div>
  )
}

function CompositionTip({ active, payload, label, unit }: any) {
  const { language } = useI18n()
  if (!active || !payload?.length) return null
  return (
    <div className="mono-tooltip">
      <p>{label}</p>
      {payload.map((item: any) => (
        <span className="tooltip-row" key={item.dataKey}>
          <i className="tooltip-swatch" style={{ background: item.color }} />
          {item.name}
          <strong>{Number(item.value).toFixed(1)}%</strong>
          <small>{formatNumber(Number(item.payload?.[`${item.dataKey}__count`]), language)} {formatUnit(unit, language)}</small>
        </span>
      ))}
    </div>
  )
}

function MultiDistrictOverview({ entries }: { entries: OverviewEntry[] }) {
  const { language, t } = useI18n()
  const [trendMode, setTrendMode] = React.useState<'change' | 'absolute'>('change')
  const compact = compactFor(language)
  const periodChanges = entries.map(entry => {
    const firstPoint = entry.overview.trend[0]
    const lastPoint = entry.overview.trend[entry.overview.trend.length - 1]
    const absolute = firstPoint && lastPoint ? lastPoint.value - firstPoint.value : null
    const percent = absolute !== null && firstPoint.value
      ? Math.round((absolute / firstPoint.value) * 10_000) / 100
      : null
    return { ...entry, absolute, percent }
  }).sort((left, right) => {
    if (left.percent === null) return right.percent === null ? left.displayName.localeCompare(right.displayName) : 1
    if (right.percent === null) return -1
    return right.percent - left.percent || left.displayName.localeCompare(right.displayName)
  })
  const rankedEntries: OverviewEntry[] = periodChanges
  const first = rankedEntries[0].overview
  const latestPeriods = Array.from(new Set(rankedEntries.map(entry => entry.overview.period)))
  const monthlyPeriods = Array.from(new Set(rankedEntries.flatMap(entry => entry.overview.trend.map(point => point.period)))).sort()
  // Quarterly sampling makes the direction changes legible while preserving
  // the exact first and latest observations used for the ranking.
  const trendPeriods = monthlyPeriods.filter((_, index) => index % 3 === 0 || index === monthlyPeriods.length - 1)
  const trendRows = trendPeriods.map(period => Object.fromEntries([
    ['period', period],
    ...rankedEntries.map(entry => {
      const value = entry.overview.trend.find(point => point.period === period)?.value
      if (value === undefined) return [entry.overview.districtCode, null]
      const baseline = entry.overview.trend[0]?.value
      return [entry.overview.districtCode, trendMode === 'change' && baseline
        ? Math.round(((value - baseline) / baseline) * 10_000) / 100
        : value]
    }),
  ]))
  const compositionData = (kind: 'ageDistribution' | 'genderDistribution') => {
    const keys = Array.from(new Set(rankedEntries.flatMap(entry => entry.overview[kind].map(item => item.key))))
    const series = keys.map(key => ({
      key,
      label: rankedEntries.flatMap(entry => entry.overview[kind]).find(item => item.key === key)?.label ?? key,
    }))
    const rows = rankedEntries.map(entry => Object.fromEntries([
      ['label', entry.displayName],
      ...series.flatMap(item => {
        const match = entry.overview[kind].find(value => value.key === item.key)
        return [
          [item.key, match?.sharePercent ?? 0],
          [`${item.key}__count`, match?.value ?? 0],
        ]
      }),
    ]))
    return { rows, series }
  }
  const sourceNotes = Array.from(new Set(rankedEntries.map(entry =>
    `${entry.overview.datasetId} · ${entry.overview.datasetVersion}`,
  )))

  const renderComposition = (kind: 'ageDistribution' | 'genderDistribution') => {
    const { rows, series } = compositionData(kind)
    return (
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 18, right: 18, bottom: 18, left: 8 }}>
          <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 3" horizontal={false} />
          <XAxis type="number" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} axisLine={false} tickLine={false}
            tick={tick} tickFormatter={value => `${value}%`} />
          <YAxis type="category" dataKey="label" axisLine={false} tickLine={false} tick={tick} width={76} />
          <Tooltip content={<CompositionTip unit={first.unitCode} />} cursor={{ fill: 'var(--chart-hover)' }} />
          <Legend verticalAlign="top" align="right" iconType="square" wrapperStyle={{ fontSize: 11, paddingBottom: 10 }} />
          {series.map((item, index) => (
            <Bar key={item.key} stackId={kind} dataKey={item.key} name={item.label}
              fill={kind === 'ageDistribution' ? orderedColorFor(index) : colorFor(index)} isAnimationActive={false}>
              <LabelList dataKey={item.key} position="center"
                fill={kind === 'ageDistribution' && index === 0 ? 'var(--ink)' : 'white'}
                fontSize={9} formatter={(value: number) => value >= 9 ? `${Number(value).toFixed(1)}%` : ''} />
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  }

  return (
    <section className="district-overview" aria-label={t('selectedDistrictOverview', { count: entries.length })}>
      <header className="overview-title">
        <div>
          <span>{t('districtOverview')}</span>
          <h2>{t('selectedDistrictOverview', { count: entries.length })}</h2>
          <div className="overview-series-legend">
            {rankedEntries.map((entry, index) => (
              <span key={entry.overview.districtCode}><b>{index + 1}</b><i style={{ background: colorFor(index) }} />{entry.displayName}</span>
            ))}
          </div>
        </div>
        <p>{t('latestPeriod')} · {latestPeriods.join(' / ')}</p>
      </header>

      <div className="overview-district-kpis">
        {periodChanges.map((entry, index) => (
          <div key={entry.overview.districtCode} data-direction={entry.percent === null || entry.percent === 0 ? 'stable' : entry.percent < 0 ? 'decreasing' : 'increasing'}>
            <span>{t('rankedDistrict', { rank: index + 1, name: entry.displayName })}</span>
            <strong>{entry.percent === null
              ? '—'
              : `${entry.percent > 0 ? '▲ +' : entry.percent < 0 ? '▼ ' : ''}${entry.percent}%`}</strong>
            <small>
              {entry.percent === null ? t('noPrior') : t('overSelectedPeriod')}
              {' · '}{formatNumber(entry.overview.total, language)} {formatUnit(entry.overview.unitCode, language)}
              {entry.absolute !== null ? ` · ${entry.absolute > 0 ? '+' : ''}${formatNumber(entry.absolute, language)}` : ''}
            </small>
          </div>
        ))}
      </div>

      <figure className="viz-card overview-trend" data-overview-chart="trend">
        <figcaption className="overview-chart-head">
          <div>
            <h3>{trendMode === 'change' ? t('relativePopulationTrend') : t('populationTrend')}</h3>
            <p>{trendMode === 'change' ? t('relativeTrendDetail') : t('multiTrendDetail', { count: entries.length })}</p>
          </div>
          <div className="overview-mode" role="group" aria-label={t('trendDisplay')}>
            <button type="button" className={trendMode === 'change' ? 'is-active' : undefined} onClick={() => setTrendMode('change')}>{t('changePercent')}</button>
            <button type="button" className={trendMode === 'absolute' ? 'is-active' : undefined} onClick={() => setTrendMode('absolute')}>{t('absolutePopulation')}</button>
          </div>
        </figcaption>
        <div className="mono-chart" style={{ height: 300 }}>
          <ChartMotion motionKey={`${rankedEntries.map(entry => entry.overview.districtCode).join('-')}-trend-${trendMode}`} direction="horizontal">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendRows} margin={{ top: 12, right: 48, bottom: 22, left: 4 }}>
                <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 3" vertical={false} />
                <XAxis dataKey="period" axisLine={false} tickLine={false} tick={tick} minTickGap={24} dy={6} />
                <YAxis axisLine={false} tickLine={false} tick={tick} width={56} domain={['auto', 'auto']}
                  tickFormatter={value => trendMode === 'change' ? `${Number(value).toFixed(1)}%` : compact.format(Number(value))} />
                {trendMode === 'change' ? <ReferenceLine y={0} stroke="var(--ink-muted)" strokeDasharray="4 4" /> : null}
                <Tooltip content={<MultiOverviewTip unit={first.unitCode} percent={trendMode === 'change'} />} cursor={{ stroke: 'var(--chart-cursor)', strokeDasharray: '3 3' }} />
                {rankedEntries.map((entry, index) => (
                  <Line key={entry.overview.districtCode} dataKey={entry.overview.districtCode} name={entry.displayName}
                    type="monotone" connectNulls stroke={colorFor(index)} strokeWidth={2}
                    dot={{ r: 3, strokeWidth: 0, fill: colorFor(index) }} isAnimationActive={false}
                    label={(props: any) => props.index === trendRows.length - 1 ? (
                      <text x={Number(props.x) + 9} y={Number(props.y) + 3} fill={colorFor(index)}
                        fontSize={10} fontWeight={600}>#{index + 1}</text>
                    ) : <React.Fragment />} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </ChartMotion>
        </div>
      </figure>

      <div className="overview-demographics">
        <figure className="viz-card" data-overview-chart="age">
          <figcaption><h3>{t('ageComparison')}</h3><p>{t('ageComparisonDetail')}</p></figcaption>
          <div className="mono-chart" style={{ height: Math.max(250, rankedEntries.length * 42 + 96) }}>{renderComposition('ageDistribution')}</div>
        </figure>
        <figure className="viz-card" data-overview-chart="gender">
          <figcaption><h3>{t('genderComparison')}</h3><p>{t('genderComparisonDetail')}</p></figcaption>
          <div className="mono-chart" style={{ height: Math.max(250, rankedEntries.length * 42 + 96) }}>{renderComposition('genderDistribution')}</div>
        </figure>
      </div>

      <p className="panel-note">{t('multiOverviewFooter', { sources: sourceNotes.join(' · ') })}</p>
    </section>
  )
}

export default function DistrictOverview({ entries }: { entries: OverviewEntry[] }) {
  if (entries.length === 1) return <SingleDistrictOverview {...entries[0]} />
  return <MultiDistrictOverview entries={entries} />
}
