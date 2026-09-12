import React, { useId, useLayoutEffect, useRef } from 'react'
import { useDashboardMotion } from './MotionProvider'

const svgNS = 'http://www.w3.org/2000/svg'
const marksSelector = '.recharts-area-area, .recharts-area-curve, .recharts-area-dots .recharts-dot, .recharts-line-curve, .recharts-bar-rectangle .recharts-rectangle, .recharts-pie-sector .recharts-sector'

/** Reveal the real plot through one shared viewport mask. Forecasts and their
 * intervals draw on the SAME timeline as actual data. Text/data never move. */
export default function ChartMotion({ children, motionKey, direction = 'horizontal', decorative = false }: {
  children: React.ReactNode; motionKey: string; direction?: 'horizontal' | 'vertical' | 'ring'; decorative?: boolean
}) {
  const root = useRef<HTMLDivElement>(null)
  const id = `plot-reveal-${useId().replace(/:/g, '')}`
  const { reducedMotion } = useDashboardMotion()

  useLayoutEffect(() => {
    const element = root.current
    if (!element) return
    let visible = false
    let started = false
    let complete = reducedMotion
    let disposed = false
    let animation: Animation | null = null
    let clip: SVGClipPathElement | null = null
    let rect: SVGRectElement | null = null
    const originalClips = new Map<SVGElement, string>()
    element.dataset.motionState = reducedMotion ? 'reduced' : 'waiting'

    const sync = () => {
      if (reducedMotion || complete) return
      if (visible && !document.hidden && rect && !started) {
        started = true
        element.dataset.revealCount = String(Number(element.dataset.revealCount || 0) + 1)
        const from = direction === 'vertical' ? 'scaleY(0)' : 'scaleX(0)'
        // Deliberately slow, one-shot draw requested by the user. No shimmer.
        animation = rect.animate([{ transform: from }, { transform: 'scale(1)' }], {
          duration: direction === 'ring' ? 800 : direction === 'vertical' ? 1200 : 2200,
          delay: 100, easing: 'linear', fill: 'both',
        })
        animation.onfinish = () => {
          if (disposed) return
          complete = true
          element.dataset.motionState = 'complete'
          originalClips.forEach((value, mark) => { mark.style.clipPath = value })
          animation?.cancel()
          clip?.remove()
        }
      }
      if (!started) return
      if (visible && !document.hidden) {
        animation?.play()
        element.dataset.motionState = 'drawing'
      } else {
        animation?.pause()
        element.dataset.motionState = 'paused'
      }
    }

    const measure = () => {
      if (disposed || reducedMotion || complete) return
      const svg = element.querySelector<SVGSVGElement>('.recharts-surface')
      if (!svg) return
      const marks = [...svg.querySelectorAll<SVGElement>(marksSelector)]
      if (!marks.length) return
      if (!clip) {
        clip = document.createElementNS(svgNS, 'clipPath')
        clip.id = id
        clip.setAttribute('clipPathUnits', 'userSpaceOnUse')
        clip.classList.add('chart-reveal-mask')
        rect = document.createElementNS(svgNS, 'rect')
        rect.style.transformOrigin = direction === 'vertical' ? '0 100%' : '0 0'
        rect.style.transformBox = 'view-box'
        rect.style.transform = direction === 'vertical' ? 'scaleY(0)' : 'scaleX(0)'
        clip.append(rect)
        svg.append(clip)
      }
      rect!.setAttribute('width', String(svg.viewBox.baseVal.width || svg.width.baseVal.value))
      rect!.setAttribute('height', String(svg.viewBox.baseVal.height || svg.height.baseVal.value))
      marks.forEach(mark => {
        if (!originalClips.has(mark)) originalClips.set(mark, mark.style.clipPath)
        mark.style.clipPath = `url(#${id})`
      })
      sync()
    }

    // CSS hides waiting marks before ResponsiveContainer's first measurement:
    // no flash of a complete plot while Recharts/observers are mounting.
    const visibility = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting && entry.intersectionRatio >= 0.18
      sync()
    }, { threshold: 0.18, rootMargin: '-80px 0px -20px 0px' })
    const resize = new ResizeObserver(measure)
    const geometry = new MutationObserver(changes => {
      if (changes.some(change => !(change.target as Element).closest?.('.chart-reveal-mask'))) measure()
    })
    visibility.observe(element)
    resize.observe(element)
    geometry.observe(element, { subtree: true, childList: true, attributes: true, attributeFilter: ['d', 'viewBox'] })
    document.addEventListener('visibilitychange', sync)
    measure()
    return () => {
      disposed = true
      visibility.disconnect(); resize.disconnect(); geometry.disconnect()
      document.removeEventListener('visibilitychange', sync)
      animation?.cancel()
      originalClips.forEach((value, mark) => { mark.style.clipPath = value })
      clip?.remove()
    }
  }, [motionKey, direction, id, reducedMotion])

  return <div ref={root} className="chart-motion" data-motion-state={reducedMotion ? 'reduced' : 'waiting'} data-testid="chart-motion" role={decorative ? undefined : 'group'} aria-label={decorative ? undefined : '資料圖表'}>{children}</div>
}
