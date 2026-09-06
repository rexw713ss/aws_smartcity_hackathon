# AWS Stage 2 Adapters

> Status: implemented. Deploys real AWS resources (per-use only, no always-on compute).
> Audience: every workstream. This is what the AWS adapters provide, which ports
> they implement, and how to rehearse the deployed data path.

## What this feature is

Stage 2 plugs real AWS services into the Stage 1 port Protocols. Five adapters
bound to the existing contract-test suite, a CDK data-lake stack, a Lambda
handler wrapping the existing transforms, and a Step Functions workflow adapter
with a human-approval callback. Everything runs under moto in CI at zero cost;
the real-account path is an opt-in rehearsal.

## Delivered artifacts

| Artifact | Path | Purpose |
|---|---|---|
| CDK DataStack | `infra/stacks/data.py` | Six S3 zone buckets, Glue DB, DynamoDB metadata table, two IAM roles |
| S3 ObjectStore | `adapters/aws/s3_store.py` | `put/get/list/exists` over S3 with SHA-256 checksums |
| Glue+DynamoDB Catalog | `adapters/aws/glue_catalog.py` | `register/get/search_compatible` with rollback via version pointer |
| Athena QueryEngine | `adapters/aws/athena_query.py` | Typed QuerySpec → SQL with allowlists and cost caps |
| EventBridge EventBus | `adapters/aws/eventbridge_bus.py` | `publish/subscribe` for the docs/08 audit vocabulary |
| StepFunctions Runner | `adapters/aws/step_functions_runner.py` | `start_ingestion/resume_after_approval` with approval pause |
| Lambda Transform | `adapters/aws/transform_lambda.py` | Calls existing `profile_csv` and `analyze_mapping`, byte-identical |
| DataStack tests | `tests/infra/test_data_stack.py` | CDK assertions for IAM separation, tags, deferred services |
| Contract bindings | `tests/contract/aws/` | One `register_*` factory per adapter, all under moto |
| Lambda test | `tests/integration/aws/test_transform_lambda.py` | Byte-identical output vs local CLI |

## How to verify

```bash
# Full suite including all adapter contract tests (free, no account)
make test

# Smoke test the AWS data path under moto (free)
make aws-smoke

# Synthesize the data stack alongside the budget stack
make aws-synth ENV=dev

# Check your real account's readiness
make aws-preflight
```

## IAM role separation

The CDK DataStack creates two roles:
- **Write_Role**: used by the ingestion workflow, can write to standardized/curated/forecasts/metadata
- **Copilot_Role**: read-only, explicitly denied `s3:PutObject` and `s3:DeleteObject` on curated paths

CDK assertion tests prove this separation at synthesis time.

## Contract suite coverage

Every adapter passes its port's Stage 1 contract suite with zero edits to any
contract class body:

| Port | Reference binding | AWS binding | Contract tests |
|---|---|---|---|
| ObjectStore | `reference` | `s3-moto` | 7 tests × 2 |
| DataCatalog | `reference` | `glue-ddb-moto` | 3 tests × 2 |
| QueryEngine | `reference` | `athena-moto` | 3 tests × 2 |
| EventBus | `reference` | `eventbridge-moto` | 2 tests × 2 |
| WorkflowRunner | `reference` | `sfn-moto` | 3 tests × 2 |

## What Stage 2 does not deliver

| Absent in Stage 2 | Arrives in |
|---|---|
| Bedrock ModelProvider adapter | Stage 3 |
| SageMaker ForecastService adapter | Stage 3 |
| AgentCore Runtime deployment | Stage 3 |
| MCP Gateway tool layer | Stage 3 |

## Cost model

All Stage 2 services are per-use: S3, Glue catalog, DynamoDB on-demand, Athena
per-byte-scanned, Lambda per-invocation, Step Functions per-transition, and
EventBridge per-event. Nothing runs when no one is ingesting or querying. The
Stage 1 budget alarms deploy first.

## Rehearsal

Before 9/12, rehearse on your personal account:
```bash
make hackathon-bootstrap ASSUME_YES=1
make aws-smoke
make aws-export
```
Total cost: single-digit dollars.
