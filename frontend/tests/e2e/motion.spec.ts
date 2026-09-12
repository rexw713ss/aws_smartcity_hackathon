import { expect, test } from '@playwright/test'

test('sidebar journeys remain visible, can reverse, and give every topic its own destination', async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 0) < 1000, 'Desktop sidebar journey')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /新北青年/ })).toBeVisible({ timeout: 15000 })
  await expect(page.locator('html')).toHaveClass(/lenis/)

  const tops = await page.locator('main section[id]').evaluateAll(sections => sections.map(section => section.getBoundingClientRect().top))
  for (let index = 1; index < tops.length; index++) expect(tops[index] - tops[index - 1]).toBeGreaterThan(100)

  await page.getByRole('link', { name: /教育程度/ }).click()
  await page.waitForTimeout(450)
  const earlyPosition = await page.evaluate(() => scrollY)
  expect(earlyPosition).toBeGreaterThan(10)
  await page.waitForTimeout(350)
  const laterPosition = await page.evaluate(() => scrollY)
  expect(laterPosition).toBeGreaterThan(earlyPosition + 30)
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'true')
  const destinationDistance = await page.locator('#education-levels').evaluate(section => section.getBoundingClientRect().top)
  expect(destinationDistance).toBeGreaterThan(200)

  // Reverse the trip while still moving; never teleport to either endpoint.
  await page.getByRole('link', { name: /overview/i }).click()
  const reversedStart = await page.evaluate(() => scrollY)
  expect(reversedStart).toBeGreaterThan(10)
  await expect.poll(() => page.evaluate(() => scrollY), { timeout: 4500 }).toBeLessThan(16)
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false')

  await page.getByRole('link', { name: /婚姻狀況/ }).click()
  await page.waitForTimeout(400)
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false')
  const stopped = await page.evaluate(() => scrollY)
  await page.waitForTimeout(300)
  expect(Math.abs(await page.evaluate(() => scrollY) - stopped)).toBeLessThan(3)

  await page.getByRole('link', { name: /教育程度/ }).click()
  await page.waitForTimeout(450)
  await page.mouse.move(600, 400)
  // Record at input delivery, not before the browser round-trip while the
  // long-distance journey is still advancing by hundreds of pixels/second.
  await page.evaluate(() => window.addEventListener('wheel', () => {
    document.documentElement.dataset.interruptionScroll = String(scrollY)
  }, { capture: true, once: true }))
  await page.mouse.wheel(0, -260)
  const beforeWheel = Number(await page.locator('html').getAttribute('data-interruption-scroll'))
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false')
  await expect.poll(() => page.evaluate(() => scrollY)).toBeLessThan(beforeWheel - 80)
})

test('3D hero tilts and responds to scroll while reduced motion remains still', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  const city = page.getByTestId('city-depth')
  await expect(city).toBeVisible({ timeout: 15000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: testInfo.outputPath('spatial-hero.png') })
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)

  if ((page.viewportSize()?.width ?? 0) >= 1000) {
    const camera = page.getByTestId('city-camera')
    const bounds = await city.boundingBox()
    await page.mouse.move(bounds!.x + bounds!.width * 0.85, bounds!.y + bounds!.height * 0.2)
    await expect.poll(() => camera.evaluate(element => getComputedStyle(element).transform)).not.toBe('none')
    await page.mouse.move(400, 500)
    await page.mouse.wheel(0, 320)
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(100)
    await expect.poll(() => page.getByTestId('city-scroll-layer').evaluate(element => getComputedStyle(element).transform)).not.toBe('none')
  }

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
  await expect(page.getByTestId('city-camera')).toHaveCSS('transform', 'none')
  await expect(page.getByTestId('city-scroll-layer')).toHaveCSS('transform', 'none')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
})

test('system reduced motion is respected and switching the system preference restores default motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByTestId('city-depth')).toBeVisible({ timeout: 15000 })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
  await expect(page.getByTestId('city-scroll-layer')).toHaveCSS('transform', 'none')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'full')
  await expect(page.getByRole('button', { name: 'Smooth motion', exact: true })).toHaveCount(0)
  if ((page.viewportSize()?.width ?? 0) < 1000) await page.getByRole('button', { name: '開啟導覽選單' }).click()
  await page.getByRole('link', { name: /人口趨勢/ }).click()
  await page.waitForTimeout(300)
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'true')
  const top = await page.locator('#population-trend').evaluate(element => element.getBoundingClientRect().top)
  expect(top).toBeGreaterThan(200)
  await expect(page.getByTestId('section-scroll-progress')).toHaveAttribute('data-active', 'false', { timeout: 4500 })
})
