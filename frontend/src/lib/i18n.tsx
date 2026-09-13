import React, { createContext, useContext } from 'react'

export type Language = 'zh-TW' | 'en'

const messages = {
  'zh-TW': {
    missingTitle: '我還缺這些資料', missingIntro: '已發布的目錄不足以繼續回答，所以我先停在這裡，不做推測。',
    gapHousing: '住宅量能', gapTransport: '交通量能', gapPublicServices: '公共服務量能',
    neededMetrics: '需要的指標', neededTopics: '主題', neededPeriod: '期間',
    recommendTitle: '我的建議', recommendLead: '我找到一份應該合用的官方資料。要我去下載並處理嗎？',
    recommendNone: '白名單裡沒有相容的官方來源，所以我沒辦法自己去找。',
    recommendProcess: '下載後會經過欄位對應與品質檢查，要有人核准才會發布。',
    otherSources: '改用其他來源（{count}）', accept: '接受，開始處理', reject: '拒絕', provideOwn: '自行提供資料',
    rejected: '好，我不會下載這份來源。', ownTitle: '或由你自己提供資料',
    uploadTab: '上傳檔案', linkTab: '貼上連結', chooseFile: 'CSV、JSON 或 Excel，最大 {size}',
    uploadSubmit: '上傳並處理', linkHosts: '只接受這些官方網域：{hosts}', linkDisabled: '這個環境沒有開放以連結提交資料。',
    linkSubmit: '下載並處理', linkInvalid: '請輸入以 https:// 開頭的連結。', fileTooLarge: '檔案超過 {size} 的上限。',
    working: '處理中…',
    intakeDone: '已送進處理流程：{name}。匯入工作 {job} 正在等待核准，發布後就能再問一次。',
    mapLabel: '新北市行政區地圖', mapDistricts: '新北市各行政區', mapZoom: '地圖縮放', zoomIn: '放大', zoomOut: '縮小', resetView: '重設檢視',
    mapAreaCited: '{name}，{label} {value}', mapAreaPlain: '{name}，不在此答案中', notStated: '未註明', rankLabel: '排名 {rank}', fromSource: '來源：「{name}」',
    notInAnswer: '不在目前的答案中。', viewOverview: '查看 {name} 人口概覽', viewSelectedOverview: '查看已選取的 {count} 個行政區',
    districtsSelected: '已選取 {count} 個行政區', selectedDistrictNames: '已選取的行政區', clearSelection: '清除選取', removeDistrict: '移除 {name}',
    mapHintCited: '此答案涵蓋 {count} 個行政區。將游標移到區域上即可讀取數值。', mapHintEmpty: '將游標移到行政區上可讀取資料，或點選一個行政區來提問。',
    mapCoverageNote: '涵蓋 {observed}/{expected} 個行政區。{names} 沒有證據，因此這些區域不上色，而不是顯示為零。',
    mapUnplaceable: '未顯示於地圖：{names}。這些實體不是新北市行政區，要標出位置需要此答案未提供的空間連結。',
    mapNoData: '無資料', mapScaleAria: '色階：{label}，由 {low} 到 {high}。顏色越深代表數值越高，灰色代表此答案沒有該區資料。',
    youthOverviewOf: '{name} 青年概覽', shareOfYouth: '占青年人口 {value}%', agesOf: '{label} 歲',
    genderRegistration: '{period} 已發布的登記類別。',
    overviewFooter: '已發布資料集 {dataset} · 版本 {version} · 品質 {quality}%。數值採用「{scope}」人口範圍。',

    thinkingReading: '正在讀取已發布的資料目錄…', thinkingRetrieving: '正在檢索符合條件的觀測資料…',
    thinkingComputing: '正在依已發布資料計算…', thinkingChecking: '正在檢查證據是否足以回答…',
    asideSourceSearch: '助理正在比對白名單中的官方資料來源',
    skip: '跳到對話', brand: '新北青策', tagline: '新北市 · 決策助理', tools: '工具',
    language: '語言', traditionalChinese: '繁體中文', english: 'English',
    switchView: '切換檢視', conversation: '對話', chartsEvidence: '圖表與證據',
    assistantLabel: '青年政策決策助理', introTitle: '新北青策',
    intro: '每個答案都取自經審核並發布的資料集。系統負責檢索、篩選與計算；語言模型只解讀問題並說明結果，不會虛構數字、擅自選擇資料集或撰寫查詢。',
    availableDatasets: '可詢問的資料', publishedOnly: '僅限已發布', loadingCatalog: '正在載入已發布資料目錄…',
    noDatasets: '目前沒有已發布的資料集。', breakdowns: '分類維度', quality: '品質', tryAsking: '試著詢問',
    pending: '正在檢索已發布資料並計算…', questionPlaceholder: '例如：比較 2023 至 2025 年各行政區的青年人口趨勢',
    question: '問題', composerHint: 'Enter 傳送 · Shift+Enter 換行', cancel: '取消', send: '傳送',
    dataLimitations: '資料限制', assumptions: '假設', limitations: '限制',
    publishedToday: '今天發布', publishedDaysAgo: '發布於 {count} 天前',
    coverage: '涵蓋 {observed}/{expected} 個行政區。', noGaps: '沒有缺口。', noEvidenceFor: '以下地區沒有證據：{names}。', outsideDistricts: '不在行政區集合內：{names}。',
    noCitationWarning: '此答案沒有引用來源，採取行動前請先向後端確認。', showSource: '顯示來源 {number}：{name}', openWebSource: '開啟網頁來源 {number}：{name}', openWebResult: '開啟原始網頁', published: '發布於',
    basisRegistered: '戶籍人口', basisResident: '常住人口', basisUnknown: '未記錄人口統計基準',
    answered: '依已發布資料回答', insufficient: '證據不足', sourceRequired: '需要資料來源', unsupported: '不支援此問題',
    answeredDetail: '每個數字都來自經核准、已發布且附有引用的資料集。',
    insufficientDetail: '目錄中的合格證據不足，因此不提供建議。',
    sourceRequiredDetail: '目錄缺少回答此問題所需的資料，請提交一個已設定的來源供審核。',
    unsupportedDetail: '目前沒有已登錄的工具可以回答，系統不會拼湊不完整的答案。',
    charts: '圖表', map: '地圖', impact: '影響', evidence: '證據', trace: '執行紀錄', insightViews: '洞察檢視', supportingInsight: '輔助洞察',
    generated: '產生時間', calculating: '正在依已發布資料計算…', loadingOverview: '正在載入 {name} 青年概覽…', overviewUnavailable: '無法取得概覽',
    noCharts: '尚無圖表', noChartsAnswer: '此答案沒有產生視覺化。證據不足或不支援的回答不會產生圖表。', noChartsPrompt: '請在左側提問，後端回傳的圖表與表格會顯示在這裡。',
    noImpact: '尚無影響鏈', noImpactDetail: '請在對話中提出情境假設問題，助理會在此建立並稽核影響鏈。',
    noCitations: '沒有引用', noCitationsDetail: '只有依已發布資料集產生的答案才會顯示引用。',
    noTrace: '沒有執行紀錄', noTraceDetail: '此處會列出系統實際呼叫的工具及其回傳結果。',
    version: '版本', retrieved: '擷取時間', dataUsed: '使用的資料', relevantRows: '{count} 筆相關資料',
    excerptHelp: '下方標示引用之已發布快照中的相關資料列。', location: '地點', field: '欄位', observed: '觀測時間', value: '數值', snapshot: '快照', noExcerpt: '此來源未提供可安全顯示於本答案的資料列摘錄。',
    impactChain: '情境影響鏈', confidence: '信心程度', capacity: '量能', needs: '需要', recommendation: '投資建議', withheld: '在所有必要的量能環節都有相容證據前，暫不提供建議。',
    showingRows: '顯示 {count} 筆選定資料', cited: '引用',
    periodNotStated: '未註明期間', licenceNotStated: '未註明授權', submissionFailed: '提交失敗，請重試。',
    districtOverview: '行政區概覽', latestPeriod: '最新發布期間', youthPopulation: '青年人口', ages: '18–35 歲', latestMovement: '最近變化', largestAge: '最大年齡層', districtYouthShare: '占該區青年人口 {value}%', notAvailable: '無資料',
    noPrior: '沒有前期資料', increasing: '增加', decreasing: '減少', stable: '持平', versus: '相較於',
    populationTrend: '青年人口趨勢', recentPeriods: '最近 {count} 個已發布期間的 18–35 歲人口。', shareByAge: '年齡占比', shareByAgeDetail: '最新青年人口在各年齡層的分布。', years: '歲', genderDistribution: '性別分布', genderDetail: '最新已發布期間的青年人口性別分布。',
    selectedDistrictOverview: '{count} 個行政區比較', rankedDistrict: '第 {rank} 名 · {name}', multiTrendDetail: '比較已選取的 {count} 個行政區；每 3 個月顯示一個觀測點，並保留最新月份。', relativePopulationTrend: '青年人口增減趨勢', relativeTrendDetail: '以各行政區第一個期間為 0%；每 3 個月顯示一點，依最新增減幅度排序。', trendDisplay: '趨勢顯示方式', changePercent: '增減幅度', absolutePopulation: '人口總數', overSelectedPeriod: '全期間', ageComparison: '青年年齡結構', ageComparisonDetail: '各行政區皆標準化為 100%，用來比較年齡結構而非人口規模。', genderComparison: '性別結構', genderComparisonDetail: '各行政區皆標準化為 100%，可直接比較性別比例。', multiOverviewFooter: '資料來源：{sources}。各數值保留其已發布資料集的定義。',
    people: '人', yesNo: '是／否', points: '分', dataChart: '資料圖表',
    configInvalid: '前端 API 設定無效。', timeout: '請求已取消或超過 90 秒。', unexpected: '發生未預期的錯誤。',
  },
  en: {
    missingTitle: 'Here is what I am missing', missingIntro: 'The published catalog does not hold enough to go further, so I stop here rather than guess.',
    gapHousing: 'Housing capacity', gapTransport: 'Transport capacity', gapPublicServices: 'Public service capacity',
    neededMetrics: 'Metrics needed', neededTopics: 'Topics', neededPeriod: 'Period',
    recommendTitle: 'What I suggest', recommendLead: 'I found an official source that should fit. Shall I download and process it?',
    recommendNone: 'No compatible official source is on the allowlist, so I cannot fetch this myself.',
    recommendProcess: 'Once downloaded it goes through field mapping and quality checks, and nothing is published until someone approves it.',
    otherSources: 'Use another source ({count})', accept: 'Accept and process', reject: 'Reject', provideOwn: 'Provide your own data',
    rejected: 'Understood. I will not download that source.', ownTitle: 'Or provide the data yourself',
    uploadTab: 'Upload a file', linkTab: 'Paste a link', chooseFile: 'CSV, JSON, or Excel, up to {size}',
    uploadSubmit: 'Upload and process', linkHosts: 'Only these official hosts are accepted: {hosts}', linkDisabled: 'Submitting data by link is not enabled here.',
    linkSubmit: 'Fetch and process', linkInvalid: 'Enter a link that starts with https://.', fileTooLarge: 'The file is larger than the {size} limit.',
    working: 'Working…',
    intakeDone: 'Sent for processing: {name}. Ingestion job {job} is waiting for approval; ask again once it is published.',
    mapLabel: 'New Taipei district map', mapDistricts: 'New Taipei City districts', mapZoom: 'Map zoom', zoomIn: 'Zoom in', zoomOut: 'Zoom out', resetView: 'Reset view',
    mapAreaCited: '{name} District, {label} {value}', mapAreaPlain: '{name} District, not in this answer', notStated: 'not stated', rankLabel: 'rank {rank}', fromSource: 'from “{name}”',
    notInAnswer: 'Not part of the current answer.', viewOverview: 'View {name} population overview', viewSelectedOverview: 'View {count} selected districts',
    districtsSelected: '{count} districts selected', selectedDistrictNames: 'Selected districts', clearSelection: 'Clear selection', removeDistrict: 'Remove {name}',
    mapHintCited: '{count} district(s) in this answer. Point at an area to read its figure.', mapHintEmpty: 'Point at a district to read it, or select one to ask about it.',
    mapCoverageNote: 'Covered {observed} of {expected} districts. No evidence for {names}, so those areas are unshaded rather than shown as zero.',
    mapUnplaceable: 'Not shown on the map: {names}. These entities are not New Taipei districts, and placing them would require a spatial join this answer does not provide.',
    mapNoData: 'No data', mapScaleAria: 'Colour scale for {label}, from {low} to {high}. Darker areas hold a higher figure; grey areas carry no data in this answer.',
    youthOverviewOf: '{name} youth overview', shareOfYouth: '{value}% of youth', agesOf: 'Ages {label}',
    genderRegistration: 'Published registration categories in {period}.',
    overviewFooter: 'Published dataset {dataset} · version {version} · quality {quality}%. Values use the {scope} population scope.',

    thinkingReading: 'Reading the published catalog…', thinkingRetrieving: 'Retrieving qualifying observations…',
    thinkingComputing: 'Calculating from published data…', thinkingChecking: 'Checking whether the evidence is enough…',
    asideSourceSearch: 'the assistant checks the allowlisted official sources',
    skip: 'Skip to conversation', brand: '新北青策', tagline: 'New Taipei · decision assistant', tools: 'Tools',
    language: 'Language', traditionalChinese: '繁體中文', english: 'English',
    switchView: 'Switch view', conversation: 'Conversation', chartsEvidence: 'Charts & evidence',
    assistantLabel: 'Policy decision assistant', introTitle: 'New Taipei Youth Policy',
    intro: 'Every answer is drawn from approved, published datasets. The system performs retrieval, filtering, and calculation; the language model only interprets the question and states the result. It cannot invent a figure, pick a dataset, or write a query.',
    availableDatasets: 'Data you can ask about', publishedOnly: 'Published only', loadingCatalog: 'Loading the published catalog…',
    noDatasets: 'No published dataset is currently available.', breakdowns: 'Breakdowns', quality: 'Quality', tryAsking: 'Try asking',
    pending: 'Retrieving published data and calculating…', questionPlaceholder: 'e.g. Compare the youth population trend by district from 2023 to 2025',
    question: 'Question', composerHint: 'Enter to send · Shift+Enter for a new line', cancel: 'Cancel', send: 'Send',
    dataLimitations: 'Data limitations', assumptions: 'Assumptions', limitations: 'Limitations',
    publishedToday: 'published today', publishedDaysAgo: 'published {count} days ago', coverage: 'Covers {observed} of {expected} districts.', noGaps: 'No gaps.', noEvidenceFor: 'No evidence for {names}.', outsideDistricts: 'Outside the district set: {names}.',
    noCitationWarning: 'This answer carries no citation. Confirm with the backend before acting on it.', showSource: 'Show source {number}: {name}', openWebSource: 'Open web source {number}: {name}', openWebResult: 'Open original page', published: 'Published',
    basisRegistered: 'Registered household population (戶籍人口)', basisResident: 'Usual residents (常住人口)', basisUnknown: 'Population basis not recorded',
    answered: 'Answered from published data', insufficient: 'Insufficient evidence', sourceRequired: 'Source required', unsupported: 'Unsupported question',
    answeredDetail: 'Every figure comes from an approved, published dataset and carries its citation.', insufficientDetail: 'The catalog holds too little qualifying evidence, so no recommendation is offered.', sourceRequiredDetail: 'The catalog is missing the data this question needs. Submit one configured source for review.', unsupportedDetail: 'No registered tool can answer this. The system will not assemble a partial answer.',
    charts: 'Charts', map: 'Map', impact: 'Impact', evidence: 'Evidence', trace: 'Trace', insightViews: 'Insight views', supportingInsight: 'Supporting insight', generated: 'Generated', calculating: 'Calculating from published data…', loadingOverview: 'Loading {name} youth overview…', overviewUnavailable: 'Overview unavailable',
    noCharts: 'No charts yet', noChartsAnswer: 'This answer produced no visualization. Insufficient-evidence and unsupported answers deliberately return none.', noChartsPrompt: 'Ask a question on the left. Charts and tables returned by the backend appear here.',
    noImpact: 'No impact chain yet', noImpactDetail: 'Ask a what-if question in the conversation. The agent will build and audit the chain here.', noCitations: 'No citations', noCitationsDetail: 'Citations appear only when an answer is drawn from published datasets.', noTrace: 'No trace', noTraceDetail: 'This lists the tools the system actually called and what each returned.',
    version: 'Version', retrieved: 'retrieved', dataUsed: 'Data used', relevantRows: '{count} relevant row(s)', excerptHelp: 'Relevant rows from the cited published snapshot are highlighted below.', location: 'Location', field: 'Field', observed: 'Observed', value: 'Value', snapshot: 'Snapshot', noExcerpt: 'This source does not provide a safe row-level excerpt for this answer.',
    impactChain: 'Scenario impact chain', confidence: 'Confidence', capacity: 'capacity', needs: 'Needs', recommendation: 'Investment recommendation', withheld: 'Withheld until every required capacity link has compatible evidence.', showingRows: 'Showing {count} selected rows', cited: 'Cited',
    periodNotStated: 'Period not stated', licenceNotStated: 'licence not stated', submissionFailed: 'Submission failed. Try again.',
    districtOverview: 'District overview', latestPeriod: 'Latest published period', youthPopulation: 'Youth population', ages: 'ages 18–35', latestMovement: 'Latest movement', largestAge: 'Largest age group', districtYouthShare: '{value}% of district youth', notAvailable: 'Not available', noPrior: 'No prior period', increasing: 'Increasing', decreasing: 'Decreasing', stable: 'Stable', versus: 'vs', populationTrend: 'Youth population trend', recentPeriods: 'Most recent {count} published periods for residents aged 18–35.', shareByAge: 'Share by age', shareByAgeDetail: 'How the latest youth population divides across age groups.', years: 'years', genderDistribution: 'Gender distribution', genderDetail: 'Youth population by gender in the latest published period.',
    selectedDistrictOverview: '{count}-district comparison', rankedDistrict: 'No. {rank} · {name}', multiTrendDetail: 'The {count} selected districts, sampled every 3 months with the latest month preserved.', relativePopulationTrend: 'Youth population change', relativeTrendDetail: 'Each district starts at 0%; points are shown every 3 months and ranked by the latest change.', trendDisplay: 'Trend display', changePercent: 'Change %', absolutePopulation: 'Population', overSelectedPeriod: 'over period', ageComparison: 'Youth age composition', ageComparisonDetail: 'Each district is normalised to 100%, revealing age structure rather than population size.', genderComparison: 'Gender composition', genderComparisonDetail: 'Each district is normalised to 100% so gender shares can be compared directly.', multiOverviewFooter: 'Sources: {sources}. Each value retains its published dataset definition.',
    people: 'People', yesNo: 'Yes / No', points: 'Points', dataChart: 'Data chart', configInvalid: 'The frontend API configuration is invalid.', timeout: 'The request was cancelled or timed out after 90 seconds.', unexpected: 'An unexpected error occurred.',
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
