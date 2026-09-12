import { expect, test } from '@playwright/test'
import {
  acquisitionAnswer,
  ask,
  districtOverview,
  impactAnswer,
  insufficientAnswer,
  mockCopilot,
  rankingAnswer,
  trendAnswer,
  useLanguage,
} from './fixtures'

/** On the narrow layout the insight pane replaces the chat pane. */
async function showInsight(page: import('@playwright/test').Page) {
  const toggle = page.getByRole('button', { name: /Charts & evidence/ })
  if (await toggle.isVisible()) await toggle.click()
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
  await expect(table.getByText(/Showing 2 selected rows/)).toBeVisible()
})

test('shows only published datasets and derives usable starter questions', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')

  const guide = page.getByRole('region', { name: 'Available published datasets' })
  await expect(guide).toContainText('Population')
  await expect(guide).toContainText('Quality 100%')
  await expect(guide).not.toContainText('Employment')
  await expect(guide).not.toContainText('internal-version-not-for-intro')
  await expect(page.getByRole('button', { name: 'Compare population trends by district' })).toBeVisible()
})

test('draws one line per series and leaves a gap for a missing period', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await ask(page, 'Compare population trend from 2023 to 2025')
  await expect(page.locator('.answer-text li')).toHaveCount(2)
  await expect(page.locator('.answer-text li').first()).toContainText('Banqiao: 120 → 150')
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
  await showChat(page)

  await expect(page.getByText('Source required')).toBeVisible()
  // The assistant asks for the missing source in the thread, not in the
  // insight pane, so the reader never has to go looking for the question.
  await expect(page.locator('.chat-panel .acquire')).toBeVisible()
  await expect(page.locator('.insight-panel .acquire')).toHaveCount(0)
  await expect(page.getByText('New Taipei population statistics')).toBeVisible()
  // The ask shows the host, never a clickable download link.
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

test('reads out the backend figure for a district and says when there is none', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')
  await ask(page, 'Where should I buy a home?')
  await showInsight(page)
  await page.getByRole('tab', { name: /Map/ }).click()

  await page.locator('.map-district[data-district="01"]').click()
  const readout = page.locator('.map-readout')
  await expect(readout).toContainText('Banqiao')
  await expect(readout).toContainText('55.6')
  await expect(readout).toContainText('Candidate ranking')

  // An uncited district must never borrow a neighbour's figure.
  await page.locator('.map-district[data-district="29"]').click()
  await expect(readout).toContainText('Not part of the current answer')
  await expect(readout).not.toContainText('55.6')
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

test('a declared choropleth drives the map and does not repeat in the charts tab', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await ask(page, 'Compare the population trend')
  await showInsight(page)

  // The map spec belongs to the Map tab, so the charts list keeps the other two.
  await expect(page.locator('.viz-card')).toHaveCount(2)
  await expect(page.locator('[data-viz-id="observation-map"]')).toHaveCount(0)

  await page.getByRole('tab', { name: /Map/ }).click()
  await expect(page.locator('.map-district.is-cited')).toHaveCount(2)
  await expect(page.locator('.map-district[data-district="01"]')).toHaveClass(/is-cited/)
  await expect(page.locator('.map-district[data-district="17"]')).toHaveClass(/is-cited/)

  // The readout names the map spec, not the trend line it was inferred from before.
  await page.locator('.map-district[data-district="01"]').click()
  const readout = page.locator('.map-readout')
  await expect(readout).toContainText('150')
  await expect(readout).toContainText('2025')

  // A district with no evidence stays unshaded and says so.
  await expect(page.locator('.map-note').first()).toContainText('Covered 2 of 29 districts')
  await expect(page.locator('.map-note').first()).toContainText('烏來區')
})

test('the limitation audit states source age, coverage, and population basis', async ({ page }) => {
  await mockCopilot(page, { query: trendAnswer })
  await page.goto('/')
  await ask(page, 'Compare the population trend')
  await showChat(page)

  const limits = page.locator('.data-limits')
  await limits.getByText('Data limitations').click()
  await expect(limits).toContainText('Registered household population')
  await expect(limits).toContainText('published 10 days ago')
  await expect(limits).toContainText('Covers 2 of 29 districts')
  await expect(limits).toContainText('貢寮區')
})

test('builds an impact chain and withholds unsupported investment advice', async ({ page }) => {
  await mockCopilot(page, { query: impactAnswer })
  await page.goto('/')
  await ask(page, 'Nếu thêm 2.000 thanh niên chuyển đến Linkou trước 2030, nên đầu tư hạ tầng gì?')
  await showInsight(page)

  await expect(page.getByRole('tab', { name: /Impact/ })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText('27,000')).toBeVisible()
  await expect(page.getByText('Housing capacity')).toBeVisible()
  await expect(page.getByText('Transport capacity')).toBeVisible()
  await expect(page.getByText('Public Services capacity')).toBeVisible()
  await expect(page.getByText(/Withheld until every required capacity link/)).toBeVisible()
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
