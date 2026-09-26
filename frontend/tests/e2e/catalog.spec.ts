import { expect, test } from '@playwright/test'
import { datasetCatalog, mockCopilot, rankingAnswer, useLanguage } from './fixtures'

test('empty catalog explains publication and refresh recovers after data is published', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer, datasets: [] })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  const notice = page.locator('.catalog-notice')
  await expect(notice).toContainText('目前沒有可查詢的已發布資料')
  await expect(notice).toContainText('70%')
  await page.route('**/api/v1/datasets', route => route.fulfill({ json: datasetCatalog }))
  await page.getByRole('button', { name: '重新整理資料目錄' }).click()
  await expect(notice).toHaveCount(0)
})

test('catalog connection failure is distinct from empty data and can be retried', async ({ page }) => {
  await mockCopilot(page, { query: rankingAnswer })
  await useLanguage(page, 'zh-TW')
  await page.route('**/api/v1/datasets', route => route.abort('failed'))
  await page.goto('/')
  const notice = page.locator('.catalog-notice')
  await expect(notice).toHaveAttribute('role', 'alert')
  await expect(notice).toContainText('無法連線至後端')
  await expect(notice).not.toContainText('目前沒有可查詢')
  await page.route('**/api/v1/datasets', route => route.fulfill({ json: datasetCatalog }))
  await page.getByRole('button', { name: '重新整理資料目錄' }).click()
  await expect(notice).toHaveCount(0)
})

test('published statistical topics offer citywide questions without switching to population', async ({ page }) => {
  const requests: unknown[] = []
  await mockCopilot(page, { query: rankingAnswer, onQuery: value => requests.push(value), datasets: [
    ...datasetCatalog,
    { ...datasetCatalog[0], datasetId: 'population_age_share', topic: 'population_age_share' },
  ] })
  await useLanguage(page, 'zh-TW')
  await page.goto('/')
  await page.getByRole('radio', { name: '人口年齡結構', exact: true }).click()
  await expect(page.getByRole('button', { name: '比較各行政區的人口年齡結構' })).toHaveCount(0)
  await page.getByRole('button', { name: '概覽人口年齡結構', exact: true }).click()
  await expect.poll(() => requests.length).toBe(1)
  expect(requests[0]).toMatchObject({ topicHint: 'population_age_share' })
  await expect(page.getByRole('button', { name: '改為分析新主題' })).toHaveCount(0)
})
