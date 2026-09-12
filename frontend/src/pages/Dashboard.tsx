import React, { useEffect, useMemo, useState } from 'react'
import Papa from 'papaparse'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import Filters from '../components/Filters'
import Icon, { IconName } from '../components/Icon'
import CityDepth from '../components/CityDepth'
import DistrictMap from '../components/DistrictMap'
import DistrictStats from '../components/DistrictStats'
import { MonoDonut, MonoPillBars, MonoSparkline, MonoTooltip as MetricTooltip } from '../components/MonoCharts'
import FloatingScene, { FloatingElement } from '../components/FloatingScene'
import ChartMotion from '../components/ChartMotion'
import AiAssistant from '../components/AiAssistant'
import { ChartContext, DashboardAction } from '../lib/copilot'
import { useLenis } from 'lenis/react'
import { useDashboardMotion } from '../components/MotionProvider'
import { useSectionTransitions } from '../hooks/useSectionTransitions'

type PopulationRow = {
  year: number
  roc_year: number
  month: number
  district_code: number
  district: string
  total_population: number
  youth_population: number
  male_youth: number
  female_youth: number
  age_15_19: number
  age_20_24: number
  age_25_29: number
  age_30_34: number
  age_35_39: number
}

type EducationRow = {
  year: number
  roc_year: number
  district_code: number
  district: string
  level: string
  people: number
}

type MarriageRow = {
  year: number
  roc_year: number
  district_code: number
  district: string
  status: string
  people: number
}

type MigrationRow = {
  district_code: number
  district: string
  year: number
  month: number
  period: string
  series: 'actual' | 'forecast'
  people: number
  lower: number | null
  upper: number | null
}

type MigrationSummaryRow = {
  district_code: number
  district: string
  training_start: number
  training_end: number
  forecast_year: number
  latest_actual_total: number
  forecast_total: number
  forecast_lower: number
  forecast_upper: number
  forecast_change_pct: number
  backtest_mae: number
  backtest_wape_pct: number
  backtest_accuracy_pct: number
  model: string
}

const integer = new Intl.NumberFormat('zh-TW')
const compact = new Intl.NumberFormat('zh-TW', { notation: 'compact', maximumFractionDigits: 1 })
const percent = new Intl.NumberFormat('zh-TW', { style: 'percent', maximumFractionDigits: 1 })

const educationCategories = [
  { label: '國小以下', levels: ['不識字', '自學', '國小'] },
  { label: '國中', levels: ['國中', '國中(職業)'] },
  { label: '高中／高職', levels: ['高中', '高職', '五專前三年'] },
  { label: '專科', levels: ['二專', '五專後二年'] },
  { label: '大學', levels: ['大學'] },
  { label: '研究所', levels: ['碩士', '博士'] },
]

const marriageStatuses = [
  { raw: '未婚', label: '未婚', color: 'var(--mono-ink)' },
  { raw: '有偶', label: '有偶', color: 'var(--mono-secondary)' },
  { raw: '離婚', label: '離婚', color: 'var(--mono-muted)' },
  { raw: '喪偶', label: '喪偶', color: 'var(--mono-muted)' },
]

function parseRow(row: Record<string, string>): PopulationRow {
  return {
    year: Number(row.year),
    roc_year: Number(row.roc_year),
    month: Number(row.month),
    district_code: Number(row.district_code),
    district: row.district,
    total_population: Number(row.total_population),
    youth_population: Number(row.youth_population),
    male_youth: Number(row.male_youth),
    female_youth: Number(row.female_youth),
    age_15_19: Number(row.age_15_19),
    age_20_24: Number(row.age_20_24),
    age_25_29: Number(row.age_25_29),
    age_30_34: Number(row.age_30_34),
    age_35_39: Number(row.age_35_39),
  }
}

function parseEducationRow(row: Record<string, string>): EducationRow {
  return {
    year: Number(row.year),
    roc_year: Number(row.roc_year),
    district_code: Number(row.district_code),
    district: row.district,
    level: row.level,
    people: Number(row.people),
  }
}

function parseMarriageRow(row: Record<string, string>): MarriageRow {
  return {
    year: Number(row.year),
    roc_year: Number(row.roc_year),
    district_code: Number(row.district_code),
    district: row.district,
    status: row.status,
    people: Number(row.people),
  }
}

function parseMigrationRow(row: Record<string, string>): MigrationRow {
  return {
    district_code: Number(row.district_code),
    district: row.district,
    year: Number(row.year),
    month: Number(row.month),
    period: row.period,
    series: row.series as MigrationRow['series'],
    people: Number(row.people),
    lower: row.lower === '' ? null : Number(row.lower),
    upper: row.upper === '' ? null : Number(row.upper),
  }
}

function parseMigrationSummaryRow(row: Record<string, string>): MigrationSummaryRow {
  return {
    district_code: Number(row.district_code),
    district: row.district,
    training_start: Number(row.training_start),
    training_end: Number(row.training_end),
    forecast_year: Number(row.forecast_year),
    latest_actual_total: Number(row.latest_actual_total),
    forecast_total: Number(row.forecast_total),
    forecast_lower: Number(row.forecast_lower),
    forecast_upper: Number(row.forecast_upper),
    forecast_change_pct: Number(row.forecast_change_pct),
    backtest_mae: Number(row.backtest_mae),
    backtest_wape_pct: Number(row.backtest_wape_pct),
    backtest_accuracy_pct: Number(row.backtest_accuracy_pct),
    model: row.model,
  }
}

function publishedYearAtOrBefore<T extends { year: number }>(records: T[], selectedYear: number) {
  const available = records.filter(record => record.year <= selectedYear).map(record => record.year)
  return available.length ? Math.max(...available) : null
}

function MigrationTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  const value = point.actual ?? point.forecast
  if (!Number.isFinite(value)) return null
  const [yearValue, monthValue] = String(point.period).split('-').map(Number)
  const monthLabel = new Intl.DateTimeFormat('zh-TW', { month: 'long' }).format(new Date(2024, monthValue - 1, 1))
  const isForecast = Number.isFinite(point.forecast) && !Number.isFinite(point.actual)

  return (
    <div className="mono-tooltip">
      <div className="flex items-center gap-2">
        <span className="mono-legend-dot" style={{ opacity: isForecast ? 0.55 : 1 }} />
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{yearValue} 年 {monthLabel}</p>
      </div>
      <p className="mt-1 text-sm font-bold text-slate-900 dark:text-white">{integer.format(value)}</p>
      <p className="mt-0.5 text-xs text-slate-400">{isForecast ? '預估遷出人次' : '實際遷出人次'}</p>
      {isForecast && Number.isFinite(point.lower) && Number.isFinite(point.upper) && (
        <p className="mt-1.5 border-t border-slate-100 pt-1.5 text-xs text-slate-500 dark:border-white/10 dark:text-slate-400">
          80% 預測區間 {integer.format(point.lower)}–{integer.format(point.upper)}
        </p>
      )}
    </div>
  )
}

function Card({ children, className = '', id }: { children: React.ReactNode; className?: string; id?: string }) {
  const floatChildren = (nodes: React.ReactNode): React.ReactNode => React.Children.map(nodes, (child, index) => {
    if (!React.isValidElement(child)) return child
    if (child.type === React.Fragment) return floatChildren(child.props.children)
    if (child.type === FloatingElement || child.props.className?.includes('district-atlas-layout')) return child
    return <FloatingElement phase={index + 1} strength={index === 0 ? 0.9 : 0.55} reading={index !== 0}>{child}</FloatingElement>
  })
  // Stationary section anchors and text; motion is isolated to chart marks.
  return <section id={id} className={`open-section scroll-mt-28 ${className}`}>{floatChildren(children)}</section>
}

function CardHeader({ title, subtitle, tag, onAsk }: { title: string; subtitle: string; tag?: string; onAsk?: () => void }) {
  return (
    <div className="card-header flex flex-wrap items-start justify-between gap-4 px-5 pb-4 pt-5 sm:px-7 sm:pt-7">
      <div>
        <h3 className="card-title text-[17px] font-semibold tracking-[-0.02em]">{title}</h3>
        <p className="card-subtitle mt-1.5 text-xs leading-5">{subtitle}</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {tag && <span className="card-tag border px-2.5 py-1 font-mono text-xs font-semibold uppercase tracking-[0.08em]">{tag}</span>}
        {onAsk && <button type="button" className="ai-ask-chart" onClick={onAsk} aria-label={`詢問「${title}」`}>詢問此圖表 <Icon name="arrow-up-right" className="h-4 w-4" /></button>}
      </div>
    </div>
  )
}

type KpiProps = {
  detail: React.ReactNode
  icon: IconName
  label: string
  series?: number[]
  tone: 'blue' | 'emerald' | 'orange' | 'cyan'
  value: string
}

const tones = {
  blue: {
    glow: 'bg-blue-500',
    icon: 'bg-blue-50 text-blue-700 ring-blue-600/10 dark:bg-blue-400/10 dark:text-blue-300 dark:ring-blue-300/10',
    line: 'var(--mono-ink)',
  },
  emerald: {
    glow: 'bg-teal-500',
    icon: 'bg-teal-50 text-teal-700 ring-teal-600/10 dark:bg-teal-400/10 dark:text-teal-300 dark:ring-teal-300/10',
    line: 'var(--mono-secondary)',
  },
  orange: {
    glow: 'bg-amber-500',
    icon: 'bg-amber-50 text-amber-700 ring-amber-600/10 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-300/10',
    line: 'var(--mono-muted)',
  },
  cyan: {
    glow: 'bg-cyan-500',
    icon: 'bg-cyan-50 text-cyan-800 ring-cyan-700/10 dark:bg-cyan-300/10 dark:text-cyan-200 dark:ring-cyan-200/10',
    line: 'var(--chart-tertiary)',
  },
}

function KpiCard({ detail, icon, label, series, tone, value }: KpiProps) {
  const palette = tones[tone]

  return (
    <FloatingElement className="metric-island" phase={['blue', 'emerald', 'orange', 'cyan'].indexOf(tone)} strength={0.8}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="metric-label font-mono text-xs font-semibold uppercase tracking-[0.1em]">{label}</p>
          <p className="metric-value mt-2 text-2xl font-bold tracking-[-0.04em] sm:text-[28px]">{value}</p>
        </div>
        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ring-1 ${palette.icon}`}><Icon name={icon} className="h-[19px] w-[19px]" /></span>
      </div>
      <div className="mt-4 flex min-h-10 items-end justify-between gap-3">
        <div className="min-w-0 flex-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{detail}</div>
        {series && series.length > 0 && <MonoSparkline values={series} />}
      </div>
    </FloatingElement>
  )
}

type SignalItem = {
  icon: IconName
  label: string
  text: React.ReactNode
  tone: string
}

function PolicySignalCard({
  cohortLabel,
  cohortShare,
  cohortValue,
  signals,
  year,
}: {
  cohortLabel: string
  cohortShare: number
  cohortValue: number
  signals: SignalItem[]
  year: number
}) {
  const [expanded, setExpanded] = useState(true)

  return (
    <Card className="overflow-hidden">
      <CardHeader title="政策訊號" subtitle={`${year} 年重點觀察`} tag="資料快照" />
      <div className="px-5 pb-5 pt-3 sm:px-6 sm:pb-6">
        <div className="insight-stat">
          <div className="relative">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-[0.13em] text-teal-300">最大年齡層</span>
              <span className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/10 text-teal-300 shadow-inner"><Icon name="age" className="h-[18px] w-[18px]" /></span>
            </div>
            <p className="mt-5 text-3xl font-bold tracking-[-0.04em]">{cohortLabel} 歲</p>
            <div className="mt-2 flex items-center justify-between gap-4 text-xs text-slate-300">
              <span>{integer.format(cohortValue)} 人</span>
              <span className="font-semibold text-white">占青年 {percent.format(cohortShare)}</span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
              <span className="mono-meter-fill block h-full rounded-full" style={{ width: `${Math.min(cohortShare * 100, 100)}%` }} />
            </div>
          </div>
        </div>

        <button
          aria-controls="policy-signal-details"
          aria-expanded={expanded}
          className="mt-3 flex w-full items-center justify-between rounded-xl px-2 py-2.5 text-left transition hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-500/10 dark:hover:bg-white/[0.04]"
          onClick={() => setExpanded(value => !value)}
          type="button"
        >
          <span>
            <span className="block text-xs font-semibold text-slate-800 dark:text-slate-200">證據說明</span>
            <span className="mt-0.5 block text-xs text-slate-400">此快照由 {signals.length} 項指標支持</span>
          </span>
          <span className={`grid h-8 w-8 place-items-center rounded-lg border border-slate-200 text-slate-500 transition duration-300 dark:border-white/10 dark:text-slate-300 ${expanded ? 'rotate-180' : ''}`}>
            <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8"><path d="m7 10 5 5 5-5" /></svg>
          </span>
        </button>

        <div aria-hidden={!expanded} className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`} id="policy-signal-details">
          <div className="overflow-hidden">
            <div className="divide-y divide-slate-100 border-t border-slate-100 dark:divide-white/[0.07] dark:border-white/[0.07]">
              {signals.map(signal => (
                <div className="group flex gap-3 py-3.5" key={signal.label}>
                  <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${signal.tone}`}><Icon name={signal.icon} className="h-4 w-4" /></span>
                  <p className="text-xs leading-5 text-slate-500 dark:text-slate-400"><strong className="font-semibold text-slate-800 dark:text-slate-200">{signal.label}:</strong> {signal.text}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Card>
  )
}

function LoadingState() {
  return (
    <div className="space-y-5 animate-pulse">
      <div className="h-32 rounded-2xl bg-slate-200/70 dark:bg-white/5" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, index) => <div key={index} className="h-36 rounded-2xl bg-slate-200/70 dark:bg-white/5" />)}</div>
      <div className="h-[430px] rounded-2xl bg-slate-200/70 dark:bg-white/5" />
    </div>
  )
}

export type DashboardSelection = { district: string; year: number; month: number }

export default function Dashboard({ onSelectionChange }: { onSelectionChange?: (selection: DashboardSelection) => void }) {
  const [rows, setRows] = useState<PopulationRow[]>([])
  const [educationRows, setEducationRows] = useState<EducationRow[]>([])
  const [marriageRows, setMarriageRows] = useState<MarriageRow[]>([])
  const [migrationRows, setMigrationRows] = useState<MigrationRow[]>([])
  const [migrationSummaryRows, setMigrationSummaryRows] = useState<MigrationSummaryRow[]>([])
  const [district, setDistrict] = useState('New Taipei City')
  const [year, setYear] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [assistantChart, setAssistantChart] = useState('population-trend')
  const [drawVersion, setDrawVersion] = useState(0)
  const lenis = useLenis()
  const { reducedMotion } = useDashboardMotion()

  const navigateTo = (id: string, focus = false) => {
    // Wait for React to commit a newly selected assistant context.
    requestAnimationFrame(() => {
      const section = document.getElementById(id)
      if (!section) return
      const header = document.querySelector('header')?.getBoundingClientRect().height ?? 80
      const finish = () => { if (focus) document.getElementById('ai-title')?.focus({ preventScroll: true }) }
      if (lenis) lenis.scrollTo(section, { offset: -header - 20, duration: 1.8, easing: progress => (1 - Math.cos(Math.PI * progress)) / 2, immediate: reducedMotion, onComplete: finish })
      else { window.scrollTo({ top: section.getBoundingClientRect().top + scrollY - header - 20, behavior: 'auto' }); finish() }
      window.history.replaceState(null, '', `#${id}`)
    })
  }
  const askChart = (id: string) => { setAssistantChart(id); navigateTo('ai-assistant', true) }

  useEffect(() => {
    const files = [
      '/data/youth_population_summary.csv',
      '/data/education_summary.csv',
      '/data/marriage_summary.csv',
      '/data/migration_forecast.csv',
      '/data/migration_forecast_summary.csv',
    ]

    Promise.all(files.map(async file => {
      const response = await fetch(file)
      if (!response.ok) throw new Error(`資料載入失敗：${file}（${response.status}）`)
      return response.text()
    }))
      .then(([populationCsv, educationCsv, marriageCsv, migrationCsv, migrationSummaryCsv]) => {
        const populationResult = Papa.parse<Record<string, string>>(populationCsv, { header: true, skipEmptyLines: true })
        const educationResult = Papa.parse<Record<string, string>>(educationCsv, { header: true, skipEmptyLines: true })
        const marriageResult = Papa.parse<Record<string, string>>(marriageCsv, { header: true, skipEmptyLines: true })
        const migrationResult = Papa.parse<Record<string, string>>(migrationCsv, { header: true, skipEmptyLines: true })
        const migrationSummaryResult = Papa.parse<Record<string, string>>(migrationSummaryCsv, { header: true, skipEmptyLines: true })
        if (populationResult.data.length === 0) throw new Error('人口摘要資料為空。')

        const population = populationResult.data.map(parseRow).filter(row => Number.isFinite(row.year) && row.district)
        setRows(population)
        setEducationRows(educationResult.data.map(parseEducationRow).filter(row => Number.isFinite(row.year) && row.district))
        setMarriageRows(marriageResult.data.map(parseMarriageRow).filter(row => Number.isFinite(row.year) && row.district))
        setMigrationRows(migrationResult.data.map(parseMigrationRow).filter(row => Number.isFinite(row.year) && row.district))
        setMigrationSummaryRows(migrationSummaryResult.data.map(parseMigrationSummaryRow).filter(row => Number.isFinite(row.forecast_total) && row.district))
        setYear(Math.max(...population.map(row => row.year)))
      })
      .catch(cause => setError(cause instanceof Error ? cause.message : '無法載入儀表板資料。'))
  }, [])

  const years = useMemo(() => [...new Set(rows.map(row => row.year))].sort((a, b) => b - a), [rows])
  const districts = useMemo(() => rows
    .filter(row => row.year === years[0] && row.district_code !== 0)
    .sort((a, b) => a.district_code - b.district_code)
    .map(row => row.district), [rows, years])
  const yearMonths = useMemo(() => Object.fromEntries(
    rows.filter(row => row.district_code === 0).map(row => [row.year, row.month]),
  ), [rows])

  const current = rows.find(row => row.year === year && row.district === district)
  const dashboardReady = Boolean(current)
  useSectionTransitions(dashboardReady)
  useEffect(() => {
    if (current) onSelectionChange?.({ district, year, month: current.month })
  }, [district, year, current?.month, onSelectionChange])

  const previous = rows
    .filter(row => row.district === district && row.year < year)
    .sort((a, b) => b.year - a.year)[0]

  const trendData = rows
    .filter(row => row.district === district && row.year <= year)
    .sort((a, b) => a.year - b.year)

  const districtRows = rows
    .filter(row => row.year === year && row.district_code !== 0)
    .sort((a, b) => b.youth_population - a.youth_population)

  if (error) {
    return (
      <Card className="p-8">
        <div className="mx-auto max-w-lg text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-rose-50 text-rose-600 dark:bg-rose-400/10 dark:text-rose-300"><Icon name="info" /></span>
          <h2 className="mt-4 text-lg font-semibold">無法載入儀表板資料</h2>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{error}</p>
          <p className="mt-4 text-xs text-slate-400">請執行 scripts/build_dashboard_data.ps1，再重新啟動 Vite 伺服器。</p>
        </div>
      </Card>
    )
  }

  if (!current) return <LoadingState />

  const change = previous ? (current.youth_population - previous.youth_population) / previous.youth_population : 0
  const changeValue = previous ? current.youth_population - previous.youth_population : 0
  const youthShare = current.youth_population / current.total_population
  const selectedRank = districtRows.findIndex(row => row.district === district) + 1
  const largestCohort = [
    { label: '15–19', value: current.age_15_19 },
    { label: '20–24', value: current.age_20_24 },
    { label: '25–29', value: current.age_25_29 },
    { label: '30–34', value: current.age_30_34 },
    { label: '35–39', value: current.age_35_39 },
  ].sort((a, b) => b.value - a.value)[0]
  const ageData = [
    { age: '15–19', people: current.age_15_19 },
    { age: '20–24', people: current.age_20_24 },
    { age: '25–29', people: current.age_25_29 },
    { age: '30–34', people: current.age_30_34 },
    { age: '35–39', people: current.age_35_39 },
  ]
  const genderData = [
    { name: '男性', value: current.male_youth, color: 'var(--mono-ink)' },
    { name: '女性', value: current.female_youth, color: 'var(--mono-secondary)' },
  ]
  const displayDistrict = district === 'New Taipei City' ? '新北市' : district
  const educationYear = publishedYearAtOrBefore(educationRows, year)
  const marriageYear = publishedYearAtOrBefore(marriageRows, year)
  const educationData = educationCategories.map(category => ({
    level: category.label,
    people: educationRows
      .filter(row => row.year === educationYear && row.district === district && category.levels.includes(row.level))
      .reduce((sum, row) => sum + row.people, 0),
  }))
  const educationTotal = educationData.reduce((sum, item) => sum + item.people, 0)
  const tertiaryEducation = educationData
    .filter(item => ['專科', '大學', '研究所'].includes(item.level))
    .reduce((sum, item) => sum + item.people, 0)
  const marriageData = marriageStatuses.map(status => ({
    status: status.label,
    people: marriageRows
      .filter(row => row.year === marriageYear && row.district === district && row.status === status.raw)
      .reduce((sum, row) => sum + row.people, 0),
    color: status.color,
  }))
  const marriageTotal = marriageData.reduce((sum, item) => sum + item.people, 0)
  const married = marriageData.find(item => item.status === '有偶')?.people ?? 0
  const migrationSummary = migrationSummaryRows.find(row => row.district === district)
  const selectedMigrationRows = migrationRows
    .filter(row => row.district === district)
    .sort((a, b) => a.period.localeCompare(b.period))
  const latestMigrationActual = [...selectedMigrationRows].reverse().find(row => row.series === 'actual')
  const migrationChartData = selectedMigrationRows.map(row => ({
    ...row,
    actual: row.series === 'actual' ? row.people : null,
    forecast: row.series === 'forecast' || row.period === latestMigrationActual?.period ? row.people : null,
    intervalBase: row.series === 'forecast' ? row.lower : null,
    intervalRange: row.series === 'forecast' && row.lower !== null && row.upper !== null ? row.upper - row.lower : null,
  }))
  const formatMigrationPeriod = (periodValue: string) => {
    const [periodYear, periodMonth] = periodValue.split('-').map(Number)
    if (periodMonth !== 1 && periodMonth !== 7) return ''
    return `${String(periodYear).slice(-2)} 年 ${periodMonth} 月`
  }
  const annualChangeSeries = trendData.slice(1).map((item, index) => {
    const earlier = trendData[index]
    return (item.youth_population - earlier.youth_population) / earlier.youth_population
  })
  const rankSeries = district === 'New Taipei City'
    ? trendData.map(() => 29)
    : trendData.map(item => {
      const districtRank = rows
        .filter(row => row.year === item.year && row.district_code !== 0)
        .sort((a, b) => b.youth_population - a.youth_population)
        .findIndex(row => row.district === district) + 1
      return districtRank > 0 ? 30 - districtRank : 0
    })
  const policySignals: SignalItem[] = [
    {
      icon: 'trend',
      label: '長期趨勢',
      text: <>目前青年人口較最早資料{trendData[0].youth_population > current.youth_population ? '減少' : '增加'} {percent.format(Math.abs(current.youth_population / trendData[0].youth_population - 1))}。</>,
      tone: 'bg-blue-50 text-blue-700 dark:bg-blue-400/10 dark:text-blue-300',
    },
    {
      icon: 'users',
      label: '性別結構',
      text: <>此檢視中的女性青年占戶籍青年人口 {percent.format(current.female_youth / current.youth_population)}。</>,
      tone: 'bg-teal-50 text-teal-700 dark:bg-teal-400/10 dark:text-teal-300',
    },
    {
      icon: 'calendar',
      label: '資料期別',
      text: <>{year} 年採用第 {current.month} 月資料，跨年比較時請留意基準月份。</>,
      tone: 'bg-amber-50 text-amber-700 dark:bg-amber-400/10 dark:text-amber-300',
    },
  ]

  const snapshotPeriod = `${year}-${String(current.month).padStart(2, '0')}`
  const commonContext = { district: displayDistrict, districtCode: String(current.district_code), selectedYear: year }
  const annualPeriod = (release: number | null) => release ? { start: `${release}-01`, end: `${release}-12` } : null
  const contexts: ChartContext[] = [
    {
      ...commonContext, id: 'population-trend', title: '青年人口趨勢', metric: 'youth_population',
      period: { start: `${trendData[0].year}-${String(trendData[0].month).padStart(2, '0')}`, end: snapshotPeriod },
      scope: '15–39 歲戶籍青年人口', unit: 'persons', source: 'youth_population_summary.csv',
      points: trendData.map(row => ({ label: String(row.year), value: row.youth_population, period: `${row.year}-${String(row.month).padStart(2, '0')}` })),
      warnings: [`年度快照採用當年最新可用月份；${year} 年為第 ${current.month} 月，各年資料可能涵蓋不同月份。`, '人口變化無法辨識遷徙流向，也不能據此建立因果關係。'],
    },
    {
      ...commonContext, id: 'age-structure', title: '年齡結構', metric: 'youth_age_distribution',
      period: { start: snapshotPeriod, end: snapshotPeriod }, scope: '15–39 歲戶籍青年人口', unit: 'persons',
      source: 'youth_population_summary.csv', points: ageData.map(point => ({ label: point.age, value: point.people, period: snapshotPeriod })),
      warnings: ['五歲年齡組是單一時間快照，不代表同一群人隨時間的推估變化。'],
    },
    {
      ...commonContext, id: 'education-levels', title: '教育程度', metric: 'education_distribution',
      period: annualPeriod(educationYear), scope: '有登記教育程度的全體居民', unit: 'persons',
      source: 'education_summary.csv', points: educationYear ? educationData.map(point => ({ label: point.level, value: point.people, period: String(educationYear) })) : [],
      warnings: ['教育資料涵蓋有登記教育程度的居民，不限青年；13 個來源層級已彙整為 6 類。',
        educationYear ? `此為 ${educationYear} 年發布資料，不一定等於所選的 ${year} 年；CSV 未註明基準月份。` : '教育資料自 2017 年起提供。'],
    },
    {
      ...commonContext, id: 'marriage-status', title: '婚姻狀況', metric: 'youth_marriage_distribution',
      period: annualPeriod(marriageYear), scope: '15–39 歲戶籍青年人口', unit: 'persons',
      source: 'marriage_summary.csv', points: marriageYear ? marriageData.map(point => ({ label: point.status, value: point.people, period: String(marriageYear) })) : [],
      warnings: ['婚姻狀況為人口快照，不代表結婚事件或新組成家戶數。',
        marriageYear ? `此為 ${marriageYear} 年發布資料；CSV 未註明基準月份。` : '婚姻資料自 2019 年起提供。'],
    },
    {
      ...commonContext, id: 'migration-forecast', title: '遷出人口預測', metric: 'outbound_migration',
      period: migrationSummary ? annualPeriod(migrationSummary.forecast_year) : null, scope: '全年齡遷出人次；既有 2026 年預測', unit: 'moves',
      source: 'migration_forecast_summary.csv',
      points: migrationSummary ? [{ label: '2026 年預測', value: migrationSummary.forecast_total, period: '2026', estimated: true }] : [],
      warnings: ['這項固定的 2026 年預測不受資料年份篩選器影響；它是既有季節性基準模型，不是由此助理即時預測。',
        '數值為全年齡遷徙人次，不是獨立人數或青年專屬遷出量；來源未提供目的行政區。',
        migrationSummary ? `80% 預測區間為 ${integer.format(migrationSummary.forecast_lower)}–${integer.format(migrationSummary.forecast_upper)} 人次，估計具有不確定性。` : '目前沒有可用預測。'],
    },
  ]
  const assistantContext = contexts.find(chart => chart.id === assistantChart) || contexts[0]
  const actionOption = (action: DashboardAction) => {
    const unavailable = (reason: string) => ({ label: '無法套用建議操作', reason, apply: () => {} })
    if (action.type === 'OPEN_PANEL' && typeof action.value === 'string') {
      const panel = action.value === 'forecast' ? 'migration-forecast' : action.value
      if (!['overview', 'population-trend', 'district-profile', 'age-structure', 'migration-forecast', 'education-levels', 'marriage-status', 'data-methods'].includes(panel)) return unavailable('不支援建議的面板。')
      const panelName = contexts.find(item => item.id === panel)?.title ?? '指定面板'
      return { label: `開啟${panelName}`, apply: () => navigateTo(panel) }
    }
    if (action.type === 'SELECT_DISTRICTS' && action.values?.length === 1) {
      const code = action.values[0]
      const target = /^\d{1,2}$/.test(code) ? rows.find(row => row.year === year && row.district_code === Number(code)) : undefined
      return target ? { label: `選擇${target.district}`, apply: () => setDistrict(target.district) } : unavailable('建議的行政區不在此資料集中。')
    }
    if (action.type === 'SET_PERIOD' && typeof action.value === 'object') {
      const period = action.value
      const targetYear = Number(period.end.slice(0, 4))
      if (period.start !== period.end || !years.includes(targetYear) ||
          Number(period.end.slice(5)) !== yearMonths[targetYear]) return unavailable('儀表板僅支援已發布的年度快照，不支援任意日期區間。')
      return { label: `使用 ${targetYear} 年資料`, apply: () => setYear(targetYear) }
    }
    if (action.type === 'SET_METRIC') {
      const chart = contexts.find(item => item.metric === action.value)
      if (chart) return { label: `查看${chart.title}`, apply: () => { setAssistantChart(chart.id); navigateTo(chart.id) } }
    }
    return unavailable('系統不會自動套用多行政區操作或未支援的指標。')
  }

  return (
    <FloatingScene>
    <div className="spatial-dashboard">
      <section id="overview" className="civic-hero relative isolate scroll-mt-28">
        <div className="hero-copy-grid hero-spatial-layout relative z-10 grid gap-6">
          <div className="hero-editorial">
            <FloatingElement phase={0} strength={1.2}><h2 className="hero-title">更清楚地看見<em>新北青年</em>的樣貌。</h2></FloatingElement>
            <FloatingElement phase={2} strength={0.7}><p className="hero-copy mt-6 max-w-xl text-[16px] leading-7">透過清理後的公開資料，探索 29 個行政區的人口、地方與世代如何變化。</p></FloatingElement>
            <FloatingElement phase={3} className="hero-action" strength={0.6}>
            <a href="/data/youth_population_summary.csv" download className="hero-download depth-button mt-7 inline-flex min-h-11 items-center gap-3 rounded-lg border px-4 py-2.5 text-[13px] font-semibold">
              <Icon name="download" className="h-4 w-4" />下載人口 CSV
            </a>
            </FloatingElement>
          </div>
        <div className="hero-filter-dock relative z-20">
          <Filters district={district} districts={districts} month={current.month} onDistrictChange={setDistrict} onYearChange={setYear} year={year} yearMonths={yearMonths} years={years} />
        </div>
          <FloatingElement className="hero-city-panel" phase={2} strength={0.6} reading>
            <p className="city-overline">從數據俯瞰城市 <span>{year}</span></p>
            <CityDepth records={districtRows} year={year} district={district} />
            <div className="hero-city-caption">
              <span>29 個行政區，一座城市</span><span>青年人口相對規模</span>
            </div>
            <p className="city-explanation">每個方塊代表一個行政區，高度呈現青年人口；位置僅供示意。</p>
          </FloatingElement>
        </div>
      </section>

      <section aria-label="主要指標" className="indicator-grid grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="青年人口" value={integer.format(current.youth_population)} icon="users" series={trendData.map(item => item.youth_population)} tone="blue" detail={<><span className="font-semibold text-slate-700 dark:text-slate-200">15–39 歲</span>・{displayDistrict}</>} />
        <KpiCard label="占總人口比例" value={percent.format(youthShare)} icon="percent" series={trendData.map(item => item.youth_population / item.total_population)} tone="emerald" detail={<>總戶籍人口 {integer.format(current.total_population)} 人</>} />
        <KpiCard
          label="較前期變化"
          value={previous ? `${change >= 0 ? '+' : ''}${percent.format(change)}` : '—'}
          icon={previous && change < 0 ? 'arrow-down' : 'arrow-up'}
          series={annualChangeSeries}
          tone="orange"
          detail={previous
            ? <span className={change >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400'}>{changeValue >= 0 ? '+' : ''}{integer.format(changeValue)} 人・相較 {previous.year} 年</span>
            : '無較早期資料'}
        />
        <KpiCard
          label={district === 'New Taipei City' ? '資料涵蓋率' : '行政區排名'}
          value={district === 'New Taipei City' ? '29 / 29' : `#${selectedRank}`}
          icon="building"
          series={rankSeries}
          tone="cyan"
          detail={district === 'New Taipei City' ? '涵蓋全部行政區' : '依青年人口於 29 個行政區中排名'}
        />
      </section>

      <div className="dashboard-grid scroll-reveal grid grid-cols-1 gap-px xl:grid-cols-3" data-scroll-reveal>
        <Card id="population-trend" className="xl:col-span-2">
          <CardHeader title="青年人口趨勢" subtitle={`${displayDistrict}・年度發布快照`} tag={`${trendData[0]?.year}–${year}`} onAsk={() => askChart('population-trend')} />
          <div aria-label={`${displayDistrict}自 ${trendData[0]?.year} 年至 ${year} 年的青年人口趨勢；最新值為 ${integer.format(current.youth_population)} 人。`} data-chart-design="amicro-mono-curved-wave" className="chart-well h-[330px] px-2 pb-3 pr-4 sm:h-[390px] sm:px-4 sm:pb-5" role="img">
            <ChartMotion motionKey={`${district}:${year}:${drawVersion}`}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trendData} margin={{ top: 22, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="youthTrend" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--mono-ink)" stopOpacity={0.28} />
                    <stop offset="92%" stopColor="var(--mono-ink)" stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--mono-grid)" strokeDasharray="2 3" vertical={false} />
                <XAxis axisLine={false} dataKey="year" dy={10} tick={{ fill: 'var(--mono-muted)', fontSize: 12 }} tickLine={false} />
                <YAxis
                  axisLine={false}
                  domain={[
                    (dataMin: number) => Math.max(0, Math.floor((dataMin * 0.9) / 1000) * 1000),
                    (dataMax: number) => Math.ceil((dataMax * 1.05) / 1000) * 1000,
                  ]}
                  tick={{ fill: 'var(--mono-muted)', fontSize: 12 }}
                  tickFormatter={value => compact.format(Number(value))}
                  tickLine={false}
                  width={50}
                />
                <Tooltip content={<MetricTooltip valueLabel="戶籍青年人口" />} cursor={{ stroke: 'var(--mono-secondary)', strokeDasharray: '4 4' }} />
                <Area activeDot={{ r: 5, strokeWidth: 3, stroke: 'var(--panel)' }} dot={trendData.length === 1 ? { r: 4, fill: 'var(--mono-ink)' } : false} dataKey="youth_population" fill="url(#youthTrend)" isAnimationActive={false} stroke="var(--mono-ink)" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" type="monotone" />
              </AreaChart>
            </ResponsiveContainer>
            </ChartMotion>
          </div>
          <div className="chart-end-value"><span>最新快照・{snapshotPeriod}：<strong>{integer.format(current.youth_population)} 名青年</strong></span>
            {!reducedMotion && <button className="ai-ask-chart" type="button" onClick={() => setDrawVersion(value => value + 1)}>重播繪製動畫</button>}</div>
        </Card>

        <PolicySignalCard
          cohortLabel={largestCohort.label}
          cohortShare={largestCohort.value / current.youth_population}
          cohortValue={largestCohort.value}
          signals={policySignals}
          year={year}
        />
      </div>

      <div className="analysis-stack">
        <Card id="district-profile" className="xl:col-span-3">
          <CardHeader title="一座城市，29 種地方樣貌" subtitle={`探索地圖，認識 ${year} 年各行政區的人口樣貌。`} tag="行政區剖面" />
          <div className="district-atlas-layout">
          <DistrictMap records={districtRows} district={district} year={year} onSelect={setDistrict} />
          <FloatingElement className="district-stats-island" phase={3} strength={0.4} reading>
            <DistrictStats current={current} previous={previous} largestCohort={largestCohort} onClear={() => setDistrict('New Taipei City')} />
          </FloatingElement>
          </div>
        </Card>

        <Card id="age-structure" className="xl:col-span-2">
          <CardHeader title="年齡結構" subtitle={`${displayDistrict}・五歲年齡組`} tag="15–39 歲" onAsk={() => askChart('age-structure')} />
          <div aria-label={`${displayDistrict}青年年齡分布；最大五歲年齡組為 ${largestCohort.label} 歲，共 ${integer.format(largestCohort.value)} 人。`} className="chart-well h-[390px] px-3 pb-5 pr-5 sm:px-5" role="img">
            <MonoPillBars data={ageData} nameKey="age" valueLabel="該年齡組人數" />
          </div>
        </Card>
      </div>

      <div className="dashboard-grid scroll-reveal grid grid-cols-1 gap-px xl:grid-cols-3" data-scroll-reveal>
        <Card id="migration-forecast" className="xl:col-span-2">
          <CardHeader
            title="遷出人口預測"
            onAsk={() => askChart('migration-forecast')}
            subtitle={`${displayDistrict}・遷往其他鄉鎮市區的人次`}
            tag="2026 年估計"
          />
          {migrationSummary ? (
            <>
              <div aria-label={`${displayDistrict}自 2023 至 2025 年的實際遷出與 2026 年預測；預測總數 ${integer.format(migrationSummary.forecast_total)} 人次，80% 區間為 ${integer.format(migrationSummary.forecast_lower)} 至 ${integer.format(migrationSummary.forecast_upper)} 人次。`} data-chart-design="amicro-mono-range-wave" className="chart-well h-[350px] px-2 pb-3 pr-4 sm:h-[410px] sm:px-4 sm:pb-5" role="img">
                <ChartMotion motionKey={district}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={migrationChartData} margin={{ top: 22, right: 8, bottom: 0, left: 0 }}>
                    <defs>
                      <linearGradient id="migrationActual" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--mono-ink)" stopOpacity={0.18} />
                        <stop offset="92%" stopColor="var(--mono-ink)" stopOpacity={0.01} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="var(--mono-grid)" strokeDasharray="2 3" vertical={false} />
                    <XAxis
                      axisLine={false}
                      dataKey="period"
                      dy={10}
                      interval={0}
                      minTickGap={2}
                      tick={{ fill: 'var(--mono-muted)', fontSize: 10 }}
                      tickFormatter={formatMigrationPeriod}
                      tickLine={false}
                    />
                    <YAxis axisLine={false} tick={{ fill: 'var(--mono-muted)', fontSize: 12 }} tickFormatter={value => compact.format(Number(value))} tickLine={false} width={50} />
                    <Tooltip content={<MigrationTooltip />} cursor={{ stroke: 'var(--mono-secondary)', strokeDasharray: '4 4' }} />
                    <Area dataKey="intervalBase" fill="transparent" isAnimationActive={false} stackId="confidence" stroke="none" type="monotone" />
                    <Area dataKey="intervalRange" fill="var(--mono-secondary)" fillOpacity={0.16} isAnimationActive={false} stackId="confidence" stroke="none" type="monotone" />
                    <Area activeDot={{ r: 4, strokeWidth: 3, stroke: 'var(--panel)' }} dataKey="actual" fill="url(#migrationActual)" isAnimationActive={false} stroke="var(--mono-ink)" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" type="monotone" />
                    <Area activeDot={{ r: 4, strokeWidth: 3, stroke: 'var(--panel)' }} dataKey="forecast" fill="transparent" isAnimationActive={false} stroke="var(--mono-secondary)" strokeDasharray="4 4" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" type="monotone" />
                  </AreaChart>
                </ResponsiveContainer>
                </ChartMotion>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4 text-xs dark:border-white/10">
                <div className="flex flex-wrap items-center gap-4 text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-2"><span className="mono-legend-line" />實際值</span>
                  <span className="inline-flex items-center gap-2"><span className="mono-legend-line is-forecast" />預測值</span>
                  <span className="inline-flex items-center gap-2"><span className="mono-legend-band" />80% 區間</span>
                </div>
                <a className="font-semibold text-blue-700 transition hover:text-blue-800 dark:text-blue-300 dark:hover:text-blue-200" download href="/data/migration_forecast.csv">下載預測 CSV</a>
              </div>
            </>
          ) : (
            <div className="grid h-[410px] place-items-center px-6 text-center text-sm text-slate-400">此行政區目前沒有遷徙預測。</div>
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader title="預測摘要" subtitle="可供規劃參考，並附不確定性" tag={migrationSummary ? '季節性基準' : '基準模型'} />
          {migrationSummary && (
            <div className="px-5 pb-6 pt-3 sm:px-6">
              <div className="insight-stat">
                <div className="relative">
                  <p className="text-xs font-bold uppercase tracking-[0.13em] text-teal-300">2026 年預估遷出</p>
                  <p className="mt-4 text-4xl font-bold tracking-[-0.05em]">{integer.format(migrationSummary.forecast_total)}</p>
                  <p className="mt-2 text-xs text-slate-300">80% 區間・{integer.format(migrationSummary.forecast_lower)}–{integer.format(migrationSummary.forecast_upper)}</p>
                  <div className="mt-5 flex items-center justify-between border-t border-white/10 pt-4 text-xs">
                    <span className="text-slate-400">相較 2025 年</span>
                    <span className={migrationSummary.forecast_change_pct >= 0 ? 'font-semibold text-teal-300' : 'font-semibold text-rose-300'}>
                      {migrationSummary.forecast_change_pct >= 0 ? '+' : ''}{migrationSummary.forecast_change_pct.toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-3">
                <div className="rounded-xl bg-slate-50 p-3.5 dark:bg-white/[0.04]">
                  <p className="text-xs font-bold uppercase tracking-[0.1em] text-slate-400">2025 年實際值</p>
                  <p className="mt-1.5 text-lg font-bold text-slate-900 dark:text-white">{integer.format(migrationSummary.latest_actual_total)}</p>
                </div>
                <div className="rounded-xl bg-slate-50 p-3.5 dark:bg-white/[0.04]">
                  <p className="text-xs font-bold uppercase tracking-[0.1em] text-slate-400">回測誤差</p>
                  <p className="mt-1.5 text-lg font-bold text-slate-900 dark:text-white">{migrationSummary.backtest_wape_pct.toFixed(1)}%</p>
                </div>
              </div>

              <div className="mt-4 rounded-xl border border-amber-200/70 bg-amber-50/70 p-4 dark:border-amber-300/10 dark:bg-amber-300/[0.05]">
                <div className="flex gap-3">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-amber-100 text-amber-700 dark:bg-amber-300/10 dark:text-amber-300"><Icon name="info" className="h-4 w-4" /></span>
                  <p className="text-xs leading-5 text-amber-900/75 dark:text-amber-100/65">
                    本資料涵蓋全年齡層。來源僅標示「其他鄉鎮市區」，未提供目的行政區，因此預測的是遷出人次，而非精確的行政區間路徑。
                  </p>
                </div>
              </div>
            </div>
          )}
        </Card>
      </div>

      <FloatingElement phase={2} strength={0.8}><div className="social-intro flex flex-col justify-between gap-2 pt-2 sm:flex-row sm:items-end">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.14em] text-teal-700 dark:text-teal-300">社會指標</p>
          <h3 className="mt-1 text-xl font-bold tracking-tight text-slate-900 dark:text-white">教育與家庭脈絡</h3>
        </div>
        <p className="max-w-xl text-xs leading-5 text-slate-500 sm:text-right dark:text-slate-400">若所選年份超出主題資料涵蓋範圍，系統會顯示並標示最近的相容資料。</p>
      </div></FloatingElement>

      <div className="analysis-stack">
        <Card id="education-levels" className="xl:col-span-3">
          <CardHeader
            title="教育程度"
            onAsk={() => askChart('education-levels')}
            subtitle={`${displayDistrict}・有登記教育程度的居民`}
            tag={educationYear ? `${educationYear} 年${educationYear < year ? '・最新可用' : ''}` : '無可用資料'}
          />
          {educationYear ? (
            <>
              <div aria-label={`${displayDistrict} ${educationYear} 年教育程度分布；專科以上教育程度占有登記居民的 ${percent.format(tertiaryEducation / educationTotal)}。`} className="chart-well h-[390px] px-3 pb-4 pr-5 sm:px-5" role="img">
                <MonoPillBars data={educationData} nameKey="level" horizontal labelWidth={112} valueLabel="登記居民" />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-5 py-4 text-xs dark:border-white/10">
                <span className="text-slate-500 dark:text-slate-400">由 13 個標準化來源層級彙整</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">專科以上：{percent.format(tertiaryEducation / educationTotal)}</span>
              </div>
            </>
          ) : (
            <div className="grid h-[438px] place-items-center px-6 text-center text-sm text-slate-400">教育資料自 2017 年起提供，請選擇較晚年份查看分析。</div>
          )}
        </Card>

        <Card id="marriage-status" className="xl:col-span-2">
          <CardHeader
            title="婚姻狀況"
            onAsk={() => askChart('marriage-status')}
            subtitle={`${displayDistrict}・15–39 歲青年`}
            tag={marriageYear ? `${marriageYear} 年${marriageYear < year ? '・最新可用' : ''}` : '無可用資料'}
          />
          {marriageYear ? (
            <>
              <div aria-label={`${displayDistrict} ${marriageYear} 年青年婚姻狀況分布；有偶青年占 ${percent.format(married / marriageTotal)}。`} className="chart-well h-[390px] px-3 pb-4 pr-5 sm:px-5" role="img">
                <MonoPillBars data={marriageData} nameKey="status" horizontal labelWidth={78} valueLabel="青年人口" />
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-5 py-4 text-xs dark:border-white/10">
                <span className="text-slate-500 dark:text-slate-400">共呈現 {integer.format(marriageTotal)} 名青年</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">有偶：{percent.format(married / marriageTotal)}</span>
              </div>
            </>
          ) : (
            <div className="grid h-[438px] place-items-center px-6 text-center text-sm text-slate-400">婚姻資料自 2019 年起提供，請選擇較晚年份查看分析。</div>
          )}
        </Card>
      </div>

      <AiAssistant key={`${district}:${year}:${assistantContext.id}`} contexts={contexts} context={assistantContext} onContextChange={setAssistantChart} actionOption={actionOption} />

      <div className="dashboard-grid scroll-reveal grid grid-cols-1 gap-px lg:grid-cols-3" data-scroll-reveal>
        <Card className="lg:col-span-1">
          <CardHeader title="性別結構" subtitle={`${displayDistrict}・${year} 年`} />
          <div aria-label={`${displayDistrict}青年性別結構：男性占 ${percent.format(current.male_youth / current.youth_population)}，女性占 ${percent.format(current.female_youth / current.youth_population)}。`} className="chart-well relative h-[260px]" role="img">
            <MonoDonut data={genderData} />
          </div>
          <div className="grid grid-cols-2 gap-3 px-5 pb-6 sm:px-6">
            {genderData.map(item => (
              <div className="rounded-xl bg-slate-50 p-3 dark:bg-white/[0.04]" key={item.name}>
                <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400"><span className="h-2 w-2 rounded-full" style={{ background: item.color }} />{item.name}</div>
                <p className="mt-1 text-sm font-bold text-slate-900 dark:text-white">{percent.format(item.value / current.youth_population)}</p>
              </div>
            ))}
          </div>
        </Card>

        <Card id="data-methods" className="lg:col-span-2">
          <CardHeader title="資料說明與方法" subtitle="如何閱讀這份儀表板" tag="透明可追溯" />
          <div className="grid gap-px overflow-hidden border-t border-slate-100 bg-slate-100 sm:grid-cols-2 dark:border-white/10 dark:bg-white/10">
            {[
              { icon: 'database' as IconName, label: '資料來源', text: '清理後的新北市人口、教育、婚姻與遷徙 CSV 發布資料。' },
              { icon: 'users' as IconName, label: '青年定義', text: '15 至 39 歲（含）的戶籍人口。' },
              { icon: 'calendar' as IconName, label: '時間基準', text: `採各年最新可用月份；${year} 年使用第 ${current.month} 月資料。` },
              { icon: 'districts' as IconName, label: '地理範圍', text: '涵蓋全部 29 個行政區，另含全市彙整。' },
              { icon: 'education' as IconName, label: '教育範圍', text: '涵蓋有登記教育程度的全體居民，並將類別分組以利比較。' },
              { icon: 'heart' as IconName, label: '婚姻範圍', text: '婚姻狀況限定於同一套 15–39 歲青年人口。' },
              { icon: 'migration' as IconName, label: '遷徙範圍', text: '涵蓋全年齡層遷往來源分類「其他鄉鎮市區」的人次；未提供目的行政區。' },
              { icon: 'trend' as IconName, label: '預測方法', text: '以 2018–2025 年訓練季節性趨勢基準，提供 80% 區間與 2025 年時間回測。' },
            ].map(item => (
              <div className="flex gap-3 bg-white p-5 dark:bg-[#0d1b2a]" key={item.label}>
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600 dark:bg-white/[0.06] dark:text-slate-300"><Icon name={item.icon} className="h-[18px] w-[18px]" /></span>
                <div><p className="text-xs font-semibold text-slate-800 dark:text-slate-200">{item.label}</p><p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{item.text}</p></div>
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-2 border-t border-slate-100 px-5 py-4 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between dark:border-white/10">
            <span>人口資料 {years[years.length - 1]}–{years[0]}・遷徙歷史 2018–2025・遷徙預測 2026</span>
            <span>預測是估計值，不代表個人結果。</span>
          </div>
        </Card>
      </div>
    </div>
    </FloatingScene>
  )
}
