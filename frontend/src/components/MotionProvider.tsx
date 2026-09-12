import React, { createContext, useContext, useEffect, useState } from 'react'
import { ReactLenis, useLenis } from 'lenis/react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import 'lenis/dist/lenis.css'

gsap.registerPlugin(ScrollTrigger)

type MotionPreference = 'system' | 'full'
const consentKey = 'youth-compass-animation-consent'
const MotionContext = createContext({ reducedMotion: false, enableMotion: () => {} })
export const useDashboardMotion = () => useContext(MotionContext)

function ScrollClock() {
  const lenis = useLenis()

  useEffect(() => {
    if (!lenis) return
    // One clock keeps the Lenis journey and GSAP's depth layers in step.
    const tick = (seconds: number) => lenis.raf(seconds * 1000)
    lenis.on('scroll', ScrollTrigger.update)
    gsap.ticker.add(tick)
    return () => {
      gsap.ticker.remove(tick)
      lenis.off('scroll', ScrollTrigger.update)
    }
  }, [lenis])

  return null
}

export default function MotionProvider({ children }: { children: React.ReactNode }) {
  const [systemReduced, setSystemReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [preference, setPreference] = useState<MotionPreference>(() => {
    const requested = new URLSearchParams(window.location.search).get('motion')
    if (requested === 'full') return 'full'
    if (requested === 'system') return 'system'
    // This key records explicit app-only consent, not the obsolete mode switch.
    try { return localStorage.getItem(consentKey) === 'full' ? 'full' : 'system' } catch { return 'system' }
  })
  const reducedMotion = preference !== 'full' && systemReduced

  useEffect(() => {
    try {
      if (preference === 'full') localStorage.setItem(consentKey, 'full')
      else localStorage.removeItem(consentKey)
      const address = new URL(window.location.href)
      if (['full', 'system'].includes(address.searchParams.get('motion') || '')) {
        address.searchParams.delete('motion')
        window.history.replaceState(window.history.state, '', `${address.pathname}${address.search}${address.hash}`)
      }
    } catch { /* Private storage can be unavailable; the current session still works. */ }
  }, [preference])

  useEffect(() => {
    const query = matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setSystemReduced(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full'
    document.documentElement.dataset.motionSource = preference === 'full' ? 'dashboard-consent' : 'system'
    return () => { delete document.documentElement.dataset.motion; delete document.documentElement.dataset.motionSource }
  }, [reducedMotion, preference])

  return (
    <MotionContext.Provider value={{ reducedMotion, enableMotion: () => setPreference('full') }}>
      <ReactLenis root options={{
        autoRaf: false,
        lerp: reducedMotion ? 1 : 0.038,
        smoothWheel: !reducedMotion,
        // Only native-scroll a nested region when it really has scrollable content.
        // A blanket exclusion on the fixed sidebar used to swallow wheel input.
        allowNestedScroll: true,
        syncTouch: false,
        wheelMultiplier: 1,
        // An explicit dashboard opt-in must apply to Lenis as well as CSS/GSAP.
        respectReducedMotion: preference !== 'full',
      }}>
        <ScrollClock />
        {children}
      </ReactLenis>
    </MotionContext.Provider>
  )
}
