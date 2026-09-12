import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

const out = 'artifacts/chart-assistant'
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge' })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: 'dark', reducedMotion: null })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('http://localhost:5173/?motion=full')
  await page.locator('.spatial-dashboard').waitFor()
  const plot = page.locator('#population-trend')
  await plot.evaluate(el => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 110))
  await page.waitForFunction(() => document.querySelector('#population-trend .chart-motion')?.dataset.motionState === 'drawing')
  const mask = plot.locator('.chart-reveal-mask rect')
  await mask.evaluate(el => { const animation = el.getAnimations()[0]; animation.pause(); animation.currentTime = 0 })
  await plot.screenshot({ path: out + '/plot-blank.png' })
  await mask.evaluate(el => { el.getAnimations()[0].currentTime = 1200 })
  await plot.screenshot({ path: out + '/plot-half.png' })
  await mask.evaluate(el => { el.getAnimations()[0].finish() })
  await plot.screenshot({ path: out + '/plot-complete.png' })
  await page.getByRole('button', { name: 'Ask about youth population trend', exact: true }).click()
  await page.waitForTimeout(2000)
  await page.getByRole('button', { name: 'Summarize this chart' }).click()
  await page.waitForTimeout(300)
  await page.locator('#ai-assistant').screenshot({ path: out + '/assistant-dark.png' })
  await page.getByRole('button', { name: 'Toggle color theme' }).count().then(async count => {
    if (count) await page.getByRole('button', { name: 'Toggle color theme' }).click()
    else await page.evaluate(() => document.documentElement.classList.remove('dark'))
  })
  await page.locator('#ai-assistant').screenshot({ path: out + '/assistant-light.png' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('#ai-assistant').screenshot({ path: out + '/assistant-mobile.png' })
  await page.locator('#ai-assistant').evaluate(el => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 90))
  await page.waitForTimeout(300)
  await page.screenshot({ path: out + '/assistant-mobile-viewport.png' })
  await page.locator('.ai-composer').evaluate(el => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - 110))
  await page.waitForTimeout(300)
  await page.screenshot({ path: out + '/assistant-mobile-composer.png' })
  console.log(JSON.stringify({ pageErrors: errors, horizontalOverflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), url: page.url(), artifacts: out }))
} finally { await browser.close() }
