import React, { createContext, useContext } from 'react'

export type Language = 'zh-TW' | 'en'

const messages = {
  'zh-TW': {
    mapLabel: '新北市行政區地圖', mapDistricts: '新北市各行政區', mapZoom: '地圖縮放', zoomIn: '放大', zoomOut: '縮小', resetView: '重設檢視',
    mapAreaCited: '{name}，{label} {value}', mapAreaPlain: '{name}，不在此答案中', notStated: '未註明', rankLabel: '排名 {rank}', fromSource: '來源：「{name}」',
    notInAnswer: '不在目前的答案中。', viewOverview: '查看 {name} 人口概覽',
    mapHintCited: '此答案涵蓋 {count} 個行政區。將游標移到區域上即可讀取數值。', mapHintEmpty: '將游標移到行政區上可讀取資料，或點選一個行政區來提問。',
    mapCoverageNote: '涵蓋 {observed}/{expected} 個行政區。{names} 沒有證據，因此這些區域不上色，而不是顯示為零。',
    mapUnplaceable: '未顯示於地圖：{names}。這些實體不是新北市行政區，要標出位置需要此答案未提供的空間連結。',
    mapAttribution: '邊界：taiwan-atlas {edition}，已簡化。著色代表後端針對目前答案回傳的數值；灰色區域位於新北市之外。',
    youthOverviewOf: '{name} 青年概覽', shareOfYouth: '占青年人口 {value}%', agesOf: '{label} 歲',
    genderRegistration: '{period} 已發布的登記類別。',
    overviewFooter: '已發布資料集 {dataset} · 版本 {version} · 品質 {quality}%。數值採用「{scope}」人口範圍。',
    sourceCandidatesLabel: '可用的候選資料來源',
    askForSource: '我需要一份目錄裡還沒有的資料才能回答。要我從下列官方來源擷取一份快照送審嗎？',
    thinkingReading: '正在讀取已發布的資料目錄…', thinkingRetrieving: '正在檢索符合條件的觀測資料…',
    thinkingComputing: '正在依已發布資料計算…', thinkingChecking: '正在檢查證據是否足以回答…',
    asideSourceSearch: '助理正在比對白名單中的官方資料來源',
    skip: '跳到對話', brand: '青年羅盤', tagline: '新北市 · 決策助理', tools: '工具',
    language: '語言', traditionalChinese: '繁體中文', english: 'English',
    switchView: '切換檢視', conversation: '對話', chartsEvidence: '圖表與證據',
    assistantLabel: '青年政策決策助理', introTitle: '新北青年政策羅盤',
    intro: '每個答案都取自經審核並發布的資料集。系統負責檢索、篩選與計算；語言模型只解讀問題並說明結果，不會虛構數字、擅自選擇資料集或撰寫查詢。',
    availableDatasets: '可詢問的資料', publishedOnly: '僅限已發布', loadingCatalog: '正在載入已發布資料目錄…',
    noDatasets: '目前沒有已發布的資料集。', breakdowns: '分類維度', quality: '品質', tryAsking: '試著詢問',
    pending: '正在檢索已發布資料並計算…', questionPlaceholder: '例如：比較 2023 至 2025 年各行政區的青年人口趨勢',
    question: '問題', composerHint: 'Enter 傳送 · Shift+Enter 換行', cancel: '取消', send: '傳送',
    dataLimitations: '資料限制', assumptions: '假設', limitations: '限制',
    publishedToday: '今天發布', publishedDaysAgo: '發布於 {count} 天前',
    coverage: '涵蓋 {observed}/{expected} 個行政區。', noGaps: '沒有缺口。', noEvidenceFor: '以下地區沒有證據：{names}。', outsideDistricts: '不在行政區集合內：{names}。',
    noCitationWarning: '此答案沒有引用來源，採取行動前請先向後端確認。', showSource: '顯示來源 {number}：{name}',
    basisRegistered: '戶籍人口', basisResident: '常住人口', basisUnknown: '未記錄人口統計基準',
    answered: '依已發布資料回答', insufficient: '證據不足', sourceRequired: '需要資料來源', unsupported: '不支援此問題',
    answeredDetail: '每個數字都來自經核准、已發布且附有引用的資料集。',
    insufficientDetail: '目錄中的合格證據不足，因此不提供建議。',
    sourceRequiredDetail: '目錄缺少回答此問題所需的資料，請提交一個已設定的來源供審核。',
    unsupportedDetail: '目前沒有已登錄的工具可以回答，系統不會拼湊不完整的答案。',
    charts: '圖表', map: '地圖', impact: '影響', evidence: '證據', trace: '執行紀錄', insightViews: '洞察檢視', supportingInsight: '輔助洞察',
    generated: '產生時間', calculating: '正在依已發布資料計算…', loadingOverview: '正在載入 {name} 青年概覽…', overviewUnavailable: '無法取得概覽',
    noCharts: '尚無圖表', noChartsAnswer: '此答案沒有產生視覺化。證據不足或不支援的回答不會產生圖表。', noChartsPrompt: '請在左側提問，後端回傳的圖表與表格會顯示在這裡。',
    chartNote: '圖表類型、欄位與數值皆由後端決定；此面板只負責呈現，不會重新計算排名、變化或百分比。',
    noImpact: '尚無影響鏈', noImpactDetail: '請在對話中提出情境假設問題，助理會在此建立並稽核影響鏈。',
    noCitations: '沒有引用', noCitationsDetail: '只有依已發布資料集產生的答案才會顯示引用。',
    noTrace: '沒有執行紀錄', noTraceDetail: '此處會列出系統實際呼叫的工具及其回傳結果。',
    version: '版本', retrieved: '擷取時間', dataUsed: '使用的資料', relevantRows: '{count} 筆相關資料',
    excerptHelp: '下方標示引用之已發布快照中的相關資料列。', location: '地點', field: '欄位', observed: '觀測時間', value: '數值', snapshot: '快照', noExcerpt: '此來源未提供可安全顯示於本答案的資料列摘錄。',
    impactChain: '情境影響鏈', confidence: '信心程度', capacity: '量能', needs: '需要', recommendation: '投資建議', withheld: '在所有必要的量能環節都有相容證據前，暫不提供建議。',
    showingRows: '顯示 {count} 筆選定資料', cited: '引用',
    sourceCandidates: '候選資料來源', sourceCandidatesIntro: '資料目錄缺少回答此問題所需的資料。這些來源已預先加入連接器白名單；提交的快照仍會經過與手動上傳相同的欄位對應、品質檢查與核准流程。',
    periodNotStated: '未註明期間', licenceNotStated: '未註明授權', reviewerIdentity: '審核者身分', submitting: '提交中…', submitSource: '擷取快照並提交審核', submissionFailed: '提交失敗，請重試。',
    submitted: '已提交 {candidate}。匯入工作 {job} 正等待核准；發布前請檢查欄位對應與品質報告。',
    districtOverview: '行政區概覽', latestPeriod: '最新發布期間', youthPopulation: '青年人口', ages: '18–35 歲', latestMovement: '最近變化', largestAge: '最大年齡層', districtYouthShare: '占該區青年人口 {value}%', notAvailable: '無資料',
    noPrior: '沒有前期資料', increasing: '增加', decreasing: '減少', stable: '持平', versus: '相較於',
    populationTrend: '青年人口趨勢', recentPeriods: '最近 {count} 個已發布期間的 18–35 歲人口。', shareByAge: '年齡占比', shareByAgeDetail: '最新青年人口在各年齡層的分布。', years: '歲', genderDistribution: '性別分布', genderDetail: '最新已發布期間的青年人口性別分布。',
    people: '人', yesNo: '是／否', points: '分', dataChart: '資料圖表',
    configInvalid: '前端 API 設定無效。', timeout: '請求已取消或超過 30 秒。', unexpected: '發生未預期的錯誤。',
  },
  en: {
    mapLabel: 'New Taipei district map', mapDistricts: 'New Taipei City districts', mapZoom: 'Map zoom', zoomIn: 'Zoom in', zoomOut: 'Zoom out', resetView: 'Reset view',
    mapAreaCited: '{name} District, {label} {value}', mapAreaPlain: '{name} District, not in this answer', notStated: 'not stated', rankLabel: 'rank {rank}', fromSource: 'from “{name}”',
    notInAnswer: 'Not part of the current answer.', viewOverview: 'View {name} population overview',
    mapHintCited: '{count} district(s) in this answer. Point at an area to read its figure.', mapHintEmpty: 'Point at a district to read it, or select one to ask about it.',
    mapCoverageNote: 'Covered {observed} of {expected} districts. No evidence for {names}, so those areas are unshaded rather than shown as zero.',
    mapUnplaceable: 'Not shown on the map: {names}. These entities are not New Taipei districts, and placing them would require a spatial join this answer does not provide.',
    mapAttribution: 'Boundaries: taiwan-atlas {edition}, simplified. Shading encodes the figure the backend returned for the current answer; grey areas are outside New Taipei City.',
    youthOverviewOf: '{name} youth overview', shareOfYouth: '{value}% of youth', agesOf: 'Ages {label}',
    genderRegistration: 'Published registration categories in {period}.',
    overviewFooter: 'Published dataset {dataset} · version {version} · quality {quality}%. Values use the {scope} population scope.',
    sourceCandidatesLabel: 'Available source candidates',
    askForSource: 'I need data the catalog does not hold yet. Shall I fetch a snapshot from one of these official sources and send it for review?',
    thinkingReading: 'Reading the published catalog…', thinkingRetrieving: 'Retrieving qualifying observations…',
    thinkingComputing: 'Calculating from published data…', thinkingChecking: 'Checking whether the evidence is enough…',
    asideSourceSearch: 'the assistant checks the allowlisted official sources',
    skip: 'Skip to conversation', brand: 'Youth Compass', tagline: 'New Taipei · decision assistant', tools: 'Tools',
    language: 'Language', traditionalChinese: '繁體中文', english: 'English',
    switchView: 'Switch view', conversation: 'Conversation', chartsEvidence: 'Charts & evidence',
    assistantLabel: 'Policy decision assistant', introTitle: 'New Taipei Youth Compass',
    intro: 'Every answer is drawn from approved, published datasets. The system performs retrieval, filtering, and calculation; the language model only interprets the question and states the result. It cannot invent a figure, pick a dataset, or write a query.',
    availableDatasets: 'Data you can ask about', publishedOnly: 'Published only', loadingCatalog: 'Loading the published catalog…',
    noDatasets: 'No published dataset is currently available.', breakdowns: 'Breakdowns', quality: 'Quality', tryAsking: 'Try asking',
    pending: 'Retrieving published data and calculating…', questionPlaceholder: 'e.g. Compare the youth population trend by district from 2023 to 2025',
    question: 'Question', composerHint: 'Enter to send · Shift+Enter for a new line', cancel: 'Cancel', send: 'Send',
    dataLimitations: 'Data limitations', assumptions: 'Assumptions', limitations: 'Limitations',
    publishedToday: 'published today', publishedDaysAgo: 'published {count} days ago', coverage: 'Covers {observed} of {expected} districts.', noGaps: 'No gaps.', noEvidenceFor: 'No evidence for {names}.', outsideDistricts: 'Outside the district set: {names}.',
    noCitationWarning: 'This answer carries no citation. Confirm with the backend before acting on it.', showSource: 'Show source {number}: {name}',
    basisRegistered: 'Registered household population (戶籍人口)', basisResident: 'Usual residents (常住人口)', basisUnknown: 'Population basis not recorded',
    answered: 'Answered from published data', insufficient: 'Insufficient evidence', sourceRequired: 'Source required', unsupported: 'Unsupported question',
    answeredDetail: 'Every figure comes from an approved, published dataset and carries its citation.', insufficientDetail: 'The catalog holds too little qualifying evidence, so no recommendation is offered.', sourceRequiredDetail: 'The catalog is missing the data this question needs. Submit one configured source for review.', unsupportedDetail: 'No registered tool can answer this. The system will not assemble a partial answer.',
    charts: 'Charts', map: 'Map', impact: 'Impact', evidence: 'Evidence', trace: 'Trace', insightViews: 'Insight views', supportingInsight: 'Supporting insight', generated: 'Generated', calculating: 'Calculating from published data…', loadingOverview: 'Loading {name} youth overview…', overviewUnavailable: 'Overview unavailable',
    noCharts: 'No charts yet', noChartsAnswer: 'This answer produced no visualization. Insufficient-evidence and unsupported answers deliberately return none.', noChartsPrompt: 'Ask a question on the left. Charts and tables returned by the backend appear here.', chartNote: 'The backend decides the chart type, the fields, and every value. This panel only draws them; it never recalculates a ranking, a change, or a percentage.',
    noImpact: 'No impact chain yet', noImpactDetail: 'Ask a what-if question in the conversation. The agent will build and audit the chain here.', noCitations: 'No citations', noCitationsDetail: 'Citations appear only when an answer is drawn from published datasets.', noTrace: 'No trace', noTraceDetail: 'This lists the tools the system actually called and what each returned.',
    version: 'Version', retrieved: 'retrieved', dataUsed: 'Data used', relevantRows: '{count} relevant row(s)', excerptHelp: 'Relevant rows from the cited published snapshot are highlighted below.', location: 'Location', field: 'Field', observed: 'Observed', value: 'Value', snapshot: 'Snapshot', noExcerpt: 'This source does not provide a safe row-level excerpt for this answer.',
    impactChain: 'Scenario impact chain', confidence: 'Confidence', capacity: 'capacity', needs: 'Needs', recommendation: 'Investment recommendation', withheld: 'Withheld until every required capacity link has compatible evidence.', showingRows: 'Showing {count} selected rows', cited: 'Cited',
    sourceCandidates: 'Source candidates', sourceCandidatesIntro: 'The catalog is missing the data this question needs. These sources are pre-configured in the connector allowlist. A submitted snapshot goes through exactly the same mapping, quality, and approval steps as a manual upload.', periodNotStated: 'Period not stated', licenceNotStated: 'licence not stated', reviewerIdentity: 'Reviewer identity', submitting: 'Submitting…', submitSource: 'Fetch snapshot and submit for review', submissionFailed: 'Submission failed. Try again.', submitted: 'Submitted {candidate}. Ingestion job {job} is awaiting approval. Review the field mapping and quality report before approving publication.',
    districtOverview: 'District overview', latestPeriod: 'Latest published period', youthPopulation: 'Youth population', ages: 'ages 18–35', latestMovement: 'Latest movement', largestAge: 'Largest age group', districtYouthShare: '{value}% of district youth', notAvailable: 'Not available', noPrior: 'No prior period', increasing: 'Increasing', decreasing: 'Decreasing', stable: 'Stable', versus: 'vs', populationTrend: 'Youth population trend', recentPeriods: 'Most recent {count} published periods for residents aged 18–35.', shareByAge: 'Share by age', shareByAgeDetail: 'How the latest youth population divides across age groups.', years: 'years', genderDistribution: 'Gender distribution', genderDetail: 'Youth population by gender in the latest published period.',
    people: 'People', yesNo: 'Yes / No', points: 'Points', dataChart: 'Data chart', configInvalid: 'The frontend API configuration is invalid.', timeout: 'The request was cancelled or timed out after 30 seconds.', unexpected: 'An unexpected error occurred.',
  },
} as const

export type MessageKey = keyof typeof messages.en
type Replacements = Record<string, string | number>

export function translate(language: Language, key: MessageKey, replacements: Replacements = {}): string {
  let value: string = messages[language][key]
  for (const [name, replacement] of Object.entries(replacements)) {
    // split/join, not replaceAll: the project's TS target is ES2020.
    value = value.split(`{${name}}`).join(String(replacement))
  }
  return value
}

const I18nContext = createContext<Language>('zh-TW')

export function I18nProvider({ language, children }: { language: Language; children: React.ReactNode }) {
  return <I18nContext.Provider value={language}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const language = useContext(I18nContext)
  return { language, t: (key: MessageKey, replacements?: Replacements) => translate(language, key, replacements) }
}
