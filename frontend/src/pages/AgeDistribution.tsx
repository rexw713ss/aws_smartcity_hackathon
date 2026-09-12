import React from 'react'
import Filters from '../components/Filters'

export default function AgeDistribution(){
  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">年齡分布</h2>
      <Filters />
      <div className="bg-white dark:bg-gray-800 p-4 rounded border border-gray-100 dark:border-gray-700 h-72">直方圖／人口金字塔預留區</div>
    </div>
  )
}
