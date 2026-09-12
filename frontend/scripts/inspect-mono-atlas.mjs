import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

await mkdir('designs/mono-atlas', { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['mobile', { width: 390, height: 844 }]]) {
    const page = await browser.newPage({ viewport, colorScheme: 'light', reducedMotion: 'reduce' })
    page.on('pageerror', error => console.log('PAGE ERROR', error.message))
    await page.goto('http://127.0.0.1:5173/')
    await page.getByTestId('district-map').waitFor()
    if (name === 'mobile') {
      await page.getByRole('button', { name: '開啟導覽選單' }).click()
      const navigation = page.getByRole('navigation', { name: '儀表板章節' })
      await navigation.screenshot({ path: 'designs/mono-atlas/mobile-light-navbar.png' })
      console.log('mobile navigation', { links: await navigation.getByRole('link').count() })
      await page.getByRole('button', { name: '關閉選單' }).click()
    }
    const shape = page.getByRole('button', { name: /^選擇板橋區，/ })
    await shape.focus()
    await page.keyboard.press('Enter')
    for (const theme of ['light', 'dark']) {
      if (theme === 'dark') await page.getByRole('button', { name: '切換為深色模式' }).click()
      for (const section of ['district-profile', 'population-trend', 'age-structure', 'education-levels', 'marriage-status']) {
        await page.locator(`#${section}`).evaluate(el => window.scrollTo(0, el.getBoundingClientRect().top + scrollY - (document.querySelector('header')?.getBoundingClientRect().height ?? 105) - 20))
        await page.waitForTimeout(150)
        await page.screenshot({ path: `designs/mono-atlas/${name}-${theme}-${section}.png` })
      }
    }
    console.log(name, { districts: await page.locator('.map-district').count(), charts: await page.locator('[data-chart-design]').count(), overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth) })
    await page.close()
  }
} finally { await browser.close() }
