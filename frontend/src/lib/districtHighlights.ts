import type { CopilotResponse, VisualizationSpec, VisualizationValue } from './copilot'
import { resolveDistrict, type District } from './districts'

export type DistrictHighlight = {
  district: District
  /** The grounded figure the backend attached to this entity, if any. */
  value: number | null
  valueLabel: string | null
  unit: string | null
  rank: number | null
  period: string | null
  /** Which visualization this reading came from, for the readout. */
  source: string
}

export type HighlightSet = {
  byCode: Map<string, DistrictHighlight>
  /** Entity ids the backend returned that are not districts (sites, grid cells). */
  unplaceable: string[]
  /** Observed value range of the driving visualization; a change metric is negative. */
  minimum: number
  maximum: number
}

const numeric = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

/** Prefer a spec that carries a quantitative reading per entity. */
function readingField(spec: VisualizationSpec): { field: string; label: string; unit: string | null } | null {
  for (const encoding of [spec.y, spec.x]) {
    if (encoding && encoding.data_type === 'quantitative') {
      return { field: encoding.field, label: encoding.label, unit: encoding.unit }
    }
  }
  const column = spec.columns.find(item => item.field === 'score' || item.field === 'value')
  return column ? { field: column.field, label: column.label, unit: column.unit } : null
}

const districtFor = (row: Record<string, VisualizationValue>) => {
  // `district_code` is the declared region key on a choropleth; `entity_id` is
  // what every other spec carries. Prefer the declared key when both exist.
  const id = row.district_code ?? row.entity_id ?? null
  const label = row.entity_name ?? row.district_name ?? null
  const district =
    resolveDistrict(typeof id === 'string' ? id : null) ??
    resolveDistrict(typeof label === 'string' ? label : null)
  const shown = typeof label === 'string' ? label : typeof id === 'string' ? id : null
  return { district, shown }
}

/** Collect the districts a grounded answer actually spoke about.
 *
 * Reads only the visualization rows the backend already returned — no extra
 * request, no recalculation, and no inference about entities that are not
 * districts. An entity that does not resolve exactly is reported, not guessed.
 *
 * Exactly one visualization drives the map. A single answer can carry several
 * with different quantities — a trend returns population per month alongside
 * absolute change per district, and the change values are negative — so merging
 * them would paint one colour scale from two incompatible units.
 *
 * A `choropleth` spec wins outright when the backend sends one: it already
 * states which field is the region key, which boundary set it belongs to, and
 * which single period it describes. Only when no such spec arrives does this
 * fall back to inferring the driving spec, which is why the fallback keeps its
 * own rule — the spec covering the most districts wins. */
export function districtHighlights(response: CopilotResponse | null): HighlightSet {
  const empty: HighlightSet = { byCode: new Map(), unplaceable: [], minimum: 0, maximum: 0 }
  if (!response) return empty

  const unplaceable = new Set<string>()
  let best: { spec: VisualizationSpec; rows: Map<string, Record<string, VisualizationValue>> } | null = null

  // The backend drops non-district entities from a choropleth, so unplaceable
  // ones are gathered from every spec; only the driving spec is restricted.
  const declared = response.visualizations.filter(spec => spec.type === 'choropleth')
  const driving = declared.length ? declared : response.visualizations
  for (const spec of response.visualizations) {
    const rows = new Map<string, Record<string, VisualizationValue>>()
    for (const row of spec.rows) {
      const { district, shown } = districtFor(row)
      if (!district) {
        if (shown) unplaceable.add(shown)
        continue
      }
      // Keep the first row per district: a trend carries one row per period.
      if (!rows.has(district.code)) rows.set(district.code, row)
    }
    if (!driving.includes(spec)) continue
    if (!best || rows.size > best.rows.size) best = { spec, rows }
  }

  if (!best || best.rows.size === 0) {
    return { ...empty, unplaceable: [...unplaceable] }
  }

  const reading = readingField(best.spec)
  const byCode = new Map<string, DistrictHighlight>()
  for (const [code, row] of best.rows) {
    const district = resolveDistrict(code)
    if (!district) continue
    byCode.set(code, {
      district,
      value: reading ? numeric(row[reading.field]) : null,
      valueLabel: reading?.label ?? null,
      unit: reading?.unit ?? null,
      rank: numeric(row.rank),
      period: typeof row.period === 'string' ? row.period : null,
      source: best.spec.title,
    })
  }

  // A change metric is negative across every district, so the scale has to span
  // the observed range rather than assume it starts at zero.
  const values = [...byCode.values()].map(item => item.value).filter((v): v is number => v !== null)
  return {
    byCode,
    unplaceable: [...unplaceable],
    minimum: values.length ? Math.min(...values) : 0,
    maximum: values.length ? Math.max(...values) : 0,
  }
}
