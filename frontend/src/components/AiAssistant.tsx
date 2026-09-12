import React, { useEffect, useRef, useState } from 'react'
import Icon from './Icon'
import { ChartContext, CopilotResponse, DashboardAction, createCopilotClient, previewAnswer, suggestions } from '../lib/copilot'

type Exchange = { question: string; response?: CopilotResponse }
type ActionOption = { label: string; reason?: string; apply: () => void }

const displayUnit = (unit: string) => unit === 'persons' ? '人' : unit === 'moves' ? '人次' : unit

export default function AiAssistant({ contexts, context, onContextChange, actionOption }: {
  contexts: ChartContext[]
  context: ChartContext
  onContextChange: (id: string) => void
  actionOption: (action: DashboardAction) => ActionOption
}) {
  const baseUrl = import.meta.env.VITE_COPILOT_API_BASE?.trim() || ''
  const live = Boolean(baseUrl)
  const [question, setQuestion] = useState('')
  const [exchanges, setExchanges] = useState<Exchange[]>([])
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const request = useRef<AbortController | null>(null)
  const session = useRef<string | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const followingLatest = useRef(true)

  useEffect(() => () => { request.current?.abort(); request.current = null }, [])
  useEffect(() => {
    if (followingLatest.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight
  }, [exchanges])

  const cancel = () => {
    request.current?.abort()
    request.current = null
    session.current = null
    setPending(false)
    setStatus('已取消請求，未新增回答。')
  }
  const reset = () => {
    cancel()
    setExchanges([]); setError(''); setQuestion(''); setStatus('已清除對話。')
    input.current?.focus({ preventScroll: true })
  }

  const send = async (text: string, retry = false) => {
    const message = text.trim()
    if (!message || message.length > 2000 || request.current || !context.period) return
    followingLatest.current = true
    setError(''); setStatus(''); setQuestion('')
    if (!retry) setExchanges(items => [...items, { question: message }])
    if (!live) {
      const response = previewAnswer(context, message)
      setExchanges(items => items.map((item, index) => index === items.length - 1 ? { ...item, response } : item))
      setStatus('CSV 預覽已完成，未呼叫 AI 服務。')
      return
    }
    const controller = new AbortController()
    request.current = controller
    setPending(true)
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 30000)
    try {
      const client = createCopilotClient(baseUrl)
      if (!session.current) session.current = await client.session(controller.signal)
      if (request.current !== controller) return
      const response = await client.chat(session.current, message, {
        selectedDistricts: [context.districtCode], period: context.period,
        activeMetric: context.metric, activePanel: context.id,
      }, controller.signal)
      if (request.current !== controller) return
      setExchanges(items => items.map((item, index) => index === items.length - 1 ? { ...item, response } : item))
      setStatus('已收到回答，請檢視引用證據與限制。')
    } catch (cause) {
      if (request.current !== controller) return
      session.current = null
      setError(timedOut ? 'AI 助理回應逾時，請再試一次。' :
        cause instanceof TypeError ? '無法連線至 AI 助理，請檢查 API 位址與後端 CORS 設定。' :
          cause instanceof Error ? cause.message : 'AI 助理無法回答，請再試一次。')
    } finally {
      window.clearTimeout(timeout)
      if (request.current === controller) { request.current = null; setPending(false) }
    }
  }

  const exportBrief = () => {
    const body = [
      live ? 'AI 助理回答（使用前請查證）' : 'CSV 資料預覽（非 AI 生成）',
      context.title, context.district, `選擇年份：${context.selectedYear}；來源期間：${context.period?.start}／${context.period?.end}`,
      context.scope, `資料來源：${context.source}`, '',
      ...exchanges.flatMap(item => [`問題：${item.question}`, item.response?.answer || '未收到回答。',
        ...(item.response?.evidence.map(e => `證據：${e.datasetId}｜${e.metric}｜${e.period}｜行政區代碼 ${e.districtCode}｜${e.value} ${displayUnit(e.unit)}${e.isEstimated ? '（估計值）' : ''}`) || []),
        ...(item.response?.warnings.map(w => `限制：${w}`) || []), '']),
    ].join('\n')
    const url = URL.createObjectURL(new Blob([body], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url; link.download = `youth-compass-${context.id}-${context.selectedYear}.txt`
    link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    setStatus('摘要已下載，並附上來源說明。')
  }

  const last = exchanges[exchanges.length - 1]
  return <section id="ai-assistant" className="ai-assistant scroll-mt-28" aria-labelledby="ai-title">
    <div className="ai-heading">
      <div><h3 id="ai-title" tabIndex={-1}>向資料提問</h3><p>可理解圖表脈絡的助理，協助查詢、檢視證據與掌握全貌。</p></div>
      <span className="ai-mode" data-mode={live ? 'connected' : 'preview'}>{live ? 'API 已連線' : 'CSV 預覽・尚未連接 AI'}</span>
    </div>
    <div className="ai-workspace">
      <aside className="ai-context" aria-label="AI 助理資料脈絡">
        <label htmlFor="ai-chart">圖表脈絡</label>
        <select id="ai-chart" value={context.id} onChange={event => onContextChange(event.target.value)}>
          {contexts.map(chart => <option value={chart.id} key={chart.id}>{chart.title}</option>)}
        </select>
        <dl>
          <div><dt>行政區</dt><dd>{context.district}</dd></div>
          <div><dt>選擇年份</dt><dd>{context.selectedYear}</dd></div>
          <div><dt>資料期間</dt><dd>{context.period ? context.period.start === context.period.end ? context.period.end : `${context.period.start} 至 ${context.period.end}` : '沒有相容資料'}</dd></div>
          <div><dt>統計範圍</dt><dd>{context.scope}</dd></div>
        </dl>
        <a className="ai-source" href={`/data/${context.source}`} download><Icon name="download" className="h-4 w-4" />下載來源 CSV</a>
        <details className="ai-context-help"><summary>關於這段對話</summary><p className="ai-context-note">變更行政區、年份或圖表時會開始新對話，避免回答混用不同資料脈絡。</p></details>
      </aside>
      <div className="ai-conversation">
        <div className="ai-tools">
          <span>{live ? '先看證據，再做解讀' : '探索前端資料預覽'}</span>
          <div><button type="button" onClick={exportBrief} disabled={!exchanges.some(item => item.response) || pending}>儲存摘要</button><button type="button" onClick={reset} disabled={!exchanges.length && !pending}>清除</button></div>
        </div>
        {!exchanges.length && <div className="ai-empty">
          <h4>你想了解什麼？</h4>
          <p>{live ? '針對目前圖表提問；回答可附來源證據，並提供需由你確認的儀表板操作建議。' : '選擇建議問題，即可根據 CSV 計算摘要；後端串接 AI 後才會提供自由提問與解讀。'}</p>
        </div>}
        <div className="ai-suggestions" aria-label="建議問題">
          {suggestions.map(text => <button type="button" key={text} disabled={pending || !context.period} onClick={() => void send(text)}>{text}<Icon name="arrow-up-right" className="h-3.5 w-3.5" /></button>)}
        </div>
        <div ref={transcript} className="ai-transcript" role="log" aria-label="AI 助理對話" aria-live="polite" aria-relevant="additions text" data-lenis-prevent onScroll={event => { const el = event.currentTarget; followingLatest.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60 }}>
          {exchanges.map((item, index) => <article className="ai-exchange" key={index}>
            <p className="ai-question"><span>你</span>{item.question}</p>
            {item.response && <div className="ai-response">
              <p className="ai-response-label">{live ? 'AI 助理' : 'CSV 預覽・非 AI 生成'}</p>
              <p className="ai-answer">{item.response.answer}</p>
              {item.response.evidence.length > 0 ? <details className="ai-evidence"><summary>來源證據（{item.response.evidence.length}）</summary>
                {item.response.evidence.map((e, i) => <div key={i}><strong>{new Intl.NumberFormat('zh-TW').format(e.value)} {displayUnit(e.unit)}{e.isEstimated ? '・估計值' : ''}</strong><span>{e.metric}・{e.period}・行政區代碼 {e.districtCode}</span><span>{e.datasetId}{e.datasetVersion ? `・${e.datasetVersion}` : ''}</span></div>)}
              </details> : <p className="ai-warning">未提供支持證據，請勿將此回答視為已驗證資訊。</p>}
              {item.response.warnings.length > 0 && <div className="ai-warnings"><p>請留意</p><ul>{item.response.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></div>}
              {item.response.dashboardActions.map((action, i) => {
                const option = actionOption(action)
                return <div className="ai-proposed-action" key={i}><button type="button" disabled={Boolean(option.reason)} onClick={option.apply}>{option.label}</button>{option.reason && <p>{option.reason}</p>}</div>
              })}
            </div>}
          </article>)}
        </div>
        {pending && <div className="ai-pending" role="status"><span>正在取得附有證據的回答…</span><button type="button" onClick={cancel}>取消請求</button></div>}
        {error && <div className="ai-error" role="alert"><p>{error}</p><button type="button" onClick={() => last && void send(last.question, true)}>重試</button></div>}
        <form className="ai-composer" onSubmit={event => { event.preventDefault(); void send(question) }}>
          <label htmlFor="ai-question">詢問「{context.title}」</label>
          <textarea ref={input} id="ai-question" placeholder={live ? '針對這張圖表提出問題…' : '試用資料預覽，或先準備要詢問 AI 的問題…'} value={question} maxLength={2000} rows={3} disabled={pending || !context.period} onChange={event => setQuestion(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(question) } }} aria-describedby="ai-input-help" />
          <div><p id="ai-input-help">{question.length}/2,000・Shift + Enter 換行</p><button type="submit" disabled={pending || !question.trim() || !context.period}>{live ? '詢問助理' : '試用預覽'}<span aria-hidden="true">↗</span></button></div>
        </form>
        {!context.period && <p className="ai-warning">這張圖表在 {context.selectedYear} 年沒有相容資料，請改選較晚年份或其他圖表。</p>}
        <p className="ai-disclaimer">請勿輸入個人資料。將回答用於決策前，請先檢查來源證據。</p>
        <p className="sr-only" role="status">{status}</p>
      </div>
    </div>
  </section>
}
