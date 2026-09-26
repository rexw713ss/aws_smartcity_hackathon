import type { Language } from './i18n'

// Exact display aliases only. Never translate API keys, source values or IDs in
// requests. Unknown vocabulary remains visible for audit and future extension.
const chineseLabels: Record<string, string> = {
  population: '人口', education: '教育', employment: '就業', unemployment: '失業',
  marriage: '婚姻', migration: '遷徙', income: '所得', housing: '住宅',
  transport: '交通', public_services: '公共服務', household_registration: '戶籍',
  birth_events: '出生與生育', others: '其他',
  population_count: '人口數', employment_count: '就業人數', unemployment_count: '失業人數',
  unemployment_rate: '失業率', youth_population: '青年人口',
  year: '年', year_roc: '民國年', year_gregorian: '西元年', month: '月',
  district: '行政區', district_code: '行政區代碼', district_name: '行政區名稱',
  age_label_original: '原始年齡標籤', age_lower: '年齡下限', age_upper: '年齡上限',
  gender_code: '性別代碼', gender: '性別', metric_code: '指標代碼', unit_code: '單位代碼',
  source_row_number: '來源資料列', source_sha256: '來源雜湊值', dataset_id: '資料集識別碼',
  dataset_version: '資料集版本', mapping_version: '對應版本', transformation_version: '轉換版本',
  dataset_role: '資料集角色', period_start: '期間起始', period_granularity: '時間粒度',
  city_code: '縣市代碼', city_name: '縣市名稱', geography_granularity: '地理粒度',
  youth_relationship: '青年關係', youth_weight: '青年權重', is_estimated: '是否為推估值',
  gender_label_original: '原始性別標籤', education_code: '教育程度代碼', education_order: '教育程度順序',
  graduation_status: '畢業狀態', marital_status_code: '婚姻狀態代碼', same_sex_marriage: '同性婚姻',
  direction: '遷徙方向', counterpart_region: '對應地區', initial_registration_reason: '初設戶籍原因',
  event_code: '事件代碼', marriage_type: '婚姻類型', source_topic: '來源主題',
  source_agency: '來源機關', source_dataset_name: '來源資料集名稱', source_record_id: '來源紀錄識別碼',
  metric_value: '指標數值', metric_value_original: '原始指標數值', aggregation_method: '聚合方式',
  value: '數值', period: '期間', topic: '主題', population_scope: '人口範圍',
  youth_specific: '青年人口', all_ages: '全年齡人口', age_specific: '特定年齡人口',
  district_context: '行政區背景資料', general_population: '一般人口', context: '背景資料',
  total_population: '總人口', registered_population: '戶籍人口', usual_residents: '常住人口',
  pending: '待處理', running: '處理中', awaiting_approval: '等待核准',
  approved: '已核准', published: '已發布', rejected: '已拒絕', quarantined: '已隔離',
  failed: '失敗', succeeded: '成功', success: '成功', completed: '已完成',
  ok: '成功', empty: '空值', error: '錯誤', skipped: '已略過', blocked: '已阻擋',
  insufficient_data: '資料不足', unsupported: '不支援', not_found: '未找到',
  received: '已接收', unavailable: '無法取得', no_match: '沒有符合結果', data_gap: '資料缺口',
  clarification: '需要釐清', degraded: '使用備援', candidates: '找到候選來源', applied: '已套用',
  fact: '事實資料', dimension: '維度資料', reference: '參考資料',
  integer: '整數', float: '小數', string: '文字', boolean: '布林值', date: '日期', mixed: '混合型別',
  sum: '加總', mean: '平均', average: '平均', count: '計數', min: '最小值', max: '最大值',
  first: '第一筆', last: '最後一筆', none: '無', unknown: '未知',
  parse_year: '解析年份', parse_compact_date: '解析日期', parse_month: '解析月份',
  normalize_district_code: '標準化行政區代碼', normalize_district: '標準化行政區',
  extract_district: '擷取行政區', parse_age_range: '解析年齡範圍',
  parse_integer: '解析整數', parse_float: '解析小數', normalize_gender: '標準化性別',
  normalize_education: '標準化教育程度', normalize_graduation_status: '標準化畢業狀態',
  normalize_marital_status: '標準化婚姻狀態', normalize_boolean: '標準化布林值',
  normalize_direction: '標準化遷徙方向', normalize_event: '標準化事件',
  normalize_marriage_type: '標準化婚姻類型', normalize_youth_relationship: '標準化青年關係',
  normalize_text: '標準化文字', mapping_warning: '欄位對應警告',
  search_tools: '尋找分析工具', search_catalog: '搜尋資料目錄', get_features: '取得分析特徵',
  rank_candidates: '候選方案排名', explain_lineage: '追溯資料來源', inspect_dataset: '檢查資料集',
  query_observations: '查詢觀測資料', compare_entities: '比較地區變化', join_observations: '整合觀測資料',
  forecast_metric: '取得指標推估', discover_sources: '尋找資料來源', acquire_source: '匯入資料來源',
  web_search: '搜尋網路', search_web: '搜尋網路', simulate_scenario: '模擬情境',
  assess_capacity: '檢查服務量能', recommend_investment: '提出投資建議',
  audit_completeness: '檢查完整性', compare_versions: '比較版本', validate_analysis_plan: '驗證分析計畫',
  validate_dataset_scope: '驗證資料範圍', inspect_temporal_coverage: '檢查時間涵蓋範圍',
  resolve_local_ontology: '解析地區與主題定義', conversation_context: '解析對話脈絡',
  discover_web_sources: '尋找網路資料來源', query_decomposer: '拆解問題',
  resolve_decision_profile: '解析決策設定', answer_composer: '整理回答',
  audit_limitations: '檢查資料限制', visualization_builder: '建立圖表', visualization_selector: '選擇圖表',
}

export function translatedLabel(value: string, language: Language): string | undefined {
  if (language !== 'zh-TW') return undefined
  const key = value.trim().toLowerCase().replace(/[\s-]+/g, '_')
  return Object.prototype.hasOwnProperty.call(chineseLabels, key) ? chineseLabels[key] : undefined
}

const toolDescriptions: Record<string, string> = {
  search_tools: '尋找符合分析目標、已登錄且有明確使用範圍的工具。',
  search_catalog: '查找已登錄的語意特徵與決策設定。',
  get_features: '取得不可變更的特徵快照及佐證資料。',
  rank_candidates: '依已登錄的限制、權重與計分規則排列候選方案。',
  explain_lineage: '將來源證據整理成附有資料集版本的引用。',
  inspect_dataset: '檢查欄位結構、指標清單、地理及時間涵蓋範圍。',
  query_observations: '執行經驗證的標準觀測資料唯讀查詢。',
  compare_entities: '依相容的資料計算地區變化。',
  join_observations: '依標準地區與期間鍵值整合已聚合的資料集。',
  forecast_metric: '取得已發布的推估、預測區間及模型來源。',
  discover_sources: '在白名單中尋找符合資料需求的外部來源。',
  acquire_source: '將選定來源的快照送入需要人工核准的匯入流程。',
  search_web: '搜尋公開網路資訊，並附上原始網址與摘要。',
  simulate_scenario: '依人口基準模擬指定行政區的青年人口變動。',
  assess_capacity: '檢查已發布的基礎設施量能資料是否足以支持影響評估。',
  recommend_investment: '僅在量能證據完整時排列投資方案。',
}

export function toolDescription(operation: string, original: string, language: Language): string {
  return language === 'zh-TW' ? toolDescriptions[operation] ?? original : original
}

const genders: Record<string, Record<Language, string>> = {
  male: { 'zh-TW': '男性', en: 'Male' }, female: { 'zh-TW': '女性', en: 'Female' },
  other: { 'zh-TW': '其他', en: 'Other' },
  total: { 'zh-TW': '合計', en: 'Total' }, unknown: { 'zh-TW': '未註明', en: 'Unknown' },
}

export function genderLabel(key: string, original: string, language: Language): string {
  return genders[key]?.[language] ?? original
}
