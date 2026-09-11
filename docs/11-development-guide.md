# Local Development Guide

## Runtime

The approved runtime is **CPython 3.12**. The repository pins the minor version through `.python-version` and uses `uv` for Python installation, virtual environments, dependency resolution, locking, and command execution.

Do not create a separate `venv` with `python -m venv` and do not maintain a parallel `requirements.txt`.

## Setup

```bash
uv sync --python 3.12 --all-groups
```

This creates `.venv/` and installs the versions locked in `uv.lock`.

Verify:

```bash
uv run python --version
uv run youth-compass --help
```

## Profile a CSV

Full profile:

```bash
uv run youth-compass profile \
  data/source/01_人口/_全部年度_全區.csv \
  --output /tmp/population-profile.json
```

Development sample:

```bash
uv run youth-compass profile \
  tests/fixtures/employment_unfamiliar.csv \
  --max-rows 1000
```

The profiler:

- detects UTF-8, UTF-8 BOM, CP950/Big5, and common delimiters;
- streams rows instead of loading the entire CSV;
- calculates column types, nulls, bounded distinct values, samples, and numeric ranges;
- infers initial semantic roles;
- detects ROC/Gregorian year coverage;
- recognizes New Taipei districts;
- samples duplicate rows;
- warns about partial latest years and malformed rows;
- emits a Pydantic-validated JSON contract.

## Propose and validate a mapping

Run the offline deterministic mapper:

```bash
uv run youth-compass map \
  tests/fixtures/employment_unfamiliar.csv \
  --output /tmp/employment-mapping.json
```

For quick iteration on a large file:

```bash
uv run youth-compass map \
  data/source/01_人口/_全部年度_全區.csv \
  --max-rows 10000 \
  --output /tmp/population-mapping.json
```

Use `--topic <topic>` only when an operator intentionally overrides topic inference.

The output is one `MappingAnalysis` object containing:

- the source profile;
- a proposed topic, dataset role, grain, canonical column mappings, metrics, confidence, evidence, and warnings;
- deterministic validation issues with blocking status;
- a mandatory human-approval flag for the MVP.

The mapper uses exact normalized aliases and an allowlisted transformation registry. It does not execute model-generated code. Unknown units, missing required time/geography/metric dimensions, incompatible types, and unknown transformations block publication. Empty optional columns do not fail type validation because no value will be transformed.

## Transform and publish Parquet

Publication requires an explicit local reviewer identity:

```bash
uv run youth-compass transform \
  data/source/01_人口/_全部年度_全區.csv \
  --approved-by local-reviewer \
  --output /tmp/population-manifest.json
```

For a development-only sample, use `--max-rows`. The row limit becomes part of the immutable dataset version, so a sample can never be mistaken for a full publication:

```bash
uv run youth-compass transform \
  data/source/02b_教育程度_含年齡/_全部年度_全區.csv \
  --approved-by local-reviewer \
  --max-rows 10000
```

The command:

- profiles and validates the deterministic mapping before reading rows;
- executes only registered transformations;
- converts ROC years, districts, gender, age ranges, and known categories;
- retains source row number, checksums, mapping version, and transformation version;
- filters rows outside age 18-35 for youth-specific metrics;
- applies documented overlap weights to partially overlapping age bands;
- removes verified total rows from declared grain dimensions;
- writes compressed canonical Parquet in bounded batches;
- reopens Parquet and verifies schema and row count;
- rejects duplicate declared grain and excessive row errors;
- atomically publishes passing versions under `data/curated/`;
- writes failing versions and row diagnostics under `data/quarantined/`;
- reuses an identical immutable version on retry.

Each version directory contains `part-000.parquet`, `manifest.json`, `mapping-analysis.json`, and, when needed, `rejected-rows.parquet`. Generated runtime data remains ignored by Git.

## Run the API

```bash
uv run uvicorn apps.api.main:app --reload
```

Health endpoint:

```text
GET http://127.0.0.1:8000/health
```

## Quality commands

```bash
uv run ruff check .
uv run ruff format --check src apps tests scripts
uv run mypy src apps scripts
uv run pytest --cov=youth_compass --cov-report=term-missing
```

Format code intentionally with:

```bash
uv run ruff format src apps tests scripts
uv run ruff check . --fix
```

## Export canonical JSON Schemas

```bash
uv run python scripts/export_contracts.py
```

Generated schemas live in `contracts/canonical/`. Review their diffs whenever source Pydantic contracts change.

## Current implementation milestone

Implemented:

- Python/uv project bootstrap;
- validated YAML/environment configuration;
- canonical profile, mapping, metadata, and quality contracts;
- deterministic ROC year, district, gender, and age transformations;
- streaming generic CSV profiler;
- deterministic mapping proposal and validation engine;
- shared canonical field and transformation registries;
- deterministic row transformation and youth weighting;
- atomic versioned Parquet publication and quarantine;
- quality checks for row rejection, duplicate grain, empty output, and estimation;
- lineage-rich publication manifest and rejected-row diagnostics;
- CLI `profile`, `map`, and `transform` commands;
- minimal FastAPI health endpoint;
- generated canonical JSON Schemas;
- unit and integration test suite.

Not implemented yet:

- persisted approval workflow and reviewer UI;
- DuckDB catalog/query adapter;
- forecasting;
- LangGraph agent;
- AWS adapters.

## Offline and AWS boundary

Current code must run without internet, an LLM, or AWS credentials. The future LLM implementation will use Amazon Bedrock through the `ModelProvider` port. Deterministic rules remain the source of truth for validation and transformation.
