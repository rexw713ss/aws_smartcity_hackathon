import type { CopilotStatus, VisualizationValue } from './copilot'
import type { District } from './districts'
import type { Language } from './i18n'
import { translate } from './i18n'

// UI chrome follows the language picker. Chart titles, axis labels, and entity
// names come from the backend, which localizes them to the language of the
// question — so a question asked in Traditional Chinese still returns Chinese
// labels inside these charts, whichever way the picker is set.
const compactFormatters = new Map<Language, Intl.NumberFormat>()

/** Axis ticks and bar labels, abbreviated in the reader's own locale. */
export function compactFor(language: Language): Intl.NumberFormat {
  const existing = compactFormatters.get(language)
  if (existing) return existing
  const created = new Intl.NumberFormat(language, { notation: 'compact', maximumFractionDigits: 1 })
  compactFormatters.set(language, created)
  return created
}

/** District names follow the reader's language; the code stays the join key. */
export function districtLabel(district: District, language: Language): string {
  return language === 'zh-TW' ? district.name : district.english
}

const acronyms: Record<string, string> = {
  ai: 'AI', api: 'API', co2: 'CO₂', ev: 'EV', gdp: 'GDP', h3: 'H3', id: 'ID',
  km: 'km', ntd: 'NTD', pm25: 'PM2.5', uri: 'URI', url: 'URL',
}

/** Last-mile guard for backend identifiers shown as labels. Internal IDs remain
 * untouched in payloads, joins, and code-styled audit fields. */
export function formatLabel(value: string): string {
  const words = value.trim().split(/[-_\s]+/).filter(Boolean)
  if (!words.length) return value
  return words.map((word, index) => {
    const acronym = acronyms[word.toLowerCase()]
    if (acronym) return acronym
    return index === 0 ? word.charAt(0).toUpperCase() + word.slice(1).toLowerCase() : word.toLowerCase()
  }).join(' ')
}

export function formatEntityLabel(value: string): string {
  const words = value.trim().split(/[-_\s]+/).filter(Boolean)
  if (words.length > 2 && ['candidate', 'location', 'site'].includes(words[0].toLowerCase())) {
    return formatLabel(words.slice(1).join(' ')).replace(/\bEv\b/g, 'EV')
  }
  return formatLabel(value)
}

const unitLabels: Record<string, string | Partial<Record<Language, string>>> = {
  boolean_0_1: { en: 'Yes / No', 'zh-TW': '是／否' },
  chargers_per_demand_index: 'Chargers per demand index',
  ntd_per_sqm: 'NT$/m²',
  persons: { en: 'People', 'zh-TW': '人' },
  score_0_100: 'Score (0–100)',
  score_points: { en: 'Points', 'zh-TW': '分' },
  stops: { en: 'Stops', 'zh-TW': '站位' },
  routes: { en: 'Routes', 'zh-TW': '路線' },
  stops_per_1000_youth: { en: 'Stops per 1,000 youth', 'zh-TW': '每千名青年站位數' },
}

export function formatUnit(unit: string, language: Language = 'en'): string {
  const label = unitLabels[unit]
  return typeof label === 'string' ? label : label?.[language] ?? formatLabel(unit)
}

/** Format for display only. The backend owns every value and every calculation. */
export function formatNumber(value: number, language: Language = 'en'): string {
  const integer = new Intl.NumberFormat(language, { maximumFractionDigits: 0 })
  const decimal = new Intl.NumberFormat(language, { maximumFractionDigits: 2 })
  return Number.isInteger(value) ? integer.format(value) : decimal.format(value)
}

const periodPattern = /^(\d{4})((?:[-/.](?:\d{1,2}|Q[1-4]|H[12]))*)$/

/** Taiwan dates in the Minguo calendar: 2030 → "119 (2030)", 2025-06 → "114-06 (2025)".
 * Only whole-value periods are converted, so ordinary numbers are never touched. */
export function formatPeriod(value: VisualizationValue | undefined, language: Language = 'en'): string {
  if (value === null || value === undefined) return ''
  const text = String(value).trim()
  if (language !== 'zh-TW') return text
  const match = periodPattern.exec(text)
  if (!match) return text
  const year = Number(match[1])
  if (year <= 1911) return text
  return `${year - 1911}${match[2]} (${year})`
}

const hanText = /[\u4e00-\u9fff]/
// A year only in an unmistakable date context — "2025 年", "2025-06", "2023 至 2025" —
// so counts such as "2000 名" stay as written.
const proseYear = /(?<![\d,.])(19[2-9]\d|2[01]\d\d)(?:([-/.]\d{1,2}(?:[-/.]\d{1,2})?)(?!\d)|(?=\s*(?:年|間|至|到|[–~－-]\s*(?:19|2[01])\d\d)))/g

/** Chinese answer prose, streamed or complete: Gregorian years become Minguo years. */
export function formatProseYears(text: string, language: Language = 'en'): string {
  if (language !== 'zh-TW' || !hanText.test(text)) return text
  return text.replace(proseYear, (_, year: string, rest?: string) => `${Number(year) - 1911}${rest ?? ''} (${year})`)
}

export function formatCell(value: VisualizationValue, language: Language = 'en'): string {
  if (value === null) return '—'
  if (typeof value === 'boolean') return value ? (language === 'zh-TW' ? '是' : 'Yes') : (language === 'zh-TW' ? '否' : 'No')
  if (typeof value === 'number') return formatNumber(value, language)
  return formatPeriod(value, language)
}

export function formatQuality(score: number, language: Language = 'en'): string {
  return new Intl.NumberFormat(language, { style: 'percent', maximumFractionDigits: 1 }).format(score)
}

export function formatTimestamp(value: string, language: Language = 'en'): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(language === 'zh-TW' ? 'zh-TW-u-ca-roc' : language, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

export function localizedStatus(language: Language, status: CopilotStatus) {
  const keys = {
    answered: ['answered', 'answeredDetail'],
    insufficient_data: ['insufficient', 'insufficientDetail'],
    acquisition_required: ['sourceRequired', 'sourceRequiredDetail'],
    unsupported_question: ['unsupported', 'unsupportedDetail'],
  } as const
  const tones: Record<CopilotStatus, 'ok' | 'warn' | 'info'> = {
    answered: 'ok', insufficient_data: 'warn', acquisition_required: 'info', unsupported_question: 'warn',
  }
  const [labelKey, detailKey] = keys[status]
  return { label: translate(language, labelKey), detail: translate(language, detailKey), tone: tones[status] }
}

/** Qualitative colours identify nominal series. They intentionally live outside
 * the UI brand palette: a district keeps the same colour across every chart. */
export const seriesColors = [
  'var(--chart-primary)',
  'var(--chart-secondary)',
  'var(--chart-tertiary)',
  'var(--chart-warning)',
  'var(--chart-coral)',
  'var(--chart-gold)',
] as const

export const colorFor = (index: number): string => seriesColors[index % seriesColors.length]

/** A light-to-dark ramp communicates the natural order of age bands without
 * implying that each band is an unrelated nominal category. */
export const orderedColors = [
  'var(--chart-ordered-1)',
  'var(--chart-ordered-2)',
  'var(--chart-ordered-3)',
  'var(--chart-ordered-4)',
] as const

export const orderedColorFor = (index: number): string =>
  orderedColors[index % orderedColors.length]
