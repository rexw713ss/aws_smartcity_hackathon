import { expect, test } from '@playwright/test'
import {
  acquisitionAnswer,
  ask,
  insufficientAnswer,
  mockCopilot,
  rankingAnswer,
  trendAnswer,
} from './fixtures'

/** On the narrow layout the insight pane replaces the chat pane. */
async function showInsight(page: import('@playwright/test').Page) {
  const toggle = page.getByRole('button', { name: /Charts & evidence/ })
  if (await toggle.isVisible()) await toggle.click()
}

test('renders a ranking bar and the exact ranking table from one response', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')
  await ask(page, 'Which districts are best for young people buying a home?')

  await expect(page.getByText(rankingAnswer.answer)).toBeVisible()
  await showInsight(page)

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
  // `truncated: true` must be surfaced, never silently dropped.
  await expect(table.getByText(/Truncated/)).toBeVisible()
})

test('draws one line per series and leaves a gap for a missing period', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await ask(page, 'Compare population trend from 2023 to 2025')
  await showInsight(page)

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

test('reports insufficient evidence without inventing a chart', async ({ page }) => {
  await mockCopilot(page, { query: insufficientAnswer })
  await page.goto('/')
  await ask(page, 'Compare population trend from 2023 to 2025')

  await expect(page.getByText('Insufficient evidence')).toBeVisible()
  await expect(page.getByText(insufficientAnswer.warnings[0])).toBeVisible()
  await showInsight(page)
  await expect(page.locator('.viz-card')).toHaveCount(0)
  await expect(page.getByText('No charts yet')).toBeVisible()
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
  await showInsight(page)

  await expect(page.getByText('Source required')).toBeVisible()
  await expect(page.getByText('New Taipei population statistics')).toBeVisible()
  // The panel shows the host, never a clickable download link.
  await expect(page.getByText('data.example.gov.tw')).toBeVisible()
  await expect(page.locator('.acquire a')).toHaveCount(0)

  await page.getByLabel('Reviewer identity').fill('reviewer@example.gov.tw')
  await page.getByRole('button', { name: 'Fetch snapshot and submit for review' }).click()

  await expect(page.getByText('job-42')).toBeVisible()
  expect(submitted).toEqual([
    { candidateId: 'ntpc-population', submittedBy: 'reviewer@example.gov.tw' },
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
  await page.route('**/api/v1/copilot/query', async route => {
    const index = call++
    // The first question resolves after the second one.
    if (index === 0) await new Promise(resolve => setTimeout(resolve, 1500))
    return route.fulfill({
      json: index === 0
        ? { ...rankingAnswer, answer: 'stale answer' }
        : { ...insufficientAnswer, answer: 'newest answer' },
    })
  })
  await page.goto('/')
  await ask(page, 'first question')
  await ask(page, 'second question')

  await expect(page.getByText('newest answer')).toBeVisible()
  await page.waitForTimeout(2000)
  await expect(page.getByText('stale answer')).toHaveCount(0)
})
