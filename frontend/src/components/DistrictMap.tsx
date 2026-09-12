import React, { useEffect, useMemo, useRef, useState } from 'react'
import { gsap } from 'gsap'
import atlas from '../data/district-map.json'
import { useDashboardMotion } from './MotionProvider'

type DistrictRecord = { district: string; youth_population: number; total_population: number }
type Camera = { x: number; y: number; scale: number }
const integer = new Intl.NumberFormat('zh-TW')
const compact = new Intl.NumberFormat('zh-TW', { notation: 'compact', maximumFractionDigits: 1 })

export default function DistrictMap({ records, district, year, onSelect }: {
  records: DistrictRecord[]; district: string; year: number; onSelect: (name: string) => void
}) {
  const { reducedMotion } = useDashboardMotion()
  const [hovered, setHovered] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const stage = useRef<HTMLDivElement>(null)
  const camera = useRef<HTMLDivElement>(null)
  const position = useRef<Camera>({ x: 0, y: 0, scale: 1 })
  const gesture = useRef<{ id: number; x: number; y: number; origin: Camera; dragged: boolean } | null>(null)
  const suppressClick = useRef(false)
  const byName = useMemo(() => new Map(records.map(row => [row.district, row])), [records])
  const maximum = Math.max(...records.map(row => row.youth_population), 1)
  const previewName = hovered || district
  const preview = byName.get(previewName)
  const previewArea = atlas.districts.find(area => area.name === previewName)
  const covered = atlas.districts.filter(area => byName.has(area.name)).length

  useEffect(() => {
    const element = camera.current
    return () => { if (element) gsap.killTweensOf(element) }
  }, [])

  function moveCamera(next: Camera, animate = true) {
    if (!stage.current || !camera.current) return
    const scale = Math.max(1, Math.min(3, next.scale))
    const limitX = stage.current.clientWidth * (0.15 + (scale - 1) / 2)
    const limitY = stage.current.clientHeight * (0.15 + (scale - 1) / 2)
    const target = { x: Math.max(-limitX, Math.min(limitX, next.x)), y: Math.max(-limitY, Math.min(limitY, next.y)), scale }
    position.current = target
    setZoom(scale)
    gsap.killTweensOf(camera.current)
    if (animate && !reducedMotion) gsap.to(camera.current, { ...target, duration: 0.4, ease: 'power3.out', overwrite: true })
    else gsap.set(camera.current, target)
  }

  function beginDrag(event: React.PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !camera.current) return
    gsap.killTweensOf(camera.current)
    // Read the visible camera when a drag interrupts a reset/zoom tween.
    const origin = { x: Number(gsap.getProperty(camera.current, 'x')), y: Number(gsap.getProperty(camera.current, 'y')), scale: Number(gsap.getProperty(camera.current, 'scaleX')) }
    position.current = origin
    suppressClick.current = false
    gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, origin, dragged: false }
  }

  function drag(event: React.PointerEvent<HTMLDivElement>) {
    const active = gesture.current
    if (!active || active.id !== event.pointerId) return
    const dx = event.clientX - active.x
    const dy = event.clientY - active.y
    if (!active.dragged) {
      if (Math.hypot(dx, dy) < 8) return
      // Vertical touch swipes keep scrolling the page, not a trapped map region.
      if (event.pointerType === 'touch' && Math.abs(dy) > Math.abs(dx)) return
      active.dragged = true
      suppressClick.current = true
      event.currentTarget.setPointerCapture(event.pointerId)
      event.currentTarget.dataset.dragging = 'true'
      setHovered(null)
    }
    moveCamera({ ...active.origin, x: active.origin.x + dx, y: active.origin.y + (event.pointerType === 'touch' ? 0 : dy) }, false)
  }

  function endDrag(event: React.PointerEvent<HTMLDivElement>) {
    if (gesture.current?.id !== event.pointerId) return
    gesture.current = null
    delete event.currentTarget.dataset.dragging
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  return (
    <div className="district-map-island">
      <div className="district-map" data-testid="district-map">
        <div className="map-toolbar">
          <p><span className="map-live-dot" />{covered} 個行政區・3D 地圖</p>
          <span className="map-year">{year}</span>
        </div>
        <div ref={stage} className="map-stage interactive-map-stage" data-testid="map-stage" tabIndex={0}
          role="group" aria-label="地圖操作區" aria-describedby="map-interaction-help"
          onPointerDown={beginDrag} onPointerMove={drag} onPointerUp={endDrag} onPointerCancel={endDrag}
          onClickCapture={event => { if (suppressClick.current) { event.preventDefault(); event.stopPropagation(); suppressClick.current = false } }}
          onKeyDown={event => {
            if (event.target !== event.currentTarget) return
            const next = { ...position.current }
            if (event.key === '+' || event.key === '=') next.scale += 0.5
            else if (event.key === '-') next.scale -= 0.5
            else if (event.key === 'ArrowLeft') next.x -= 40
            else if (event.key === 'ArrowRight') next.x += 40
            else if (event.key === 'ArrowUp') next.y -= 40
            else if (event.key === 'ArrowDown') next.y += 40
            else if (event.key === 'Home') { event.preventDefault(); moveCamera({ x: 0, y: 0, scale: 1 }); return }
            else return
            event.preventDefault(); moveCamera(next)
          }}>
          <div className="map-camera" ref={camera} data-testid="map-camera">
            <svg className="district-map-svg is-raised" viewBox={atlas.viewBox} role="group" aria-label={`${year} 年新北市行政區青年人口地圖`} aria-describedby="map-coverage-note">
              <g className="map-neighbors" aria-hidden="true">
                {atlas.neighbors.map(area => <path key={area.name} d={area.path} fillRule="evenodd" />)}
              </g>
              <g aria-hidden="true" className="map-extrusion" transform="translate(0,12)">
                {atlas.districts.map(area => <path key={area.name} d={area.path} fillRule="evenodd" />)}
              </g>
              {atlas.districts.map(area => {
                const record = byName.get(area.name)
                const selected = district === area.name
                return (
                  <g key={area.name} role="button" tabIndex={0} aria-pressed={selected}
                    aria-label={`選擇${area.name}，青年人口 ${integer.format(record?.youth_population ?? 0)} 人`}
                    data-district={area.name}
                    className={`map-district ${selected ? 'is-selected' : ''} ${hovered === area.name ? 'is-previewed' : ''}`}
                    onClick={() => onSelect(area.name)} onFocus={() => setHovered(area.name)} onBlur={() => setHovered(null)}
                    onPointerEnter={() => { if (!gesture.current?.dragged) setHovered(area.name) }} onPointerLeave={() => setHovered(null)}
                    onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(area.name) } }}>
                    <title>{area.name}：{year} 年青年人口 {integer.format(record?.youth_population ?? 0)} 人</title>
                    <path d={area.path} fillRule="evenodd" fill={selected ? 'var(--map-selected)' : record ? `color-mix(in srgb, var(--accent) ${22 + (record.youth_population / maximum) * 73}%, var(--map-base))` : 'var(--surface-muted)'} />
                  </g>
                )
              })}
              {/* Decorative lift: original district hit targets never move on hover. */}
              {previewArea && <g className="map-focus-relief" aria-hidden="true">
                <path d={previewArea.path} fillRule="evenodd" transform="translate(0,-5)" />
                <line x1={previewArea.label.x} x2={previewArea.label.x} y1={previewArea.label.y - 4} y2={previewArea.label.y - 21} />
                <circle cx={previewArea.label.x} cy={previewArea.label.y - 23} r="3" />
              </g>}
              <g className="map-labels" aria-hidden="true">
                {atlas.neighbors.map(area => <text className="map-neighbor-label" key={area.name} x={area.label.x} y={area.label.y}>{area.name}</text>)}
              </g>
              <text x="556" y="30" className="map-north" aria-hidden="true">北 ↑</text>
            </svg>
          </div>
        </div>
        <div className="map-navigation">
          <p id="map-interaction-help">拖曳探索・點選行政區<br /><span>使用＋／−放大小型行政區。</span></p>
          <div className="map-camera-controls" role="group" aria-label="地圖縮放控制">
            <button type="button" aria-label="縮小地圖" disabled={zoom <= 1} onClick={() => moveCamera({ ...position.current, scale: zoom - 0.5 })}>−</button>
            <output aria-label="地圖縮放比例">{Math.round(zoom * 100)}%</output>
            <button type="button" aria-label="放大地圖" disabled={zoom >= 3} onClick={() => moveCamera({ ...position.current, scale: zoom + 0.5 })}>+</button>
            <button type="button" aria-label="重設地圖視角" title="重設地圖視角" onClick={() => moveCamera({ x: 0, y: 0, scale: 1 })}>↺</button>
          </div>
        </div>
        <div className="map-hover-readout" aria-live="polite" aria-atomic="true">
          {preview ? <><strong>{preview.district}</strong><span>青年人口・{integer.format(preview.youth_population)} 人</span></> : <><strong>探索新北市</strong><span>指向行政區預覽，點選即可查看剖面。</span></>}
        </div>
        <div className="map-legend"><span>青年人口較少</span><i /><span>{compact.format(maximum)}</span></div>
        <p className="map-coverage-note" id="map-coverage-note">灰色區域為不在本資料集內的臺北市與基隆市；新北市 29 個行政區均已納入。</p>
        <p className="map-attribution"><a href="https://github.com/dkaoster/taiwan-atlas" target="_blank" rel="noreferrer">行政區界線來源</a>：2021 年簡化地圖；色彩呈現 {year} 年青年人口，立體效果僅供示意，並非地形。</p>
      </div>
    </div>
  )
}
