import { expect, test } from '@playwright/test'
import Papa from 'papaparse'
import { readFileSync } from 'node:fs'

const atlas: { districts: { name: string; label: { x: number; y: number } }[] } = JSON.parse(
  readFileSync(new URL('../../src/data/district-map.json', import.meta.url), 'utf8'),
)

test('wheel input over a non-scrolling sidebar coasts the page and can interrupt a journey', async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 0) < 1000, 'Desktop sidebar input')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  await expect(page.locator('.spatial-dashboard')).toBeVisible({ timeout: 15000 })
  await page.mouse.move(120, 740)
  await page.mouse.wheel(0, 650)
  await page.waitForTimeout(170)
  const early = await page.evaluate(() => scrollY)
  expect(early).toBeGreaterThan(10)
  expect(early).toBeLessThan(600)
  await page.waitForTimeout(350)
  expect(await page.evaluate(() => scrollY)).toBeGreaterThan(early + 20)
  await page.getByRole('link', { name: /教育程度/ }).click()
  await page.waitForTimeout(450)
  await page.mouse.wheel(0, -250)
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false')
})

test('every district has map geometry, CSV coverage, and a keyboard-selectable shape without a directory', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('district-map')).toBeVisible({ timeout: 15000 })
  const names = atlas.districts.map(area => area.name).sort()
  const csv = await (await page.request.get('/data/youth_population_summary.csv')).text()
  const rows = Papa.parse<{ year: string; district: string; district_code: string }>(csv, { header: true, skipEmptyLines: true }).data
  for (const year of new Set(rows.map(row => row.year))) {
    expect(rows.filter(row => row.year === year && Number(row.district_code) !== 0).map(row => row.district).sort()).toEqual(names)
  }
  const interiorLabels = await page.evaluate(areas => areas.every(area => {
    const group = [...document.querySelectorAll<SVGGElement>('.map-district')].find(el => el.dataset.district === area.name)
    const path = group!.querySelector('path')!
    return path.isPointInFill(new DOMPoint(area.label.x, area.label.y))
  }), atlas.districts)
  expect(interiorLabels).toBe(true)
  await expect(page.locator('.map-directory')).toHaveCount(0)
  await expect(page.locator('.map-labels text:not(.map-neighbor-label)')).toHaveCount(0)
  const yonghe = page.getByRole('button', { name: /^Select 永和區,/ })
  await yonghe.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('combobox', { name: '行政區', exact: true })).toContainText('永和區')
  await expect(page.getByTestId('district-stats')).toContainText('永和區')
  await expect(page.locator('#district-profile .recharts-wrapper')).toHaveCount(0)
  await expect(page.locator('.map-neighbor-label')).toHaveCount(2)
})

test('all 29 map shapes stay under the pointer in the default 3D view', async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 0) < 1000, 'Desktop pointer precision; touch has zoom controls and the geography filter')
  test.setTimeout(60000)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  await expect(page.getByTestId('district-map')).toBeVisible({ timeout: 15000 })
  await page.getByRole('link', { name: /district profile/i }).click()
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false', { timeout: 4500 })
  for (const mode of ['3D default']) {
    await expect(page.locator('.district-map-svg')).toHaveClass(/is-raised/)
    await page.mouse.move(300, 90)
    await page.waitForTimeout(650)
    const hits = await page.evaluate(() => {
      const points = new Map<string, { x: number; y: number }[]>()
      const bounds = document.querySelector('.district-map-svg')!.getBoundingClientRect()
      for (let y = Math.max(90, bounds.top); y < Math.min(innerHeight, bounds.bottom); y += 3) {
        for (let x = bounds.left; x < bounds.right; x += 3) {
          const group = document.elementFromPoint(x, y)?.closest<SVGGElement>('.map-district')
          if (!group?.dataset.district) continue
          const list = points.get(group.dataset.district) || []
          list.push({ x, y }); points.set(group.dataset.district, list)
        }
      }
      return [...points].map(([name, points]) => ({ name, point: points[Math.floor(points.length / 2)] }))
    })
    expect(hits).toHaveLength(29)
    for (const { name, point } of hits) {
      await page.mouse.move(point.x, point.y)
      await page.waitForTimeout(150)
      await page.mouse.click(point.x, point.y)
      await expect(page.getByRole('combobox', { name: '行政區', exact: true })).toContainText(name)
    }
  }
})

test('default motion ignores the removed toggle preference and persists on reload', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.addInitScript(() => localStorage.setItem('youth-compass-motion', 'reduced'))
  await page.goto('/')
  await expect(page.locator('.spatial-dashboard')).toBeVisible({ timeout: 15000 })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'full')
  await expect(page.getByRole('button', { name: 'Smooth motion', exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.locator('.spatial-dashboard')).toBeVisible({ timeout: 15000 })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'full')
  if ((page.viewportSize()?.width ?? 0) < 1000) await page.getByRole('button', { name: '開啟導覽選單' }).click()
  await page.getByRole('link', { name: /人口趨勢/ }).click()
  await page.waitForTimeout(350)
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'true')
})

test('zero-detail sidebar clicks glide, while real keyboard activation respects the keyboard path', async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 0) < 1000, 'Desktop sidebar activation paths')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  await expect(page.locator('.spatial-dashboard')).toBeVisible({ timeout: 15000 })
  await page.getByRole('link', { name: /人口趨勢/ }).evaluate(link => (link as HTMLAnchorElement).click())
  await page.waitForTimeout(350)
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'true')
  const overview = page.getByRole('link', { name: /overview/i })
  await overview.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false')
  await expect.poll(() => page.evaluate(() => scrollY)).toBeLessThan(2)
})
