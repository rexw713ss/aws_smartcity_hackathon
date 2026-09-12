import React, { useEffect, useState } from 'react'
import Filters from '../components/Filters'
import TimeSeriesChart from '../components/TimeSeriesChart'
import Papa from 'papaparse'

type Row = Record<string, string>

function findYearField(headers: string[]) {
  const candidates = ['year_gregorian','year','民國年','年度','年']
  for (const c of candidates) {
    const found = headers.find(h => h.toLowerCase().includes(c.toLowerCase()))
    if (found) return found
  }
  return headers[0]
}

function findValueField(headers: string[]) {
  const candidates = ['人數','youth_population','population','value','人']
  for (const c of candidates) {
    const found = headers.find(h => h.toLowerCase().includes(c.toLowerCase()))
    if (found) return found
  }
  // fallback to second column if available
  return headers.length > 1 ? headers[1] : headers[0]
}

export default function Population() {
  const [data, setData] = useState<{year:number,value:number}[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const resp = await fetch('/data/population_all_districts.csv')
        if (!resp.ok) throw new Error(`找不到 CSV：${resp.status}`)
        const text = await resp.text()
        const parsed = Papa.parse<Row>(text, { header: true, skipEmptyLines: true })
        if (parsed.errors.length) console.warn('CSV parse warnings', parsed.errors)
        const rows = parsed.data
        if (rows.length === 0) {
          setError('CSV 已解析，但沒有資料列')
          setLoading(false)
          return
        }
        const headers = Object.keys(rows[0])
        const yearField = findYearField(headers)
        const valueField = findValueField(headers)

        const mapped = rows.map(r => {
          let y = NaN
          const rawYear = (r as Row)[yearField]?.trim()
          if (!rawYear) y = NaN
          else if (/^\d+$/.test(rawYear)) {
            // numeric string — could be ROC year or Gregorian
            const n = parseInt(rawYear,10)
            y = n > 1900 ? n : n + 1911
          } else {
            // try to extract digits
            const m = rawYear.match(/(\d{3,4})/)
            if (m) {
              const n = parseInt(m[1],10)
              y = n > 1900 ? n : n + 1911
            }
          }
          let v = parseFloat(((r as Row)[valueField] || '').replace(/,/g,''))
          if (isNaN(v)) {
            // try to find any numeric column
            for (const h of headers) {
              const t = parseFloat(((r as Row)[h]||'').replace(/,/g,''))
              if (!isNaN(t)) { v = t; break }
            }
          }
          return { year: isNaN(y) ? 0 : y, value: isNaN(v) ? 0 : v }
        }).filter(d => d.year > 0)

        // aggregate by year
        const byYear = new Map<number, number>()
        for (const r of mapped) {
          byYear.set(r.year, (byYear.get(r.year) || 0) + r.value)
        }
        const out = Array.from(byYear.entries()).sort((a,b)=>a[0]-b[0]).map(([year,value])=>({year,value}))
        setData(out)
      } catch (err: any) {
        console.error(err)
        setError(String(err.message || err))
      } finally { setLoading(false) }
    }
    load()
  }, [])

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">人口趨勢</h2>
      <Filters />
      {loading && <div className="p-4">正在載入 CSV…</div>}
      {error && <div className="p-4 text-red-400">{error}</div>}
      {!loading && !error && data.length > 0 && <TimeSeriesChart data={data} />}
      {!loading && !error && data.length === 0 && <div className="mt-4 bg-white dark:bg-gray-800 p-3 rounded border border-gray-100 dark:border-gray-700">目前沒有資料；請執行 scripts\sync_frontend_data.ps1，將 CSV 複製到 frontend/public/data。</div>}
    </div>
  )
}
