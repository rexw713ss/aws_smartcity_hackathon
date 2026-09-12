import type { CopilotStatus, VisualizationValue } from './copilot'

// UI chrome is English. Chart titles, axis labels, and entity names come from the
// backend, which localizes them to the language of the question — so a question
// asked in Traditional Chinese still returns Chinese labels inside these charts.
const locale = 'en'

const integer = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 })
const decimal = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 })
export const compact = new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 })
const percent = new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 })

/** Format for display only. The backend owns every value and every calculation. */
export function formatNumber(value: number): string {
  return Number.isInteger(value) ? integer.format(value) : decimal.format(value)
}

export function formatCell(value: VisualizationValue): string {
  if (value === null) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') return formatNumber(value)
  return value
}

export function formatQuality(score: number): string {
  return percent.format(score)
}

export function formatTimestamp(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

export const statusLabels: Record<CopilotStatus, { label: string; tone: 'ok' | 'warn' | 'info' }> = {
  answered: { label: 'Answered from published data', tone: 'ok' },
  insufficient_data: { label: 'Insufficient evidence', tone: 'warn' },
  acquisition_required: { label: 'Source required', tone: 'info' },
  unsupported_question: { label: 'Unsupported question', tone: 'warn' },
}

export const statusDetail: Record<CopilotStatus, string> = {
  answered: 'Every figure comes from an approved, published dataset and carries its citation.',
  insufficient_data: 'The catalog holds too little qualifying evidence, so no recommendation is offered.',
  acquisition_required: 'The catalog is missing the data this question needs. Submit one configured source for review.',
  unsupported_question: 'No registered tool can answer this. The system will not assemble a partial answer.',
}

/** Series colours come from the shared token palette, never from the response. */
export const seriesColors = [
  'var(--chart-primary)',
  'var(--chart-secondary)',
  'var(--chart-tertiary)',
  'var(--chart-warning)',
  'var(--chart-coral)',
] as const

export const colorFor = (index: number): string => seriesColors[index % seriesColors.length]
