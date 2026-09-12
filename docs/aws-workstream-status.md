# AWS Workstream — Status and Handoff

> Owner: AWS integration engineer
> Status: **Stages 1 and 2 complete and deployed. Generative AI (Bedrock) live. Ingestion pipeline verified end to end against the real account.**
> Last updated: 2026-09-12
> Audience: frontend, backend, and data-engineering teammates who need to know what the AWS lane provides today and what it still does not.

This is a living status document, not a design document. The numbered `docs/00-` through `docs/20-` files hold the approved architecture. This file records where the AWS workstream actually stands.

---

## 1. Status at a glance

| Item | State |
|---|---|
| Stage 1 — foundation (ports, contract harness, CDK app, scripts) | **Done**, merged |
| Stage 2 — AWS adapters (S3, Glue, Athena, EventBridge, Step Functions, DynamoDB) | **Done**, merged |
| PR1 — AWS orchestration infrastructure | **Done**, merged, deployed |
| PR2 — production ingestion workflow (durable state + real callback tokens) | **Done**, merged, deployed |
| Stage 3 — generative AI (Bedrock + grounded copilot) | **Done**, merged, live |
| Glue table registration on publish | **Done**, deployed, verified live |
| Forecasting ("Predict" pillar) | **Not implemented** — see section 5 |
| Real row-level transform in the deployed Lambda | **Not implemented** — see section 5 |
| Deployed stacks | Budget, Data, Workflow — all `UPDATE_COMPLETE` in `us-east-1` |
| Test suite | 588 passing, 1 skipped (opt-in real-AWS test) |
| Static checks | `ruff` clean, `ruff format` clean, `mypy --strict` clean (84 source files) |

---

## 2. Region change: Tokyo is not usable

**The project now runs in `us-east-1`, not `ap-northeast-1`.**

The hackathon account (`765996595659`, `WSParticipantRole`) blocks `ap-northeast-1` with a service control policy. This is not a configuration preference — calls to Tokyo fail outright:

| Region | Bedrock Converse result |
|---|---|
| `ap-northeast-1` | `AccessDeniedException` |
| `us-east-1` | Success |

Every adapter default, the model config, and `configs/aws.example.yaml` were switched to `us-east-1`. If you see `ap-northeast-1` anywhere in new code, it will fail on this account.

Still defaulting to Tokyo, deliberately left alone because they drive CDK deploys and were not in scope for a runtime fix: `scripts/aws_bootstrap.py`, `scripts/aws_export.py`, `scripts/aws_teardown.py`, and `infra/environments.py`. Pass `--region us-east-1` / `-c region=us-east-1` when using them, or change them as a separate decision.

---

## 3. What is deployed right now

Account `765996595659`, region `us-east-1`.

**Six S3 buckets** (versioned, public access blocked):
`youthcompasshackathon-{incoming,standardized,curated,quarantined,forecasts,metadata}-765996595659`

**Glue database:** `youth_compass_hackathon`

**DynamoDB:** `youthcompasshackathon-metadata` (on-demand)

**Lambdas:** `TransformFunction` (profiling, mapping, approval pause, publish) and `UploadEventFunction` (S3 event to workflow start)

**Step Functions Standard workflow:**
`arn:aws:states:us-east-1:765996595659:stateMachine:IngestionWorkflow29B06432-5XJBOuZbHvNw`

**Plus:** EventBridge rule on `incoming/` object-created events, and a Budgets stack that deploys before any data resource.

---

## 4. End-to-end verification against the real account

The full chain was run live, not mocked. Baseline before the run: **zero** Glue tables.

1. Presigned POST upload, exactly as a browser would do it → HTTP `204`
2. S3 EventBridge event → upload Lambda → **one** Step Functions execution
3. Execution `SUCCEEDED`
4. Curated object written to the curated bucket
5. Glue `EXTERNAL_TABLE` created, schema inferred from the source profile:
   `year bigint`, `district string`, `age_label string`, `population bigint`
6. **Athena query succeeded** — returned all three districts ordered by population, with the CSV header correctly excluded

This closes the PR2 Definition-of-Done item *"approval produces real curated objects and a Glue table"*, which previously was not met: the transform step copied the object to the curated zone but never registered it, so published data was not queryable.

Bedrock was separately verified with a real Converse call: Amazon Nova Lite answered a youth-policy question with token accounting reported.

### Two things that will bite you in a demo

**Uploads must go through the presigned API.** Dropping a file into the bucket with `aws s3 cp` or the console **will be rejected**. `verify_upload` requires `job-id` and `submitted-by` object metadata and a key shaped `incoming/job-<hex>/...`. This is intentional defence in depth, and it is working — but it means the console is not a valid upload path.

**`configs/aws.example.yaml` still ships `model_id: <PLACEHOLDER_...>`.** The copilot raises `ConfigurationError` unless it is replaced with a real model id (`amazon.nova-lite-v1:0`). Set it before demoing.

---

## 5. What is *not* implemented

Being explicit here, because two of these are easy to assume are done.

### 5.1 Forecasting — the "Predict" pillar does not exist

There is **no forecasting implementation at all**, local or AWS:

- `src/youth_compass/forecasting/` is an **empty directory**
- `adapters/local/` contains no forecast adapter
- `adapters/aws/` contains no SageMaker adapter
- The only `ForecastService` implementation is `tests/contract/reference/forecast_service.py`, registered as `reference` — a **test-only stub** that exists to exercise the contract suite

So the `ForecastService` port and its `ForecastRequest` / `ForecastResult` / `ForecastPoint` models are defined and contract-tested, but nothing implements them for production use.

SageMaker has been dropped by decision — local prediction is the agreed direction. That local implementation still needs to be written, and it is currently the largest missing piece of the product story. The architecture already anticipates the cheap path: ship the forecast as a **precomputed Parquet artifact** in the `forecasts/` bucket (per `docs/10` section 11) rather than training anything live.

### 5.2 The deployed transform does not transform rows

`adapters/aws/transform_lambda.py` `_transform` copies the source object into the curated or quarantined zone and registers the Glue table. It does **not** run the row-level canonical transformation (dimension normalisation, youth weighting, Parquet output, rejection thresholds).

That logic exists and is well tested — but in the **local** pipeline (`src/youth_compass/transformation/`), not in the Lambda. Consequence: curated output is the original CSV, not a transformed Parquet fact table. The publish/quarantine branch, the curated write, and catalog registration are all genuinely proven; the heavy transform is the gap.

### 5.3 API-role IAM for approval callbacks

Resuming a paused workflow needs `states:SendTaskSuccess` / `SendTaskFailure`. This works locally with developer credentials. A deployed API role has not been granted these permissions yet.

---

## 6. Architectural rules that still hold

The dependency direction from `docs/07` section 13 is intact and enforced by a test: **`src/youth_compass/` never imports `boto3`.** All AWS code lives in `adapters/aws/`. Swapping local for AWS is a configuration change, not a code change.

Adapters are selected by config (`configs/local.yaml` vs `configs/aws.example.yaml`). Every adapter satisfies the same contract suite as its local counterpart, so an adapter swap cannot silently change behaviour.

One deliberate exception worth knowing: the Lambda registers the Glue table directly rather than reusing the `GlueCatalog` adapter. That adapter writes a single `placeholder` column and requires a full `DatasetMetadata` object the Lambda does not have, so reusing it would have produced a worse schema.

---

## 7. Cost posture

No always-on compute is deployed. Everything is per-invocation or small storage: S3 objects (a few MB), an on-demand DynamoDB table, two Lambdas, a Standard workflow that suspends without charge while awaiting approval, and Bedrock billed per token.

Idle cost is a few cents per month. The money-burning resources — SageMaker endpoints and notebook instances, NAT Gateways, RDS, unassociated Elastic IPs — are **not** in the deployment, and creating any of them should be a deliberate, flagged decision.

Guardrails: the Budgets stack deploys before any data resource, `make aws-teardown` cleans up behind a confirmation prompt, and the preflight checker flags always-on resources it finds.

---

## 8. What other teams can rely on

**Can rely on now:** presigned browser uploads to S3, an S3 event starting exactly one workflow execution, job status surviving API and Lambda restarts (DynamoDB-backed), mapping proposals and quality reports through the existing API, approval producing real curated objects **and** a queryable Glue table, rejection producing no published data, and a working Bedrock model provider behind the `ModelProvider` port.

**Cannot rely on yet:** any forecast (section 5.1), transformed Parquet in the curated zone (section 5.2), and approval callbacks from a deployed API role (section 5.3).

**Frontend:** uploads must use the presigned API, not direct bucket writes. See section 4.

**Data engineering:** the forecast is still expected as a Parquet artifact under the `forecasts/` bucket. Keep `ml/` scripts path-argument driven and free of web-application imports.

**Backend:** Bedrock is wired and live. Set `model.model_id` before any deploy, and keep `model.region` at `us-east-1`.

---

## 9. Where the detail lives

- `docs/01-system-architecture.md` — ports, architectures, provider config
- `docs/07-project-structure.md` — layout, adapter filenames, ownership, dependency rules
- `docs/08-quality-security-observability.md` — IAM separation, query controls, cost controls
- `docs/10-demo-and-evaluation.md` — demo narrative, acceptance tests, resilience checklist
- `docs/20-grounded-copilot.md` — the copilot and agent layer
- `docs/aws-architecture.md` — the deployed AWS architecture diagram

---

## 10. Suggested next steps

1. **Local forecasting** — the one missing product pillar. Cheapest credible path is a precomputed Parquet artifact in the `forecasts/` bucket, served through the `ForecastService` port.
2. **Real row-level transform in the Lambda** — makes curated output a genuine Parquet fact table instead of a copied CSV.
3. **API-role IAM** for `SendTaskSuccess` / `SendTaskFailure` before the API is deployed to AWS.
4. **Before the account is suspended:** run the data export (`scripts/aws_export.py --region us-east-1`). The organizer does not preserve team data.
