import React from 'react'
import Filters from '../components/Filters'

export default function Education(){
  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">教育程度分析</h2>
      <Filters />
      <div className="bg-white dark:bg-gray-800 p-4 rounded border border-gray-100 dark:border-gray-700 h-72">堆疊長條圖／趨勢預留區</div>
    </div>
  )
}
