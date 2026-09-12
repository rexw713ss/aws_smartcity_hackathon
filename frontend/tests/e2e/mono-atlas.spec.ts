import { expect, test } from '@playwright/test'
import Papa from 'papaparse'

test('district profile shows accurate selected CSV statistics, not a comparison chart', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByTestId('district-map')).toBeVisible({ timeout: 15000 })
  const csv = await (await page.request.get('/data/youth_population_summary.csv')).text()
  const rows = Papa.parse<Record<string, string>>(csv, { header: true, skipEmptyLines: true }).data
  const district = page.getByRole('button', { name: /^Select 烏來區,/ })
  await district.focus()
  await page.keyboard.press('Enter')
  const latest = rows.filter(row => row.district === '烏來區').sort((a, b) => Number(b.year) - Number(a.year))[0]
  await expect(page.getByTestId('district-youth-count')).toHaveText(Number(latest.youth_population).toLocaleString('en-US'))
  await expect(page.getByTestId('district-stats')).toContainText(Number(latest.total_population).toLocaleString('en-US'))
  await expect(page.locator('#district-profile .recharts-wrapper')).toHaveCount(0)
  await expect(page.locator('.map-directory')).toHaveCount(0)
  await expect(page.locator('.map-labels text:not(.map-neighbor-label)')).toHaveCount(0)
  if ((page.viewportSize()?.width ?? 0) >= 1000) {
    const map = await page.getByTestId('district-map').boundingBox()
    const stats = await page.getByTestId('district-stats').boundingBox()
    expect(stats!.x).toBeGreaterThan(map!.x + map!.width)
    expect(Math.abs(stats!.y - map!.y)).toBeLessThan(25)
  }
})

test('3D map camera zooms, pans without selecting, resets, and leaves wheel scrolling available', async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 0) < 1000, 'Mouse camera manipulation')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  await expect(page.getByTestId('district-map')).toBeVisible({ timeout: 15000 })
  await page.getByRole('link', { name: /district profile/i }).click()
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false', { timeout: 4500 })
  await page.getByRole('button', { name: '放大地圖', exact: true }).click()
  await expect(page.getByLabel('地圖縮放比例', { exact: true })).toHaveText('150%')
  await page.waitForTimeout(500)
  const stage = page.getByTestId('map-stage')
  const box = await stage.boundingBox()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await page.mouse.down()
  await page.mouse.move(box!.x + box!.width / 2 + 70, box!.y + box!.height / 2 + 30, { steps: 10 })
  await page.mouse.up()
  await expect(page.locator('.map-district[aria-pressed="true"]')).toHaveCount(0)
  const translation = await page.getByTestId('map-camera').evaluate(el => new DOMMatrix(getComputedStyle(el).transform).m41)
  expect(translation).toBeGreaterThan(60)
  await page.getByRole('button', { name: '重設地圖視角' }).click()
  await expect(page.getByLabel('地圖縮放比例', { exact: true })).toHaveText('100%')
  await expect.poll(() => page.getByTestId('map-camera').evaluate(el => new DOMMatrix(getComputedStyle(el).transform).m41)).toBeLessThan(1)
  await stage.focus()
  await page.keyboard.press('+')
  await expect(page.getByLabel('地圖縮放比例', { exact: true })).toHaveText('150%')
  await page.keyboard.press('Home')
  await expect(page.getByLabel('地圖縮放比例', { exact: true })).toHaveText('100%')
  const before = await page.evaluate(() => scrollY)
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await page.mouse.wheel(0, 380)
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(before + 100)
})

test('all charts use Mono styling and retain visible real-data marks in both themes', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByTestId('district-map')).toBeVisible({ timeout: 15000 })
  await expect(page.locator('[data-chart-design]')).toHaveCount(10)
  await expect(page.locator('[data-chart-design="amicro-mono-pill-bars"]')).toHaveCount(3)
  await expect(page.locator('#age-structure .recharts-bar-rectangle')).toHaveCount(5)
  await expect(page.locator('#education-levels .recharts-bar-rectangle')).toHaveCount(6)
  await expect(page.locator('#marriage-status .recharts-bar-rectangle')).toHaveCount(4)
  for (const theme of ['light', 'dark']) {
    await page.getByRole('button', { name: `Use ${theme} theme` }).click()
    const ink = await page.locator('html').evaluate(el => getComputedStyle(el).getPropertyValue('--mono-ink').trim())
    expect(ink).toBe(theme === 'light' ? '#18181b' : '#fafafa')
    await expect(page.locator('.mono-donut .recharts-pie-sector')).toHaveCount(2)
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  }
  expect(errors).toEqual([])
})
