import { expect, test, type Locator } from '@playwright/test'

async function placeAt(section: Locator, viewportFraction: number) {
  await section.evaluate((el, fraction) => {
    window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - innerHeight * fraction, behavior: 'auto' })
  }, viewportFraction)
}

test('sections scrub into focus in both scroll directions without transforming text', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  const section = page.locator('#population-trend')
  await expect(section).toHaveAttribute('data-scroll-state', 'scrubbing', { timeout: 15000 })
  await expect(page.locator('.section-transition')).toHaveCount(8)
  await placeAt(section, .98)
  await expect(section).toHaveCSS('opacity', '0.28')
  await placeAt(section, .80)
  await expect.poll(() => section.evaluate(el => Number(el.dataset.scrollProgress))).toBeGreaterThan(.30)
  await expect.poll(() => section.evaluate(el => Number(getComputedStyle(el).opacity))).toBeLessThan(.75)
  const middle = await section.evaluate(el => Number(getComputedStyle(el).opacity))
  expect(middle).toBeGreaterThan(.28)
  await expect(section).toHaveCSS('transform', 'none')
  await expect(section.locator('.card-title')).toHaveCSS('transform', 'none')

  await placeAt(section, .50)
  await expect(section).toHaveAttribute('data-scroll-state', 'settled')
  await expect(section).toHaveCSS('opacity', '1')
  await placeAt(section, .80)
  await expect(section).toHaveAttribute('data-scroll-state', 'scrubbing')
  await expect.poll(() => section.evaluate(el => Number(getComputedStyle(el).opacity))).toBeLessThan(.75)

  // Keyboard reading never fades content, even at the viewport edge.
  await page.keyboard.press('Tab')
  await expect(section).toHaveCSS('opacity', '1')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('.section-transition[data-scroll-state="reduced"]')).toHaveCount(8)
  await expect(section).toHaveCSS('opacity', '1')
  await expect(section.locator('.chart-motion')).toHaveAttribute('data-motion-state', 'reduced')
})

test('sticky selection stays accurate and returns to unobscured filters', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  const selection = page.getByLabel('目前的儀表板篩選條件')
  await expect(selection).toContainText('2026', { timeout: 15000 })
  await page.getByRole('combobox', { name: '行政區', exact: true }).click()
  await page.getByLabel('搜尋行政區').fill('板橋')
  await page.getByRole('option', { name: /^板橋區/ }).click()
  await page.getByRole('combobox', { name: '資料年份', exact: true }).click()
  await page.getByRole('option', { name: /^2025/ }).click()
  await expect(selection).toContainText('板橋區')
  await expect(selection).toContainText('2025')
  // A context update replaces the AI section; the new node gets a trigger.
  await expect(page.locator('#ai-assistant')).toHaveClass(/section-transition/)
  await expect(page.locator('.section-transition')).toHaveCount(8)
  await placeAt(page.locator('#education-levels'), .25)
  const bounds = await selection.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThan(130)
  await page.getByRole('button', { name: '調整儀表板篩選條件' }).click()
  const geography = page.getByRole('combobox', { name: '行政區', exact: true })
  await expect(geography).toBeFocused({ timeout: 4000 })
  const filterBounds = await geography.boundingBox()
  const toolbar = await page.locator('header').boundingBox()
  expect(filterBounds!.y).toBeGreaterThan(toolbar!.height)
  expect(filterBounds!.y + filterBounds!.height).toBeLessThan(page.viewportSize()!.height)
})

test('skip link and mobile navigation have a complete keyboard path', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.spatial-dashboard')).toBeVisible({ timeout: 15000 })
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: '跳至儀表板內容' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
  if (page.viewportSize()!.width >= 1024) return
  const navigation = page.locator('nav[aria-label="儀表板章節"]').nth(1)
  await expect(navigation).toHaveAttribute('inert', '')
  const open = page.getByRole('button', { name: '開啟導覽選單' })
  await open.click()
  await expect(navigation).not.toHaveAttribute('inert')
  await expect(navigation.getByRole('link', { name: /總覽/ })).toBeFocused()
  const last = navigation.getByRole('link', { name: /資料與方法/ })
  await last.focus()
  await page.keyboard.press('Tab')
  await expect(navigation.getByRole('button', { name: '關閉選單' })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(last).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(navigation).toHaveAttribute('inert', '')
  await expect(open).toBeFocused()
})

test('captions remain readable and mobile filters precede the illustration', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.spatial-dashboard')).toBeVisible({ timeout: 15000 })
  const labels = await page.locator('.metric-label, .filter-label, .mono-legend').evaluateAll(elements =>
    elements.map(el => parseFloat(getComputedStyle(el).fontSize)),
  )
  labels.forEach(size => expect(size).toBeGreaterThanOrEqual(12))
  if (page.viewportSize()!.width < 768) {
    const filters = await page.locator('#dashboard-filters').boundingBox()
    const city = await page.locator('.hero-city-panel').boundingBox()
    expect(filters!.y + filters!.height).toBeLessThan(city!.y)
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})
