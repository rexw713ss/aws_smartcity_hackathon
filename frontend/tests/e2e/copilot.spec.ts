import { expect, test } from '@playwright/test'
import {
  acquisitionAnswer,
  ask,
  datasetCatalog,
  districtForecast,
  districtOverview,
  impactAnswer,
  insufficientAnswer,
  mockCopilot,
  rankingAnswer,
  trendAnswer,
  useLanguage,
  webAcquisitionAnswer,
} from './fixtures'

/** On the narrow layout the insight pane replaces the chat pane. */
async function showInsight(page: import('@playwright/test').Page) {
  const toggle = page.getByRole('button', { name: /Charts & evidence/ })
  if (await toggle.isVisible()) await toggle.click()
}

async function showCharts(page: import('@playwright/test').Page) {
  await showInsight(page)
  await page.getByRole('tab', { name: /^Charts/ }).click()
}

/** The inverse: bring the conversation back on the narrow layout, where an
 * answer's caveats live beside the answer rather than in the insight pane. */
async function showChat(page: import('@playwright/test').Page) {
  const toggle = page.getByRole('button', { name: /^Conversation$/ })
  if (await toggle.isVisible()) await toggle.click()
}

test('renders a ranking bar and the exact ranking table from one response', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')
  await ask(page, 'Which districts are best for young people buying a home?')

  await expect(page.getByText(rankingAnswer.answer)).toBeVisible()
  await showCharts(page)

  const ranking = page.locator('[data-viz-id="candidate-ranking"]')
  await expect(ranking).toHaveAttribute('data-viz-type', 'ranking_bar')
  // A quantitative x encoding must lay the bars out horizontally.
  const bars = ranking.locator('.recharts-bar-rectangle path')
  await expect(bars).toHaveCount(2)
  const box = await bars.first().boundingBox()
  expect(box!.width).toBeGreaterThan(box!.height)

  // The table shows the backend's values verbatim, formatted for display only.
  const table = page.locator('[data-viz-id="candidate-ranking-table"]')
  await expect(table.locator('tbody tr')).toHaveCount(2)
  await expect(table.locator('tbody tr').first()).toContainText('Banqiao')
  await expect(table.locator('tbody tr').first()).toContainText('55.6')
  // The compact footer links the selected chart rows to the same evidence
  // target used by inline chat citations.
  await expect(table.getByText(/Showing 2 selected rows from/)).toBeVisible()
  const source = table.getByRole('button', { name: /Show source 1/ })
  await expect(source).toHaveText('[1]')
  await source.click()
  await expect(page.getByRole('tab', { name: /Evidence/ })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.locator('[data-citation-id="data-1"]')).toHaveClass(/is-focused/)
})

test('shows a compact topic picker and reveals suggestions only after selection', async ({ page }) => {
  const requests: unknown[] = []
  await mockCopilot(page, { query: rankingAnswer, onQuery: request => requests.push(request) })
  await page.goto('/')

  const tabs = page.getByRole('tablist', { name: 'Insight views' }).getByRole('tab')
  await expect(tabs.first()).toContainText('Map')
  await expect(page.getByRole('tab', { name: /^Map/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: /Impact|What-if/i })).toHaveCount(0)

  const topic = page.getByRole('radiogroup', { name: 'Topic' })
  await expect(topic.getByRole('radio', { name: 'Population' })).toHaveCount(1)
  await expect(topic.getByRole('radio', { name: 'Employment' })).toHaveCount(1)
  await expect(topic.getByRole('radio', { name: 'Education' })).toHaveCount(1)
  await expect(topic.getByRole('radio', { name: 'Others…' })).toHaveCount(1)
  await expect(topic.getByRole('radio', { name: /Transport/i })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /overview of population/i })).toHaveCount(0)

  await topic.getByRole('radio', { name: 'Population' }).click()
  await expect(page.getByRole('button', { name: 'Give me an overview of Population' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show the Population trend over time' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Compare Population across districts' })).toBeVisible()

  await topic.getByRole('radio', { name: 'Others…' }).click()
  await expect(page.getByRole('button', { name: /overview of population/i })).toHaveCount(0)
  await ask(page, 'Help me explore the available data')
  await expect(page.getByText(rankingAnswer.answer)).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0]).not.toHaveProperty('topicHint')
})

test('confirms a detected topic change before sending it to the agent', async ({ page }) => {
  const requests: unknown[] = []
  const employment = {
    ...datasetCatalog[1],
    status: 'published',
    qualityScore: 1,
    publishedAt: '2026-09-03T00:00:00Z',
  }
  await mockCopilot(page, {
    query: rankingAnswer,
    datasets: [datasetCatalog[0], employment],
    onQuery: request => requests.push(request),
  })
  await page.goto('/')
  await page.getByRole('radio', { name: 'Population' }).click()
  await page.getByRole('textbox', { name: 'Question' }).fill('Show the employment trend over time')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText(/current topic is Population/)).toBeVisible()
  expect(requests).toHaveLength(0)
  await page.getByRole('button', { name: 'Analyze new topic' }).click()

  await expect(page.getByText(rankingAnswer.answer)).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ topicHint: 'employment' })
})

test('keeps charts from earlier questions in compact history tabs', async ({ page }) => {
  await mockCopilot(page, {
    query: index => index === 0 ? trendAnswer : rankingAnswer,
  })
  await page.goto('/')

  await ask(page, 'Compare population trend from 2023 to 2025')
  await expect(page.getByText(/Population count comparison/)).toBeVisible()
  await showChat(page)
  await expect(page.getByRole('button', { name: 'Cancel' })).toHaveCount(0)
  await ask(page, 'Give me a population overview')
  await expect(page.getByText(rankingAnswer.answer)).toBeVisible()
  await showCharts(page)

  const history = page.getByRole('tablist', { name: 'Charts by question' })
  await expect(history.getByRole('tab')).toHaveCount(2)
  await expect(history.getByRole('tab', { name: /population overview/i })).toHaveAttribute('aria-selected', 'true')
  await history.getByRole('tab', { name: /Compare population trend/i }).click()
  await expect(page.locator('[data-viz-id="observation-trend"]')).toBeVisible()
  await expect(page.locator('[data-viz-id="candidate-ranking"]')).toHaveCount(0)
})

test('starts a clean conversation from the chat toolbar', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await page.getByRole('radio', { name: 'Population' }).click()
  await ask(page, 'Compare population trend from 2023 to 2025')
  await expect(page.getByText(/Population count comparison/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel' })).toHaveCount(0)

  await page.getByRole('button', { name: 'New conversation' }).click()

  await expect(page.getByText('Choose a topic')).toBeVisible()
  await expect(page.locator('.turn')).toHaveCount(0)
  await expect(page.getByRole('radio', { name: 'Population' })).toHaveAttribute('aria-checked', 'false')
  await expect(page.getByRole('button', { name: 'New conversation' })).toBeDisabled()
  await showInsight(page)
  await expect(page.getByRole('tab', { name: /^Map/ })).toHaveAttribute('aria-selected', 'true')
  await page.getByRole('tab', { name: /^Charts/ }).click()
  await expect(page.getByRole('tablist', { name: 'Charts by question' })).toHaveCount(0)
})

test('draws one continuous line per series across a missing period', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await ask(page, 'Compare population trend from 2023 to 2025')
  await expect(page.locator('.answer-text li')).toHaveCount(2)
  await expect(page.locator('.answer-text li').first()).toContainText('Banqiao: 120 → 150')
  await showCharts(page)

  const trend = page.locator('[data-viz-id="observation-trend"]')
  await expect(trend).toHaveAttribute('data-viz-type', 'line')
  await expect(trend.locator('.recharts-line-curve')).toHaveCount(2)
  await expect(trend.getByText('Banqiao')).toBeVisible()
  await expect(trend.getByText('Linkou')).toBeVisible()

  // A negative change renders on the opposite side of a zero reference line.
  const comparison = page.locator('[data-viz-id="entity-change-comparison"]')
  await expect(comparison.locator('.recharts-reference-line')).toHaveCount(1)
})

test('shows evidence and tool trace on their own tabs', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')
  await ask(page, 'Which districts are best for young people buying a home?')
  await showInsight(page)

  await page.getByRole('tab', { name: /Evidence/ }).click()
  await expect(page.getByText('property_cost_source')).toBeVisible()
  await expect(page.getByText(/Version v1/)).toBeVisible()

  await page.getByRole('tab', { name: /Trace/ }).click()
  await expect(page.locator('.trace-list li')).toHaveCount(2)
  await expect(page.getByText('2 candidates scored')).toBeVisible()
})

test('opens and focuses the matching evidence from a numbered inline citation', async ({ page }) => {
  await mockCopilot(page, {
    query: {
      ...rankingAnswer,
      answer: 'Banqiao leads because of transit access [data-1].',
    },
  })
  await page.goto('/')
  await ask(page, 'Where should I buy a home?')

  const citation = page.getByRole('button', { name: /Show source 1/ })
  await expect(citation).toHaveText('[1]')
  await citation.click()

  await expect(page.getByRole('tab', { name: /Evidence/ })).toHaveAttribute('aria-selected', 'true')
  const source = page.locator('[data-citation-id="data-1"]')
  await expect(source).toHaveClass(/is-focused/)
  await expect(source).toContainText('property_cost_source')
  await expect(source.getByLabel('Source 1')).toHaveText('[1]')
  await expect(source.locator('.evidence-excerpt')).toHaveAttribute('open', '')
  await expect(source.locator('.evidence-table tbody tr')).toHaveCount(2)
  await expect(source.locator('.evidence-table')).toContainText('Banqiao')
  await expect(source.locator('.evidence-table')).toContainText('82')
})

test('reports insufficient evidence without inventing a chart', async ({ page }) => {
  await mockCopilot(page, { query: insufficientAnswer })
  await page.goto('/')
  await ask(page, 'Compare population trend from 2023 to 2025')

  await expect(page.getByText('Insufficient evidence')).toBeVisible()
  await expect(page.getByText(insufficientAnswer.warnings[0])).toBeVisible()
  await expect(page.locator('.chat-panel .data-request')).toBeVisible()
  await expect(page.locator('.data-request .gap-summary')).toContainText('Population · Employment')
  await showCharts(page)
  await expect(page.locator('.viz-card')).toHaveCount(0)
  await expect(page.getByText('No charts yet')).toBeVisible()
})

test('does not force the first missing topic onto a multi-topic upload', async ({ page }) => {
  let uploadBody = ''
  await mockCopilot(page, { query: insufficientAnswer })
  await page.route('**/api/v1/datasets/upload', route => {
    uploadBody = route.request().postData() ?? ''
    return route.fulfill({ status: 202, json: {
      jobId: 'job-employment', status: 'awaiting_approval',
      links: { job: '/api/v1/ingestion-jobs/job-employment' },
    } })
  })
  await page.goto('/')
  await ask(page, 'Compare youth population and employment by district')

  const request = page.locator('.chat-panel .data-request')
  await request.getByRole('button', { name: 'Provide your own data' }).click()
  await request.locator('input[type="file"]').setInputFiles('../data/samples/employment_demo.csv')
  await request.getByRole('button', { name: 'Upload and process' }).click()

  await expect(page.getByRole('heading', { name: 'Review the AI-proposed mapping' })).toBeVisible()
  expect(uploadBody).not.toContain('name="topic_hint"')
})

test('submits only a configured candidateId for acquisition', async ({ page }) => {
  const submitted: unknown[] = []
  await mockCopilot(page, { query: acquisitionAnswer })
  await page.route('**/api/v1/copilot/acquisitions', route => {
    submitted.push(route.request().postDataJSON())
    return route.fulfill({
      json: {
        candidate: acquisitionAnswer.source_candidates[0],
        ingestion_job_id: 'job-42',
        ingestion_status: 'awaiting_approval',
        created_at: '2026-09-12T07:05:00Z',
      },
    })
  })
  await page.goto('/')
  await ask(page, 'Is there newer population data?')
  await showChat(page)

  await expect(page.getByText('Source required')).toBeVisible()
  // The assistant asks for the missing data in the thread, as its own turn,
  // and never in the insight pane.
  const request = page.locator('.chat-panel .data-request')
  await expect(request).toBeVisible()
  await expect(page.locator('.insight-panel .data-request')).toHaveCount(0)
  await expect(request.getByText('Here is what I am missing')).toBeVisible()
  await expect(request.getByText('The published catalog does not hold enough to go further, so I stop here rather than guess.')).toHaveCount(0)
  await expect(request.locator('.gap-summary')).toContainText('Needed')
  await expect(request.getByText('New Taipei population statistics')).toBeVisible()
  // The suggestion shows the host, never a clickable download link.
  await expect(request.getByText(/data\.example\.gov\.tw/)).toBeVisible()
  await expect(request.locator('a')).toHaveCount(0)
  // Bringing your own data starts as a third action in the same card and
  // expands the file/link controls in place.
  const provideOwn = request.getByRole('button', { name: 'Provide your own data' })
  await expect(provideOwn).toBeVisible()
  await expect(request.locator('.request-step')).toHaveCount(1)
  await expect(request.getByRole('tab', { name: 'Upload a file' })).toHaveCount(0)
  await provideOwn.click()
  await expect(provideOwn).toHaveAttribute('aria-expanded', 'true')
  await expect(request.getByRole('tab', { name: 'Upload a file' })).toBeVisible()
  await expect(request.getByRole('tab', { name: 'Paste a link' })).toBeVisible()

  await expect(request.getByLabel('Submitted by')).toHaveCount(0)
  await request.getByRole('button', { name: 'Accept and process' }).click()

  await expect(request.locator('.intake-progress')).toBeVisible()
  await expect(request.getByText('Building canonical mapping')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Review the AI-proposed mapping' })).toBeVisible()
  expect(submitted).toEqual([
    { candidateId: 'ntpc-population', submittedBy: 'youth-compass-web' },
  ])
})

test('reviews mapping evidence and explicitly approves publication in React', async ({ page }) => {
  const decisions: unknown[] = []
  const requests: unknown[] = []
  await mockCopilot(page, {
    query: index => index === 0 ? acquisitionAnswer : rankingAnswer,
    onQuery: request => requests.push(request),
  })
  await page.route('**/api/v1/ingestion-jobs/*/decision', route => {
    decisions.push(route.request().postDataJSON())
    return route.fulfill({ json: {
      jobId: 'job-42', datasetId: 'population', status: 'published', sourceFormat: 'csv',
      currentStep: 'published', qualityScore: 0.99, createdAt: '2026-09-12T07:05:00Z', warnings: [], links: {},
    } })
  })
  await page.goto('/')
  await ask(page, 'Find newer population data')
  await showChat(page)
  await page.getByRole('button', { name: 'Accept and process' }).click()

  await expect(page.getByRole('heading', { name: 'Review the AI-proposed mapping' })).toBeVisible()
  await expect(page.getByText('population.csv')).toBeVisible()
  await expect(page.getByRole('cell', { name: 'year_gregorian' })).toBeVisible()
  await expect(page.getByText('Year gregorian: 2025')).toBeVisible()
  await expect(page.getByText('District code: 01')).toBeVisible()
  await expect(page.getByText('No structural issue blocks publication.')).toBeVisible()

  await page.getByLabel('Review note').fill('District, time, metric, and unit checked.')
  await page.getByRole('button', { name: 'Approve & publish' }).click()

  await expect(page.getByText('Dataset published')).toBeVisible()
  expect(requests).toHaveLength(1)
  expect(decisions).toEqual([{
    decision: 'approve',
    decidedBy: 'steward@newtaipei.gov.tw',
    comment: 'District, time, metric, and unit checked.',
  }])

  await page.locator('.review-outcome').getByRole('button', { name: 'Back to assistant' }).click()
  await expect(page.getByText(rankingAnswer.answer)).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[1]).toMatchObject(requests[0] as Record<string, unknown>)
})

test('submits an approved web suggestion through governed link intake', async ({ page }) => {
  const submitted: unknown[] = []
  await mockCopilot(page, { query: webAcquisitionAnswer })
  await page.route('**/api/v1/copilot/acquisitions/link', route => {
    submitted.push(route.request().postDataJSON())
    return route.fulfill({
      json: {
        ingestion_job_id: 'job-web-42',
        ingestion_status: 'awaiting_approval',
        file_name: 'housing.csv',
      },
    })
  })
  await page.goto('/')
  await ask(page, 'Find the missing housing data')
  await showChat(page)

  const request = page.locator('.chat-panel .data-request')
  const source = request.getByRole('link', { name: 'New Taipei housing open data' })
  await expect(source).toHaveAttribute(
    'href',
    'https://data.ntpc.gov.tw/datasets/housing.csv',
  )
  await expect(request.getByText('Found with Brave Search; format is checked after acceptance')).toBeVisible()
  await request.getByRole('button', { name: 'Accept and process' }).click()

  await expect(request.locator('.intake-progress')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Review the AI-proposed mapping' })).toBeVisible()
  expect(submitted).toEqual([
    {
      url: 'https://data.ntpc.gov.tw/datasets/housing.csv',
      submittedBy: 'youth-compass-web',
      topicHint: 'housing',
    },
  ])
})

test('rejects a response that breaks the published contract', async ({ page }) => {
  await mockCopilot(page, {
    query: { ...rankingAnswer, status: 'totally_made_up' },
  })
  await page.goto('/')
  await ask(page, 'Which districts are best for young people buying a home?')

  await expect(page.getByRole('alert')).toContainText('contract')
  await expect(page.locator('.viz-card')).toHaveCount(0)
})

test('rejects a chart row carrying a non-finite number', async ({ page }) => {
  await mockCopilot(page, {
    query: () => JSON.parse(
      JSON.stringify(rankingAnswer).replace('"score": 55.6', '"score": 1e999'),
    ),
  })
  await page.goto('/')
  await ask(page, 'Which districts are best for young people buying a home?')
  await expect(page.getByRole('alert')).toBeVisible()
})

test('renders a model-authored answer as text, never as markup', async ({ page }) => {
  await mockCopilot(page, {
    query: { ...rankingAnswer, answer: '<img src=x onerror="window.__xss=1">injection probe' },
  })
  await page.goto('/')
  await ask(page, 'Which districts are best for young people buying a home?')

  await expect(page.getByText('injection probe')).toBeVisible()
  expect(await page.evaluate(() => (window as never as { __xss?: number }).__xss)).toBeUndefined()
  await expect(page.locator('.answer-text img')).toHaveCount(0)
})

test('a stale reply cannot replace the newest answer', async ({ page }) => {
  await page.route('**/api/v1/copilot/capabilities', route => route.fulfill({ json: [] }))
  let call = 0
  await page.route('**/api/v1/copilot/query/stream', async route => {
    const index = call++
    // The first question resolves after the second one.
    if (index === 0) await new Promise(resolve => setTimeout(resolve, 1500))
    const response = index === 0
      ? { ...rankingAnswer, answer: 'stale answer' }
      : { ...insufficientAnswer, answer: 'newest answer' }
    return route.fulfill({
      contentType: 'application/x-ndjson',
      body: `${JSON.stringify({ type: 'delta', text: response.answer })}\n${JSON.stringify({ type: 'result', response })}\n`,
    })
  })
  await page.goto('/')
  await ask(page, 'first question')
  await ask(page, 'second question')

  await expect(page.getByText('newest answer')).toBeVisible()
  await page.waitForTimeout(2000)
  await expect(page.getByText('stale answer')).toHaveCount(0)
})

test('highlights only districts the answer actually names', async ({ page }) => {
  await mockCopilot(page, {
    query: {
      ...rankingAnswer,
      visualizations: [
        {
          ...rankingAnswer.visualizations[0],
          rows: [
            { rank: 1, entity_id: 'banqiao', entity_name: 'Banqiao', score: 55.6, eligible: true },
            { rank: 2, entity_id: '17', entity_name: '林口區', score: 41.2, eligible: true },
            { rank: 3, entity_id: 'site-xindian-river', entity_name: 'Xindian riverside', score: 30, eligible: true },
          ],
        },
      ],
    },
  })
  await page.goto('/')
  await ask(page, 'Where should I buy a home?')
  await showInsight(page)
  await page.getByRole('tab', { name: /Map/ }).click()

  // 'banqiao' (English slug) and '17' (district code) both resolve; the site does not.
  await expect(page.locator('.map-district.is-cited')).toHaveCount(2)
  await expect(page.locator('.map-district[data-district="01"]')).toHaveClass(/is-cited/)
  await expect(page.locator('.map-district[data-district="17"]')).toHaveClass(/is-cited/)
  await expect(page.getByText(/Not shown on the map/)).toContainText('Xindian riverside')
})

test('labels every district and keeps the map stable while a label is hovered', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')
  await ask(page, 'Where should I buy a home?')
  await showInsight(page)
  await page.getByRole('tab', { name: /Map/ }).click()

  await expect(page.locator('.map-district-label')).toHaveCount(29)
  const stage = page.locator('.map-stage')
  const initialHeight = (await stage.boundingBox())!.height
  const banqiao = page.locator('.map-district[data-district="01"]')
  await page.locator('.map-district-label[data-district-label="01"]').hover({ force: true })
  await expect(banqiao).toHaveClass(/is-hovered/)
  expect((await stage.boundingBox())!.height).toBe(initialHeight)

  await page.getByRole('tab', { name: /Map/ }).hover()
  await expect(banqiao).not.toHaveClass(/is-hovered/)
  expect((await stage.boundingBox())!.height).toBe(initialHeight)

  // The lower card contains selection state only, not a hover readout.
  await page.locator('.map-district[data-district="29"]').click()
  const selection = page.locator('.map-readout')
  await expect(selection).toContainText('Wulai')
  await expect(selection).not.toContainText('Not part of the current answer')
})

test('opens a district overview without creating another agent turn', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')
  await ask(page, 'Where should I buy a home?')
  await showInsight(page)
  await page.getByRole('tab', { name: /Map/ }).click()

  await page.locator('.map-district[data-district="01"]').click()
  await page.getByRole('button', { name: 'View Banqiao population overview' }).click()

  await expect(page.getByRole('tab', { name: /Charts/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('heading', { name: /Banqiao/ })).toBeVisible()
  await expect(page.locator('[data-overview-chart]')).toHaveCount(3)
  await expect(page.locator('[data-overview-chart="trend"] .recharts-line-curve')).toHaveCount(1)
  await expect(page.locator('[data-overview-chart="age"]')).toContainText('32.4%')
  await expect(page.locator('[data-overview-chart="age"] .recharts-pie-sector')).toHaveCount(4)
  await expect(page.locator('.turn.question')).toHaveCount(1)
  await expect(page.locator('.turn.answer')).toHaveCount(1)
  await expect(page.getByText(districtOverview.total.toLocaleString())).toBeVisible()
})

test('draws the published forecast after the observed trend in a district overview', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer, districtForecast })
  await page.goto('/')
  await ask(page, 'Where should I buy a home?')
  await showInsight(page)
  await page.getByRole('tab', { name: /Map/ }).click()

  await page.locator('.map-district[data-district="01"]').click()
  await page.getByRole('button', { name: 'View Banqiao population overview' }).click()

  const chart = page.locator('[data-overview-chart="forecast"]')
  await expect(chart).toBeVisible()
  await expect(chart.locator('.recharts-line-curve')).toHaveCount(2)
  await expect(chart).toContainText('80% interval')
  // The forecast is kept apart from the published figures, under its own label.
  await expect(page.locator('.overview-kpis')).not.toContainText('89,800')
  const section = page.locator('[data-overview-section="forecast"]')
  await expect(section).toContainText('Model estimate, not published data')
  await expect(section.locator('[data-overview-kpi="forecast"]')).toContainText('89,800')
  await expect(section).toContainText('Metrics: 5-year mean absolute error 1.3%')
  await expect(section).not.toContainText('cohort-change-ratio-v1')
  await expect(section).not.toContainText('Backtest')
  await expect(section).toContainText('mean absolute error 1.3%')
  await expect(page.locator('[data-overview-chart="forecast-components"]')).toContainText('Turning 18')
  await expect(page.locator('.turn.question')).toHaveCount(1)
})

test('selects multiple map districts and compares all of them in one overview', async ({ page }) => {
  await mockCopilot(page, {
    query: rankingAnswer,
    districtOverview: code => code === '02'
      ? {
          ...districtOverview,
          districtCode: '02',
          districtName: '三重區',
          total: 80120,
          percentChange: 0.4,
          trend: districtOverview.trend.map(point => ({ ...point, value: point.value - 12000 })),
          ageDistribution: districtOverview.ageDistribution.map(item => ({ ...item, value: item.value - 1000 })),
          genderDistribution: districtOverview.genderDistribution.map(item => ({ ...item, value: item.value - 6000 })),
        }
      : districtOverview,
  })
  await page.goto('/')
  await ask(page, 'Where should I buy a home?')
  await showInsight(page)
  await page.getByRole('tab', { name: /Map/ }).click()

  await page.locator('.map-district[data-district="01"]').click()
  await page.locator('.map-district[data-district="02"]').click()
  await expect(page.locator('.map-district.is-selected')).toHaveCount(2)
  await expect(page.getByText('2 districts selected')).toBeVisible()
  await page.getByRole('button', { name: 'View 2 selected districts' }).click()

  await expect(page.getByRole('heading', { name: '2-district comparison' })).toBeVisible()
  await expect(page.locator('[data-overview-chart]')).toHaveCount(3)
  await expect(page.locator('[data-overview-chart="trend"] .recharts-line-curve')).toHaveCount(2)
  await expect(page.locator('.overview-series-legend')).toContainText('Banqiao')
  await expect(page.locator('.overview-series-legend')).toContainText('Sanchong')
})

test('a declared choropleth drives the map and does not repeat in the charts tab', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await ask(page, 'Compare the population trend')
  await showCharts(page)

  // The map spec belongs to the Map tab, so the charts list keeps the other two.
  await expect(page.locator('.viz-card')).toHaveCount(2)
  await expect(page.locator('[data-viz-id="observation-map"]')).toHaveCount(0)

  await page.getByRole('tab', { name: /Map/ }).click()
  await expect(page.locator('.map-district.is-cited')).toHaveCount(2)
  await expect(page.locator('.map-district[data-district="01"]')).toHaveClass(/is-cited/)
  await expect(page.locator('.map-district[data-district="17"]')).toHaveClass(/is-cited/)

  // Selecting a district only adds it to the compact selection card; detailed
  // values remain encoded by the map and its legend rather than duplicated below.
  await page.locator('.map-district[data-district="01"]').click()
  const selection = page.locator('.map-readout')
  await expect(selection).toContainText('Banqiao')
  await expect(selection).not.toContainText('2025')

  // A district with no evidence stays unshaded and says so.
  await expect(page.locator('.map-note').first()).toContainText('Covered 2 of 29 districts')
  await expect(page.locator('.map-note').first()).toContainText('烏來區')
})

test('a negative change map makes the strongest decline darkest', async ({ page }) => {
  const changeAnswer = structuredClone(trendAnswer)
  const map = changeAnswer.visualizations.find(item => item.type === 'choropleth')!
  map.title = 'Population change'
  map.y = { field: 'value', label: 'Change (%)', data_type: 'quantitative', unit: 'percent' }
  map.rows[0].value = -7.5
  map.rows[0].period = '2011–2026'
  map.rows[1].value = -17
  map.rows[1].period = '2011–2026'

  await mockCopilot(page, { query: changeAnswer })
  await page.goto('/')
  await ask(page, 'Show population change by district')
  await showInsight(page)
  await page.getByRole('tab', { name: /Map/ }).click()

  const mild = page.locator('.map-district[data-district="01"] path')
  const severe = page.locator('.map-district[data-district="17"] path')
  await expect(mild).toHaveAttribute('fill', /chart-negative.*44/)
  await expect(severe).toHaveAttribute('fill', /chart-negative.*88/)
  await expect(page.locator('.map-legend-ramp')).toHaveAttribute('data-scale', 'negative')

  await page.locator('.map-district[data-district="17"]').hover()
  const hover = page.locator('.map-hover-card')
  await expect(hover).toContainText('Linkou')
  await expect(hover).toContainText('-17')
  await expect(hover).toContainText('2011–2026')
})

test('does not render the backend data-limitations audit', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await ask(page, 'Compare the population trend')
  await showChat(page)

  await expect(page.locator('.data-limits')).toHaveCount(0)
  await expect(page.locator('.status-pill')).toHaveCount(0)

  await showInsight(page)
  await page.getByRole('tab', { name: /Evidence/ }).click()
  await expect(page.locator('.evidence-audit')).toHaveCount(0)
  await expect(page.getByText('Data limitations')).toHaveCount(0)
  await expect(page.getByText(/Outside the district set/)).toHaveCount(0)
})

test('keeps what-if output out of the insight navigation', async ({ page }) => {
  await mockCopilot(page, { query: impactAnswer })
  await page.goto('/')
  await ask(page, 'Nếu thêm 2.000 thanh niên chuyển đến Linkou trước 2030, nên đầu tư hạ tầng gì?')
  await showInsight(page)

  await expect(page.getByRole('tab', { name: /Impact|What-if/i })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: /^Map/ })).toHaveAttribute('aria-selected', 'true')
})


test('opens in Traditional Chinese and switches the whole shell to English', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  // Runs after the fixture's own init script, so it wins: this page starts with
  // no stored preference and must fall back to the shipped default.
  await page.addInitScript(() => window.localStorage.removeItem('youth-compass-language'))
  await page.goto('/')

  const picker = page.getByLabel('語言')
  await expect(picker).toHaveValue('zh-TW')
  await expect(page.locator('html')).toHaveAttribute('lang', 'zh-TW')
  await expect(page.getByLabel('問題')).toBeVisible()

  await picker.selectOption('en')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByLabel('Question')).toBeVisible()

  // The choice survives a reload.
  await page.reload()
  await expect(page.getByLabel('Language')).toHaveValue('en')
})

test('regenerates existing chat and charts when the interface language changes', async ({ page }) => {
  const requests: unknown[] = []
  const chineseAnswer = {
    ...trendAnswer,
    answer: '板橋區人口在所選期間增加。[data-1]',
    visualizations: trendAnswer.visualizations.map((spec, index) => ({
      ...spec,
      title: index === 0 ? '人口趨勢' : spec.title,
    })),
  }
  await mockCopilot(page, {
    query: (_index, request) => (
      (request as { responseLanguage?: string }).responseLanguage === 'zh-TW'
        ? chineseAnswer
        : trendAnswer
    ),
    onQuery: request => requests.push(request),
  })
  await page.goto('/')
  await ask(page, 'Compare population trend from 2023 to 2025')
  await expect(page.getByText(/Population count comparison/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel' })).toHaveCount(0)

  await page.getByLabel('Language').selectOption('zh-TW')
  await expect(page.getByText(/板橋區人口在所選期間增加/)).toBeVisible()
  await expect(page.getByText(/Population count comparison/)).toHaveCount(0)
  await showInsight(page)
  await page.getByRole('tab', { name: /^圖表/ }).click()
  await expect(page.locator('[data-viz-id="observation-trend"]')).toContainText('人口趨勢')
  expect(requests).toHaveLength(2)
  expect(requests[0]).toMatchObject({ responseLanguage: 'en' })
  expect(requests[1]).toMatchObject({ responseLanguage: 'zh-TW' })
})

test('names every district in the reader’s language on the map', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  await ask(page, '哪些行政區最適合青年購屋？')

  const toggle = page.getByRole('button', { name: /圖表與證據/ })
  if (await toggle.isVisible()) await toggle.click()
  await page.getByRole('tab', { name: /地圖/ }).click()

  await expect(page.getByRole('button', { name: /^板橋區/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Banqiao District/ })).toHaveCount(0)
})
