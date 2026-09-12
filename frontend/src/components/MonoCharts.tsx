// Adapted from Amicro's Mono Rounded Bar, Donut and Sparkline charts (MIT).
// Source revision and full license: public/data/amicro-attribution.txt.
import React, { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, LabelList, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import ChartMotion from './ChartMotion'

const integer = new Intl.NumberFormat('zh-TW')
const compact = new Intl.NumberFormat('zh-TW', { notation: 'compact', maximumFractionDigits: 1 })
const tick = { fill: 'var(--mono-muted)', fontSize: 12 }

export function MonoTooltip({ active, payload, label, valueLabel = '人數' }: any) {
  if (!active || !payload?.length) return null
  return <div className="mono-tooltip">
    <p>{label ?? payload[0].name}</p>
    <strong>{integer.format(Number(payload[0].value))}</strong>
    <span>{valueLabel}</span>
  </div>
}

export function MonoSparkline({ values }: { values: number[] }) {
  const points = values.length === 1 ? [values[0], values[0]] : values
  return <div className="mono-sparkline" aria-hidden="true" data-chart-design="amicro-mono-sparkline">
    <ChartMotion motionKey={values.join(',')} decorative>
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={points.map(value => ({ value }))} margin={{ top: 5, right: 3, bottom: 5, left: 3 }}>
        <YAxis hide domain={['dataMin', 'dataMax']} />
        <Line dataKey="value" type="monotone" stroke="var(--mono-ink)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
    </ChartMotion>
  </div>
}

export function MonoPillBars({ data, nameKey, valueKey = 'people', horizontal = false, labelWidth = 90, valueLabel = '人數' }: {
  data: Record<string, string | number>[]; nameKey: string; valueKey?: string; horizontal?: boolean; labelWidth?: number; valueLabel?: string
}) {
  return <div className="mono-chart" data-chart-design="amicro-mono-pill-bars">
    <ChartMotion motionKey={data.map(item => `${item[nameKey]}:${item[valueKey]}`).join('|')} direction={horizontal ? 'horizontal' : 'vertical'}>
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 24, right: horizontal ? 42 : 12, bottom: 6, left: 0 }}>
        <CartesianGrid stroke="var(--mono-grid)" strokeDasharray="2 3" vertical={horizontal} horizontal={!horizontal} />
        <XAxis dataKey={horizontal ? undefined : nameKey} type={horizontal ? 'number' : 'category'} axisLine={false} tickLine={false} tick={tick} dy={8}
          tickFormatter={horizontal ? value => compact.format(Number(value)) : undefined} minTickGap={16} />
        <YAxis dataKey={horizontal ? nameKey : undefined} type={horizontal ? 'category' : 'number'} axisLine={false} tickLine={false}
          tick={{ ...tick, fill: horizontal ? 'var(--mono-ink)' : tick.fill }} width={horizontal ? labelWidth : 46}
          tickFormatter={horizontal ? undefined : value => compact.format(Number(value))} />
        <Tooltip content={<MonoTooltip valueLabel={valueLabel} />} cursor={{ fill: 'var(--mono-hover)', radius: 8 }} />
        <Bar dataKey={valueKey} fill="var(--mono-ink)" radius={[8, 8, 8, 8]} barSize={horizontal ? 14 : 22} isAnimationActive={false}>
          <LabelList dataKey={valueKey} position={horizontal ? 'right' : 'top'} offset={10} fill="var(--mono-muted)" fontSize={12} formatter={(value: number) => compact.format(Number(value))} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
    </ChartMotion>
  </div>
}

export function MonoDonut({ data }: { data: { name: string; value: number; color: string }[] }) {
  const [active, setActive] = useState<number | null>(null)
  const total = data.reduce((sum, item) => sum + item.value, 0)
  const selected = active === null ? null : data[active]
  return <div className="mono-chart mono-donut" data-chart-design="amicro-mono-rounded-donut">
    <ChartMotion motionKey={data.map(item => `${item.name}:${item.value}`).join('|')} direction="ring">
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Tooltip content={<MonoTooltip valueLabel="戶籍青年人口" />} />
        <Pie cx="50%" cy="50%" data={data} dataKey="value" innerRadius={68} outerRadius={94} paddingAngle={6} cornerRadius={8}
          stroke="var(--canvas)" strokeWidth={2} isAnimationActive={false}
          onMouseEnter={(_, index) => setActive(index)} onMouseLeave={() => setActive(null)}>
          {data.map((item, index) => <Cell key={item.name} fill={item.color} opacity={active === null || active === index ? 1 : 0.45}
            tabIndex={0} role="img" aria-label={`${item.name}：${integer.format(item.value)} 名青年`}
            onFocus={() => setActive(index)} onBlur={() => setActive(null)} />)}
        </Pie>
      </PieChart>
    </ResponsiveContainer>
    </ChartMotion>
    <div className="mono-donut-center"><strong>{selected ? `${(selected.value / total * 100).toFixed(1)}%` : compact.format(total)}</strong><span>{selected?.name ?? '青年總數'}</span></div>
  </div>
}
