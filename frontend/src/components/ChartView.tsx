import React from 'react'
import {
  Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, LabelList, Legend, Line, LineChart,
  ReferenceDot, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from 'recharts'
import type { VisualizationSpec, VisualizationValue } from '../lib/copilot'
import { colorFor, compactFor, formatCell, formatNumber, formatUnit } from '../lib/format'
import { useI18n } from '../lib/i18n'
import ChartMotion from './ChartMotion'

const tick = { fill: 'var(--chart-muted)', fontSize: 12 }
const axisLabel = { fill: 'var(--chart-muted)', fontSize: 11 }

function Tip({ active, payload, label, unit }: any) {
  const { language } = useI18n()
  if (!active || !payload?.length) return null
  return (
    <div className="mono-tooltip">
      <p>{label}</p>
      {payload.map((item: any) => (
        <span key={item.dataKey} className="tooltip-row">
          <i className="tooltip-swatch" style={{ background: item.color }} />
          {item.name}
          <strong>{formatNumber(Number(item.value), language)}</strong>
        </span>
      ))}
      {unit ? <span className="tooltip-unit">{formatUnit(unit, language)}</span> : null}
    </div>
  )
}

/** Ember is functional punctuation: it marks the leader of a ranking and the
 * negative side of a change. Everything else stays achromatic graphite, keeping
 * the page ~95% achromatic as the design system requires. The leader is row 0
 * because the backend already ordered the ranking — nothing is recomputed here. */
function barFill(
  spec: VisualizationSpec,
  row: Record<string, VisualizationValue>,
  field: string,
  index: number,
): string {
  if (Number(row[field]) < 0) return 'var(--chart-negative)'
  if (spec.type === 'ranking_bar' && index === 0) return 'var(--chart-primary)'
  return 'var(--chart-positive)'
}

/** A spec whose quantitative encoding sits on x renders horizontally; one whose
 * quantitative encoding sits on y renders vertically. That single rule covers
 * ranking, contribution, and comparison bars without per-type branching. */
function BarView({ spec }: { spec: VisualizationSpec }) {
  const { language } = useI18n()
  const compact = compactFor(language)
  const horizontal = spec.x?.data_type === 'quantitative'
  const value = horizontal ? spec.x! : spec.y!
  const category = horizontal ? spec.y! : spec.x!
  const rows = spec.rows.filter(row => typeof row[value.field] === 'number')
  const hasNegative = rows.some(row => Number(row[value.field]) < 0)
  const longestLabel = rows.reduce((width, row) => Math.max(width, String(row[category.field] ?? '').length), 0)

  return (
    <div className="mono-chart" style={{ height: Math.max(240, horizontal ? rows.length * 38 + 70 : 260) }}>
      <ChartMotion motionKey={spec.visualization_id + rows.length} direction={horizontal ? 'horizontal' : 'vertical'}>
        {/* The top margin holds the value label of the tallest bar, which
            Recharts prints above a bar that reaches the top of the plot. */}
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={rows}
            layout={horizontal ? 'vertical' : 'horizontal'}
            margin={{ top: horizontal ? 12 : 26, right: horizontal ? 52 : 16, bottom: 24, left: 4 }}
          >
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 3" vertical={horizontal} horizontal={!horizontal} />
            <XAxis
              type={horizontal ? 'number' : 'category'}
              dataKey={horizontal ? undefined : category.field}
              axisLine={false}
              tickLine={false}
              tick={tick}
              dy={6}
              interval={0}
              angle={!horizontal && longestLabel > 4 ? -30 : 0}
              textAnchor={!horizontal && longestLabel > 4 ? 'end' : 'middle'}
              height={!horizontal && longestLabel > 4 ? 62 : 34}
              tickFormatter={horizontal ? v => compact.format(Number(v)) : undefined}
              label={{ value: horizontal ? value.label : category.label, position: 'insideBottom', offset: -14, style: axisLabel }}
            />
            <YAxis
              type={horizontal ? 'category' : 'number'}
              dataKey={horizontal ? category.field : undefined}
              axisLine={false}
              tickLine={false}
              tick={{ ...tick, fill: horizontal ? 'var(--chart-text)' : tick.fill }}
              width={horizontal ? Math.min(160, Math.max(70, longestLabel * 14 + 16)) : 52}
              tickFormatter={horizontal ? undefined : v => compact.format(Number(v))}
            />
            {hasNegative ? <ReferenceLine {...(horizontal ? { x: 0 } : { y: 0 })} stroke="var(--chart-cursor)" /> : null}
            <Tooltip content={<Tip unit={value.unit} />} cursor={{ fill: 'var(--chart-hover)' }} />
            {/* Square bars: precision over softness, matching the 0px button edge. */}
            <Bar
              dataKey={value.field}
              name={value.label}
              radius={0}
              barSize={horizontal ? 14 : 22}
              isAnimationActive={false}
            >
              {rows.map((row, index) => (
                <Cell key={index} fill={barFill(spec, row, value.field, index)} />
              ))}
              {/* A zero-value row draws no bar; the printed figure keeps it legible
                  instead of leaving an axis label with nothing beside it. */}
              <LabelList
                dataKey={value.field}
                position={horizontal ? 'right' : 'top'}
                offset={8}
                fill="var(--chart-muted)"
                fontSize={10}
                fontFamily="ui-monospace, monospace"
                formatter={(raw: number) => compact.format(Number(raw))}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartMotion>
    </div>
  )
}

/** A series is focused when the backend named it, or when it named none. */
function isFocused(spec: VisualizationSpec, name: string): boolean {
  return spec.focus_entities.length === 0 || spec.focus_entities.includes(name)
}

/** Rows arrive in long format (one row per period per entity). Pivot by the x
 * field without aggregating: the backend already produced final values. */
function LineView({ spec }: { spec: VisualizationSpec }) {
  const { language } = useI18n()
  const compact = compactFor(language)
  const x = spec.x!
  const y = spec.y!
  const seriesField = spec.series_field
  const seriesNames: string[] = []
  const byX = new Map<string, Record<string, VisualizationValue>>()

  const lowerField = spec.band_lower_field
  const upperField = spec.band_upper_field
  for (const row of spec.rows) {
    const key = String(row[x.field] ?? '')
    const name = seriesField ? String(row[seriesField] ?? y.label) : y.label
    if (!seriesNames.includes(name)) seriesNames.push(name)
    const bucket = byX.get(key) ?? { [x.field]: key }
    // A duplicate (period, series) pair would mean the backend sent conflicting
    // grounded values; surface the first and never silently sum them.
    if (bucket[name] === undefined) bucket[name] = row[y.field]
    // Recharts draws a band as one area between two numbers, so the interval
    // travels as [lower, upper] on its own key beside the point estimate.
    if (lowerField && upperField && bucket[bandKey(name)] === undefined) {
      const lower = row[lowerField]
      const upper = row[upperField]
      if (typeof lower === 'number' && typeof upper === 'number') {
        bucket[bandKey(name)] = [lower, upper] as unknown as VisualizationValue
      }
    }
    byX.set(key, bucket)
  }
  const data = [...byX.values()]
  const values = data.flatMap(row =>
    seriesNames
      .flatMap(name => [row[name], ...((row[bandKey(name)] as unknown as number[]) ?? [])])
      .filter((value): value is number => typeof value === 'number'),
  )
  const yDomain: [number, number] | ['auto', 'auto'] = values.length
    ? (() => {
        const minimum = Math.min(...values)
        const maximum = Math.max(...values)
        const span = maximum - minimum
        const padding = Math.max(span * 0.12, Math.abs(maximum) * 0.01, 1)
        return [Math.max(0, minimum - padding), maximum + padding]
      })()
    : ['auto', 'auto']

  return (
    <div className="mono-chart" style={{ height: 280 }}>
      <ChartMotion motionKey={spec.visualization_id + data.length} direction="horizontal">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 12, right: 18, bottom: 24, left: 4 }}>
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 3" vertical={false} />
            <XAxis
              dataKey={x.field}
              axisLine={false}
              tickLine={false}
              tick={tick}
              dy={6}
              minTickGap={18}
              label={{ value: x.label, position: 'insideBottom', offset: -14, style: axisLabel }}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              tick={tick}
              width={54}
              domain={yDomain}
              allowDataOverflow={false}
              tickFormatter={v => compact.format(Number(v))}
            />
            <Tooltip content={<Tip unit={y.unit} />} cursor={{ stroke: 'var(--chart-cursor)', strokeDasharray: '3 3' }} />
            {seriesNames.length > 1 ? (
              <Legend verticalAlign="top" align="right" iconType="plainline" wrapperStyle={{ fontSize: 12, paddingBottom: 8 }} />
            ) : null}
            {spec.reference_lines.map(line => (
              <ReferenceLine
                key={line.label}
                y={line.axis === 'y' ? line.value : undefined}
                x={line.axis === 'x' ? line.value : undefined}
                stroke="var(--chart-muted)"
                strokeDasharray="4 4"
                label={{ value: line.label, position: 'insideTopRight', fill: 'var(--chart-muted)', fontSize: 11 }}
              />
            ))}
            {spec.annotations.map(annotation =>
              annotation.period !== null && annotation.value !== null ? (
                <ReferenceDot
                  key={`${annotation.kind}-${annotation.period}`}
                  x={annotation.period}
                  y={annotation.value}
                  r={4}
                  fill="var(--chart-primary)"
                  stroke="none"
                  label={{ value: annotation.label, position: 'top', fill: 'var(--chart-muted)', fontSize: 11 }}
                />
              ) : null,
            )}
            {lowerField && upperField
              ? seriesNames.map((name, index) => (
                  <Area
                    key={`${name}-band`}
                    dataKey={bandKey(name)}
                    // Named for the legend and the tooltip: an unlabelled shadow
                    // behind a forecast reads as decoration rather than doubt.
                    name={`${name} · interval`}
                    stroke="none"
                    fill={colorFor(index)}
                    fillOpacity={0.14}
                    isAnimationActive={false}
                    legendType="none"
                  />
                ))
              : null}
            {seriesNames.map((name, index) => (
              <Line
                key={name}
                dataKey={name}
                name={name}
                type="monotone"
                stroke={colorFor(index)}
                // A named focus makes every other series context. Dimming is
                // the only difference: nothing is hidden or recomputed.
                strokeOpacity={isFocused(spec, name) ? 1 : 0.28}
                strokeWidth={isFocused(spec, name) ? 2 : 1.25}
                strokeLinecap="round"
                dot={data.length <= 24 ? { r: 2, strokeWidth: 0, fill: colorFor(index) } : false}
                // A gap means the backend published no value for that period.
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </ChartMotion>
    </div>
  )
}

/** Recharts keys a band by one data key holding [lower, upper]. */
function bandKey(name: string): string {
  return `${name}__band`
}

/** Two periods, many entities: one segment each, labelled at both ends. A line
 * chart of the same data is a bundle of parallel strokes nobody can follow. */
function SlopeView({ spec }: { spec: VisualizationSpec }) {
  const { language } = useI18n()
  const compact = compactFor(language)
  const x = spec.x!
  const y = spec.y!
  const seriesField = spec.series_field ?? 'entity_name'
  const periods = [...new Set(spec.rows.map(row => String(row[x.field] ?? '')))].sort()
  const byEntity = new Map<string, Record<string, VisualizationValue>>()
  for (const row of spec.rows) {
    const name = String(row[seriesField] ?? '')
    const bucket = byEntity.get(name) ?? { [seriesField]: name }
    bucket[String(row[x.field] ?? '')] = row[y.field]
    byEntity.set(name, bucket)
  }
  const data = periods.map(period => {
    const point: Record<string, VisualizationValue> = { [x.field]: period }
    for (const [name, values] of byEntity) point[name] = values[period] ?? null
    return point
  })
  const names = [...byEntity.keys()]

  return (
    <div className="mono-chart" style={{ height: 300 }}>
      <ChartMotion motionKey={spec.visualization_id + names.length} direction="horizontal">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 12, right: 84, bottom: 24, left: 4 }}>
            <XAxis
              dataKey={x.field}
              axisLine={false}
              tickLine={false}
              tick={tick}
              dy={6}
              padding={{ left: 24, right: 24 }}
              label={{ value: x.label, position: 'insideBottom', offset: -14, style: axisLabel }}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              tick={tick}
              width={54}
              tickFormatter={v => compact.format(Number(v))}
            />
            <Tooltip content={<Tip unit={y.unit} />} cursor={{ stroke: 'var(--chart-cursor)', strokeDasharray: '3 3' }} />
            {names.map((name, index) => (
              <Line
                key={name}
                dataKey={name}
                name={name}
                type="linear"
                stroke={colorFor(index)}
                strokeOpacity={isFocused(spec, name) ? 1 : 0.28}
                strokeWidth={isFocused(spec, name) ? 2 : 1.25}
                dot={{ r: 3, strokeWidth: 0, fill: colorFor(index) }}
                connectNulls={false}
                isAnimationActive={false}
              >
                <LabelList
                  dataKey={name}
                  position="right"
                  content={({ index: pointIndex, x: px, y: py }: any) =>
                    pointIndex === data.length - 1 ? (
                      <text x={Number(px) + 8} y={Number(py) + 4} fill="var(--chart-muted)" fontSize={11}>
                        {name}
                      </text>
                    ) : null
                  }
                />
              </Line>
            ))}
          </LineChart>
        </ResponsiveContainer>
      </ChartMotion>
    </div>
  )
}

/** Two joined metrics, one point per district. Position only: the backend's
 * description states plainly that this is not a causal claim. */
function ScatterView({ spec }: { spec: VisualizationSpec }) {
  const { language } = useI18n()
  const compact = compactFor(language)
  const x = spec.x!
  const y = spec.y!
  const labelField = spec.series_field ?? 'entity_name'
  const data = spec.rows.filter(
    row => typeof row[x.field] === 'number' && typeof row[y.field] === 'number',
  )

  return (
    <div className="mono-chart" style={{ height: 300 }}>
      <ChartMotion motionKey={spec.visualization_id + data.length} direction="horizontal">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 18, bottom: 28, left: 4 }}>
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 3" />
            <XAxis
              type="number"
              dataKey={x.field}
              name={x.label}
              axisLine={false}
              tickLine={false}
              tick={tick}
              dy={6}
              tickFormatter={v => compact.format(Number(v))}
              label={{ value: x.label, position: 'insideBottom', offset: -16, style: axisLabel }}
            />
            <YAxis
              type="number"
              dataKey={y.field}
              name={y.label}
              axisLine={false}
              tickLine={false}
              tick={tick}
              width={54}
              tickFormatter={v => compact.format(Number(v))}
            />
            <ZAxis range={[42, 42]} />
            <Tooltip
              cursor={{ stroke: 'var(--chart-cursor)', strokeDasharray: '3 3' }}
              content={({ active, payload }: any) => {
                if (!active || !payload?.length) return null
                const row = payload[0].payload as Record<string, VisualizationValue>
                return (
                  <div className="mono-tooltip">
                    <p>{String(row[labelField] ?? '')}</p>
                    <span className="tooltip-row">
                      {x.label}
                      <strong>{formatNumber(Number(row[x.field]), language)}</strong>
                    </span>
                    <span className="tooltip-row">
                      {y.label}
                      <strong>{formatNumber(Number(row[y.field]), language)}</strong>
                    </span>
                  </div>
                )
              }}
            />
            <Scatter data={data} fill="var(--chart-primary)" isAnimationActive={false} />
          </ScatterChart>
        </ResponsiveContainer>
      </ChartMotion>
    </div>
  )
}

function TableView({ spec }: { spec: VisualizationSpec }) {
  const { language } = useI18n()
  // Columns are declared by the backend; fall back to the row keys only when a
  // spec arrives without them so a new table type still renders something exact.
  const columns = spec.columns.length
    ? spec.columns
    : Object.keys(spec.rows[0] ?? {}).map(field => ({ field, label: field, unit: null }))

  return (
    <div className="table-scroll">
      <table className="spec-table">
        <thead>
          <tr>
            {columns.map(column => (
              <th key={column.field} scope="col">
                {column.label}
                {column.unit ? <span className="unit">{formatUnit(column.unit, language)}</span> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.rows.map((row, index) => (
            <tr key={index}>
              {columns.map(column => (
                <td
                  key={column.field}
                  className={[
                    typeof row[column.field] === 'number' ? 'numeric' : '',
                    `field-${column.field.replace(/[^a-zA-Z0-9_-]/g, '-')}`,
                  ].filter(Boolean).join(' ')}
                >
                  {formatCell(row[column.field] ?? null, language)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Render one allowlisted spec. An unknown or unrenderable type degrades to the
 * exact table rather than dropping grounded data, as docs/22 requires. */
export default function ChartView({ spec }: { spec: VisualizationSpec }) {
  const renderable =
    spec.rows.length > 0 &&
    (spec.type === 'data_table' || (!!spec.x && !!spec.y))

  if (!renderable) return <TableView spec={spec} />
  if (spec.type === 'line') return <LineView spec={spec} />
  if (spec.type === 'slope') return <SlopeView spec={spec} />
  if (spec.type === 'scatter') return <ScatterView spec={spec} />
  // A choropleth is drawn by DistrictMap, which owns the boundary geometry.
  // Anywhere else it degrades to its exact table rather than to a bar chart,
  // whose category axis would read the region key as an ordinary label.
  if (spec.type === 'data_table' || spec.type === 'choropleth') return <TableView spec={spec} />
  return <BarView spec={spec} />
}

export { TableView }
