import React from 'react'

type Profile = {
  district: string; year: number; month: number; total_population: number; youth_population: number
  male_youth: number; female_youth: number
}
const integer = new Intl.NumberFormat('zh-TW')
const percent = new Intl.NumberFormat('zh-TW', { style: 'percent', maximumFractionDigits: 1 })

export default function DistrictStats({ current, previous, largestCohort, onClear }: {
  current: Profile; previous?: Profile; largestCohort: { label: string; value: number }; onClear: () => void
}) {
  const citywide = current.district === 'New Taipei City'
  const change = previous ? current.youth_population - previous.youth_population : null
  const release = (row: Profile) => new Intl.DateTimeFormat('zh-TW', { year: 'numeric', month: 'short' }).format(new Date(row.year, row.month - 1))

  return <div className="district-profile-stats" role="region" aria-label="行政區統計" aria-live="polite" aria-atomic="true" data-testid="district-stats">
    <div className="district-profile-eyebrow"><span>{citywide ? '全市資料快照' : '已選行政區'}</span><span>{release(current)}</span></div>
    <h4>{citywide ? '新北市' : current.district}</h4>
    <p className="district-profile-subtitle">{citywide ? '在地圖上選擇行政區，查看詳細資料。' : `${current.district}・新北市`}</p>
    <div className="district-profile-population"><span>青年人口</span><strong data-testid="district-youth-count">{integer.format(current.youth_population)}</strong><p>15–39 歲・戶籍人口</p></div>
    <dl className="district-facts">
      <div><dt>總人口</dt><dd>{integer.format(current.total_population)}</dd></div>
      <div><dt>青年占比</dt><dd>{percent.format(current.youth_population / current.total_population)}</dd></div>
      <div><dt>男性青年</dt><dd>{integer.format(current.male_youth)}</dd></div>
      <div><dt>女性青年</dt><dd>{integer.format(current.female_youth)}</dd></div>
      <div><dt>最大年齡層</dt><dd>{largestCohort.label}<small>{integer.format(largestCohort.value)} 人</small></dd></div>
      <div><dt>青年人口變化</dt><dd>{change === null ? '—' : `${change >= 0 ? '+' : ''}${integer.format(change)}`}<small>{previous ? `相較 ${release(previous)}` : '無較早期資料'}</small></dd></div>
    </dl>
    <div className="district-profile-footer"><p>地圖選擇會同步更新所有指標；各資料發布月份可能不同。</p>{!citywide && <button type="button" onClick={onClear}>清除行政區選擇 <span aria-hidden="true">↗</span></button>}</div>
  </div>
}
