# Product Vision

> Product: New Taipei Youth Policy (新北青策)
> Positioning: Adaptive youth data integration and policy decision-support platform

## 1. Problem statement

Youth-related statistics are distributed across central and local government organizations. Sources differ in format, schema, reporting period, geographic granularity, age definition, and terminology. A policy analyst currently has to discover datasets, interpret their fields, normalize them manually, and reconcile incompatible definitions before producing even a basic comparison.

The policy scope defines youth as people aged **18 through 35**. Existing datasets may instead provide single-year ages, ranges such as 15-19 and 35-39, or no age dimension at all. This makes a superficially simple question such as "which district needs more youth employment support next year?" difficult to answer responsibly.

The product addresses four connected problems:

1. **Discovery:** relevant data is difficult to find and understand.
2. **Harmonization:** fields, values, units, and definitions conflict.
3. **Relationship:** datasets cannot be joined safely without understanding their grain.
4. **Decision timing:** descriptive reports explain the past but do not forecast future demand.

## 2. Product promise

The platform allows a user to upload a new dataset or register an API source. It then:

1. profiles the source;
2. proposes a semantic mapping to the canonical data model;
3. applies deterministic normalization rules;
4. validates age, time, geography, units, grain, and duplicate risk;
5. requests approval when confidence is insufficient;
6. stores approved data in a curated analytical layer;
7. generates new cross-domain insights where valid;
8. refreshes or retrains forecasting assets when required;
9. updates the decision dashboard and policy copilot.

The desired outcome is summarized by:

> Move policy work from reviewing last year's reports to anticipating next year's needs.

## 3. Primary users

### 3.1 Policy analyst

Needs to locate trends, compare districts, validate evidence, and prepare policy briefs. The analyst values traceability and should be able to inspect how each number was produced.

### 3.2 Data steward

Uploads or registers new sources, reviews schema mappings, resolves low-confidence fields, and approves publication into the curated layer.

### 3.3 Department manager

Consumes a concise city overview, priority ranking, forecast, and explanation. The manager does not need to understand SQL or file formats.

### 3.4 Technical operator

Monitors ingestion jobs, failed validations, model versions, costs, latency, and access control.

## 4. Core user journeys

### 4.1 New dataset onboarding

1. A data steward uploads a CSV file.
2. The system displays detected encoding, delimiter, columns, types, sample rows, and likely topic.
3. The AI proposes mappings such as `stat_year -> year` and `area -> district_name`.
4. Deterministic validators confirm values against district, gender, calendar, and age dictionaries.
5. The system identifies the dataset grain and safe integration options.
6. The steward reviews warnings and approves or rejects the proposal.
7. The curated dataset is published with lineage and quality metadata.
8. The dashboard announces which metrics and insights became available.

### 4.2 District policy analysis

1. An analyst selects a district on the map.
2. The dashboard shows historical youth population, education and marriage profiles, and contextual indicators.
3. The analyst views a 12-month forecast with uncertainty.
4. The analyst asks the copilot to compare the district with another district.
5. The copilot calls approved data and forecast tools, verifies evidence, updates the visual filters, and produces a sourced explanation.

### 4.3 Resource prioritization

1. A manager asks which three districts should be reviewed first for a selected policy focus.
2. The system calculates a transparent ranking from allowlisted metrics.
3. The copilot explains the signals, forecast uncertainty, and missing evidence.
4. The manager exports a policy brief but retains final decision authority.

## 5. Product pillars

### Integrate

- Accept new sources without hardcoding a single schema.
- Preserve raw input and transformation lineage.
- Harmonize ROC/Gregorian year, district, gender, age group, education, and marriage categories.
- Detect whether the source should append to an existing fact table or create a new topic table.

### Predict

- Forecast youth population at a defined district-month grain.
- Compare learned models with simple baselines.
- Communicate uncertainty and backtest performance.
- Retrain only when data relevance and quality rules permit it.

### Act

- Make the dashboard the primary interface.
- Allow the copilot to query, compare, explain, and control dashboard state.
- Show data provenance and quality next to every important conclusion.
- Keep policy recommendations advisory and reviewable.

## 6. MVP scope

The MVP proves one complete vertical slice:

```text
Unknown CSV upload
  -> profiling
  -> mapping proposal
  -> deterministic validation
  -> human approval
  -> curated Parquet
  -> DuckDB query
  -> dashboard update
  -> forecast lookup
  -> grounded copilot explanation
```

The MVP supports:

- CSV upload;
- UTF-8/UTF-8-BOM and common delimiter detection;
- canonical time, district, gender, age, metric, and unit fields;
- schema mapping with confidence and evidence;
- quality report and quarantine state;
- human approval;
- Parquet publication;
- district-level dashboard;
- one forecasting target: monthly youth population;
- one LangGraph agent with data and forecast tools.

## 7. Explicit non-goals for MVP

- Perfect extraction from arbitrary scanned PDFs.
- Fully autonomous publication without confidence thresholds.
- Automatic causal claims from observational data.
- Support for arbitrary SQL generated by an LLM.
- Multi-agent collaboration.
- Real-time model retraining after every file upload.
- Production-scale tenancy, billing, or organization management.
- Replacing human policy judgment.

## 8. Product success criteria

The MVP succeeds when:

- a held-out CSV with unfamiliar headers can be processed without code changes;
- a valid mapping and quality report are generated in less than two minutes on a development machine;
- unsafe grain combinations are rejected or require review;
- approved data becomes queryable from the dashboard;
- the forecast beats or honestly reports failure against the baseline;
- the copilot never presents district-wide context as youth-specific data;
- every answer exposes evidence, period, source, and uncertainty;
- the full demo can recover gracefully from a deliberately invalid file.

## 9. Demo narrative

The initial dashboard contains youth population, education, and marriage data. A data steward uploads a new employment CSV whose headers and categories differ from the existing model. The system recognizes ROC year, normalizes district and gender labels, assigns partial youth overlap to the 15-19 group, identifies its grain, and requests approval. After approval, a new employment context appears on the dashboard. The policy copilot compares Shimen and Linkou, combines historical metrics with the SageMaker-compatible forecast output, and explains two different policy responses with clear limitations.

This demonstrates that the product is not a static dashboard or a generic chatbot. It is a controlled data-to-decision workflow.
