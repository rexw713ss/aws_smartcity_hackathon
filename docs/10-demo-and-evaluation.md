# Demo and Evaluation Strategy

## 1. Demo objective

Prove that the platform can safely turn an unfamiliar public dataset into a new, traceable dashboard insight and combine that insight with a reproducible forecast.

The demo should not depend on live training, unrestricted model generation, or a fragile external data source.

## 2. Main scenario

### Initial state

The dashboard contains:

- youth population by district;
- historical trend;
- education and marriage profile where available;
- precomputed 12-month forecast;
- no employment-seeker metric.

### New file

Upload a held-out file such as:

```csv
stat_year,area,age_group,sex,job_seekers
115,板橋,15-19,M,1250
115,板橋,20-24,M,3420
115,板橋,25-29,M,2980
```

The fixture is illustrative. Final demo values must be clearly labeled synthetic unless they come from a documented public source.

### Expected system behavior

1. Store the original file and checksum.
2. Detect CSV structure and profile columns.
3. Propose:
   - `stat_year -> year_roc`;
   - `area -> district_name`;
   - `sex -> gender_code`;
   - `job_seekers -> metric` with unit `persons`;
   - `15-19 -> youth_weight 0.4`.
4. Display confidence, evidence, grain, and warnings.
5. Require human approval because this is a new topic.
6. Publish approved Parquet and catalog version.
7. Refresh the dashboard with the new metric.
8. Let the copilot compare districts and explain the new evidence.

## 3. Policy question

The demonstration question:

> If the city can review only three districts for youth support next year, which districts should be examined first and why?

The system should:

- retrieve historical youth population;
- retrieve the approved forecast;
- retrieve the newly onboarded metric when relevant;
- retrieve quality and scope metadata;
- return transparent ranking components;
- explain uncertainty and limitations;
- update the dashboard selection.

## 4. Demo screen sequence

### Screen 1 - City pulse

- KPI cards;
- 29-district map;
- latest period and data-quality status;
- top increasing/decreasing districts.

### Screen 2 - Upload and review

- file profile;
- source-to-target mapping table;
- before/after preview;
- grain and join recommendation;
- confidence and warning badges;
- approve/reject controls.

### Screen 3 - Updated insight

- new metric badge;
- affected dashboard card/chart;
- dataset version and source drawer;
- comparison with existing metrics at a safe grain.

### Screen 4 - Forecast and copilot

- actual versus forecast line;
- P10-P90 band;
- model metric and version;
- copilot answer, evidence, warnings;
- automatic district highlighting.

## 5. Failure scenario

Upload a second file with:

- unknown metric unit;
- duplicate key rows;
- total and detail rows mixed;
- an unresolved district value.

Expected behavior:

- job enters `awaiting_approval` or `quarantined`;
- field-level issues are visible;
- current published dashboard remains unchanged;
- copilot refuses to use the unpublished data;
- operator can reject the job.

## 6. Evidence to show judges

- raw source checksum and immutable path;
- structured mapping proposal;
- deterministic validation result;
- human approval event;
- curated schema and Parquet version;
- DuckDB/Athena-compatible query result;
- model version and backtest against baseline;
- agent tool trace at a safe action/evidence level;
- dashboard answer with provenance and uncertainty.

## 7. End-to-end acceptance tests

| ID | Scenario | Expected result |
|---|---|---|
| E2E-01 | Known-format population CSV | Auto maps canonical dimensions, requires publish approval according to policy |
| E2E-02 | Held-out employment CSV | Creates valid new-topic proposal without code change |
| E2E-03 | 15-19 age group | Applies 0.4 weight and estimated flag |
| E2E-04 | Unknown unit | Blocks publication |
| E2E-05 | Duplicate grain key | Blocks or requires deterministic deduplication rule |
| E2E-06 | Context-only income source | Never labels value youth-specific |
| E2E-07 | Copilot district comparison | Calls correct tools and includes evidence |
| E2E-08 | Forecast question | Returns model version, metric, and uncertainty |
| E2E-09 | Agent unavailable | Direct dashboard remains usable |
| E2E-10 | Training failure | Previous production forecast remains active |

## 8. Agent golden questions

- Which districts lost the largest share of youth population?
- Compare Shimen and Linkou from 2018 to 2025.
- Is the latest population year complete?
- Why is this district marked high priority?
- How accurate is the forecast?
- Which values are estimates rather than exact counts?
- Is district income the income of youth residents?
- What changed after the new employment file was published?
- Can this new dataset be joined directly with monthly population?
- Produce a one-page evidence summary for the selected districts.

## 9. Quantitative demo targets

| Measure | Target |
|---|---:|
| Held-out CSV to mapping proposal | < 30 seconds local target |
| Approved CSV to curated publication | < 2 minutes local target |
| Dashboard analytical API p95 | < 1 second on precomputed local data |
| Copilot first progress event | < 1 second |
| Copilot complete response | < 15 seconds, provider dependent |
| Mapping proposal schema validity | 100% after validation/retry |
| Required evidence present | 100% |
| Unsafe automatic publication in test set | 0 |

These are demo engineering targets, not production service-level objectives.

## 10. Presentation narrative

Suggested order:

1. Show that youth population change is geographically uneven.
2. Explain that current public data integration is manual and definitions conflict.
3. Upload an unfamiliar file.
4. Show AI-proposed mapping plus deterministic validation.
5. Approve and reveal the new insight.
6. Ask a policy question in the dashboard.
7. Show SageMaker-compatible forecast evidence and uncertainty.
8. Close with the offline-to-AWS architecture and human-control boundary.

## 11. Demo resilience checklist

- precompute forecast;
- cache city and district summaries;
- keep local deterministic mapping fallback;
- keep a fake-model mode for rehearsals/tests;
- store expected demo fixture checksum;
- prepare screenshots or recording;
- verify clean startup script;
- confirm ports are available;
- reset only generated demo state, never source data;
- rehearse failure path and recovery;
- verify no secrets appear on screen.
