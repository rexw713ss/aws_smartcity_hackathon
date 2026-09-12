// Typed against contracts/api/openapi.json — the generated backend contract, not
// the design documents. Regenerate that file with scripts/export_openapi.py and
// re-check this module whenever the copilot response changes.
//
// Casing asymmetry is intentional and matches the backend: REQUEST bodies use
// camelCase aliases (apps/api/schemas.ApiModel), RESPONSE bodies are the domain
// contracts serialized in snake_case.

export const visualizationTypes = ['line', 'comparison_bar', 'ranking_bar', 'contribution_bar', 'data_table'] as const
export type VisualizationType = (typeof visualizationTypes)[number]

export const copilotStatuses = ['answered', 'insufficient_data', 'acquisition_required', 'unsupported_question'] as const
export type CopilotStatus = (typeof copilotStatuses)[number]

export type VisualizationEncoding = { field: string; label: string; data_type: string; unit: string | null }
export type VisualizationColumn = { field: string; label: string; unit: string | null }
export type VisualizationValue = string | number | boolean | null

export type VisualizationSpec = {
  schema_version: string
  visualization_id: string
  type: VisualizationType
  title: string
  description: string | null
  x: VisualizationEncoding | null
  y: VisualizationEncoding | null
  series_field: string | null
  columns: VisualizationColumn[]
  rows: Record<string, VisualizationValue>[]
  citation_ids: string[]
  truncated: boolean
}

export type EvidenceCitation = {
  citation_id: string
  dataset_id: string
  dataset_version: string
  quality_score: number
  retrieved_at: string
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

export type CopilotResponse = {
  status: CopilotStatus
  answer: string
  generated_at: string
  visualizations: VisualizationSpec[]
  citations: EvidenceCitation[]
  tool_trace: ToolTrace[]
  source_candidates: SourceCandidate[]
  assumptions: string[]
  warnings: string[]
}

export type ToolCapability = {
  name: string
  operation: string
  description: string
  requires: string[]
}

export type AcquisitionStart = {
  candidate: SourceCandidate
  ingestion_job_id: string
  ingestion_status: string
  created_at: string
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
    columns,
    rows,
    citation_ids: array(raw.citation_ids, 200).map(item => {
      if (!isText(item, 120)) throw new ContractError()
      return item
    }),
    truncated: raw.truncated === true,
  }
}

function parseCitation(raw: unknown): EvidenceCitation {
  if (!isObject(raw) || !isText(raw.citation_id, 120) || !isText(raw.dataset_id, 200) ||
      !isText(raw.dataset_version, 200) || !isNumber(raw.quality_score) || !isText(raw.retrieved_at, 64)) {
    throw new ContractError()
  }
  return {
    citation_id: raw.citation_id,
    dataset_id: raw.dataset_id,
    dataset_version: raw.dataset_version,
    quality_score: raw.quality_score,
    retrieved_at: raw.retrieved_at,
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

const textList = (value: unknown, limit: number, max = 2000): string[] =>
  array(value, limit).map(item => {
    if (!isText(item, max)) throw new ContractError()
    return item
  })

export function parseCopilotResponse(raw: unknown): CopilotResponse {
  if (!isObject(raw) || !isText(raw.answer, 16000) || !isText(raw.generated_at, 64)) throw new ContractError()
  if (!copilotStatuses.includes(raw.status as CopilotStatus)) throw new ContractError()
  return {
    status: raw.status as CopilotStatus,
    answer: raw.answer,
    generated_at: raw.generated_at,
    visualizations: array(raw.visualizations, 12).map(parseVisualization),
    citations: array(raw.citations, 200).map(parseCitation),
    tool_trace: array(raw.tool_trace, 40).map(item => {
      if (!isObject(item) || !isText(item.tool, 120) || !isText(item.outcome, 80) || !isText(item.summary, 2000)) {
        throw new ContractError()
      }
      return { tool: item.tool, outcome: item.outcome, summary: item.summary }
    }),
    source_candidates: array(raw.source_candidates, 40).map(parseSourceCandidate),
    assumptions: textList(raw.assumptions, 40),
    warnings: textList(raw.warnings, 40),
  }
}

export type CopilotQuery = {
  question: string
  entityIds?: string[]
  minQualityScore?: number
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
  }
}

export type CopilotClient = ReturnType<typeof createCopilotClient>
