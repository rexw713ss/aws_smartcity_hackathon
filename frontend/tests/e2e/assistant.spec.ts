import { expect, test, Page, Route } from '@playwright/test'

const answer = {
  answer: 'A source-backed answer from the backend.',
  evidence: [{ datasetId: 'fact_youth_population_monthly', metric: 'youth_population', period: '2025-12', districtCode: '0', value: 1234, unit: 'persons', isEstimated: false }],
  warnings: ['Historical association does not establish a cause.'],
  dashboardActions: [{ type: 'SELECT_DISTRICTS', values: ['1'] }],
}

async function liveMode(page: Page) {
  // Simulates the build-time public API base without changing developer .env.
  await page.route('**/src/components/AiAssistant.tsx*', async route => {
    const response = await route.fetch()
    const source = await response.text()
    expect(source).toContain('import.meta.env.VITE_COPILOT_API_BASE')
    await route.fulfill({ response, body: source.replace('import.meta.env.VITE_COPILOT_API_BASE', JSON.stringify('/api/v1')) })
  })
  await page.route('**/api/v1/copilot/sessions', route => route.fulfill({ json: { sessionId: 'test-session' } }))
}

test('chart shortcuts carry real context; preview and saved briefs never pretend to be AI', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  let networkCalls = 0
  page.on('request', request => { if (request.url().includes('/copilot/')) networkCalls++ })
  await page.goto('/')
  await page.getByRole('button', { name: '詢問「教育程度」', exact: true }).click()
  await expect(page.locator('#ai-chart')).toHaveValue('education-levels')
  await expect(page.locator('#ai-title')).toBeFocused()
  const context = page.getByRole('complementary', { name: 'AI 助理資料脈絡' })
  await expect(context).toContainText('2026')
  await expect(context).toContainText('2025-01 至 2025-12')
  await expect(context).toContainText('有登記教育程度的全體居民')
  await page.getByRole('button', { name: '摘要這張圖表' }).click()
  await expect(page.locator('.ai-response')).toContainText('非 AI 生成')
  await expect(page.locator('.ai-answer')).toContainText('新北市')
  await expect(page.locator('.ai-warnings')).toContainText('不限青年')
  await page.getByText('來源證據（1）', { exact: true }).click()
  await expect(page.locator('.ai-evidence')).toContainText('education_summary.csv')
  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '儲存摘要' }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toBe('youth-compass-education-levels-2026.txt')
  await page.locator('#ai-question').fill('Why do people move?')
  await page.getByRole('button', { name: '試用預覽', exact: true }).click()
  await expect(page.locator('.ai-answer').last()).toContainText('未解讀你的問題')
  await page.locator('#ai-chart').selectOption('migration-forecast')
  await expect(page.locator('.ai-exchange')).toHaveCount(0)
  await page.getByRole('button', { name: '摘要這張圖表' }).click()
  await expect(page.locator('.ai-answer')).toContainText('全年齡層')
  await expect(page.locator('.ai-warnings')).toContainText('不受資料年份篩選器影響')
  expect(networkCalls).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('missing historical releases have no fabricated data', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await page.getByLabel('資料年份', { exact: true }).click()
  await page.getByRole('option', { name: /^2011/ }).click()
  await expect(page.locator('#population-trend .recharts-area-dots .recharts-dot')).toHaveCount(1)
  await expect(page.locator('#population-trend .recharts-area-dots .recharts-dot')).toHaveCSS('visibility', 'visible')
  await page.getByRole('button', { name: '詢問「教育程度」', exact: true }).click()
  await expect(page.locator('.ai-context')).toContainText('沒有相容資料')
  await expect(page.getByRole('button', { name: '摘要這張圖表' })).toBeDisabled()
  await expect(page.locator('#ai-assistant')).toContainText('這張圖表在 2011 年沒有相容資料')
})

test('live API context is typed, failures can retry, and model actions need a click', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await liveMode(page)
  let calls = 0
  let payload: any
  await page.route('**/api/v1/copilot/chat', async route => {
    calls++
    payload = route.request().postDataJSON()
    await route.fulfill(calls === 1 ? { status: 503, json: {} } : { json: answer })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '詢問「青年人口趨勢」', exact: true }).click()
  await expect(page.locator('.ai-mode')).toHaveText('API 已連線')
  expect(calls).toBe(0)
  await page.getByRole('button', { name: '摘要這張圖表' }).click()
  await expect(page.getByRole('alert')).toContainText('503')
  await page.getByRole('button', { name: '重試' }).click()
  await expect(page.locator('.ai-answer')).toContainText('source-backed answer')
  expect(payload).toMatchObject({ sessionId: 'test-session', message: '摘要這張圖表',
    dashboardContext: { selectedDistricts: ['0'], activePanel: 'population-trend', activeMetric: 'youth_population', period: { start: '2011-12', end: '2026-07' } } })
  await expect(page.getByRole('combobox', { name: '行政區', exact: true })).toContainText('全市')
  await page.getByRole('button', { name: '選擇板橋區', exact: true }).click()
  await expect(page.getByRole('combobox', { name: '行政區', exact: true })).toContainText('板橋區')
  await expect(page.locator('.ai-exchange')).toHaveCount(0)
})

test('cancel and context changes discard late answers; malformed actions are rejected', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await liveMode(page)
  const routes: Route[] = []
  await page.route('**/api/v1/copilot/chat', route => { routes.push(route) })
  await page.goto('/')
  await page.getByRole('button', { name: '詢問「青年人口趨勢」', exact: true }).click()
  await page.getByRole('button', { name: '摘要這張圖表' }).click()
  await expect.poll(() => routes.length).toBe(1)
  await page.getByRole('button', { name: '取消請求' }).click()
  await routes[0].fulfill({ json: answer }).catch(() => {})
  await expect(page.locator('.ai-answer')).toHaveCount(0)
  await page.getByRole('button', { name: '摘要這張圖表' }).click()
  await expect.poll(() => routes.length).toBe(2)
  await page.locator('#ai-chart').selectOption('age-structure')
  await routes[1].fulfill({ json: answer }).catch(() => {})
  await expect(page.locator('.ai-answer')).toHaveCount(0)
  await page.getByRole('button', { name: '摘要這張圖表' }).click()
  await expect.poll(() => routes.length).toBe(3)
  await routes[2].fulfill({ json: { ...answer, dashboardActions: [{ type: 'DELETE_DATA' }] } })
  await expect(page.getByRole('alert')).toContainText('格式無效')
  await expect(page.locator('.ai-answer')).toHaveCount(0)
})

test('a timed-out request is recoverable and never becomes a preview answer', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await liveMode(page)
  let pendingRoute: Route | undefined
  await page.route('**/api/v1/copilot/chat', route => { pendingRoute = route })
  await page.goto('/')
  await page.getByRole('button', { name: '詢問「青年人口趨勢」', exact: true }).click()
  await page.clock.install()
  await page.getByRole('button', { name: '摘要這張圖表' }).click()
  await expect.poll(() => Boolean(pendingRoute)).toBe(true)
  await page.clock.fastForward(30001)
  await expect(page.getByRole('alert')).toContainText('回應逾時')
  await expect(page.locator('.ai-answer')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '重試' })).toBeEnabled()
  await pendingRoute!.fulfill({ json: answer }).catch(() => {})
})
