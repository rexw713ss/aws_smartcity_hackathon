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
    { tool: 'assess_capacity', outcome: 'data_gap', summary: 'housing, transport, and public services need data' },
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
      candidate_id: 'ntpc-bus-stops',
      title: 'New Taipei bus stop and route information',
      metric_codes: ['transit_stop_coverage'],
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
      { domain: 'transport', required_metrics: ['transit_boardings', 'passenger_capacity'], reason: 'Transport pressure requires observed demand and capacity.' },
      { domain: 'public_services', required_metrics: ['service_facility_capacity', 'service_utilization'], reason: 'Public service investment requires capacity and utilization.' },
    ],
    recommendations: [],
  },
}

export const whatIfAnswer = {
  metric_code: 'youth_population_18_35',
  observed_period: '2026-07',
  target_year: 2030,
  baseline_method: 'observed_age_cohorts_with_historical_district_retention',
  age_lower: 18,
  age_upper: 35,
  balance_mode: 'open',
  baseline_total: 754542,
  scenario_total: 755154,
  total_delta: 612,
  population_conserved: false,
  rows: [
    {
      district_code: '14', district_name: 'Ruifang', baseline_value: 5589,
      scenario_value: 6201, absolute_delta: 612, percent_delta: 10.9501,
      baseline_rank: 18, scenario_rank: 18, rank_change: 0,
      historical_retention_rate: 0.981154, scenario_retention_rate: 1.006993,
    },
  ],
  trajectory: [
    { year: 2026, baseline_value: 832214, scenario_value: 832214, absolute_delta: 0 },
    { year: 2027, baseline_value: 812322, scenario_value: 812499, absolute_delta: 177 },
    { year: 2028, baseline_value: 791379, scenario_value: 791717, absolute_delta: 338 },
    { year: 2029, baseline_value: 770142, scenario_value: 770624, absolute_delta: 482 },
    { year: 2030, baseline_value: 754542, scenario_value: 755154, absolute_delta: 612 },
  ],
  evidence: [
    {
      kind: 'official', label: 'Observed district population',
      detail: 'New Taipei Civil Affairs monthly household-registration counts.',
      source_url: 'https://www.ca.ntpc.gov.tw/',
    },
    {
      kind: 'derived', label: 'Cohort projection baseline',
      detail: 'Observed single-year cohorts are aged forward using recent transition rates.',
      source_url: null,
    },
    {
      kind: 'user_assumption', label: 'Scenario adjustments',
      detail: 'Raise district 14 to the observed top-quartile benchmark.', source_url: null,
    },
  ],
  assumptions: ['Raise district 14 to the observed top-quartile benchmark.'],
  warnings: ['Scenario adjustments are user assumptions, not predictions or causal estimates.'],
  generated_at: '2026-09-12T12:00:00Z',
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
    query: unknown | ((index: number) => unknown)
    acquire?: unknown
    whatIf?: unknown
    districtOverview?: unknown | ((districtCode: string) => unknown)
    datasets?: unknown
    queryStatus?: number
  },
) {
  let index = 0
  await useLanguage(page, 'en')
  await page.route('**/api/v1/copilot/capabilities', (route: Route) =>
    route.fulfill({ json: capabilities }),
  )
  await page.route('**/api/v1/datasets', (route: Route) =>
    route.fulfill({ json: options.datasets ?? datasetCatalog }),
  )
  await page.route('**/api/v1/copilot/query/stream', (route: Route) => {
    const body = typeof options.query === 'function'
      ? (options.query as (i: number) => unknown)(index++)
      : options.query
    if (options.queryStatus && options.queryStatus >= 400) {
      return route.fulfill({ status: options.queryStatus, json: { detail: 'nope' } })
    }
    return route.fulfill({
      contentType: 'application/x-ndjson',
      body: `${JSON.stringify({ type: 'delta', text: (body as { answer?: string }).answer ?? '' })}\n${JSON.stringify({ type: 'result', response: body })}\n`,
    })
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
    route.fulfill({ json: { linkHosts: ['data.ntpc.gov.tw'], uploadFormats: ['csv', 'json', 'xlsx'], maxUploadBytes: 26214400 } }),
  )
  await page.route('**/api/v1/copilot/what-if', (route: Route) =>
    route.fulfill({ json: options.whatIf ?? whatIfAnswer }),
  )
  await page.route('**/api/v1/districts/*/overview', (route: Route) => {
    const districtCode = new URL(route.request().url()).pathname.match(/\/districts\/(\d{2})\/overview$/)?.[1] ?? ''
    const body = typeof options.districtOverview === 'function'
      ? options.districtOverview(districtCode)
      : options.districtOverview ?? districtOverview
    return route.fulfill({ json: body })
  })
}

export async function ask(page: Page, question: string) {
  const composer = page.getByLabel('Question')
  await composer.fill(question)
  await composer.press('Enter')
}
