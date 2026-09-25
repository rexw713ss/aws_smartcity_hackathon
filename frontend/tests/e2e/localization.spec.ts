import { expect, test, type Page } from '@playwright/test'
import { mockCopilot, rankingAnswer, useLanguage } from './fixtures'

async function showInsights(page: Page) {
  const toggle = page.getByRole('button', { name: '圖表與證據' })
  if (await toggle.isVisible()) await toggle.click()
}

test('Chinese topics, suggestions and tool descriptions keep canonical API identifiers', async ({ page }) => {
  const requests: unknown[] = []
  await mockCopilot(page, { query: { ...rankingAnswer, answer: '已完成分析。' }, onQuery: request => requests.push(request) })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  await expect(page).toHaveTitle('新北青策 · 決策助理')
  await expect(page.locator('meta[name="description"]')).toHaveAttribute('content', /新北青策/)
  for (const name of ['人口', '教育', '就業', '其他…']) {
    await expect(page.getByRole('radio', { name, exact: true })).toBeVisible()
  }
  // The existing compact mobile header hides the tools menu.
  const tools = page.locator('.capability-menu summary')
  if (await tools.isVisible()) {
    await tools.click()
    await expect(page.locator('.capability-menu')).toContainText('查詢觀測資料')
    await expect(page.locator('.capability-menu')).toContainText('執行經驗證的標準觀測資料唯讀查詢。')
    await tools.click()
  }
  await page.getByRole('radio', { name: '人口', exact: true }).click()
  await expect(page.getByRole('button', { name: '查看人口的時間趨勢' })).toBeVisible()
  await expect(page.getByRole('button', { name: '按性別比較人口' })).toBeVisible()
  await page.getByRole('button', { name: '概覽人口', exact: true }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toMatchObject({ question: '概覽人口', topicHint: 'population', responseLanguage: 'zh-TW' })
})

test('Chinese topic-change confirmation preserves the selected topic until accepted', async ({ page }) => {
  const requests: unknown[] = []
  await mockCopilot(page, { query: rankingAnswer, onQuery: request => requests.push(request) })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  await page.getByRole('radio', { name: '人口', exact: true }).click()
  await page.getByRole('textbox', { name: '問題' }).fill('查看就業的時間趨勢')
  await page.getByRole('button', { name: '傳送', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('目前選擇的「人口」')
  await expect(page.getByRole('alert')).toContainText('改為分析「就業」')
  expect(requests).toHaveLength(0)
  await page.getByRole('button', { name: '改為分析新主題' }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toMatchObject({ topicHint: 'employment', responseLanguage: 'zh-TW' })
})

test('IME confirmation and Shift+Enter do not submit an unfinished Chinese question', async ({ page }) => {
  const requests: unknown[] = []
  await mockCopilot(page, { query: rankingAnswer, onQuery: request => requests.push(request) })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  const input = page.getByRole('textbox', { name: '問題' })
  await input.fill('青年人口')
  await input.dispatchEvent('compositionstart')
  await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true })
  await input.dispatchEvent('compositionend', { data: '人口' })
  await expect(input).toHaveValue('青年人口')
  await expect(page.locator('.turn.question')).toHaveCount(0)
  await input.press('Shift+Enter')
  expect(requests).toHaveLength(0)
  await input.press('Enter')
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toMatchObject({ question: '青年人口' })
})

test('Chinese district overview translates genders and scope without changing values', async ({ page }, testInfo) => {
  await mockCopilot(page, { query: rankingAnswer })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  await showInsights(page)
  await page.locator('.map-district[data-district="01"]').click()
  await page.getByRole('button', { name: '查看 板橋區 人口概覽' }).click()
  const overview = page.locator('.district-overview')
  await expect(overview).toContainText('92,340')
  await expect(overview).toContainText('115-07 (2026)')
  const gender = page.locator('[data-overview-chart="gender"]')
  await expect(gender).toContainText('男性')
  await expect(gender).toContainText('女性')
  await expect(overview.locator('.panel-note')).toContainText('「青年人口」人口範圍')
  await expect(overview).not.toContainText('youth specific')
  await expect(gender).not.toContainText('Male')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('chinese-overview.png'), fullPage: true })
  await page.getByLabel('語言').selectOption('en')
  await expect(gender).toContainText('Male')
  await expect(gender).toContainText('Female')
  await expect(overview).toContainText('92,340')
})

test('Chinese review shows readable mappings and retains source keys for audit', async ({ page }, testInfo) => {
  await mockCopilot(page, { query: rankingAnswer })
  await useLanguage(page, 'zh-TW')
  await page.goto('/?review=job-42')
  await expect(page.getByRole('heading', { name: '檢查 AI 建議的資料對應' })).toBeVisible()
  await expect(page.locator('.review-job-bar')).toContainText('等待核准')
  await expect(page.locator('.review-summary')).toContainText('人口')
  await expect(page.locator('.review-summary')).toContainText('西元年 · 行政區代碼 · 原始年齡標籤')
  await expect(page.getByRole('cell', { name: '西元年 year_gregorian', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '解析年份', exact: true })).toBeVisible()
  await expect(page.getByRole('cell', { name: '加總 · 人', exact: true })).toBeVisible()
  await expect(page.locator('.preview-grid')).toContainText('民國年: 114 · 西元年: 2025')
  await expect(page.locator('.preview-grid')).toContainText('行政區代碼: 01')
  await expect(page.getByRole('button', { name: '核准並發布' })).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('chinese-review.png'), fullPage: true })
  await page.getByLabel('語言').selectOption('en')
  await expect(page.locator('.review-job-bar')).toContainText('Awaiting approval')
  await expect(page.getByRole('cell', { name: 'year_gregorian', exact: true })).toBeVisible()
})

test('Chinese request errors explain HTTP failures', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer, queryStatus: 429 })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  await page.getByRole('textbox', { name: '問題' }).fill('概覽人口')
  await page.getByRole('button', { name: '傳送', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('助理目前忙碌，請稍後再試。')
})

test('failed language refresh is visible and preserves the previous answer', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Question' }).fill('Overview of population')
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  await expect(page.getByLabel('Language')).toBeEnabled()
  await page.route('**/api/v1/copilot/query', route => route.fulfill({ status: 503, json: {} }))
  await page.getByLabel('Language').selectOption('zh-TW')
  const chat = page.getByRole('button', { name: '對話', exact: true })
  if (await chat.isVisible()) await chat.click()
  await expect(page.getByRole('alert')).toContainText('回答語言更新失敗')
  await expect(page.locator('.turn.answer')).toContainText(rankingAnswer.answer)
})
