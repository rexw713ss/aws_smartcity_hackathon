import type { CopilotResponse, VisualizationSpec } from './copilot'
import { resolveDistrict, type District } from './districts'

export type DistrictHighlight = {
  district: District
  /** The grounded figure the backend attached to this entity, if any. */
  value: number | null
  valueLabel: string | null
  unit: string | null
  rank: number | null
  /** Which visualization this reading came from, for the readout. */
  source: string
}

export type HighlightSet = {
  byCode: Map<string, DistrictHighlight>
  /** Entity ids the backend returned that are not districts (sites, grid cells). */
  unplaceable: string[]
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

/** Collect the districts a grounded answer actually spoke about.
 *
 * Reads only the visualization rows the backend already returned — no extra
 * request, no recalculation, and no inference about entities that are not
 * districts. An entity that does not resolve exactly is reported, not guessed. */
export function districtHighlights(response: CopilotResponse | null): HighlightSet {
  const byCode = new Map<string, DistrictHighlight>()
  const unplaceable = new Set<string>()
  if (!response) return { byCode, unplaceable: [], maximum: 0 }

  for (const spec of response.visualizations) {
    const reading = readingField(spec)
    for (const row of spec.rows) {
      const id = row.entity_id ?? row.district_code ?? null
      const label = row.entity_name ?? row.district_name ?? null
      const district =
        resolveDistrict(typeof id === 'string' ? id : null) ??
        resolveDistrict(typeof label === 'string' ? label : null)

      if (!district) {
        const shown = typeof label === 'string' ? label : typeof id === 'string' ? id : null
        if (shown) unplaceable.add(shown)
        continue
      }
      // First spec wins: the backend orders decision rankings first, so the
      // ranking reading is the one a reader expects to see on the map.
      if (byCode.has(district.code)) continue
      const value = reading ? numeric(row[reading.field]) : null
      byCode.set(district.code, {
        district,
        value,
        valueLabel: reading?.label ?? null,
        unit: reading?.unit ?? null,
        rank: numeric(row.rank),
        source: spec.title,
      })
    }
  }

  const maximum = [...byCode.values()].reduce(
    (top, item) => (item.value !== null && item.value > top ? item.value : top),
    0,
  )
  return { byCode, unplaceable: [...unplaceable], maximum }
}
