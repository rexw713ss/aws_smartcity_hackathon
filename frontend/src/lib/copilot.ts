// Typed against contracts/api/openapi.json — the generated backend contract, not
// the design documents. Regenerate that file with scripts/export_openapi.py and
// re-check this module whenever the copilot response changes.
//
// Casing asymmetry is intentional and matches the backend: REQUEST bodies use
// camelCase aliases (apps/api/schemas.ApiModel), RESPONSE bodies are the domain
// contracts serialized in snake_case.

export const visualizationTypes = ['line', 'slope', 'scatter', 'comparison_bar', 'ranking_bar', 'contribution_bar', 'choropleth', 'data_table'] as const
export type VisualizationType = (typeof visualizationTypes)[number]

/** Boundary sets a choropleth may be keyed against. The spec names the scheme;
 * geometry stays on this side, so the answer contract carries no coordinates. */
export const regionSchemes = ['new_taipei_district'] as const
export type RegionScheme = (typeof regionSchemes)[number]

export const registrationBases = ['registered_household', 'resident', 'unknown'] as const
export type RegistrationBasis = (typeof registrationBases)[number]

export const copilotStatuses = ['answered', 'insufficient_data', 'acquisition_required', 'unsupported_question'] as const
export type CopilotStatus = (typeof copilotStatuses)[number]

export type VisualizationEncoding = { field: string; label: string; data_type: string; unit: string | null }
export type VisualizationColumn = { field: string; label: string; unit: string | null }
export type VisualizationValue = string | number | boolean | null
export const annotationKinds = ['peak', 'trough', 'turning_point', 'latest'] as const
export type AnnotationKind = (typeof annotationKinds)[number]
export type VisualizationAnnotation = {
  kind: AnnotationKind
  label: string
  entity_name: string | null
  period: string | null
  value: number | null
}
export type VisualizationReferenceLine = { label: string; value: number; axis: 'x' | 'y' }

export type VisualizationSpec = {
  schema_version: string
  visualization_id: string
  type: VisualizationType
  title: string
  description: string | null
  x: VisualizationEncoding | null
  y: VisualizationEncoding | null
  series_field: string | null
  band_lower_field: string | null
  band_upper_field: string | null
  region_field: string | null
  region_scheme: RegionScheme | null
  columns: VisualizationColumn[]
  headline: string | null
  annotations: VisualizationAnnotation[]
  reference_lines: VisualizationReferenceLine[]
  focus_entities: string[]
  rows: Record<string, VisualizationValue>[]
  citation_ids: string[]
  truncated: boolean
}

export type DataFreshness = {
  citation_id: string
  dataset_id: string
  dataset_version: string
  published_at: string
  age_days: number
}

export type CoverageGap = {
  region_scheme: RegionScheme
  expected_entity_count: number
  observed_entity_count: number
  missing_entity_names: string[]
  unmapped_entity_ids: string[]
}

export type DataLimitations = {
  freshness: DataFreshness[]
  coverage: CoverageGap | null
  registration_basis: RegistrationBasis
  notes: string[]
}

export type EvidenceCitation = {
  citation_id: string
  dataset_id: string
  dataset_version: string
  quality_score: number
  retrieved_at: string
  excerpt: EvidenceExcerptRow[]
}

export type WebCitation = {
  citation_id: string
  title: string
  url: string
  snippet: string
  published_at: string | null
}

export type EvidenceExcerptRow = {
  entity_id: string
  entity_name: string
  metric_code: string
  metric_name: string
  value: number
  period: string | null
  observed_at: string | null
}

export type ToolTrace = { tool: string; outcome: string; summary: string }

export type SourceCandidate = {
  candidate_id: string
  connector_id: string
  title: string
  publisher: string
  download_url: string
  file_name: string
  source_format: string
  topic_terms: string[]
  metric_codes: string[]
  entity_ids: string[]
  license: string | null
  period_start: string | null
  period_end: string | null
  updated_at: string | null
}

/** What the backend could not find in the published catalog. */
export type DataRequirement = {
  topic_terms: string[]
  metric_codes: string[]
  entity_ids: string[]
  time_expression: string | null
  accepted_formats: string[]
}

export type CopilotResponse = {
  status: CopilotStatus
  answer: string
  generated_at: string
  session_id: string | null
  visualizations: VisualizationSpec[]
  citations: EvidenceCitation[]
  web_citations: WebCitation[]
  tool_trace: ToolTrace[]
  source_candidates: SourceCandidate[]
  data_requirement: DataRequirement | null
  assumptions: string[]
  warnings: string[]
  limitations: DataLimitations | null
  impact_analysis: ImpactAnalysis | null
}

export type ImpactFinding = {
  stage: 'population' | 'housing' | 'transport' | 'public_services'
  label: string
  baseline_value: number | null
  scenario_value: number | null
  absolute_delta: number | null
  unit: string
  evidence_kind: ScenarioEvidenceKind
}

export type ImpactDataGap = {
  domain: 'housing' | 'transport' | 'public_services'
  required_metrics: string[]
  reason: string
}

export type InvestmentRecommendation = {
  priority: number
  domain: 'housing' | 'transport' | 'public_services'
  action: string
  rationale: string
  confidence: 'low' | 'medium' | 'high'
}

export type ImpactAnalysis = {
  district_code: string
  district_name: string
  observed_period: string
  target_year: number
  shock_people: number
  findings: ImpactFinding[]
  data_gaps: ImpactDataGap[]
  recommendations: InvestmentRecommendation[]
  confidence: 'insufficient' | 'low' | 'medium' | 'high'
}

export type ToolCapability = {
  name: string
  operation: string
  description: string
  requires: string[]
}

export type DatasetCatalogItem = {
  datasetId: string
  topic: string
  status: string
  datasetRole: string
  grain: string[]
  populationScope: string
  qualityScore: number
}

export type AcquisitionStart = {
  candidate: SourceCandidate
  ingestion_job_id: string
  ingestion_status: string
  created_at: string
}

/** A reviewer's own link or file, handed to the same approval-gated workflow. */
export type IntakeStart = {
  job_id: string
  status: string
  file_name: string | null
}

export type IntakeOptions = {
  linkHosts: string[]
  uploadFormats: string[]
  maxUploadBytes: number
}

export const scenarioEvidenceKinds = ['official', 'derived', 'user_assumption'] as const
export type ScenarioEvidenceKind = (typeof scenarioEvidenceKinds)[number]

export type DistrictTrendPoint = { period: string; value: number }

export type DistrictBreakdown = {
  key: string
  label: string
  value: number
  sharePercent: number
}

export type DistrictOverview = {
  datasetId: string
  datasetVersion: string
  districtCode: string
  districtName: string | null
  period: string
  unitCode: string
  populationScope: string
  qualityScore: number
  total: number
  previousPeriod: string | null
  absoluteChange: number | null
  percentChange: number | null
  trend: DistrictTrendPoint[]
  ageDistribution: DistrictBreakdown[]
  genderDistribution: DistrictBreakdown[]
}

const isObject = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
const isText = (value: unknown, max = 2000): value is string =>
  typeof value === 'string' && value.length > 0 && value.length <= max
const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const optionalText = (value: unknown, max = 2000): value is string | null =>
  value === null || value === undefined || isText(value, max)

const array = (value: unknown, limit: number): unknown[] => {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > limit) throw new ContractError()
  return value
}

/** The response did not match the published contract. Never shown as data. */
export class ContractError extends Error {
  constructor(detail = 'The backend response does not match the published contract.') {
    super(detail)
    this.name = 'ContractError'
  }
}

function parseEncoding(raw: unknown): VisualizationEncoding | null {
  if (raw === null || raw === undefined) return null
  if (!isObject(raw) || !isText(raw.field, 120) || !isText(raw.label, 200) || !isText(raw.data_type, 40)) {
    throw new ContractError()
  }
  if (!optionalText(raw.unit, 80)) throw new ContractError()
  return { field: raw.field, label: raw.label, data_type: raw.data_type, unit: (raw.unit as string) ?? null }
}

function parseRow(raw: unknown): Record<string, VisualizationValue> {
  if (!isObject(raw)) throw new ContractError()
  const row: Record<string, VisualizationValue> = {}
  for (const [key, value] of Object.entries(raw)) {
    if (value === null) row[key] = null
    else if (typeof value === 'boolean') row[key] = value
    else if (typeof value === 'number') {
      if (!Number.isFinite(value)) throw new ContractError()
      row[key] = value
    } else if (typeof value === 'string') {
      if (value.length > 2000) throw new ContractError()
      row[key] = value
    } else throw new ContractError()
  }
  return row
}

function parseVisualization(raw: unknown): VisualizationSpec {
  if (!isObject(raw) || !isText(raw.visualization_id, 120) || !isText(raw.title, 400)) throw new ContractError()
  if (!visualizationTypes.includes(raw.type as VisualizationType)) throw new ContractError()
  if (!optionalText(raw.description, 2000) || !optionalText(raw.series_field, 120)) throw new ContractError()
  if (!optionalText(raw.region_field, 120)) throw new ContractError()
  if (!optionalText(raw.band_lower_field, 120) || !optionalText(raw.band_upper_field, 120)) throw new ContractError()
  // A map without a usable region key would silently render nothing; refuse it
  // here rather than show an empty map beside a populated table.
  if (raw.type === 'choropleth' && (!isText(raw.region_field, 120) || !regionSchemes.includes(raw.region_scheme as RegionScheme))) {
    throw new ContractError()
  }
  const columns = array(raw.columns, 60).map(item => {
    if (!isObject(item) || !isText(item.field, 120) || !isText(item.label, 200) || !optionalText(item.unit, 80)) {
      throw new ContractError()
    }
    return { field: item.field, label: item.label, unit: (item.unit as string) ?? null }
  })
  // The backend caps each spec at 200 rows and flags the cut with `truncated`.
  const rows = array(raw.rows, 200).map(parseRow)
  return {
    schema_version: isText(raw.schema_version, 20) ? raw.schema_version : '1.0',
    visualization_id: raw.visualization_id,
    type: raw.type as VisualizationType,
    title: raw.title,
    description: (raw.description as string) ?? null,
    x: parseEncoding(raw.x),
    y: parseEncoding(raw.y),
    series_field: (raw.series_field as string) ?? null,
    // Both or neither: half a band would draw an interval with one edge.
    band_lower_field: isText(raw.band_lower_field, 120) && isText(raw.band_upper_field, 120) ? raw.band_lower_field : null,
    band_upper_field: isText(raw.band_lower_field, 120) && isText(raw.band_upper_field, 120) ? raw.band_upper_field : null,
    region_field: (raw.region_field as string) ?? null,
    region_scheme: regionSchemes.includes(raw.region_scheme as RegionScheme)
      ? (raw.region_scheme as RegionScheme)
      : null,
    columns,
    headline: isText(raw.headline, 300) ? raw.headline : null,
    annotations: array(raw.annotations, 12).map(item => {
      if (!isObject(item) || !isText(item.label, 200)) throw new ContractError()
      if (!annotationKinds.includes(item.kind as AnnotationKind)) throw new ContractError()
      return {
        kind: item.kind as AnnotationKind,
        label: item.label,
        entity_name: isText(item.entity_name, 200) ? item.entity_name : null,
        period: isText(item.period, 60) ? item.period : null,
        value: typeof item.value === 'number' ? item.value : null,
      }
    }),
    reference_lines: array(raw.reference_lines, 4).map(item => {
      if (!isObject(item) || !isText(item.label, 200) || typeof item.value !== 'number') {
        throw new ContractError()
      }
      return { label: item.label, value: item.value, axis: item.axis === 'x' ? 'x' as const : 'y' as const }
    }),
    focus_entities: array(raw.focus_entities, 40).map(item => {
      if (!isText(item, 200)) throw new ContractError()
      return item
    }),
    rows,
    citation_ids: array(raw.citation_ids, 200).map(item => {
      if (!isText(item, 120)) throw new ContractError()
      return item
    }),
    truncated: raw.truncated === true,
  }
}

function parseLimitations(raw: unknown): DataLimitations | null {
  if (raw === null || raw === undefined) return null
  if (!isObject(raw)) throw new ContractError()
  const freshness = array(raw.freshness, 200).map(item => {
    if (!isObject(item) || !isText(item.citation_id, 120) || !isText(item.dataset_id, 200) ||
        !isText(item.dataset_version, 200) || !isText(item.published_at, 64) || !isNumber(item.age_days)) {
      throw new ContractError()
    }
    return {
      citation_id: item.citation_id,
      dataset_id: item.dataset_id,
      dataset_version: item.dataset_version,
      published_at: item.published_at,
      age_days: item.age_days,
    }
  })
  let coverage: CoverageGap | null = null
  if (raw.coverage !== null && raw.coverage !== undefined) {
    const item = raw.coverage
    if (!isObject(item) || !regionSchemes.includes(item.region_scheme as RegionScheme) ||
        !isNumber(item.expected_entity_count) || !isNumber(item.observed_entity_count)) {
      throw new ContractError()
    }
    coverage = {
      region_scheme: item.region_scheme as RegionScheme,
      expected_entity_count: item.expected_entity_count,
      observed_entity_count: item.observed_entity_count,
      missing_entity_names: textList(item.missing_entity_names, 200, 200),
      unmapped_entity_ids: textList(item.unmapped_entity_ids, 200, 200),
    }
  }
  if (!registrationBases.includes(raw.registration_basis as RegistrationBasis)) throw new ContractError()
  return {
    freshness,
    coverage,
    registration_basis: raw.registration_basis as RegistrationBasis,
    notes: textList(raw.notes, 40),
  }
}

function parseCitation(raw: unknown): EvidenceCitation {
  if (!isObject(raw) || !isText(raw.citation_id, 120) || !isText(raw.dataset_id, 200) ||
      !isText(raw.dataset_version, 200) || !isNumber(raw.quality_score) || !isText(raw.retrieved_at, 64)) {
    throw new ContractError()
  }
  const excerpt = array(raw.excerpt, 100).map(item => {
    if (!isObject(item) || !isText(item.entity_id, 200) || !isText(item.entity_name, 300) ||
        !isText(item.metric_code, 200) || !isText(item.metric_name, 300) || !isNumber(item.value) ||
        !optionalText(item.period, 64) || !optionalText(item.observed_at, 64)) {
      throw new ContractError()
    }
    return {
      entity_id: item.entity_id,
      entity_name: item.entity_name,
      metric_code: item.metric_code,
      metric_name: item.metric_name,
      value: item.value,
      period: (item.period as string) ?? null,
      observed_at: (item.observed_at as string) ?? null,
    }
  })
  return {
    citation_id: raw.citation_id,
    dataset_id: raw.dataset_id,
    dataset_version: raw.dataset_version,
    quality_score: raw.quality_score,
    retrieved_at: raw.retrieved_at,
    excerpt,
  }
}

function parseWebCitation(raw: unknown): WebCitation {
  if (!isObject(raw) || !isText(raw.citation_id, 120) || !isText(raw.title, 500) ||
      !isText(raw.url, 2000) || !raw.url.startsWith('https://') || !optionalText(raw.snippet, 2000) ||
      !optionalText(raw.published_at, 64)) {
    throw new ContractError()
  }
  return {
    citation_id: raw.citation_id,
    title: raw.title,
    url: raw.url,
    snippet: (raw.snippet as string | undefined) ?? '',
    published_at: (raw.published_at as string | undefined) ?? null,
  }
}

function parseSourceCandidate(raw: unknown): SourceCandidate {
  if (!isObject(raw) || !isText(raw.candidate_id, 120) || !isText(raw.connector_id, 120) ||
      !isText(raw.title, 400) || !isText(raw.publisher, 200) || !isText(raw.download_url, 2000) ||
      !isText(raw.file_name, 400) || !isText(raw.source_format, 40)) {
    throw new ContractError()
  }
  // The backend only ever configures HTTPS candidates; refuse anything else
  // rather than rendering a link the connector policy would have rejected.
  if (!raw.download_url.startsWith('https://')) throw new ContractError()
  const terms = (value: unknown) => array(value, 60).map(item => {
    if (!isText(item, 200)) throw new ContractError()
    return item
  })
  return {
    candidate_id: raw.candidate_id,
    connector_id: raw.connector_id,
    title: raw.title,
    publisher: raw.publisher,
    download_url: raw.download_url,
    file_name: raw.file_name,
    source_format: raw.source_format,
    topic_terms: terms(raw.topic_terms),
    metric_codes: terms(raw.metric_codes),
    entity_ids: terms(raw.entity_ids),
    license: optionalText(raw.license, 400) ? ((raw.license as string) ?? null) : null,
    period_start: optionalText(raw.period_start, 40) ? ((raw.period_start as string) ?? null) : null,
    period_end: optionalText(raw.period_end, 40) ? ((raw.period_end as string) ?? null) : null,
    updated_at: optionalText(raw.updated_at, 64) ? ((raw.updated_at as string) ?? null) : null,
  }
}

function parseImpactAnalysis(raw: unknown): ImpactAnalysis | null {
  if (raw === null || raw === undefined) return null
  if (!isObject(raw) || !isText(raw.district_code, 4) || !isText(raw.district_name, 120) ||
      !isText(raw.observed_period, 20) || !isNumber(raw.target_year) || !isNumber(raw.shock_people) ||
      !['insufficient', 'low', 'medium', 'high'].includes(String(raw.confidence))) throw new ContractError()
  const findings = array(raw.findings, 20).map(item => {
    if (!isObject(item) || !['population', 'housing', 'transport', 'public_services'].includes(String(item.stage)) ||
        !isText(item.label, 400) || !optionalText(item.unit, 80) ||
        !(item.baseline_value === null || isNumber(item.baseline_value)) ||
        !(item.scenario_value === null || isNumber(item.scenario_value)) ||
        !(item.absolute_delta === null || isNumber(item.absolute_delta)) ||
        !scenarioEvidenceKinds.includes(item.evidence_kind as ScenarioEvidenceKind)) throw new ContractError()
    return item as ImpactFinding
  })
  const dataGaps = array(raw.data_gaps, 10).map(item => {
    if (!isObject(item) || !['housing', 'transport', 'public_services'].includes(String(item.domain)) ||
        !isText(item.reason, 1000)) throw new ContractError()
    return { domain: item.domain, required_metrics: textList(item.required_metrics, 20, 120), reason: item.reason } as ImpactDataGap
  })
  const recommendations = array(raw.recommendations, 10).map(item => {
    if (!isObject(item) || !isNumber(item.priority) ||
        !['housing', 'transport', 'public_services'].includes(String(item.domain)) ||
        !isText(item.action, 500) || !isText(item.rationale, 1000) ||
        !['low', 'medium', 'high'].includes(String(item.confidence))) throw new ContractError()
    return item as InvestmentRecommendation
  })
  return {
    district_code: raw.district_code,
    district_name: raw.district_name,
    observed_period: raw.observed_period,
    target_year: raw.target_year,
    shock_people: raw.shock_people,
    findings,
    data_gaps: dataGaps,
    recommendations,
    confidence: raw.confidence as ImpactAnalysis['confidence'],
  }
}

const textList = (value: unknown, limit: number, max = 2000): string[] =>
  array(value, limit).map(item => {
    if (!isText(item, max)) throw new ContractError()
    return item
  })

function parseDataRequirement(raw: unknown): DataRequirement | null {
  if (raw === null || raw === undefined) return null
  if (!isObject(raw) || !optionalText(raw.time_expression, 200)) throw new ContractError()
  return {
    topic_terms: textList(raw.topic_terms, 40, 120),
    metric_codes: textList(raw.metric_codes, 40, 120),
    entity_ids: textList(raw.entity_ids, 500, 120),
    time_expression: (raw.time_expression as string | undefined) ?? null,
    accepted_formats: textList(raw.accepted_formats, 10, 20),
  }
}

export function parseCopilotResponse(raw: unknown): CopilotResponse {
  if (!isObject(raw) || !isText(raw.answer, 16000) || !isText(raw.generated_at, 64)) throw new ContractError()
  if (!copilotStatuses.includes(raw.status as CopilotStatus)) throw new ContractError()
  if (!optionalText(raw.session_id, 40)) throw new ContractError()
  return {
    status: raw.status as CopilotStatus,
    answer: raw.answer,
    generated_at: raw.generated_at,
    session_id: (raw.session_id as string | undefined) ?? null,
    visualizations: array(raw.visualizations, 12).map(parseVisualization),
    citations: array(raw.citations, 200).map(parseCitation),
    web_citations: array(raw.web_citations, 20).map(parseWebCitation),
    tool_trace: array(raw.tool_trace, 40).map(item => {
      if (!isObject(item) || !isText(item.tool, 120) || !isText(item.outcome, 80) || !isText(item.summary, 2000)) {
        throw new ContractError()
      }
      return { tool: item.tool, outcome: item.outcome, summary: item.summary }
    }),
    source_candidates: array(raw.source_candidates, 40).map(parseSourceCandidate),
    data_requirement: parseDataRequirement(raw.data_requirement),
    assumptions: textList(raw.assumptions, 40),
    warnings: textList(raw.warnings, 40),
    limitations: parseLimitations(raw.limitations),
    impact_analysis: parseImpactAnalysis(raw.impact_analysis),
  }
}

function parseDistrictOverview(raw: unknown): DistrictOverview {
  if (!isObject(raw) || !isText(raw.datasetId, 200) || !isText(raw.datasetVersion, 200) ||
      !isText(raw.districtCode, 4) || !optionalText(raw.districtName, 120) ||
      !isText(raw.period, 20) || !isText(raw.unitCode, 80) || !isText(raw.populationScope, 80) ||
      !isNumber(raw.qualityScore) || !isNumber(raw.total) || !optionalText(raw.previousPeriod, 20) ||
      !(raw.absoluteChange === null || raw.absoluteChange === undefined || isNumber(raw.absoluteChange)) ||
      !(raw.percentChange === null || raw.percentChange === undefined || isNumber(raw.percentChange))) {
    throw new ContractError()
  }
  const trend = array(raw.trend, 24).map(item => {
    if (!isObject(item) || !isText(item.period, 20) || !isNumber(item.value)) throw new ContractError()
    return { period: item.period, value: item.value }
  })
  const parseBreakdown = (value: unknown) => array(value, 12).map(item => {
    if (!isObject(item) || !isText(item.key, 40) || !isText(item.label, 120) ||
        !isNumber(item.value) || !isNumber(item.sharePercent)) throw new ContractError()
    return { key: item.key, label: item.label, value: item.value, sharePercent: item.sharePercent }
  })
  return {
    datasetId: raw.datasetId,
    datasetVersion: raw.datasetVersion,
    districtCode: raw.districtCode,
    districtName: (raw.districtName as string | undefined) ?? null,
    period: raw.period,
    unitCode: raw.unitCode,
    populationScope: raw.populationScope,
    qualityScore: raw.qualityScore,
    total: raw.total,
    previousPeriod: (raw.previousPeriod as string | undefined) ?? null,
    absoluteChange: (raw.absoluteChange as number | undefined) ?? null,
    percentChange: (raw.percentChange as number | undefined) ?? null,
    trend,
    ageDistribution: parseBreakdown(raw.ageDistribution),
    genderDistribution: parseBreakdown(raw.genderDistribution),
  }
}

function parseDatasetCatalogItem(raw: unknown): DatasetCatalogItem {
  if (!isObject(raw) || !isText(raw.datasetId, 200) || !isText(raw.topic, 200) ||
      !isText(raw.status, 80) || !isText(raw.datasetRole, 80) ||
      !isText(raw.populationScope, 80) || !isNumber(raw.qualityScore)) {
    throw new ContractError()
  }
  return {
    datasetId: raw.datasetId,
    topic: raw.topic,
    status: raw.status,
    datasetRole: raw.datasetRole,
    grain: textList(raw.grain, 60, 120),
    populationScope: raw.populationScope,
    qualityScore: raw.qualityScore,
  }
}

export type CopilotQuery = {
  question: string
  entityIds?: string[]
  minQualityScore?: number
  sessionId?: string
}

/** Only a configured API base; endpoints never come from chat or model text. */
export function createCopilotClient(baseUrl: string, fetcher: typeof fetch = fetch) {
  const base = new URL(baseUrl, window.location.origin)
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) {
    throw new Error('VITE_COPILOT_API_BASE must be an HTTP(S) URL or a same-origin path.')
  }
  const root = base.href.replace(/\/$/, '')

  const read = async (response: Response): Promise<unknown> => {
    if (!response.ok) {
      // A refused link or file carries the backend's reason in the error
      // envelope; that reason is what the reviewer needs to fix it.
      if ([409, 413, 415, 422].includes(response.status)) {
        const reason = await response.json()
          .then((body: unknown) => isObject(body) && isObject(body.error) && isText(body.error.message, 400)
            ? body.error.message
            : null)
          .catch(() => null)
        if (reason) throw new Error(reason)
      }
      if (response.status === 429) throw new Error('The assistant is busy. Try again shortly.')
      if ([401, 403].includes(response.status)) throw new Error('Access denied. Check the backend sign-in configuration.')
      if (response.status === 404) throw new Error('The backend does not expose this endpoint. Check the API version.')
      throw new Error(`Request failed (${response.status}). Try again.`)
    }
    const reader = response.body?.getReader()
    if (!reader) throw new ContractError('The backend returned an empty body.')
    const decoder = new TextDecoder()
    let text = ''
    let bytes = 0
    try {
      for (;;) {
        const chunk = await reader.read()
        if (chunk.done) break
        bytes += chunk.value.byteLength
        // Bound while reading rather than after allocating arbitrary output.
        if (bytes > 1_000_000) {
          await reader.cancel()
          throw new ContractError('The backend response was too large.')
        }
        text += decoder.decode(chunk.value, { stream: true })
      }
    } finally {
      reader.releaseLock()
    }
    try {
      return JSON.parse(text + decoder.decode()) as unknown
    } catch {
      throw new ContractError('The backend did not return valid JSON.')
    }
  }

  const send = async (path: string, body: unknown, signal: AbortSignal) =>
    read(await fetcher(root + path, {
      method: 'POST',
      credentials: 'same-origin',
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    }))

  return {
    /** POST /copilot/query — the one grounded entry point. */
    async query(request: CopilotQuery, signal: AbortSignal): Promise<CopilotResponse> {
      return parseCopilotResponse(await send('/copilot/query', request, signal))
    },

    /** POST /copilot/query/stream — NDJSON snapshots sourced from Bedrock
     * ConverseStream followed by the complete validated response. */
    async queryStream(
      request: CopilotQuery,
      signal: AbortSignal,
      onText: (text: string) => void,
    ): Promise<CopilotResponse> {
      const response = await fetcher(root + '/copilot/query/stream', {
        method: 'POST',
        credentials: 'same-origin',
        signal,
        headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
        body: JSON.stringify(request),
      })
      if (!response.ok) {
        await read(response)
        throw new Error(`Request failed (${response.status}). Try again.`)
      }
      const reader = response.body?.getReader()
      if (!reader) throw new ContractError('The backend returned an empty stream.')
      const decoder = new TextDecoder()
      let buffered = ''
      let bytes = 0
      let result: CopilotResponse | null = null
      let streamedText = ''

      const consume = (line: string) => {
        if (!line.trim()) return
        let event: unknown
        try { event = JSON.parse(line) as unknown }
        catch { throw new ContractError('The backend returned an invalid stream event.') }
        if (!isObject(event) || !isText(event.type, 20)) throw new ContractError()
        if (event.type === 'delta' && isText(event.text, 100_000)) {
          streamedText += event.text
          onText(streamedText)
        }
        else if (event.type === 'text' && isText(event.text, 100_000)) {
          streamedText = event.text
          onText(streamedText)
        }
        else if (event.type === 'result') result = parseCopilotResponse(event.response)
        else if (event.type === 'error' && isText(event.message, 400)) throw new Error(event.message)
        else if (event.type !== 'text') throw new ContractError('The backend returned an unknown stream event.')
      }

      try {
        for (;;) {
          const chunk = await reader.read()
          if (chunk.done) break
          bytes += chunk.value.byteLength
          if (bytes > 2_000_000) throw new ContractError('The backend response was too large.')
          buffered += decoder.decode(chunk.value, { stream: true })
          const lines = buffered.split('\n')
          buffered = lines.pop() ?? ''
          lines.forEach(consume)
        }
        buffered += decoder.decode()
        if (buffered) consume(buffered)
      } finally {
        reader.releaseLock()
      }
      if (!result) throw new ContractError('The stream ended before the final response.')
      return result
    },

    /** GET /districts/{code}/overview — dashboard data, never an agent turn. */
    async districtOverview(districtCode: string, signal: AbortSignal): Promise<DistrictOverview> {
      if (!/^\d{2}$/.test(districtCode)) throw new ContractError('Invalid district code.')
      const raw = await read(await fetcher(
        `${root}/districts/${encodeURIComponent(districtCode)}/overview`,
        {
          credentials: 'same-origin',
          signal,
          headers: { Accept: 'application/json' },
        },
      ))
      return parseDistrictOverview(raw)
    },

    /** GET /copilot/capabilities — the exact tools this runtime advertises. */
    async capabilities(signal: AbortSignal): Promise<ToolCapability[]> {
      const raw = await read(await fetcher(`${root}/copilot/capabilities`, {
        credentials: 'same-origin',
        signal,
        headers: { Accept: 'application/json' },
      }))
      return array(raw, 40).map(item => {
        if (!isObject(item) || !isText(item.name, 120) || !isText(item.operation, 120) ||
            !isText(item.description, 2000)) {
          throw new ContractError()
        }
        return {
          name: item.name,
          operation: item.operation,
          description: item.description,
          requires: textList(item.requires, 20, 120),
        }
      })
    },

    /** GET /datasets — catalog metadata used to explain what can be asked. */
    async datasets(signal: AbortSignal): Promise<DatasetCatalogItem[]> {
      const raw = await read(await fetcher(`${root}/datasets`, {
        credentials: 'same-origin',
        signal,
        headers: { Accept: 'application/json' },
      }))
      return array(raw, 200).map(parseDatasetCatalogItem)
    },

    /** POST /copilot/acquisitions — a reviewer submits a configured candidateId,
     * never a URL. The snapshot then enters the approval-gated ingestion flow. */
    async acquire(candidateId: string, submittedBy: string, signal: AbortSignal): Promise<AcquisitionStart> {
      const raw = await send('/copilot/acquisitions', { candidateId, submittedBy }, signal)
      if (!isObject(raw) || !isText(raw.ingestion_job_id, 200) || !isText(raw.ingestion_status, 80) ||
          !isText(raw.created_at, 64)) {
        throw new ContractError()
      }
      return {
        candidate: parseSourceCandidate(raw.candidate),
        ingestion_job_id: raw.ingestion_job_id,
        ingestion_status: raw.ingestion_status,
        created_at: raw.created_at,
      }
    },

    /** GET /copilot/intake-options — which hosts a pasted link may use. */
    async intakeOptions(signal: AbortSignal): Promise<IntakeOptions> {
      const raw = await read(await fetcher(`${root}/copilot/intake-options`, {
        credentials: 'same-origin',
        signal,
        headers: { Accept: 'application/json' },
      }))
      if (!isObject(raw) || !isNumber(raw.maxUploadBytes)) throw new ContractError()
      return {
        linkHosts: textList(raw.linkHosts, 40, 253),
        uploadFormats: textList(raw.uploadFormats, 10, 20),
        maxUploadBytes: raw.maxUploadBytes,
      }
    },

    /** POST /copilot/acquisitions/link — the backend fetches only from approved
     * hosts; anything else is refused with a reason. */
    async acquireLink(url: string, submittedBy: string, topicHint: string | null, signal: AbortSignal): Promise<IntakeStart> {
      const raw = await send('/copilot/acquisitions/link', { url, submittedBy, topicHint }, signal)
      if (!isObject(raw) || !isText(raw.ingestion_job_id, 200) || !isText(raw.ingestion_status, 80) ||
          !isText(raw.file_name, 400)) {
        throw new ContractError()
      }
      return { job_id: raw.ingestion_job_id, status: raw.ingestion_status, file_name: raw.file_name }
    },

    /** POST /datasets/upload — a reviewer's own file, into the same workflow. */
    async uploadDataset(file: File, submittedBy: string, topicHint: string | null, signal: AbortSignal): Promise<IntakeStart> {
      const form = new FormData()
      form.append('file', file)
      form.append('submitted_by', submittedBy)
      if (topicHint) form.append('topic_hint', topicHint)
      const raw = await read(await fetcher(`${root}/datasets/upload`, {
        method: 'POST',
        credentials: 'same-origin',
        signal,
        headers: { Accept: 'application/json' },
        body: form,
      }))
      if (!isObject(raw) || !isText(raw.jobId, 200) || !isText(raw.status, 80)) throw new ContractError()
      return { job_id: raw.jobId, status: raw.status, file_name: file.name }
    },
  }
}

export type CopilotClient = ReturnType<typeof createCopilotClient>
