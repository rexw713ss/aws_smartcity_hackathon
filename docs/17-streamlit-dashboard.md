# Temporary Streamlit Dashboard

> Status: local demo interface implemented

## Purpose

This interface is a disposable but functional reviewer/dashboard client for the
offline reference runtime. It validates the product flow before the final frontend
and AWS integration are available. It talks only to the public FastAPI contract, so
the UI does not know whether storage and analytics are backed by local adapters or AWS.

## Run locally

Use two terminals from the repository root:

```bash
make local-api
make dashboard
```

Open `http://127.0.0.1:8501`. The API base URL can be changed from the sidebar or
with `YOUTH_COMPASS_API_URL`.

## Included flows

- API health and runtime status;
- published dataset catalog and quality overview;
- city summary and district comparison chart;
- CSV, TSV, Excel, JSON, line-delimited JSON, and text-based PDF table upload with an
  optional topic hint;
- inferred column mapping, confidence, and warnings;
- explicit human approval or rejection;
- post-publication quality counts.

For a short happy-path demo, upload `data/samples/population_demo.csv`, approve
the mapping, and use metric code `population_count` with period `2025`. To show
that bad data cannot silently alter the dashboard, upload
`tests/fixtures/employment_unfamiliar.csv` as a separate quarantine-path demo.

## Intentional limitations

- Metric code is temporarily typed by the reviewer because the catalog API does not
  yet expose a metric dictionary.
- The interface does not contain authentication; the reviewer identity is supplied
  as a visible demo field.
- Streamlit session state holds the active review job. Durable workflow state remains
  in SQLite through the backend.
- PDF scan OCR is not part of the local adapter yet. Image-only PDFs are rejected with
  guidance to use OCR or Amazon Textract.
- This interface can be replaced by the planned React dashboard without changing the
  backend contracts.
