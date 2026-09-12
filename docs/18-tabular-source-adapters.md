# Tabular Source Adapters

> Status: CSV, Excel, JSON, and text-based PDF tables implemented in the offline reference runtime

## Purpose

The source adapter separates file decoding from the existing ingestion workflow.
Every supported source is converted to a UTF-8 CSV staging object, then processed
by the same profiler, deterministic mapping, quality gate, human approval, and
Parquet publication code.

```text
original CSV / TSV / XLSX / XLSM / JSON / JSONL / NDJSON / PDF
                              |
                      SourceAdapter port
                              |
                   normalized UTF-8 CSV staging
                              |
            profile -> mapping -> approval -> quality -> Parquet
```

The application depends on the `SourceAdapter` protocol. The offline composition
root uses `LocalTabularSourceAdapter`; a future AWS adapter can normalize objects
with Lambda or Glue without changing the workflow.

## Supported formats

| Source | Extensions | Decoder | Policy |
|---|---|---|---|
| Delimited text | `.csv`, `.tsv` | Existing streaming CSV profiler | Original bytes pass through unchanged |
| Excel | `.xlsx`, `.xlsm` | `openpyxl` read-only/data-only mode | First visible sheet is imported; multiple sheets produce a reviewer warning |
| JSON records | `.json` | Python JSON decoder | Accepts an array, one object, or `data`/`records`/`results`/`items` wrapper |
| Line-delimited JSON | `.jsonl`, `.ndjson` | Python JSON decoder | Each non-empty line must contain one object |
| PDF table | `.pdf` | `pdfplumber` | Extracts text-based tables, merges tables with the same header, and requires reviewer verification |

Nested JSON objects and arrays are retained as compact deterministic JSON strings
inside a cell. The adapter rejects scalar arrays, empty inputs, invalid encodings,
more than 512 fields, and more than 500,000 source records.

Legacy `.xls` is intentionally rejected because `openpyxl` does not support the
binary format. Add a dedicated adapter such as `python-calamine` only when a real
source requires it.

PDF support deliberately targets digitally generated documents whose tables contain
extractable text. It uses ruled-line detection first and text alignment as a fallback.
The first usable table defines the staging schema; compatible tables across pages are
merged, while tables with different headers are skipped and reported as reviewer
warnings. PDF extraction is heuristic, so approval must include a check of column and
cell boundaries.

Scanned/image-only PDFs are not silently accepted. They return a stable 422 error with
an explicit requirement for OCR or Amazon Textract. Narrative PDFs with no detectable
table, encrypted PDFs, and malformed PDFs are also rejected before a workflow job can
be created. OCR remains a separate adapter because its confidence scores and review
requirements differ materially from text-table extraction.

## Lineage and safety

- The object store preserves the original uploaded bytes under an immutable
  checksum-addressed key.
- Normalized CSV is stored separately under the standardized prefix.
- Dataset lineage and version metadata retain the SHA-256 of the original file,
  not the staging CSV.
- Source format and adapter warnings are saved in the durable workflow checkpoint
  and exposed to the reviewer API.
- Unsupported or malformed formats return a stable 422 API error and never create
  a publishable version.

## Local test

The Streamlit uploader accepts every implemented extension. For a JSON happy path,
upload `data/samples/population_demo.json`, approve the proposal, then query metric
`population_count` for period `2025`. A text-based PDF table follows the same flow and
shows an extraction warning before approval.

Run the focused verification suite:

```bash
uv run pytest tests/unit/test_source_adapter.py \
  tests/integration/test_local_ingestion_workflow.py \
  tests/integration/test_reviewer_dashboard_api.py -q
```

## AWS migration

Keep the same port and response contract. Replace only the implementation:

- read originals from S3;
- use Lambda for small files or Glue for large files;
- use Amazon Textract `TABLES` analysis for scanned PDFs and preserve block-level
  confidence for reviewer inspection;
- write normalized staging objects and curated Parquet back to S3;
- preserve the original object version ID, ETag, and SHA-256 in lineage metadata.
