import React from 'react'
import Filters from '../components/Filters'

export default function Marriage(){
  return (
    <div>
      <h2 className="text-2xl font-semibold mb-4">婚姻狀況與事件</h2>
      <Filters />
      <div className="bg-white dark:bg-gray-800 p-4 rounded border border-gray-100 dark:border-gray-700 h-72">事件率／教育程度分析預留區</div>
    </div>
  )
}
