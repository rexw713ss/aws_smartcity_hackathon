import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

const phase = process.argv[2] || 'before'
if (!['before', 'after', 'confirm'].includes(phase)) throw new Error('Expected before, after, or confirm')
const out = 'artifacts/impeccable-' + phase
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge' })
try {
  for (const [name, width, height, theme] of [
    ['desktop-dark', 1440, 1000, 'dark'], ['desktop-light', 1440, 1000, 'light'],
    ['tablet', 768, 1024, 'light'], ['mobile', 390, 844, 'dark'], ['narrow', 320, 700, 'light'],
  ]) {
    const page = await browser.newPage({ viewport: { width, height }, colorScheme: theme, reducedMotion: 'reduce' })
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto('http://localhost:5173/')
    await page.locator('.spatial-dashboard').waitFor()
    await page.evaluate(() => document.fonts.ready)
    await page.screenshot({ path: out + '/' + name + '-overview.png' })
    const sizes = await page.evaluate(() => ({
      pageWidth: innerWidth, documentWidth: document.documentElement.scrollWidth,
      populationTop: document.querySelector('#population-trend').getBoundingClientRect().top + scrollY,
      heroTitleSize: getComputedStyle(document.querySelector('.hero-title')).fontSize,
      metricLabelSize: getComputedStyle(document.querySelector('.metric-label')).fontSize,
      smallText: [...document.querySelectorAll('main p, main dt, main button')].filter(el => el.getClientRects().length && parseFloat(getComputedStyle(el).fontSize) < 12).length,
    }))
    for (const target of ['.indicator-grid', '#population-trend', '#district-profile', '#education-levels', '#ai-assistant']) {
      const section = page.locator(target)
      await section.evaluate(el => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - (document.querySelector('header').getBoundingClientRect().height + 20)))
      await page.screenshot({ path: out + '/' + name + '-' + target.replace(/[#.]/g, '') + '.png' })
    }
    for (const label of ['Geography', 'Reference year']) {
      await page.getByLabel(label, { exact: true }).click()
      const menu = await page.locator('.filter-menu-portal').boundingBox()
      console.log(JSON.stringify({ name, label, menu, fits: menu.x >= 0 && menu.y >= 0 && menu.x + menu.width <= width && menu.y + menu.height <= height }))
      await page.keyboard.press('Escape')
    }
    console.log(JSON.stringify({ name, ...sizes, errors }))
    await page.close()
  }
  if (phase === 'confirm') {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: 'dark', reducedMotion: 'no-preference' })
    await page.goto('http://localhost:5173/')
    const section = page.locator('#population-trend')
    await section.waitFor()
    for (const [position, fraction] of [['entering', .80], ['reading', .50]]) {
      await section.evaluate((el, value) => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - innerHeight * value), fraction)
      await page.waitForTimeout(450)
      await page.screenshot({ path: out + '/scroll-transition-' + position + '.png' })
      console.log(JSON.stringify({ position, ...await section.evaluate(el => ({ opacity: getComputedStyle(el).opacity, progress: el.dataset.scrollProgress, state: el.dataset.scrollState })) }))
    }
    await page.close()
  }
} finally { await browser.close() }
