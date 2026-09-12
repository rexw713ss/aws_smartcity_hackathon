import { chromium } from '@playwright/test'

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.goto('http://127.0.0.1:5173')
await page.getByRole('heading', { name: /clearer view of new taipei/i }).waitFor()
await page.waitForTimeout(1100)
console.log('Environment', await page.evaluate(() => ({
  reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
  htmlClass: document.documentElement.className,
  scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
  sections: [...document.querySelectorAll('main section[id]')].map(section => ({
    id: section.id,
    top: Math.round(section.getBoundingClientRect().top + scrollY),
  })),
})))
await page.evaluate(() => {
  window.motionSamples = []
  const start = performance.now()
  function sample(now) {
    window.motionSamples.push({ ms: Math.round(now - start), y: scrollY })
    if (now - start < 2500) requestAnimationFrame(sample)
  }
  requestAnimationFrame(sample)
})
await page.getByRole('link', { name: /population trend/i }).click()
await page.waitForTimeout(2700)
console.log('Scroll samples', await page.evaluate(() => window.motionSamples.filter((_, i) => i % 12 === 0)))
console.log('Runtime errors', errors)
await browser.close()
