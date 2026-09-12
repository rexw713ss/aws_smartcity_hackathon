import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

await mkdir('designs/running-motion', { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  // Playwright otherwise defaults to forced no-preference, unlike real Chrome.
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: null })
  page.on('pageerror', error => console.log('PAGE ERROR', error.message))
  await page.goto('http://localhost:5173')
  await page.locator('.spatial-dashboard').waitFor()
  console.log('Unmodified browser preference', await page.evaluate(() => ({ reduced: matchMedia('(prefers-reduced-motion: reduce)').matches, mode: document.documentElement.dataset.motion })))
  await page.goto('http://localhost:5173/?motion=full')
  await page.locator('.spatial-dashboard').waitFor()
  console.log('Explicit dashboard opt-in', await page.evaluate(() => ({ reduced: matchMedia('(prefers-reduced-motion: reduce)').matches, mode: document.documentElement.dataset.motion, source: document.documentElement.dataset.motionSource })))
  await page.mouse.move(100, 740)
  await page.waitForTimeout(1000)
  console.log('Idle motion', await page.locator('.hero-editorial .float-bob').first().evaluate(el => ({ name: getComputedStyle(el).animationName, transform: getComputedStyle(el).transform })))
  for (const [section, link] of [['population-trend', /population trend/i], ['age-structure', /age structure/i], ['education-levels', /education levels/i], ['marriage-status', /marriage status/i]]) {
    await page.getByRole('link', { name: link }).click()
    await page.waitForTimeout(2700)
    const motion = page.locator(`#${section} .chart-motion`)
    const states = []
    for (let frame = 0; frame < 3; frame++) {
      states.push(await motion.evaluate(el => ({ state: el.dataset.motionState, reveal: el.dataset.revealCount, animations: el.getAnimations({ subtree: true }).map(a => ({ time: a.currentTime, state: a.playState })), transform: getComputedStyle(el.querySelector('.chart-running-stripe')).transform })))
      await page.screenshot({ path: `designs/running-motion/${section}-${frame}.png` })
      await page.waitForTimeout(600)
    }
    console.log(section, states)
  }
  console.log('Overflow', await page.evaluate(() => document.documentElement.scrollWidth > innerWidth))
  await page.close()
} finally { await browser.close() }
