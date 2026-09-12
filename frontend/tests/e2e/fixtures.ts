import type { Page, Route } from '@playwright/test'

// Shape matches ToolCapability in contracts/api/openapi.json: `name`, not `tool`.
export const capabilities = [
  { name: 'query_observations', operation: 'query_observations', description: 'Query published observations', requires: [] },
  { name: 'rank_candidates', operation: 'rank_candidates', description: 'Rank candidates against a decision profile', requires: ['get_features'] },
]

export const rankingAnswer = {
  status: 'answered',
  answer: 'banqiao ranks first with a deterministic score of 55.6/100.',
  generated_at: '2026-09-12T06:41:45.946811Z',
  visualizations: [
    {
      schema_version: '1.0',
      visualization_id: 'candidate-ranking',
      type: 'ranking_bar',
      title: 'Candidate ranking',
      description: null,
      x: { field: 'score', label: 'Score', data_type: 'quantitative', unit: 'score_0_100' },
      y: { field: 'entity_name', label: 'Candidate', data_type: 'nominal', unit: null },
      series_field: null,
      columns: [],
      rows: [
        { rank: 1, entity_id: 'banqiao', entity_name: 'Banqiao', score: 55.6, eligible: true },
        { rank: 2, entity_id: 'linkou', entity_name: 'Linkou', score: 41.2, eligible: true },
      ],
      citation_ids: ['data-1'],
      truncated: false,
    },
    {
      schema_version: '1.0',
      visualization_id: 'candidate-ranking-table',
      type: 'data_table',
      title: 'Candidate ranking table',
      description: null,
      x: null,
      y: null,
      series_field: null,
      columns: [
        { field: 'rank', label: 'Rank', unit: null },
        { field: 'entity_name', label: 'Candidate', unit: null },
        { field: 'score', label: 'Score', unit: 'score_0_100' },
      ],
      rows: [
        { rank: 1, entity_name: 'Banqiao', score: 55.6 },
        { rank: 2, entity_name: 'Linkou', score: 41.2 },
      ],
      citation_ids: ['data-1'],
      truncated: true,
    },
  ],
  citations: [
    {
      citation_id: 'data-1',
      dataset_id: 'property_cost_source',
      dataset_version: 'v1',
      quality_score: 0.95,
      retrieved_at: '2026-09-02T00:00:00Z',
    },
  ],
  tool_trace: [
    { tool: 'rank_candidates', outcome: 'ok', summary: '2 candidates scored' },
    { tool: 'explain_lineage', outcome: 'ok', summary: '1 dataset cited' },
  ],
  source_candidates: [],
  assumptions: ['Using decision profile home_buying@v1'],
  warnings: [],
}

/** Long-format rows with a deliberate gap: Banqiao has no 2024 value. */
export const trendAnswer = {
  status: 'answered',
  answer: 'The two districts diverge between 2023 and 2025.',
  generated_at: '2026-09-12T06:50:00Z',
  visualizations: [
    {
      schema_version: '1.0',
      visualization_id: 'observation-trend',
      type: 'line',
      // Deliberately Chinese: proves a backend label still renders under the English UI.
      title: 'population_count 趨勢',
      description: null,
      x: { field: 'period', label: 'Period', data_type: 'temporal', unit: null },
      y: { field: 'value', label: 'Value', data_type: 'quantitative', unit: 'persons' },
      series_field: 'entity_name',
      columns: [],
      rows: [
        { period: '2023', entity_id: 'banqiao', entity_name: 'Banqiao', value: 120 },
        { period: '2024', entity_id: 'linkou', entity_name: 'Linkou', value: 90 },
        { period: '2023', entity_id: 'linkou', entity_name: 'Linkou', value: 80 },
        { period: '2025', entity_id: 'banqiao', entity_name: 'Banqiao', value: 150 },
        { period: '2025', entity_id: 'linkou', entity_name: 'Linkou', value: 95 },
      ],
      citation_ids: ['data-1'],
      truncated: false,
    },
    {
      schema_version: '1.0',
      visualization_id: 'entity-change-comparison',
      type: 'comparison_bar',
      title: 'Change by district',
      description: null,
      x: { field: 'entity_name', label: 'District', data_type: 'nominal', unit: null },
      y: { field: 'absolute_change', label: 'Absolute change', data_type: 'quantitative', unit: 'persons' },
      series_field: null,
      columns: [],
      rows: [
        { entity_id: 'banqiao', entity_name: 'Banqiao', absolute_change: 30, direction: 'increase' },
        { entity_id: 'linkou', entity_name: 'Linkou', absolute_change: -15, direction: 'decrease' },
      ],
      citation_ids: ['data-1'],
      truncated: false,
    },
  ],
  citations: rankingAnswer.citations,
  tool_trace: [{ tool: 'query_observations', outcome: 'ok', summary: '5 points' }],
  source_candidates: [],
  assumptions: [],
  warnings: [],
}

export const acquisitionAnswer = {
  status: 'acquisition_required',
  answer: 'The catalog is missing the data this question needs.',
  generated_at: '2026-09-12T07:00:00Z',
  visualizations: [],
  citations: [],
  tool_trace: [{ tool: 'discover_sources', outcome: 'ok', summary: '1 candidate' }],
  source_candidates: [
    {
      candidate_id: 'ntpc-population',
      connector_id: 'configured_http',
      title: 'New Taipei population statistics',
      publisher: 'New Taipei City Government',
      download_url: 'https://data.example.gov.tw/population.csv',
      file_name: 'population.csv',
      source_format: 'csv',
      topic_terms: ['population'],
      metric_codes: ['population_count'],
      entity_ids: [],
      license: 'OGDL-1.0',
      period_start: '2023-01',
      period_end: '2025-12',
      updated_at: null,
    },
  ],
  assumptions: [],
  warnings: ['This source has not been approved or published yet.'],
}

export const insufficientAnswer = {
  status: 'insufficient_data',
  answer: 'There is not enough compatible observation data for this analysis.',
  generated_at: '2026-09-12T07:10:00Z',
  visualizations: [],
  citations: [],
  tool_trace: [{ tool: 'query_observations', outcome: 'missing', summary: 'only one period' }],
  source_candidates: [],
  assumptions: [],
  warnings: ["at least two periods are required to compare entity '01'"],
}

/** Route the copilot API. `query` may be a payload or a per-call handler. */
export async function mockCopilot(
  page: Page,
  options: { query: unknown | ((index: number) => unknown); acquire?: unknown; queryStatus?: number },
) {
  let index = 0
  await page.route('**/api/v1/copilot/capabilities', (route: Route) =>
    route.fulfill({ json: capabilities }),
  )
  await page.route('**/api/v1/copilot/query', (route: Route) => {
    const body = typeof options.query === 'function'
      ? (options.query as (i: number) => unknown)(index++)
      : options.query
    if (options.queryStatus && options.queryStatus >= 400) {
      return route.fulfill({ status: options.queryStatus, json: { detail: 'nope' } })
    }
    return route.fulfill({ json: body })
  })
  await page.route('**/api/v1/copilot/acquisitions', (route: Route) =>
    route.fulfill({
      json: options.acquire ?? {
        candidate: acquisitionAnswer.source_candidates[0],
        ingestion_job_id: 'job-42',
        ingestion_status: 'awaiting_approval',
        created_at: '2026-09-12T07:05:00Z',
      },
    }),
  )
}

export async function ask(page: Page, question: string) {
  const composer = page.getByLabel('Question')
  await composer.fill(question)
  await composer.press('Enter')
}
