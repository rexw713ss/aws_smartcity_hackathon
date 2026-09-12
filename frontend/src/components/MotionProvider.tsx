import React, { createContext, useContext, useEffect, useState } from 'react'

type MotionPreference = 'system' | 'full'
const consentKey = 'youth-compass-animation-consent'
const MotionContext = createContext({ reducedMotion: false, enableMotion: () => {} })
export const useDashboardMotion = () => useContext(MotionContext)

/** Chart-draw motion consent only. A chat layout scrolls its own panes, so no
 * document-scroll hijacking library is involved. ChartMotion reads this context. */
export default function MotionProvider({ children }: { children: React.ReactNode }) {
  const [systemReduced, setSystemReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [preference, setPreference] = useState<MotionPreference>(() => {
    const requested = new URLSearchParams(window.location.search).get('motion')
    if (requested === 'full') return 'full'
    if (requested === 'system') return 'system'
    try { return localStorage.getItem(consentKey) === 'full' ? 'full' : 'system' } catch { return 'system' }
  })
  const reducedMotion = preference !== 'full' && systemReduced

  useEffect(() => {
    try {
      if (preference === 'full') localStorage.setItem(consentKey, 'full')
      else localStorage.removeItem(consentKey)
    } catch { /* Private storage can be unavailable; the session still works. */ }
  }, [preference])

  useEffect(() => {
    const query = matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setSystemReduced(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full'
    return () => { delete document.documentElement.dataset.motion }
  }, [reducedMotion])

  return (
    <MotionContext.Provider value={{ reducedMotion, enableMotion: () => setPreference('full') }}>
      {children}
    </MotionContext.Provider>
  )
}
