import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'

const url = process.argv[2] || 'https://d2pz0g4ehmpkee.cloudfront.net'
const output = resolve(process.argv[3] || '../artifacts/reports/frontend-performance.json')
const iterations = Number(process.argv[4] || 10)
const browser = await chromium.launch({ headless: true })
const samples = []

try {
  for (let index = 0; index < iterations; index += 1) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const page = await context.newPage()
    await page.addInitScript(() => {
      window.__lcp = 0
      new PerformanceObserver(list => {
        const entries = list.getEntries()
        window.__lcp = entries.at(-1)?.startTime || window.__lcp
      }).observe({ type: 'largest-contentful-paint', buffered: true })
    })
    const started = performance.now()
    const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 60_000 })
    const wallMs = performance.now() - started
    const metrics = await page.evaluate(() => {
      const navigation = performance.getEntriesByType('navigation')[0]
      const paint = Object.fromEntries(
        performance.getEntriesByType('paint').map(entry => [entry.name, entry.startTime]),
      )
      return {
        dnsMs: navigation.domainLookupEnd - navigation.domainLookupStart,
        connectMs: navigation.connectEnd - navigation.connectStart,
        ttfbMs: navigation.responseStart - navigation.requestStart,
        domContentLoadedMs: navigation.domContentLoadedEventEnd,
        loadMs: navigation.loadEventEnd,
        fcpMs: paint['first-contentful-paint'] ?? null,
        lcpMs: window.__lcp || null,
        transferBytes: navigation.transferSize,
        encodedBytes: navigation.encodedBodySize,
      }
    })
    samples.push({ iteration: index + 1, httpStatus: response?.status() ?? null, wallMs, ...metrics })
    await context.close()
  }
} finally {
  await browser.close()
}

function percentile(values, p) {
  const ordered = [...values].sort((a, b) => a - b)
  const position = (ordered.length - 1) * p / 100
  const lower = Math.floor(position)
  const upper = Math.ceil(position)
  if (lower === upper) return ordered[lower]
  return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
}

function summary(field) {
  const values = samples.map(sample => sample[field]).filter(value => typeof value === 'number')
  return {
    mean: values.reduce((sum, value) => sum + value, 0) / values.length,
    p50: percentile(values, 50),
    p95: percentile(values, 95),
    max: Math.max(...values),
  }
}

const report = {
  generatedAt: new Date().toISOString(),
  url,
  iterations,
  success: samples.filter(sample => sample.httpStatus === 200).length,
  wallMs: summary('wallMs'),
  ttfbMs: summary('ttfbMs'),
  fcpMs: summary('fcpMs'),
  lcpMs: summary('lcpMs'),
  loadMs: summary('loadMs'),
  samples,
}
await mkdir(dirname(output), { recursive: true })
await writeFile(output, JSON.stringify(report, null, 2))
console.log(JSON.stringify(report, null, 2))
