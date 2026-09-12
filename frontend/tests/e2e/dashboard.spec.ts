import { expect, test } from '@playwright/test'

test('headline components remain legible in light theme', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('youth-compass-theme', 'light'))
  await page.goto('/')

  await expect(page.locator('html')).not.toHaveClass(/dark/)
  await expect(page.getByRole('heading', { name: /新北青年/ })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('button', { name: /證據說明/ })).toBeVisible()
  await page.waitForTimeout(950)
  await page.screenshot({ path: testInfo.outputPath('dashboard-light.png') })
})

test('filters update the dashboard without layout overflow', async ({ page }, testInfo) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /新北青年/ })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('region', { name: '儀表板篩選條件' })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('dashboard-top.png') })

  const geography = page.getByRole('combobox', { name: '行政區', exact: true })
  const referenceYear = page.getByRole('combobox', { name: '資料年份', exact: true })

  await expect(geography).toContainText('全市')
  await expect(referenceYear).toContainText('2026')

  await geography.click()
  await expect(page.getByRole('listbox', { name: '行政區選項' })).toBeVisible()
  await expect(page.getByRole('listbox', { name: '行政區選項' }).getByRole('option')).toHaveCount(30)
  const geographyMenuBox = await page.locator('.filter-menu-portal').boundingBox()
  const viewport = page.viewportSize()
  expect(geographyMenuBox?.x).toBeGreaterThanOrEqual(0)
  expect(geographyMenuBox?.y).toBeGreaterThanOrEqual(0)
  expect((geographyMenuBox?.x ?? 0) + (geographyMenuBox?.width ?? 0)).toBeLessThanOrEqual(viewport?.width ?? 1440)
  expect((geographyMenuBox?.y ?? 0) + (geographyMenuBox?.height ?? 0)).toBeLessThanOrEqual(viewport?.height ?? 1000)
  await page.screenshot({ path: testInfo.outputPath('geography-open.png') })
  await page.getByLabel('搜尋行政區').fill('板橋')
  await page.getByRole('option', { name: /^板橋區/ }).click()

  await referenceYear.click()
  await expect(page.getByRole('listbox', { name: '資料年份選項' })).toBeVisible()
  const yearMenuBox = await page.locator('.filter-menu-portal').boundingBox()
  expect((yearMenuBox?.y ?? 0) + (yearMenuBox?.height ?? 0)).toBeLessThanOrEqual(viewport?.height ?? 1000)
  await page.screenshot({ path: testInfo.outputPath('year-open.png') })
  await page.getByRole('option', { name: /^2025/ }).click()

  await expect(geography).toContainText('板橋區')
  await expect(referenceYear).toContainText('2025')
  await expect(page.locator('#age-structure')).toContainText('板橋區')
  await expect(page.getByRole('heading', { name: '教育程度' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '婚姻狀況' })).toBeVisible()

  const evidenceNotes = page.getByRole('button', { name: /證據說明/ })
  await expect(evidenceNotes).toHaveAttribute('aria-expanded', 'true')
  await evidenceNotes.click()
  await expect(evidenceNotes).toHaveAttribute('aria-expanded', 'false')
  await evidenceNotes.click()
  await expect(evidenceNotes).toHaveAttribute('aria-expanded', 'true')

  const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(hasHorizontalOverflow).toBe(false)

  const filterBox = await page.getByRole('region', { name: '儀表板篩選條件' }).boundingBox()
  expect(filterBox?.width).toBeLessThanOrEqual(testInfo.project.use.viewport?.width ?? 1440)

  await page.getByRole('region', { name: '儀表板篩選條件' }).screenshot({
    path: testInfo.outputPath('filters.png'),
  })
})

test('mobile navigation exposes every analysis view', async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 1440) > 500, 'Mobile-only navigation check')

  await page.goto('/')
  await page.getByRole('button', { name: '開啟導覽選單' }).click()

  await expect(page.getByRole('link', { name: /人口趨勢/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /行政區剖面/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /年齡結構/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /遷徙預測/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /教育程度/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /婚姻狀況/ })).toBeVisible()
})

test('migration forecast responds to the geography filter and exposes uncertainty', async ({ page }, testInfo) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /新北青年/ })).toBeVisible({ timeout: 15_000 })

  await page.getByRole('combobox', { name: '行政區', exact: true }).click()
  await page.getByLabel('搜尋行政區').fill('板橋')
  await page.getByRole('option', { name: /^板橋區/ }).click()

  const forecast = page.locator('#migration-forecast')
  await expect(forecast.getByRole('heading', { name: '遷出人口預測' })).toBeVisible()
  await expect(forecast).toContainText('板橋區')
  await expect(page.getByText('2026 年預估遷出')).toBeVisible()
  await expect(page.getByText(/80% 區間/).first()).toBeVisible()
  await expect(page.getByText(/目的行政區/).first()).toBeVisible()
  await forecast.scrollIntoViewIfNeeded()
  await page.waitForTimeout(950)
  await page.screenshot({ path: testInfo.outputPath('migration-forecast.png') })
})

test('top navigation indicates the section currently being viewed', async ({ page }, testInfo) => {
  test.skip((page.viewportSize()?.width ?? 0) < 1000, 'Desktop scroll-spy check')

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /新北青年/ })).toBeVisible({ timeout: 15_000 })

  const navigation = page.getByRole('navigation', { name: '儀表板章節' })
  const overviewLink = navigation.getByRole('link', { name: '總覽', exact: true })
  const populationLink = navigation.getByRole('link', { name: '人口趨勢', exact: true })
  const educationLink = navigation.getByRole('link', { name: '教育程度', exact: true })

  await expect(overviewLink).toHaveAttribute('aria-current', 'location')
  await populationLink.click()
  await expect(page).toHaveURL(/#population-trend$/)
  await expect(populationLink).toHaveAttribute('aria-current', 'location')
  await expect.poll(() => page.evaluate(() => {
    const section = document.getElementById('population-trend')
    const headerHeight = document.querySelector('header')?.getBoundingClientRect().height ?? 80
    return section ? Math.abs(section.getBoundingClientRect().top - headerHeight - 20) : Infinity
  })).toBeLessThan(8)

  await educationLink.click()
  await expect(educationLink).toHaveAttribute('aria-current', 'location')
  await navigation.screenshot({ path: testInfo.outputPath('navbar-active.png') })
})
