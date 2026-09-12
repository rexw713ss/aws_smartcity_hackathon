# 清理後資料

> 新的產品、離線架構、Agentic AI、資料契約及實作計畫請參閱 [`docs/README.md`](./docs/README.md)。
>
> 注意：共用欄位不代表原始主題表可以直接 JOIN。跨主題分析前必須先對齊時間、地理與人口維度的粒度，詳見 [`docs/02-data-architecture.md`](./docs/02-data-architecture.md)。

由 `data/raw/` 原始檔清理而來。各主題盡量共用同一組欄位命名，但必須先聚合到相容粒度後才能 JOIN。

| 主題 | 列數 | 檔案 | 年度數 | 說明 |
|---|---|---|---|---|
| `08_新北市全集` | 49,222 | 40 | 39 | D14：開放平臺 211 個統計表（⚠️欄位名稱為 field1/itemvalue2，需對照統計年報） |

## 共用欄位

`民國年, 月, 區代碼, 行政區, 年齡標籤, 年齡下限, 年齡上限, 青年關係, 青年權重, 性別, <主題維度>, 人數`

## 三張對照表（命題「定義衝突」的解法）

- `data/source/_年齡對照表.csv` —— 各來源年齡標籤 → 數值區間 + 青年權重。ODRP052 用半形 `~`、ODRP068 用全形 `～`，兩種都已吃下
- `data/source/_教育程度對照表.csv` —— 「大畢」↔「大學畢業」
- `data/source/_婚姻狀況對照表.csv` —— 民107前 4 值 ↔ 民108後 7 值（同婚拆分）

## 怎麼取青年

```python
df[df.青年關係 == '完全落入'].人數.sum()                    # 保守
(df[df.青年關係 != '不相關'].人數 * df.青年權重).sum()      # 含加權推估
```

## Offline backend quick start

The backend uses Python 3.12 and `uv`:

```bash
uv sync --python 3.12 --all-groups
uv run youth-compass profile \
  data/source/01_人口/_全部年度_全區.csv \
  --output /tmp/population-profile.json
uv run youth-compass-local submit \
  tests/fixtures/employment_unfamiliar.csv \
  --submitted-by local-uploader
uv run pytest
```

See [`docs/11-development-guide.md`](./docs/11-development-guide.md) for all development commands.

## Temporary Streamlit dashboard

Run the API and dashboard in two terminals:

```bash
make demo-features
make local-api
make dashboard
```

Then open `http://127.0.0.1:8501`. The interface supports the full local demo:
upload CSV, Excel, JSON, or a text-based PDF table, inspect its proposed mapping,
approve or reject it, query published district aggregates, and run grounded home-buying
or EV-charger rankings through the Decision copilot tab. The same copilot can inspect and
compare trends in published canonical datasets without a new feature mart. Decision rankings
require an immutable `data/features/current.parquet` snapshot. Scanned PDFs remain a later
OCR/Amazon Textract integration.
