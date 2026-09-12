import React from 'react'
import Filters from '../components/Filters'

export default function DistrictComparison(){
  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">行政區比較</h2>
      <Filters />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-gray-800 p-4 rounded border border-gray-100 dark:border-gray-700 h-64">地圖／小多圖預留區</div>
        <div className="bg-white dark:bg-gray-800 p-4 rounded border border-gray-100 dark:border-gray-700 h-64">關鍵指標／成對比較預留區</div>
      </div>
    </div>
  )
}
