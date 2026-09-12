import React, { useEffect, useMemo, useRef } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useDashboardMotion } from './MotionProvider'

gsap.registerPlugin(ScrollTrigger)

type DistrictBlock = { district_code: number; district: string; youth_population: number }

export default function CityDepth({ records, year, district }: { records: DistrictBlock[]; year: number; district: string }) {
  const blocks = useMemo(() => {
    const maximum = Math.max(1, ...records.map(row => row.youth_population))
    return [...records].sort((a, b) => a.district_code - b.district_code).map((row, index) => ({
      ...row,
      x: 17 + (index % 6) * 35,
      y: 30 + Math.floor(index / 6) * 37,
      height: (row.youth_population / maximum) * 80,
      accent: district === row.district || (district === 'New Taipei City' && row.youth_population > maximum * 0.65),
    }))
  }, [records, district])
  const root = useRef<HTMLDivElement>(null)
  const camera = useRef<HTMLDivElement>(null)
  const scrollLayer = useRef<HTMLDivElement>(null)
  const { reducedMotion } = useDashboardMotion()

  useEffect(() => {
    if (reducedMotion || !root.current || !scrollLayer.current) return
    const ctx = gsap.context(() => {
      gsap.to(scrollLayer.current, {
        y: 30,
        rotationX: 8,
        rotationY: -10,
        ease: 'none',
        scrollTrigger: {
          trigger: '#overview',
          start: 'top top',
          end: 'bottom top',
          scrub: true,
          invalidateOnRefresh: true,
        },
      })
    }, root)
    return () => ctx.revert()
  }, [reducedMotion])

  useEffect(() => {
    const element = root.current
    const plane = camera.current
    if (!element || !plane || reducedMotion) return
    const finePointer = matchMedia('(hover: hover) and (pointer: fine)')
    const x = { position: 0, velocity: 0, target: 0 }
    const y = { position: 0, velocity: 0, target: 0 }
    let ticking = false
    // Critically damped spring: damping ratio 1, response 0.4s.
    // The analytic step retains velocity on reversals without overshooting.
    const omega = (2 * Math.PI) / 0.4
    const step = (axis: typeof x, dt: number) => {
      const displacement = axis.position - axis.target
      const coefficient = axis.velocity + omega * displacement
      const decay = Math.exp(-omega * dt)
      axis.position = axis.target + (displacement + coefficient * dt) * decay
      axis.velocity = (axis.velocity - omega * coefficient * dt) * decay
    }
    const tick = (_seconds: number, deltaMs: number) => {
      const dt = Math.min(deltaMs / 1000, 0.05)
      step(x, dt)
      step(y, dt)
      plane.style.transform = `rotateX(${x.position}deg) rotateY(${y.position}deg)`
      if (Math.abs(x.target - x.position) + Math.abs(y.target - y.position) + Math.abs(x.velocity) + Math.abs(y.velocity) < 0.015) {
        gsap.ticker.remove(tick)
        ticking = false
        plane.style.willChange = ''
      }
    }
    const wake = () => {
      if (ticking) return
      ticking = true
      plane.style.willChange = 'transform'
      gsap.ticker.add(tick)
    }
    const move = (event: PointerEvent) => {
      if (!finePointer.matches || event.pointerType === 'touch') return
      const bounds = element.getBoundingClientRect()
      x.target = -((event.clientY - bounds.top) / bounds.height - 0.5) * 10
      y.target = ((event.clientX - bounds.left) / bounds.width - 0.5) * 14
      wake()
    }
    const reset = () => { x.target = 0; y.target = 0; wake() }
    const visibility = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) {
        gsap.ticker.remove(tick)
        ticking = false
        for (const axis of [x, y]) axis.position = axis.velocity = axis.target = 0
        plane.style.transform = ''
        plane.style.willChange = ''
      }
    })
    visibility.observe(element)
    element.addEventListener('pointermove', move)
    element.addEventListener('pointerleave', reset)
    finePointer.addEventListener('change', reset)
    return () => {
      gsap.ticker.remove(tick)
      visibility.disconnect()
      element.removeEventListener('pointermove', move)
      element.removeEventListener('pointerleave', reset)
      finePointer.removeEventListener('change', reset)
      plane.style.transform = ''
      plane.style.willChange = ''
    }
  }, [reducedMotion])

  return (
    <div ref={root} className="city-depth" data-testid="city-depth" role="img" aria-label={`${year} 年 29 個行政區方塊；高度依青年人口成比例呈現，位置僅為示意。`}>
      <div className="city-horizon" />
      <div ref={camera} className="city-camera" data-testid="city-camera">
        <div ref={scrollLayer} className="city-scroll-layer" data-testid="city-scroll-layer">
          <div className="city-idle-layer" data-testid="city-idle-layer">
          <div className="city-model">
            <div className="city-plate city-plate-bottom" />
            <div className="city-plate city-plate-middle" />
            <div className="city-plate city-plate-top" />
            {blocks.map(block => (
              <div key={block.district_code} title={`${block.district}：${block.youth_population.toLocaleString('zh-TW')} 名青年`} data-population={block.youth_population} className={`city-block ${block.accent ? 'city-block-accent' : ''}`}
                style={{ left: block.x, top: block.y, '--block-height': `${block.height}px` } as React.CSSProperties}>
                <span className="city-block-top" />
                <span className="city-block-front" />
                <span className="city-block-side" />
              </div>
            ))}
          </div>
          </div>
        </div>
      </div>
    </div>
  )
}
