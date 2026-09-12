import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

await mkdir('designs/bug-review', { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
for (const preference of ['system', 'full', 'reduced']) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  await page.addInitScript(value => localStorage.setItem('youth-compass-motion', value), preference)
  await page.goto('http://localhost:5173')
  await page.locator('.spatial-dashboard').waitFor()
  await page.waitForTimeout(500)
  await page.getByRole('link', { name: /population trend/i }).click()
  await page.waitForTimeout(220)
  const early = await page.evaluate(() => scrollY)
  await page.waitForTimeout(450)
  console.log('Saved motion', { preference, early, later: await page.evaluate(() => scrollY), mode: await page.locator('html').getAttribute('data-motion') })
  await page.close()
}
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
await page.goto('http://localhost:5173')
await page.locator('.spatial-dashboard').waitFor()
await page.getByRole('link', { name: /district profile/i }).click()
await page.waitForTimeout(2800)
await page.screenshot({ path: 'designs/bug-review/map-before.png' })
const hitPoints = await page.evaluate(() => {
  const points = new Map()
  const bounds = document.querySelector('.district-map-svg').getBoundingClientRect()
  for (let y = Math.max(90, bounds.top); y < Math.min(innerHeight, bounds.bottom); y += 3) {
    for (let x = bounds.left; x < bounds.right; x += 3) {
      const group = document.elementFromPoint(x, y)?.closest('.map-district')
      if (!group) continue
      const name = group.getAttribute('aria-label').split(',')[0].replace('Select ', '')
      const list = points.get(name) || []
      list.push({ x, y })
      points.set(name, list)
    }
  }
  return [...points].map(([name, points]) => ({ name, point: points[Math.floor(points.length / 2)], pixels: points.length * 9 }))
})
console.log('Map clickable district coverage', hitPoints.length, hitPoints.map(item => ({ name: item.name, pixels: item.pixels })))
// Exercise actual pointer movement/clicks, unlike the previous keyboard-only map test.
for (const item of hitPoints) {
  await page.mouse.move(item.point.x, item.point.y)
  await page.waitForTimeout(350)
  const hitBefore = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest('.map-district')?.getAttribute('aria-label'), item.point)
  await page.mouse.click(item.point.x, item.point.y)
  const selected = await page.getByLabel('Geography', { exact: true }).innerText()
  console.log('Map pointer', { expected: item.name, hitBefore, matches: selected.includes(item.name) })
}
await page.mouse.move(130, 750)
await page.mouse.wheel(0, 600)
await page.waitForTimeout(160)
const overSidebarEarly = await page.evaluate(() => scrollY)
await page.waitForTimeout(350)
console.log('Wheel over sidebar', { early: overSidebarEarly, later: await page.evaluate(() => scrollY) })
await browser.close()
