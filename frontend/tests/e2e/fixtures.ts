import type { Page, Route } from '@playwright/test'

// Shape matches ToolCapability in contracts/api/openapi.json: `name`, not `tool`.
export const capabilities = [
  { name: 'search_tools', operation: 'search_tools', description: 'Find relevant registered tools', requires: [] },
  { name: 'query_observations', operation: 'query_observations', description: 'Query published observations', requires: [] },
  { name: 'rank_candidates', operation: 'rank_candidates', description: 'Rank candidates against a decision profile', requires: ['get_features'] },
  { name: 'simulate_scenario', operation: 'simulate_scenario', description: 'Project a population shock', requires: ['search_catalog'] },
  { name: 'assess_capacity', operation: 'assess_capacity', description: 'Audit infrastructure capacity evidence', requires: ['simulate_scenario'] },
  { name: 'recommend_investment', operation: 'recommend_investment', description: 'Rank supported investments', requires: ['assess_capacity'] },
]

export const datasetCatalog = [
  {
    datasetId: 'population',
    version: 'internal-version-not-for-intro',
    topic: 'population',
    status: 'published',
    datasetRole: 'fact',
    grain: ['year_gregorian', 'district_code', 'age_label_original', 'gender_code'],
    populationScope: 'youth_specific',
    qualityScore: 1,
    createdAt: '2026-09-01T00:00:00Z',
    publishedAt: '2026-09-02T00:00:00Z',
  },
  {
    datasetId: 'employment',
    version: 'quarantined-version',
    topic: 'employment',
    status: 'quarantined',
    datasetRole: 'fact',
    grain: ['year_gregorian', 'district_code'],
    populationScope: 'youth_specific',
    qualityScore: 0.6,
    createdAt: '2026-09-01T00:00:00Z',
    publishedAt: null,
  },
]

export const rankingAnswer = {
  status: 'answered',
  answer: 'Banqiao ranks first with a deterministic score of 55.6/100.',
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
      excerpt: [
        {
          entity_id: 'banqiao',
          entity_name: 'Banqiao',
          metric_code: 'property_cost',
          metric_name: 'Property cost',
          value: 82,
          period: null,
          observed_at: '2026-09-01T00:00:00Z',
        },
        {
          entity_id: 'linkou',
          entity_name: 'Linkou',
          metric_code: 'property_cost',
          metric_name: 'Property cost',
          value: 61,
          period: null,
          observed_at: '2026-09-01T00:00:00Z',
        },
      ],
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
  answer: 'Population count comparison · 2023–2025\n\n0 of 2 locations decreased; 2 increased.\n\n- Banqiao: 120 → 150 (+25.00%)\n- Linkou: 80 → 95 (+18.75%)\n\nSource: cited published dataset version. [data-1]',
  generated_at: '2026-09-12T06:50:00Z',
  visualizations: [
    {
      schema_version: '1.0',
      visualization_id: 'observation-trend',
      type: 'line',
      // Deliberately Chinese: proves a backend label still renders under the English UI.
      title: 'Population count 趨勢',
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
    {
      schema_version: '1.0',
      visualization_id: 'observation-map',
      type: 'choropleth',
      title: 'Population count 趨勢 · 2025',
      description: 'District choropleth; shading encodes the value the backend returned',
      x: { field: 'district_code', label: 'District', data_type: 'nominal', unit: null },
      y: { field: 'value', label: 'Value', data_type: 'quantitative', unit: 'persons' },
      series_field: null,
      region_field: 'district_code',
      region_scheme: 'new_taipei_district',
      columns: [
        { field: 'district_code', label: 'District code', unit: null },
        { field: 'district_name', label: 'District', unit: null },
        { field: 'value', label: 'Value', unit: 'persons' },
      ],
      rows: [
        { district_code: '01', district_name: '板橋區', entity_id: 'banqiao', entity_name: 'Banqiao', value: 150, rank: null, period: '2025' },
        { district_code: '17', district_name: '林口區', entity_id: 'linkou', entity_name: 'Linkou', value: 95, rank: null, period: '2025' },
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
  limitations: {
    schema_version: '1.0',
    freshness: [
      {
        citation_id: 'data-1',
        dataset_id: 'property_cost_source',
        dataset_version: 'v1',
        published_at: '2026-09-02T00:00:00Z',
        age_days: 10,
      },
    ],
    coverage: {
      region_scheme: 'new_taipei_district',
      expected_entity_count: 29,
      observed_entity_count: 2,
      missing_entity_names: ['貢寮區', '烏來區'],
      unmapped_entity_ids: [],
    },
    registration_basis: 'registered_household',
    notes: [
      'These counts are registered household population (戶籍人口): people whose household registration is in the district, which is not necessarily where they live.',
    ],
  },
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

export const webAcquisitionAnswer = {
  ...acquisitionAnswer,
  answer: 'I found an unverified source suggestion on an approved government site.',
  source_candidates: [],
  web_citations: [
    {
      citation_id: 'web-1',
      title: 'New Taipei housing open data',
      url: 'https://data.ntpc.gov.tw/datasets/housing.csv',
      snippet: 'Housing market data published by New Taipei City.',
      published_at: null,
    },
  ],
  data_requirement: {
    topic_terms: ['housing'],
    metric_codes: ['property_cost'],
    entity_ids: [],
    time_expression: null,
    accepted_formats: ['csv', 'json', 'xlsx'],
  },
  tool_trace: [{ tool: 'discover_web_sources', outcome: 'candidates', summary: '1 approved-host result' }],
  warnings: ['Web results are unverified source suggestions, not evidence.'],
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
  data_requirement: {
    topic_terms: ['population', 'employment'],
    metric_codes: ['population_count', 'employment_count'],
    entity_ids: [],
    time_expression: null,
    accepted_formats: ['csv', 'json', 'excel'],
  },
}

export const reviewerMapping = {
  profile: {
    file_name: 'population.csv', file_format: 'csv', file_size_bytes: 128,
    row_count: 2, column_count: 4, candidate_grain: ['year_gregorian', 'district_code', 'age_label_original'],
    columns: [
      { name: 'year', inferred_type: 'integer', semantic_role: 'year', null_rate: 0, distinct_count: 1, sample_values: ['2025'] },
      { name: 'district', inferred_type: 'string', semantic_role: 'district', null_rate: 0, distinct_count: 2, sample_values: ['板橋區', '林口區'] },
      { name: 'age', inferred_type: 'string', semantic_role: 'age_label', null_rate: 0, distinct_count: 1, sample_values: ['20-24'] },
      { name: 'population', inferred_type: 'integer', semantic_role: 'metric', null_rate: 0, distinct_count: 2, sample_values: ['100', '50'] },
    ],
    warnings: [],
  },
  proposal: {
    topic: 'population', dataset_role: 'fact',
    grain: { dimensions: ['year_gregorian', 'district_code', 'age_label_original'] },
    columns: [
      { source_column: 'year', target_field: 'year_gregorian', transformation: 'parse_year', confidence: 0.98, evidence: 'year header and values' },
      { source_column: 'district', target_field: 'district_code', transformation: 'normalize_district', confidence: 0.99, evidence: 'known New Taipei districts' },
      { source_column: 'age', target_field: 'age_label_original', transformation: 'parse_age_range', confidence: 0.96, evidence: 'bounded age labels' },
    ],
    metrics: [
      { source_column: 'population', metric_code: 'population_count', unit_code: 'persons', population_scope: 'youth_specific', aggregation_method: 'sum', confidence: 0.95, evidence: 'population header' },
    ],
    overall_confidence: 0.97, warnings: [], requires_human_approval: true,
  },
  validation: { valid: true, overall_confidence: 0.97, requires_human_approval: true, issues: [] },
}

export const reviewerPreview = [
  { sourceColumn: 'year', targetField: 'year_gregorian', transformation: 'parse_year', samples: [{ source: '2025', canonical: { year_roc: 114, year_gregorian: 2025 }, error: null }] },
  { sourceColumn: 'district', targetField: 'district_code', transformation: 'normalize_district', samples: [{ source: '板橋區', canonical: { district_code: '01', district_name: '板橋區' }, error: null }] },
  { sourceColumn: 'age', targetField: 'age_label_original', transformation: 'parse_age_range', samples: [{ source: '20-24', canonical: { age_label_original: '20-24', age_lower: 20, age_upper: 24 }, error: null }] },
]

export const impactAnswer = {
  status: 'acquisition_required',
  answer: 'Đến 2030, scenario Linkou có thêm 2.000 người. Chưa thể khuyến nghị đầu tư vì dữ liệu sức chứa và mức sử dụng chưa đủ.',
  generated_at: '2026-09-12T07:20:00Z',
  visualizations: [
    {
      schema_version: '1.0',
      visualization_id: 'youth-population-scenario-trajectory',
      type: 'line',
      title: 'Youth population scenario trajectory',
      description: 'Observed cohort baseline compared with the explicit user scenario.',
      x: { field: 'year', label: 'Year', data_type: 'temporal', unit: null },
      y: { field: 'value', label: 'Residents aged 18-35', data_type: 'quantitative', unit: 'persons' },
      series_field: 'series',
      region_field: null,
      region_scheme: null,
      columns: [],
      rows: [
        { year: 2026, series: 'Baseline', value: 27415 },
        { year: 2030, series: 'Baseline', value: 25000 },
        { year: 2030, series: 'Scenario', value: 27000 },
      ],
      citation_ids: [],
      truncated: false,
    },
  ],
  citations: [],
  tool_trace: [
    { tool: 'search_tools', outcome: 'ok', summary: 'selected registered impact tools' },
    { tool: 'simulate_scenario', outcome: 'ok', summary: 'projected Linkou to 2030' },
    { tool: 'assess_capacity', outcome: 'data_gap', summary: 'housing and public services need data' },
    { tool: 'discover_sources', outcome: 'candidates', summary: 'found 3 allowlisted candidates' },
    { tool: 'recommend_investment', outcome: 'withheld', summary: 'capacity evidence is incomplete' },
  ],
  source_candidates: [
    {
      ...acquisitionAnswer.source_candidates[0],
      candidate_id: 'ntpc-building-permits',
      title: 'New Taipei building permit records',
      metric_codes: ['residential_completions', 'permitted_households'],
    },
    {
      ...acquisitionAnswer.source_candidates[0],
      candidate_id: 'ntpc-hospitals',
      title: 'New Taipei hospital directory',
      metric_codes: ['service_facility_count'],
    },
  ],
  assumptions: ['The user-supplied population shock is +2,000 people by 2030.'],
  warnings: ['No downstream impact is inferred without compatible capacity data.'],
  limitations: null,
  impact_analysis: {
    district_code: '17',
    district_name: 'Linkou',
    observed_period: '2026-07',
    target_year: 2030,
    shock_people: 2000,
    confidence: 'insufficient',
    findings: [
      {
        stage: 'population',
        label: 'Registered residents aged 18-35 in Linkou',
        baseline_value: 25000,
        scenario_value: 27000,
        absolute_delta: 2000,
        unit: 'persons',
        evidence_kind: 'derived',
      },
    ],
    data_gaps: [
      { domain: 'housing', required_metrics: ['housing_unit_stock', 'vacant_housing_units'], reason: 'Housing pressure requires supply and vacancy evidence.' },
      { domain: 'public_services', required_metrics: ['service_facility_capacity', 'service_utilization'], reason: 'Public service investment requires capacity and utilization.' },
    ],
    recommendations: [],
  },
}

export const districtOverview = {
  datasetId: 'population',
  datasetVersion: 'v-overview',
  districtCode: '01',
  districtName: '板橋區',
  period: '2026-08',
  unitCode: 'persons',
  populationScope: 'youth_specific',
  qualityScore: 1,
  total: 92340,
  previousPeriod: '2026-07',
  absoluteChange: -210,
  percentChange: -0.23,
  trend: [
    { period: '2026-05', value: 92910 },
    { period: '2026-06', value: 92720 },
    { period: '2026-07', value: 92550 },
    { period: '2026-08', value: 92340 },
  ],
  ageDistribution: [
    { key: '18–20', label: '18–20', value: 14100, sharePercent: 15.3 },
    { key: '21–24', label: '21–24', value: 20600, sharePercent: 22.3 },
    { key: '25–29', label: '25–29', value: 27700, sharePercent: 30 },
    { key: '30–35', label: '30–35', value: 29940, sharePercent: 32.4 },
  ],
  genderDistribution: [
    { key: 'male', label: 'Male', value: 46700, sharePercent: 50.6 },
    { key: 'female', label: 'Female', value: 45640, sharePercent: 49.4 },
  ],
}

/** Route the copilot API. `query` may be a payload or a per-call handler. */
/** The UI ships in Traditional Chinese. These assertions read the English
 * strings, so a mocked page starts with the picker already set to English; the
 * shipped default is covered by its own test, which calls this afterwards. */
export async function useLanguage(page: Page, language: 'zh-TW' | 'en') {
  await page.addInitScript(chosen => {
    window.localStorage.setItem('youth-compass-language', chosen as string)
  }, language)
}

export async function mockCopilot(
  page: Page,
  options: {
    query: unknown | ((index: number, request: unknown) => unknown)
    acquire?: unknown
    districtOverview?: unknown | ((districtCode: string) => unknown)
    /** Omitted: the district has no published forecast (404). */
    districtForecast?: unknown
    datasets?: unknown
    queryStatus?: number
    onQuery?: (request: unknown) => void
  },
) {
  let index = 0
  const answerFor = (route: Route) => {
    const request = route.request().postDataJSON()
    options.onQuery?.(request)
    return typeof options.query === 'function'
      ? (options.query as (i: number, request: unknown) => unknown)(index++, request)
      : options.query
  }
  await useLanguage(page, 'en')
  await page.route('**/api/v1/copilot/capabilities', (route: Route) =>
    route.fulfill({ json: capabilities }),
  )
  await page.route('**/api/v1/datasets', (route: Route) =>
    route.fulfill({ json: options.datasets ?? datasetCatalog }),
  )
  await page.route('**/api/v1/copilot/query/stream', (route: Route) => {
    const body = answerFor(route)
    if (options.queryStatus && options.queryStatus >= 400) {
      return route.fulfill({ status: options.queryStatus, json: { detail: 'nope' } })
    }
    return route.fulfill({
      contentType: 'application/x-ndjson',
      body: `${JSON.stringify({ type: 'delta', text: (body as { answer?: string }).answer ?? '' })}\n${JSON.stringify({ type: 'result', response: body })}\n`,
    })
  })
  await page.route('**/api/v1/copilot/query', (route: Route) => {
    const body = answerFor(route)
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
  await page.route('**/api/v1/copilot/intake-options', (route: Route) =>
    route.fulfill({ json: { linkHosts: ['data.ntpc.gov.tw'], uploadFormats: ['csv', 'json', 'xlsx'], maxUploadBytes: 26214400, writeTokenRequired: false } }),
  )
  // Playwright evaluates matching routes in reverse registration order. Keep
  // the job fallback below the more specific reviewer endpoints.
  await page.route('**/api/v1/ingestion-jobs/*', (route: Route) =>
    route.fulfill({ json: {
      jobId: 'job-42', datasetId: 'population', status: 'awaiting_approval', sourceFormat: 'csv',
      currentStep: 'awaiting_approval', qualityScore: 0.97, createdAt: '2026-09-12T07:05:00Z', warnings: [], links: {},
    } }),
  )
  await page.route('**/api/v1/ingestion-jobs/*/mapping-preview', (route: Route) =>
    route.fulfill({ json: reviewerPreview }),
  )
  await page.route('**/api/v1/ingestion-jobs/*/mapping', (route: Route) =>
    route.fulfill({ json: reviewerMapping }),
  )
  await page.route('**/api/v1/ingestion-jobs/*/decision', (route: Route) =>
    route.fulfill({ json: {
      jobId: 'job-42', datasetId: 'population', status: 'published', sourceFormat: 'csv',
      currentStep: 'published', qualityScore: 0.98, createdAt: '2026-09-12T07:05:00Z', warnings: [], links: {},
    } }),
  )
  await page.route('**/api/v1/districts/*/overview', (route: Route) => {
    const districtCode = new URL(route.request().url()).pathname.match(/\/districts\/(\d{2})\/overview$/)?.[1] ?? ''
    const body = typeof options.districtOverview === 'function'
      ? options.districtOverview(districtCode)
      : options.districtOverview ?? districtOverview
    return route.fulfill({ json: body })
  })
  await page.route('**/api/v1/districts/*/forecast', (route: Route) =>
    options.districtForecast
      ? route.fulfill({ json: options.districtForecast })
      : route.fulfill({ status: 404, json: { code: 'forecast_not_available', message: 'No forecast.' } }),
  )
}

export const districtForecast = {
  districtCode: '01', metricCode: 'population_count', modelVersion: 'cohort-change-ratio-v1',
  generatedAt: '2026-09-13T02:10:58Z', basePeriod: '2026-07', baseValue: 91234, smallArea: false,
  targetCoverage: 0.8,
  points: [
    { year: 2027, period: '2027-07', value: 90500, lower: 89100, upper: 91900, entering: 4100, ageingOut: 5200, netChange: 366 },
    { year: 2028, period: '2028-07', value: 89800, lower: 87500, upper: 92100, entering: 8300, ageingOut: 10400, netChange: 666 },
  ],
  accuracy: [
    { horizonYears: 1, mapePercent: 0.81, intervalCoverage: 0.851 },
    { horizonYears: 2, mapePercent: 1.34, intervalCoverage: 0.858 },
  ],
}

export async function ask(page: Page, question: string) {
  const composer = page.getByLabel('Question')
  await composer.fill(question)
  await composer.press('Enter')
}
