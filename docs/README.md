# New Taipei Youth Compass - Documentation

> Status: Architecture baseline approved on 2026-08-31  
> Last updated: 2026-08-31  
> Working language: Vietnamese; source field names remain in Traditional Chinese where useful.

This directory describes the proposed product and technical design for **New Taipei Youth Compass (新北青年羅盤)**. The documents intentionally separate the offline reference implementation from the future AWS deployment so the backend and AI work can progress before cloud integration begins.

## Product summary

New Taipei Youth Compass is an adaptive data-to-decision platform for youth policy. It accepts a new public dataset, profiles and maps its schema, validates its compatibility with existing data, integrates approved data into a curated analytical layer, updates forecasts, and presents grounded insights through a dashboard with an AI policy copilot.

The system has three core capabilities:

1. **Integrate:** onboard heterogeneous CSV, Excel, JSON, and text-based PDF tables,
   with API sources and scanned-PDF OCR on the roadmap.
2. **Predict:** forecast youth population trends with reproducible ML pipelines.
3. **Act:** expose evidence, uncertainty, and policy options through a dashboard and agentic assistant.

## Documentation map

| Document | Purpose |
|---|---|
| [00-product-vision.md](./00-product-vision.md) | Problem, users, product promise, scope, and demo narrative |
| [01-system-architecture.md](./01-system-architecture.md) | Offline-first architecture, AWS target architecture, component boundaries, and portability rules |
| [02-data-architecture.md](./02-data-architecture.md) | Canonical model, grains, metadata, partitions, and safe join rules |
| [03-ingestion-and-harmonization.md](./03-ingestion-and-harmonization.md) | End-to-end onboarding workflow, mapping proposal, validation, and approval states |
| [04-agentic-ai.md](./04-agentic-ai.md) | LangGraph design, tools, state, guardrails, model adapters, and agent evaluation |
| [05-forecasting-and-ml.md](./05-forecasting-and-ml.md) | Forecasting objective, baselines, SageMaker migration, model registry, and retraining rules |
| [06-backend-api.md](./06-backend-api.md) | Backend services, REST contracts, events, errors, and dashboard integration |
| [07-project-structure.md](./07-project-structure.md) | Proposed repository layout, package ownership, configuration, and coding boundaries |
| [08-quality-security-observability.md](./08-quality-security-observability.md) | Data quality, security, auditability, logging, tracing, and operational requirements |
| [09-implementation-plan.md](./09-implementation-plan.md) | Proposed phases, milestones, deliverables, dependencies, and acceptance criteria for approval |
| [10-demo-and-evaluation.md](./10-demo-and-evaluation.md) | Demo script, held-out test data, success metrics, and judging evidence |
| [11-development-guide.md](./11-development-guide.md) | Python 3.12/uv setup, CLI, API, quality commands, and current implementation status |
| [12-aws-stage1-foundation.md](./12-aws-stage1-foundation.md) | AWS Stage 1 foundation: ports, contract harness, CDK synth, verification scripts (deploys nothing) |
| [13-aws-stage2-adapters.md](./13-aws-stage2-adapters.md) | AWS Stage 2: real S3/Glue/Athena/EventBridge/StepFunctions adapters + CDK data stack |
| [14-aws-integration-review.md](./14-aws-integration-review.md) | Backend review findings and acceptance criteria for the AWS integration workstream |
| [15-local-ingestion-workflow.md](./15-local-ingestion-workflow.md) | Offline storage, approval, publication, persistence, and AWS replacement boundary |
| [16-reviewer-dashboard-api.md](./16-reviewer-dashboard-api.md) | Implemented FastAPI reviewer/catalog/dashboard routes and safe DuckDB analytics |
| [17-streamlit-dashboard.md](./17-streamlit-dashboard.md) | Temporary local UI for reviewer approval and district analytics |
| [18-tabular-source-adapters.md](./18-tabular-source-adapters.md) | Implemented CSV, Excel, JSON, and text-based PDF-table normalization boundary |
| [19-reusable-feature-and-decision-layer.md](./19-reusable-feature-and-decision-layer.md) | Reusable feature contracts, decision profiles, constraints, and deterministic scoring |
| [20-grounded-copilot.md](./20-grounded-copilot.md) | Grounded agent tools, decision planning, evidence citations, evaluation, and Bedrock seam |
| [21-api-deployment.md](./21-api-deployment.md) | Deployed API and static site: live URLs, frontend integration, write-token and CORS model, deploy commands, and what changed in shared code |
| [aws-architecture.md](./aws-architecture.md) | Full AWS architecture diagram: all services, data flow, security boundary |
| [aws-workstream-status.md](./aws-workstream-status.md) | Living status of the AWS integration lane: staged plan, cost model, and open decisions |

## Architecture decisions at a glance

| Concern | Offline reference | AWS target |
|---|---|---|
| Object storage | Local filesystem | Amazon S3 |
| Analytical format | Parquet | Parquet on S3 |
| Query engine | DuckDB | Amazon Athena |
| Catalog | SQLite/JSON metadata | AWS Glue Data Catalog |
| Workflow | Python/LangGraph orchestration | Step Functions plus AgentCore workflows |
| LLM | Ollama-compatible local provider | Amazon Bedrock |
| Agent framework | LangGraph | LangGraph on Bedrock AgentCore Runtime |
| Forecasting | Local XGBoost/PyTorch | Amazon SageMaker AI |
| API | FastAPI | API Gateway with Lambda or container runtime |
| Dashboard | React dashboard | React with optional embedded Amazon Quick/QuickSight |
| Observability | Structured logs and OpenTelemetry | CloudWatch and AgentCore Observability |

## Non-negotiable design rules

- Business logic must not import AWS SDK types directly.
- Parquet is the stable analytical interchange format in both environments.
- DuckDB and Athena are adapters behind a shared query interface.
- LLM output is a proposal, not an executable data transformation.
- All transformations are performed by allowlisted, deterministic functions.
- No raw cross-topic JOIN is allowed without compatible grain checks.
- Every published metric must retain source, time range, unit, transformation lineage, and quality status.
- Forecasts must include model version, backtest metric, horizon, and uncertainty interval.
- Policy recommendations remain advisory and require a human decision.

## Approval status

The owner approved the baseline architecture and [implementation plan](./09-implementation-plan.md) on 2026-08-31. Future implementation changes should keep these documents synchronized and return to an explicit review when they alter the MVP boundary, framework choices, data contracts, or division of responsibility between offline and AWS workstreams.
