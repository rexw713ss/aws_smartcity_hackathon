import React from 'react'
import { useDashboardMotion } from './MotionProvider'

export default function MotionNotice() {
  const { reducedMotion, enableMotion } = useDashboardMotion()
  if (!reducedMotion) return null
  return <div className="motion-preference-notice" role="status">
    <p>您的裝置目前已關閉動畫。<span>您可只為這個儀表板開啟動畫，不會變更裝置設定。</span></p>
    <button type="button" onClick={enableMotion}>開啟儀表板動畫 <span aria-hidden="true">↗</span></button>
  </div>
}
