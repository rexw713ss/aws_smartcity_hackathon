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
- CLI profile command;
- minimal FastAPI health endpoint;
- generated canonical JSON Schemas;
- unit and integration test suite.

Not implemented yet:

- mapping proposal engine;
- transformation pipeline and curated Parquet publication;
- approval workflow;
- DuckDB catalog/query adapter;
- forecasting;
- LangGraph agent;
- AWS adapters.

## Offline and AWS boundary

Current code must run without internet, an LLM, or AWS credentials. The future LLM implementation will use Amazon Bedrock through the `ModelProvider` port. Deterministic rules remain the source of truth for validation and transformation.
