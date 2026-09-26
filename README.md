# 新北青策｜青年政策決策助理

<p align="center">
  <img src="frontend/public/youth-compass-logo.png" width="160" height="160" alt="新北青策 Logo：雲端城市與向上羅盤" />
</p>

建構於 **AWS 雲端架構**的 Smart City Hackathon 專案，以新北市公開資料協助探索青年人口、教育、就業及政策情境。整合自然語言提問、圖表、29 個行政區地圖、資料來源追溯，以及需要人工核准的資料匯入流程。

**介面預設為繁體中文，可在右上角切換 English。** 本專案可以在本機執行；AWS 部署為選用流程。

Logo 以「雲端城市羅盤」為概念：雲形象徵 AWS 雲端基礎，城市輪廓代表新北，向上羅盤代表以資料引導青年政策。橘色與深藍呼應雲端科技的視覺語彙。詳見 [品牌識別與素材](docs/brand-identity.md)。

## 主要功能

- **有來源的問答**：從經審核、已發布的資料集檢索、篩選與計算，答案附有來源、版本及限制說明。資料不足時會指出缺口。
- **人口與跨主題分析**：查詢趨勢、比較行政區，並在時間、地理與人口粒度相容時整合不同主題。
- **地圖與圖表**：新北市 29 區地圖、人口概覽、年齡及性別分布、多區比較；有推估資料時，另外呈現預測區間與模型資訊。
- **資料匯入與人工審核**：上傳檔案或提交允許的官方來源，檢查 AI 建議的欄位對應、標準化樣本與驗證結果，再核准或拒絕發布。
- **繁體中文／英文**：介面文字、主題與範例問題、工具說明、審核狀態、常用欄位與單位、性別圖表標籤及應用程式錯誤訊息依語言選擇顯示。

## 本機快速開始

### 1. 準備環境

需要 Git、**Python 3.12**、[uv](https://docs.astral.sh/uv/) 與 **Node.js 22.12 以上**（建議 Node.js 24 LTS）。以下指令由專案根目錄開始執行，Windows PowerShell 也可直接使用。

```bash
git clone https://github.com/rexw713ss/aws_smartcity_hackathon.git
cd aws_smartcity_hackathon
uv sync --python 3.12 --all-groups
```

### 2. 啟動後端 API

```bash
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

API 文件：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

### 3. 啟動前端

另開終端機，從專案根目錄執行：

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

開啟 [http://127.0.0.1:5173](http://127.0.0.1:5173)。開發伺服器會把 `/api` 代理到 `http://127.0.0.1:8000`；若後端使用其他網址，可設定 `YOUTH_COMPASS_API_ORIGIN`。

### 4. 準備可查詢資料

剛複製專案時，本機可能還沒有已發布資料。API 啟動不代表原始檔已完成匯入；請經由資料匯入與審核流程發布資料，再進行問答。可用以下測試檔建立匯入工作：

```bash
uv run youth-compass-local submit tests/fixtures/employment_unfamiliar.csv --submitted-by local-uploader
```

使用回傳的工作 ID 開啟 `http://127.0.0.1:5173/?review=<jobId>`，檢查欄位對應並決定是否核准。完整資料準備方式見 [開發指南](docs/11-development-guide.md)。

購屋或充電樁決策排名另外需要特徵快照：

```bash
uv run python -m scripts.materialize_demo_features
```

這個指令產生 `data/features/current.parquet`，不會取代一般資料集的匯入與審核流程。人口推估則由 `uv run python -m ml.youth_population_forecast` 產生，需先具備該流程所需的資料。

## 中文使用方式

1. 右上角「語言」選擇「繁體中文」。第一次開啟預設為中文；之後會記住同一瀏覽器的選擇，重新整理也會保留。
2. 選擇「人口」、「教育」、「就業」或「其他…」，再點選範例問題或輸入自己的問題。
3. 切換語言時，前端會透過 `responseLanguage: "zh-TW"` 或 `"en"` 要求後端重新產生現有問答及圖表；需要後端正常運作。若更新失敗，會顯示提示並保留先前回答。
4. 中文日期使用民國年並保留西元年對照；數字與單位依語系格式化。中文輸入法選字時按 Enter 不會送出，完成選字後按 Enter 傳送；Shift+Enter 換行。

可嘗試的問題（是否能回答取決於已發布資料）：

> 比較 112 至 114 年（2023–2025）各行政區的青年人口趨勢。
>
> 三峽區的青年人口趨勢如何？
>
> 按性別比較人口。

使用者原始提問、來源檔名、資料集 ID、版本、原始欄位、網頁引用及後端診斷內容保留原文，方便核對來源。未知標籤不會被猜測翻譯。問答與圖表敘述由後端負責語言產生，前端不自行翻譯數值或重算結果。

## 檢查與測試

前端（在 `frontend/` 執行）：

```bash
npm run typecheck
npm run build
npm run test:e2e
```

端對端測試使用 Playwright 與模擬 API，涵蓋桌面及手機尺寸。預設使用已安裝的 Microsoft Edge；若電腦沒有 Edge，可執行 `npx playwright install msedge` 安裝，或依環境調整 `frontend/playwright.config.ts` 的瀏覽器設定。

後端（在專案根目錄執行）：

```bash
uv run pytest
uv run python -m scripts.run_agent_evals --suite all
uv run python -m scripts.benchmark_system
```

評估涵蓋工具路由、答案依據、引用、語言、限制、執行紀錄及視覺化。效能報告輸出到 `artifacts/reports/`，成本邊界見 [效能與成本說明](docs/32-performance-and-cost-metrics.md)。

## 專案結構

| 路徑 | 用途 |
|---|---|
| `frontend/` | React、TypeScript、Vite 前端與 Playwright 測試 |
| `apps/api/` | FastAPI API 與 Lambda 入口 |
| `apps/dashboard/` | 舊版 Streamlit 本機備援介面 |
| `src/youth_compass/` | 問答、資料契約、映射、品質檢查與分析邏輯 |
| `adapters/` | 本機與 AWS 服務介接 |
| `data/` | 原始資料、清理資料及執行時資料區 |
| `contracts/` | 標準資料與 OpenAPI 契約 |
| `infra/`、`scripts/` | AWS CDK、部署及資料處理工具 |
| `ml/`、`evals/`、`tests/` | 推估模型、Agent 評估及測試 |
| `docs/` | 產品、架構、資料治理及開發文件 |

## 資料定義與使用限制

共用欄位包含：`民國年, 月, 區代碼, 行政區, 年齡標籤, 年齡下限, 年齡上限, 青年關係, 青年權重, 性別, <主題維度>, 人數`。

**欄位名稱相同，不代表原始主題表可以直接 JOIN。** 跨主題分析前，必須先對齊時間、地理與人口維度；不同日曆的資料可能以各年最後觀測月對齊，答案會說明處理方式。

保留的清理資料說明：`08_新北市全集` 共 49,222 列、40 個檔案、39 個年度，來自 D14 開放平臺 211 個統計表；`field1`、`itemvalue2` 等原始欄位需對照統計年報。

定義對照表位於 `data/source/`：

- `_年齡對照表.csv`：來源年齡標籤、數值區間及青年權重。
- `_教育程度對照表.csv`：「大畢」與「大學畢業」等別名。
- `_婚姻狀況對照表.csv`：民國 107 年前後分類差異與同婚拆分。

```python
# 僅計算完全落入青年年齡範圍的資料
df[df.青年關係 == '完全落入'].人數.sum()
# 納入部分年齡區間的加權推估
(df[df.青年關係 != '不相關'].人數 * df.青年權重).sum()
```

兩者的定義不同，分析時應明確標示。更完整的來源與資料粒度說明見 [資料架構](docs/02-data-architecture.md)。

## AWS 部署（選用）

部署前請閱讀 [infra 說明](infra/README.md)，準備 AWS 帳號、權限、環境設定及預算。正式前端是 `frontend/`；`web/` 是靜態託管與 API 連線的部署檢查頁。

完成 API 與靜態網站基礎設施後，先在 `frontend/` 執行 `npm run build`，再回到根目錄發布：

```bash
uv run python -m scripts.deploy_site --source frontend/dist --env hackathon --region us-east-1
```

腳本會從 CloudFormation 讀取網站儲存桶與 API 網址、注入 `/api/v1` 設定、上傳網站並清除 CloudFront 快取。請明確指定 `--source frontend/dist`，省略時會發布 `web/` 部署檢查頁。

## 延伸文件

- [文件總覽](docs/README.md) · [前端說明](frontend/README.md) · [本機開發](docs/11-development-guide.md)
- [動態資料取得](docs/22-dynamic-data-acquisition.md) · [答案視覺化](docs/23-answer-visualizations.md) · [Athena 執行環境](docs/24-athena-agent-runtime.md)
- [對話脈絡](docs/26-conversation-context.md) · [多語地名與限制](docs/27-ontology-and-limitations.md) · [跨資料集分析](docs/29-multi-dataset-analysis.md)

舊版 Streamlit 備援介面可使用 `uv run streamlit run apps/dashboard/app.py --server.port 8501` 啟動；本文的中英文切換說明以 React 前端為準。
