// Mirrors docs/04-agentic-ai.md and docs/06-backend-api.md. No model keys here.
export type Evidence = {
  datasetId: string
  metric: string
  period: string
  districtCode: string
  value: number
  unit: string
  isEstimated: boolean
  datasetVersion?: string
}
export type DashboardAction = {
  type: 'OPEN_PANEL' | 'SELECT_DISTRICTS' | 'SET_PERIOD' | 'SET_METRIC'
  value?: string | { start: string; end: string }
  values?: string[]
}
export type CopilotResponse = {
  answer: string
  evidence: Evidence[]
  warnings: string[]
  dashboardActions: DashboardAction[]
}
export type ChartContext = {
  id: string
  title: string
  metric: string
  district: string
  districtCode: string
  selectedYear: number
  period: { start: string; end: string } | null
  scope: string
  unit: 'persons' | 'moves'
  source: string
  points: { label: string; value: number; period: string; estimated?: boolean }[]
  warnings: string[]
}
export type DashboardContext = {
  selectedDistricts: string[]
  period: { start: string; end: string }
  activeMetric: string
  activePanel: string
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const string = (value: unknown, max = 2000): value is string => typeof value === 'string' && value.length > 0 && value.length <= max
const month = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-(0[1-9]|1[0-2])$/.test(value)
const period = (value: unknown): value is { start: string; end: string } =>
  object(value) && month(value.start) && month(value.end) && value.start <= value.end

export function parseCopilotResponse(raw: unknown): CopilotResponse {
  const invalid = () => { throw new Error('AI 助理回傳的格式無效，請重試或聯絡後端團隊。') }
  if (!object(raw) || !string(raw.answer, 16000) || !Array.isArray(raw.evidence) || raw.evidence.length > 100 ||
      !Array.isArray(raw.warnings) || raw.warnings.length > 20 || !raw.warnings.every(w => string(w)) ||
      !Array.isArray(raw.dashboardActions) || raw.dashboardActions.length > 10) return invalid()
  const evidence = raw.evidence.map(item => {
    if (!object(item) || !string(item.datasetId) || !string(item.metric) || !string(item.period) ||
        !string(item.districtCode, 32) || !string(item.unit, 80) || typeof item.value !== 'number' ||
        !Number.isFinite(item.value) || typeof item.isEstimated !== 'boolean' ||
        (item.datasetVersion !== undefined && !string(item.datasetVersion))) return invalid()
    return item as Evidence
  })
  const dashboardActions = raw.dashboardActions.map(action => {
    if (!object(action)) return invalid()
    // Both documented action envelopes are accepted, but only read-only types.
    const type = action.type ?? action.action
    if ((type === 'OPEN_PANEL' || type === 'SET_METRIC') && string(action.value, 80)) return { type, value: action.value } as DashboardAction
    if (type === 'SELECT_DISTRICTS' && Array.isArray(action.values) && action.values.length > 0 &&
        action.values.length <= 29 && action.values.every(v => string(v, 32))) return { type, values: action.values } as DashboardAction
    if (type === 'SET_PERIOD' && period(action.value)) return { type, value: action.value } as DashboardAction
    return invalid()
  })
  return { answer: raw.answer, evidence, warnings: raw.warnings as string[], dashboardActions }
}

/** Only configured HTTP(S) services; never take endpoints from chat/model text. */
export function createCopilotClient(baseUrl: string, fetcher: typeof fetch = fetch) {
  const base = new URL(baseUrl, window.location.origin)
  if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.search || base.hash) {
    throw new Error('VITE_COPILOT_API_BASE 必須是 HTTP(S) 網址或同源路徑。')
  }
  const post = async (path: string, body: unknown, signal: AbortSignal) => {
    const response = await fetcher(base.href.replace(/\/$/, '') + path, {
      method: 'POST', credentials: 'same-origin', signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      if (response.status === 429) throw new Error('AI 助理目前忙碌，請稍候再試。')
      if ([401, 403].includes(response.status)) throw new Error('尚未取得 AI 助理存取權，請檢查後端登入設定。')
      throw new Error(`AI 助理請求失敗（${response.status}），請重試。`)
    }
    // Bound the response while reading, not after allocating arbitrary server output.
    const reader = response.body?.getReader()
    if (!reader) throw new Error('AI 助理回傳空白內容。')
    const decoder = new TextDecoder()
    let text = '', bytes = 0
    try {
      for (;;) {
        const chunk = await reader.read()
        if (chunk.done) break
        bytes += chunk.value.byteLength
        if (bytes > 256_000) { await reader.cancel(); throw new Error('AI 助理回傳內容過大。') }
        text += decoder.decode(chunk.value, { stream: true })
      }
    } finally { reader.releaseLock() }
    try { return JSON.parse(text + decoder.decode()) as unknown } catch { throw new Error('AI 助理未回傳有效的 JSON。') }
  }
  return {
    async session(signal: AbortSignal) {
      const result = await post('/copilot/sessions', {}, signal)
      if (!object(result) || !string(result.sessionId, 128)) throw new Error('後端未回傳 sessionId。')
      return result.sessionId
    },
    async chat(sessionId: string, message: string, dashboardContext: DashboardContext, signal: AbortSignal) {
      return parseCopilotResponse(await post('/copilot/chat', { sessionId, message, dashboardContext }, signal))
    },
  }
}

export const suggestions = [
  '摘要這張圖表',
  '資料中最值得注意的是什麼？',
  '這些資料有哪些限制？',
]

/** Deterministic CSV facts, explicitly not an LLM or free-form interpretation. */
export function previewAnswer(context: ChartContext, question: string): CopilotResponse {
  const points = context.points
  const first = points[0], last = points[points.length - 1]
  const largest = [...points].sort((a, b) => b.value - a.value)[0]
  const format = (value: number) => new Intl.NumberFormat('zh-TW', { maximumFractionDigits: 1 }).format(value)
  const unit = context.unit === 'persons' ? '人' : '人次'
  let answer = ''
  let selected = last ? [last] : []
  if (!suggestions.includes(question)) {
    answer = '自由提問需要連接後端 AI。目前預覽只會摘要所選 CSV 資料，並未解讀你的問題。'
  } else if (!points.length) {
    answer = `${context.selectedYear} 年以前沒有「${context.title}」的相容資料；系統沒有自行補值或預測。`
  } else if (question === suggestions[2]) {
    answer = `請依「${context.scope}」的統計範圍解讀。${context.warnings.join(' ')}`
  } else if (question === suggestions[1] && largest) {
    answer = `畫面中的最大值是「${largest.label}」：${context.district}共有 ${format(largest.value)} ${unit}${largest.estimated ? '（估計值）' : ''}。`
    selected = [largest]
  } else if (context.id === 'population-trend' && first && last) {
    const difference = last.value - first.value
    answer = `${context.district}在 ${last.period} 的青年人口為 ${format(last.value)} 人，比 ${first.period}（${format(first.value)} 人）${difference < 0 ? '減少' : '增加'} ${format(Math.abs(difference))} 人。這是戶籍人口變化，不代表遷徙量，也無法據此判定原因。`
    selected = first === last ? [last] : [first, last]
  } else if (context.id === 'migration-forecast' && last) {
    answer = `現有 CSV 基準模型估計 ${context.district}在 2026 年將有 ${format(last.value)} 人次遷出。此數字涵蓋全年齡層，不是獨立青年人數，也不是精確的行政區對行政區流向預測。`
  } else {
    const total = points.reduce((sum, point) => sum + point.value, 0)
    answer = `${context.district}在 ${first.period} 顯示的 ${points.length} 個類別合計 ${format(total)} 人；其中「${largest.label}」最大，共 ${format(largest.value)} 人。`
    selected = [largest]
  }
  return {
    answer,
    evidence: selected.map(point => ({
      datasetId: context.source, metric: context.metric, period: point.period,
      districtCode: context.districtCode, value: point.value, unit: context.unit,
      isEstimated: point.estimated ?? false,
    })),
    warnings: context.warnings,
    dashboardActions: [],
  }
}
