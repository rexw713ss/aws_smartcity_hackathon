import React from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { DistrictOverview as DistrictOverviewData } from '../lib/copilot'
import { colorFor, compactFor, formatNumber, formatUnit } from '../lib/format'
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

export default function DistrictOverview({ overview, displayName }: {
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
                      {overview.ageDistribution.map((item, index) => <Cell key={item.key} fill={colorFor(index)} />)}
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
                  <i style={{ background: colorFor(index) }} />
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
                  <Bar dataKey="value" name={t('youthPopulation')} barSize={16} fill="var(--chart-positive)" isAnimationActive={false}>
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
