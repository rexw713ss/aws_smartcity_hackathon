import { useEffect } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useLenis } from 'lenis/react'
import { useDashboardMotion } from '../components/MotionProvider'

gsap.registerPlugin(ScrollTrigger)
const targets = '#population-trend, #district-profile, #age-structure, #migration-forecast, #education-levels, #marriage-status, #ai-assistant, #data-methods'

/** A scroll-linked handoff between analytical topics. Text never translates;
 * the main reading area is fully opaque. Lenis already updates ScrollTrigger
 * on the shared GSAP clock in MotionProvider; no second animation loop. */
export function useSectionTransitions(ready: boolean) {
  const { reducedMotion } = useDashboardMotion()
  const lenis = useLenis()
  useEffect(() => {
    if (!ready) return
    const root = document.querySelector<HTMLElement>('.spatial-dashboard')
    if (!root) return
    // The CSV replaces a short loading screen. Sync its new height before
    // the first wheel gesture; Lenis's debounced observer otherwise lags.
    lenis?.resize()
    const animations = new Map<HTMLElement, gsap.core.Tween>()
    let refreshFrame = 0
    let disposed = false

    const reconcile = () => {
      for (const [section, animation] of animations) {
        if (root.contains(section)) continue
        animation.scrollTrigger?.kill()
        animation.revert()
        animations.delete(section)
      }
      root.querySelectorAll<HTMLElement>(targets).forEach(section => {
        section.classList.add('section-transition')
        if (reducedMotion) {
          section.dataset.scrollState = 'reduced'
          return
        }
        if (animations.has(section)) return
        const animation = gsap.fromTo(section, { opacity: 0.28 }, {
          // Establish the entry state before the section is visible. Deferring
          // it makes a fully visible heading flash dim at the start boundary.
          opacity: 1, ease: 'none', immediateRender: true,
          scrollTrigger: {
            id: `dashboard-section-${section.id}`, trigger: section,
            start: 'top 92%', end: 'top 58%', scrub: 0.35,
            invalidateOnRefresh: true,
            onUpdate: self => {
              section.dataset.scrollProgress = self.progress.toFixed(3)
              section.dataset.scrollState = self.progress >= 1 ? 'settled' : 'scrubbing'
            },
          },
        })
        animations.set(section, animation)
        section.dataset.scrollState = animation.scrollTrigger!.progress >= 1 ? 'settled' : 'scrubbing'
      })
    }
    const refresh = () => {
      if (refreshFrame) cancelAnimationFrame(refreshFrame)
      refreshFrame = requestAnimationFrame(() => {
        if (disposed) return
        reconcile()
        ScrollTrigger.refresh()
      })
    }
    const keyboard = (event: KeyboardEvent) => {
      if (['Tab', 'Enter', ' ', 'ArrowDown', 'ArrowUp', 'PageDown', 'PageUp', 'Home', 'End'].includes(event.key)) {
        root.dataset.scrollInput = 'keyboard'
      }
    }
    const pointer = () => { delete root.dataset.scrollInput }
    reconcile()
    const size = new ResizeObserver(refresh)
    size.observe(root)
    const nodes = new MutationObserver(refresh)
    // A new AI context replaces its section; observe only direct children,
    // not the constantly changing Recharts SVG paths.
    nodes.observe(root, { childList: true })
    document.addEventListener('keydown', keyboard, true)
    document.addEventListener('pointerdown', pointer, { passive: true })
    document.addEventListener('wheel', pointer, { passive: true })
    document.fonts.ready.then(() => { if (!disposed) refresh() })
    return () => {
      disposed = true
      cancelAnimationFrame(refreshFrame)
      size.disconnect(); nodes.disconnect()
      animations.forEach(animation => { animation.scrollTrigger?.kill(); animation.revert() })
      root.querySelectorAll<HTMLElement>(targets).forEach(section => {
        section.classList.remove('section-transition')
        delete section.dataset.scrollState
        delete section.dataset.scrollProgress
      })
      delete root.dataset.scrollInput
      document.removeEventListener('keydown', keyboard, true)
      document.removeEventListener('pointerdown', pointer)
      document.removeEventListener('wheel', pointer)
    }
  }, [ready, reducedMotion, lenis])
}
