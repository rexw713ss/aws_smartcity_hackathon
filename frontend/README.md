# 新北青策｜React 前端

以對話為主的青年政策決策助理。左側提問，右側查看圖表、地圖、來源證據及工具執行紀錄；手機版透過「對話／圖表與證據」切換。

## 執行與檢查

在 `frontend/` 目錄執行：

```bash
npm ci
npm run dev
```

開啟 [http://127.0.0.1:5173](http://127.0.0.1:5173)。開發伺服器會把 `/api` 代理到 `http://127.0.0.1:8000`，可用 `YOUTH_COMPASS_API_ORIGIN` 指定其他後端。後端安裝、啟動與資料發布方式見 [專案 README](../README.md)。

```bash
npm run typecheck
npm run build
npm run test:e2e
```

Playwright 使用模擬 API，涵蓋桌面與手機尺寸，預設需要 Microsoft Edge。新語系測試可單獨執行：

```bash
npm run test:e2e -- tests/e2e/localization.spec.ts
```

## 繁體中文與英文

- 預設語言為 `zh-TW`，右上角可切換 `en`。偏好儲存在 `localStorage` 的 `youth-compass-language`；儲存空間無法使用時，仍可在當次頁面切換語言。
- `src/lib/i18n.tsx`：介面文案、頁面描述、錯誤提示與無障礙標籤。
- `src/lib/labels.ts`：已知主題、欄位、狀態、工具說明及性別分類的顯示字典。新增後端詞彙時，在這裡補上中文。
- `src/lib/format.ts`：數字、日期、單位與顯示標籤。中文日期呈現民國年及西元年對照。
- `src/lib/errors.ts`：依 HTTP 狀態、資料契約與連線錯誤顯示本地化訊息；後端提供的原始診斷仍保留。

語系只影響顯示，`population`、`district_code`、資料版本及審核決定等 API 鍵值不會翻譯。原始檔名、來源欄位、樣本內容及未知詞彙保留原文；審核欄位同時列出中文名稱與標準鍵值，方便查核。

提問會攜帶 `responseLanguage`。切換語言時，既有問答與圖表會按原始提問順序重新向後端取得，保留追問脈絡；若失敗會顯示錯誤並保留先前內容。這項功能需要後端連線，前端不自行改寫來源敘述或計算結果。

中文輸入法選字時按 Enter 不會送出；選字完成後按 Enter 傳送，Shift+Enter 換行。

## API 契約

前端以後端產生的 [`contracts/api/openapi.json`](../contracts/api/openapi.json) 為準。後端契約變更時，從根目錄執行 `uv run python scripts/export_openapi.py`，並檢查 `src/lib/copilot.ts`。

主要端點：

| 方法 | 路徑 | 用途 |
|---|---|---|
| `POST` | `/api/v1/copilot/query` | 取得有依據的答案 |
| `POST` | `/api/v1/copilot/query/stream` | 串流進度與答案 |
| `GET` | `/api/v1/copilot/capabilities` | 可使用的工具 |
| `GET` | `/api/v1/datasets` | 資料集目錄 |
| `POST` | `/api/v1/copilot/acquisitions` | 將指定來源送入審核流程 |
| `GET` | `/api/v1/districts/{code}/overview` | 行政區人口概覽 |
| `GET` | `/api/v1/districts/{code}/forecast` | 可選的人口推估 |

請求使用 camelCase（如 `entityIds`、`responseLanguage`），Copilot 回應領域契約使用 snake_case（如 `tool_trace`、`visualization_id`）。其他端點請依 OpenAPI 及客戶端型別處理。

前端不重新計算後端問答的排名、變化或百分比。`ChartView` 依後端回傳的圖表規格繪製，格式不符契約時拒絕顯示。答案以 React 純文字渲染，不執行模型輸出的 HTML。

## 資料審核

資料取得、檔案上傳或連結提交建立工作後，介面會進入審核工作區，顯示欄位對應、標準化前後樣本、信心程度及驗證問題。工作也能透過 `?review=<jobId>` 重新開啟。

核准後才會進行完整轉換及品質檢查；發布成功時更新資料目錄並重試原問題。拒絕不會改變已發布資料。審核權杖僅保留於目前頁面記憶體。

## 行政區地圖

地圖呈現新北市 29 區，僅替目前答案有數據的行政區上色。未涵蓋的行政區顯示為無資料，不以零值取代。

`src/lib/districts.ts` 以精確比對解析兩位數代碼（`01`）、中文名稱（`板橋區`）或英文 slug（`banqiao`）。`site-banqiao-station` 等地點 ID 不會被猜測成行政區。

字典由程式產生。後端字典或地圖更新後，從根目錄執行：

```bash
uv run python -m scripts.generate_district_dictionary
```

`tests/unit/test_district_dictionary.py` 會檢查生成結果。地圖的 `number` 依英文名稱排序，與後端行政區代碼不同，不可直接拿來關聯。

## 視覺設計與部署

視覺規範見 [`DESIGN.md`](DESIGN.md)，設計變數位於 `src/base.css`，元件樣式位於 `src/index.css`。採暖色紙面、深灰文字與橘色重點；支援深色主題及多組圖表色彩。英文字型使用 Space Grotesk 與 Inter，繁體中文使用 Noto Sans TC 及系統中文字型備援。

正式建置輸出到 `frontend/dist/`。AWS 網站發布時，從根目錄執行 `uv run python -m scripts.deploy_site --source frontend/dist`；部署腳本會注入 `window.YOUTH_COMPASS_API_BASE`。若未指定 `--source`，預設發布的是 `web/` 部署檢查頁。
