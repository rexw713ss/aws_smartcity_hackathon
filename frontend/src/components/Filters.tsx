import React from 'react'
import Icon from './Icon'
import FilterSelect, { FilterOption } from './FilterSelect'
import { FloatingElement } from './FloatingScene'

type FilterProps = {
  district?: string
  districts?: string[]
  month?: number
  onDistrictChange?: (district: string) => void
  onYearChange?: (year: number) => void
  year?: number
  yearMonths?: Record<number, number>
  years?: number[]
}

export default function Filters({
  district = 'New Taipei City',
  districts = [],
  month = 12,
  onDistrictChange = () => undefined,
  onYearChange = () => undefined,
  year = 2026,
  yearMonths = {},
  years = [],
}: FilterProps) {
  const districtOptions: FilterOption[] = [
    { value: 'New Taipei City', label: '全市', meta: '新北市・全市彙整' },
    ...districts.map((name, index) => ({ value: name, label: name, meta: `行政區・${String(index + 1).padStart(2, '0')}` })),
  ]
  const yearOptions: FilterOption[] = years.map(item => ({
    value: String(item),
    label: `${item} 年`,
    meta: `民國 ${item - 1911} 年・第 ${yearMonths[item] ?? 12} 月資料快照`,
  }))

  return (
    <section id="dashboard-filters" aria-label="儀表板篩選條件" className="filter-surface">
      <div className="filter-rail-heading">
        <div><p>選擇行政區與資料年份</p></div>
        <span className="filter-rail-summary">{district === 'New Taipei City' ? '29 個行政區' : district}／{year} 年</span>
      </div>
      <div className="filter-islands grid gap-5 sm:grid-cols-2 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,.8fr)]">
        <FloatingElement phase={1} strength={0.6} reading>
          <FilterSelect icon="districts" label="行政區" onChange={onDistrictChange} options={districtOptions} searchable value={district} />
        </FloatingElement>
        <FloatingElement phase={3} strength={0.6} reading>
          <FilterSelect icon="calendar" label="資料年份" onChange={value => onYearChange(Number(value))} options={yearOptions} value={String(year)} />
        </FloatingElement>
        <FloatingElement phase={2} strength={0.4} className="filter-status-island sm:col-span-2 xl:col-span-1">
          <div className="filter-status flex min-h-[76px] items-center gap-3 px-4 text-[13px] text-slate-600 dark:text-slate-300">
            <span className="filter-status-icon"><Icon name="check" className="h-4 w-4" /></span>
            <span><strong className="font-semibold text-slate-800 dark:text-slate-100">已發布資料</strong><br /><span className="font-mono text-[12px]">第 {month} 月快照</span></span>
          </div>
        </FloatingElement>
      </div>
    </section>
  )
}
