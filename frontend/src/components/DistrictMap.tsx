import React, { useCallback, useEffect, useRef, useState } from 'react'
import atlas from '../data/district-map.json'
import type { CoverageGap } from '../lib/copilot'
import type { HighlightSet } from '../lib/districtHighlights'
import { resolveDistrict, type District } from '../lib/districts'
import { compactFor, districtLabel, formatNumber, formatUnit } from '../lib/format'
import { useI18n } from '../lib/i18n'

type Camera = { x: number; y: number; scale: number }
const home: Camera = { x: 0, y: 0, scale: 1 }
const minScale = 1
const maxScale = 3.5

/** The one place the choropleth ramp is defined, so the fills on the map and
 * the legend beside it can never drift apart. */
const shadeFloor = 18
const shadeCeiling = 88
const shade = (share: number): string =>
  `color-mix(in srgb, var(--accent) ${shadeFloor + share * (shadeCeiling - shadeFloor)}%, var(--map-base))`

/** Atlas areas joined to the canonical dictionary by name. The atlas `number`
 * field is alphabetical by English name and is deliberately never read. */
const areas = atlas.districts
  .map(area => ({ ...area, district: resolveDistrict(area.name) }))
  .filter((area): area is typeof area & { district: District } => area.district !== null)

export default function DistrictMap({
  highlights,
  coverage,
  selected,
  onSelect,
  onExplore,
}: {
  highlights: HighlightSet
  /** The backend's own coverage audit, so a grey area reads as absent evidence
   * rather than as a zero. Null when the answer is not district-shaped. */
  coverage: CoverageGap | null
  selected: string | null
  onSelect: (code: string | null) => void
  onExplore: (district: District) => void
}) {
  const { language, t } = useI18n()
  const listSeparator = language === 'zh-TW' ? '、' : ', '
  const [camera, setCamera] = useState<Camera>(home)
  const [hovered, setHovered] = useState<string | null>(null)
  const drag = useRef<{ id: number; x: number; y: number; from: Camera; moved: boolean } | null>(null)
  const suppressClick = useRef(false)
  const stage = useRef<HTMLDivElement>(null)

  // React's synthetic onFocus/onBlur do not fire on SVG <g>, so keyboard focus
  // is tracked with the native focusin/focusout pair, which does bubble.
  useEffect(() => {
    const node = stage.current
    if (!node) return
    const enter = (event: FocusEvent) => {
      const area = (event.target as Element | null)?.closest<SVGGElement>('[data-district]')
      setHovered(area?.dataset.district ?? null)
    }
    const leave = () => setHovered(null)
    node.addEventListener('focusin', enter)
    node.addEventListener('focusout', leave)
    return () => {
      node.removeEventListener('focusin', enter)
      node.removeEventListener('focusout', leave)
    }
  }, [])

  const move = useCallback((next: Camera) => {
    const scale = Math.max(minScale, Math.min(maxScale, next.scale))
    const limit = 180 * scale
    setCamera({
      x: Math.max(-limit, Math.min(limit, next.x)),
      y: Math.max(-limit, Math.min(limit, next.y)),
      scale,
    })
  }, [])

  const readoutCode = hovered ?? selected
  const readout = readoutCode ? highlights.byCode.get(readoutCode) ?? null : null
  const readoutDistrict = readoutCode
    ? areas.find(area => area.district.code === readoutCode)?.district ?? null
    : null

  // Pointed-at first so a hover reads above a standing selection.
  const emphasis = ([
    { kind: 'selected' as const, code: selected },
    { kind: 'hovered' as const, code: hovered === selected ? null : hovered },
  ])
    .flatMap(item => {
      if (!item.code) return []
      const area = areas.find(candidate => candidate.district.code === item.code)
      return area ? [{ ...item, code: item.code, path: area.path }] : []
    })

  const fillFor = (code: string): string => {
    const hit = highlights.byCode.get(code)
    if (!hit) return 'var(--map-base)'
    const span = highlights.maximum - highlights.minimum
    if (hit.value === null || span <= 0) return 'var(--map-cited)'
    // Ember intensity encodes the backend's own figure, scaled across the
    // observed range so a wholly negative metric still reads. Nothing is
    // recomputed: the ratio is an opacity, never a number shown to the reader.
    const share = Math.max(0, Math.min(1, (hit.value - highlights.minimum) / span))
    return shade(share)
  }

  // A shaded map cannot be read without the scale that produced it. Both ends of
  // the ramp are figures the backend already returned for this answer; the ramp
  // is only labelled, never recalculated, and it is withheld when the answer
  // carries no comparable quantity to grade.
  const legend = (() => {
    if (!highlights.byCode.size) return null
    const span = highlights.maximum - highlights.minimum
    if (span <= 0) return null
    const reading = highlights.byCode.values().next().value ?? null
    const compact = compactFor(language)
    return {
      label: reading?.valueLabel ?? t('value'),
      unit: reading?.unit ?? null,
      // Top of the ramp first, so the column reads high to low like the fill.
      stops: [1, 0.5, 0].map(share => compact.format(highlights.minimum + share * span)),
      low: formatNumber(highlights.minimum, language),
      high: formatNumber(highlights.maximum, language),
    }
  })()

  return (
    <section className="district-map" aria-label={t('mapLabel')}>
      <div
        className="map-stage"
        ref={stage}
        onPointerDown={event => {
          if (event.button !== 0) return
          drag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, from: camera, moved: false }
          suppressClick.current = false
        }}
        onPointerMove={event => {
          const active = drag.current
          if (!active || active.id !== event.pointerId) return
          const dx = event.clientX - active.x
          const dy = event.clientY - active.y
          if (!active.moved) {
            if (Math.hypot(dx, dy) < 6) return
            active.moved = true
            suppressClick.current = true
            event.currentTarget.setPointerCapture(event.pointerId)
            setHovered(null)
          }
          move({ ...active.from, x: active.from.x + dx, y: active.from.y + dy })
        }}
        onPointerUp={event => {
          if (drag.current?.id !== event.pointerId) return
          drag.current = null
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId)
          }
        }}
        onPointerCancel={() => { drag.current = null }}
        onClickCapture={event => {
          if (!suppressClick.current) return
          event.preventDefault()
          event.stopPropagation()
          suppressClick.current = false
        }}
      >
        <div
          className="map-camera"
          style={{ transform: `translate(${camera.x}px, ${camera.y}px) scale(${camera.scale})` }}
        >
          <svg viewBox={atlas.viewBox} role="group" aria-label={t('mapDistricts')}>
            <g className="map-neighbors" aria-hidden="true">
              {atlas.neighbors.map(area => (
                <path key={area.name} d={area.path} fillRule="evenodd" />
              ))}
            </g>
            {/* Fills first. Strokes are a separate layer below, because a border
                drawn here would be painted over by the next district's fill —
                which is what made the outline look thick in places and missing
                in others. */}
            {areas.map(area => {
              const code = area.district.code
              const hit = highlights.byCode.get(code)
              const isSelected = selected === code
              return (
                <g
                  key={code}
                  role="button"
                  tabIndex={0}
                  aria-pressed={isSelected}
                  aria-label={
                    hit
                      ? t('mapAreaCited', {
                          name: districtLabel(area.district, language),
                          label: hit.valueLabel ?? t('value'),
                          value: hit.value === null ? t('notStated') : formatNumber(hit.value, language),
                        })
                      : t('mapAreaPlain', { name: districtLabel(area.district, language) })
                  }
                  data-district={code}
                  className={`map-district${isSelected ? ' is-selected' : ''}${hit ? ' is-cited' : ''}`}
                  onClick={() => onSelect(isSelected ? null : code)}
                  onPointerEnter={() => { if (!drag.current?.moved) setHovered(code) }}
                  onPointerLeave={() => setHovered(null)}
                  onKeyDown={event => {
                    if (event.key !== 'Enter' && event.key !== ' ') return
                    event.preventDefault()
                    onSelect(isSelected ? null : code)
                  }}
                >
                  <title>{districtLabel(area.district, language)}</title>
                  <path d={area.path} fillRule="evenodd" fill={fillFor(code)} />
                </g>
              )
            })}

            {/* Every boundary at one uniform hairline, on top of every fill, so
                the 29 districts read as separate areas before any interaction. */}
            <g className="map-borders" aria-hidden="true">
              {areas.map(area => (
                <path key={area.district.code} d={area.path} fillRule="evenodd" />
              ))}
            </g>

            {/* Emphasis last: nothing can paint over the selected or pointed
                outline, so it stays an even weight all the way round. */}
            {emphasis.map(item => (
              <path
                key={`${item.kind}-${item.code}`}
                className={`map-emphasis is-${item.kind}`}
                d={item.path}
                fillRule="evenodd"
                aria-hidden="true"
              />
            ))}

            <g className="map-labels" aria-hidden="true">
              {atlas.neighbors.map(area => (
                <text key={area.name} x={area.label.x} y={area.label.y}>{area.name}</text>
              ))}
            </g>
          </svg>
        </div>

        {legend ? (
          <div
            className="map-legend"
            role="img"
            aria-label={t('mapScaleAria', {
              label: legend.label,
              low: legend.low,
              high: legend.high,
            })}
          >
            <span className="map-legend-title">
              {legend.label}
              {legend.unit ? <i>{formatUnit(legend.unit, language)}</i> : null}
            </span>
            <div className="map-legend-body">
              <span className="map-legend-ramp" aria-hidden="true" />
              <ol className="map-legend-stops" aria-hidden="true">
                {legend.stops.map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ol>
            </div>
            <span className="map-legend-empty">
              <i aria-hidden="true" />
              {t('mapNoData')}
            </span>
          </div>
        ) : null}

        <div className="map-controls" role="group" aria-label={t('mapZoom')}>
          <button type="button" aria-label={t('zoomOut')} disabled={camera.scale <= minScale}
            onClick={() => move({ ...camera, scale: camera.scale - 0.5 })}>−</button>
          <output>{Math.round(camera.scale * 100)}%</output>
          <button type="button" aria-label={t('zoomIn')} disabled={camera.scale >= maxScale}
            onClick={() => move({ ...camera, scale: camera.scale + 0.5 })}>+</button>
          <button type="button" aria-label={t('resetView')} onClick={() => move(home)}>↺</button>
        </div>
      </div>

      <div className="map-readout" aria-live="polite">
        {readoutDistrict ? (
          <>
            <div className="map-readout-head">
              <strong>{districtLabel(readoutDistrict, language)}</strong>
              <span className="cjk-safe">
                {language === 'zh-TW' ? readoutDistrict.english : readoutDistrict.name}
              </span>
              <code>{readoutDistrict.code}</code>
            </div>
            {readout ? (
              <>
                <p className="map-reading">
                  {readout.valueLabel ?? t('value')}
                  <b>{readout.value === null ? '—' : formatNumber(readout.value, language)}</b>
                  {readout.unit ? <i>{formatUnit(readout.unit, language)}</i> : null}
                  {readout.rank !== null ? <span className="map-rank">{t('rankLabel', { rank: readout.rank })}</span> : null}
                </p>
                <p className="map-source">{t('fromSource', { name: readout.source })}</p>
              </>
            ) : (
              <p className="map-source">{t('notInAnswer')}</p>
            )}
            <button
              type="button"
              className="ghost map-ask"
              onClick={() => onExplore(readoutDistrict)}
            >
              {t('viewOverview', { name: districtLabel(readoutDistrict, language) })}
            </button>
          </>
        ) : (
          <p className="map-source">
            {highlights.byCode.size
              ? t('mapHintCited', { count: highlights.byCode.size })
              : t('mapHintEmpty')}
          </p>
        )}
      </div>

      {coverage && coverage.missing_entity_names.length ? (
        <p className="map-note">
          {t('mapCoverageNote', {
            observed: coverage.observed_entity_count,
            expected: coverage.expected_entity_count,
            names: coverage.missing_entity_names.join(listSeparator),
          })}
        </p>
      ) : null}

      {highlights.unplaceable.length ? (
        <p className="map-note">
          {t('mapUnplaceable', { names: highlights.unplaceable.join(listSeparator) })}
        </p>
      ) : null}
    </section>
  )
}
