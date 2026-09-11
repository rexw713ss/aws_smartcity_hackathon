# AWS Workstream — Status and Handoff

> Owner: AWS integration engineer
> Status: **Planning complete for Stage 1. No AWS code written yet. Nothing deployed.**
> Last updated: 2026-09-06
> Audience: frontend, backend, and data-engineering teammates who need to know what the AWS lane is doing, what it will provide, and what it does not provide yet.

This is a living status document, not a design document. The numbered `docs/00-` through `docs/11-` files hold the approved architecture. This file explains where the AWS workstream actually stands against that architecture.

---

## 1. Timeline warning

The competition is **9/12-9/13** and today is **9/6**. That is roughly six days.

Two facts from the official rules drive everything below:

1. The organizer provides the AWS environment **only on the morning of 9/12**, announced at the opening ceremony.
2. The organizer **suspends the account after the competition** and explicitly does not preserve team data.

Practical consequence: the AWS stack must be deployable into an unfamiliar, empty account in minutes, and all data must be exportable before shutdown. Neither can be figured out on competition morning.

---

## 2. Current status at a glance

| Item | State |
|---|---|
| AWS integration plan (3 cost-staged stages) | Agreed |
| Stage 1 requirements spec | Written, awaiting review |
| Stage 1 design document | Not started |
| Stage 1 task list | Not started |
| Stage 1 implementation | **Not started — zero code** |
| Any deployed AWS resource | **None. Nothing has been deployed. No AWS spend has occurred.** |
| AWS CDK CLI | Installed locally (`package.json`, `aws-cdk` ^2.1140.0) |
| AWS account | Available for cheap Stage 2 rehearsal |

Directories still empty (`.gitkeep` only): `src/youth_compass/ports/`, `adapters/aws/`, `adapters/local/`, `tests/contract/`, `ml/`.

---

## 3. Findings from the competition rules that affect other workstreams

These are not AWS-lane details. They change what other people build.

### 3.1 Bedrock is mandatory, not optional

The rules state 「僅限使用 Amazon Bedrock、SageMaker AI 的基礎模型」 — only foundation models from Amazon Bedrock or Amazon SageMaker AI may be used.

`docs/01-system-architecture.md` and `docs/04-agentic-ai.md` currently treat Ollama as a first-class local provider with Bedrock as an optional AWS swap. **For the submission this is backwards.** A local Ollama model in the final demo would violate the rules.

- Backend: the `ModelProvider` port is a required delivery, not a nice-to-have. Keep `FakeModelProvider` for tests, keep Ollama for offline development, but the demo path must run on Bedrock.
- The submission must include a 「生成式 AI 技術應用」 (generative AI application) section.

### 3.2 Submission requirements

Proposals are uploaded within the 30-hour window and must cover: problem linkage, data usage, technical architecture, generative AI application, and a live demo.

### 3.3 Judging criteria

Technical feasibility, applicability, topic fit, completeness, and creativity (bonus).

### 3.4 Eligibility logistics

All members must attend the assigned data workshop, and at least two members must attend both generative-AI workshops, or the team loses finalist eligibility. Worth confirming this is already satisfied.

---

## 4. What the AWS workstream owns

Per `docs/07-project-structure.md` section 12:

- AWS adapters under `adapters/aws/`
- IAM and account setup
- Infrastructure as code
- Deployment pipelines
- Step Functions / Lambda / Glue integration
- SageMaker managed pipeline
- Bedrock / AgentCore deployment
- CloudWatch integration and cost controls

The hard rule that keeps our lanes separate is the dependency direction in `docs/07` section 13: **domain, application, and ports must never import `boto3`.** AWS-specific code lives only in `adapters/aws/`. If you see an AWS import creeping into shared code, that is a bug in my lane.

---

## 5. The plan, staged by cost

The AWS work is split into three stages so that nothing expensive is built before the hackathon credits exist.

### Stage 1 — Zero cost, no AWS account needed

Foundation only. Deploys nothing, spends nothing.

1. Port Protocol definitions published as a proposal
2. Reusable contract-test harness backed by in-memory AWS fakes
3. AWS CDK app that synthesizes but never deploys, including a Budgets stack
4. Runnable verification scripts (preflight, smoke test, data export)
5. One-command bootstrap for a fresh account, plus a Makefile

### Stage 2 — Cheap real AWS (realistically single-digit dollars total)

S3 object store, Glue catalog, Athena query engine, Lambda-packaged transforms, Step Functions ingestion workflow with human-approval callback, EventBridge trigger and quarantine path.

**No always-on compute in this stage.** Everything is per-invocation or tiny storage.

### Stage 3 — Deferred until hackathon credits arrive

Bedrock model provider, AgentCore Runtime deployment, AgentCore Gateway MCP tool layer, and optionally a SageMaker training pipeline.

Deliberate decision: the forecast ships as a **precomputed Parquet artifact** rather than a live SageMaker pipeline, matching the demo-resilience advice in `docs/10-demo-and-evaluation.md` section 11. A judge cannot tell the difference, and it removes the largest cost and failure risk. The SageMaker pipeline is an upgrade if time allows.

---

## 6. What Stage 1 will deliver

Nothing in this list exists yet. This is the planned artifact set.

| Artifact | Path | Purpose |
|---|---|---|
| Port Protocols | `src/youth_compass/ports/` | The fixed seam between domain logic and infrastructure |
| Contract-test harness | `tests/contract/` | One suite every adapter must satisfy, local or AWS |
| CDK app | `infra/` | Infrastructure as code, synthesized and reviewable, deployed later |
| Preflight checker | `scripts/aws_preflight.py` | Ten-second account readiness table for competition morning |
| Smoke tester | `scripts/aws_smoke_test.py` | End-to-end round-trip verification with self-cleanup |
| Data exporter | `scripts/aws_export.py` | Pulls all S3 and catalog data local before account suspension |
| Makefile | `Makefile` | `make hackathon-bootstrap` plus named operational targets |
| Provider config | `configs/local.yaml`, `configs/aws.example.yaml` | Swap infrastructure by configuration, not code |
| Optional LocalStack | `docker-compose.yml` | Manual AWS exploration without an account |
| Dev dependencies | `pyproject.toml` | boto3, moto, aws-cdk-lib, constructs added to the dev group only |

### Why there are three separate verification programs

Because they answer different questions:

1. **Contract tests** (`tests/contract/`) — "is my adapter logic correct?" Runs offline, no credentials, no cost, in CI.
2. **Infra tests** (`infra/`) — "would this deploy the resources and permissions I intend?" Synthesis only, nothing created.
3. **Preflight and smoke test** (`scripts/`) — "does the real account actually work right now?" One command, pass/fail table, readable output.

---

## 7. Open decisions that need backend input

Three items in the Stage 1 spec touch backend-owned code or documents. Flagging rather than deciding unilaterally.

1. **Port count.** `docs/01` section 5 defines six ports. `docs/07` section 7 fixes eight filenames, adding CheckpointStore, EventBus, and Clock while omitting WorkflowRunner. The spec currently covers nine Protocols, with `workflow_runner.py` proposed as an addition to `docs/07` section 7. Happy to trim to the six from `docs/01` section 5 if you would rather defer the rest.

2. **`pyproject.toml` changes.** Stage 1 adds four dev dependencies, and extends ruff and mypy coverage to `infra/` and `scripts/`, which narrows the existing `[tool.mypy] exclude`. Runtime dependencies stay untouched. This is a shared file, so tell me if you would rather apply it yourself.

3. **`src/youth_compass/config.py` changes.** Provider-name validation naturally belongs in the existing loader, but that file is backend-owned. The spec is written so this validation can live in a separate AWS-workstream settings module instead. Your call.

**The port signatures are a proposal, not a decree.** They are transcribed from the owner-approved `docs/01` section 5 so I am not inventing anything, but if the real implementation needs different signatures, amend them. The contract-test suite is what keeps the change cheap: it localizes the blast radius to the adapter.

---

## 8. What other teams can and cannot rely on

**Cannot rely on yet:** any working AWS adapter, any deployed stack, any Bedrock or foundation-model integration, any SageMaker pipeline. None of these exist.

**Can plan against:** the port signatures in `docs/01` section 5, the provider-selection config shape in `docs/01` section 6, and the fact that switching between local and AWS will be a configuration change rather than a code change.

**Frontend:** nothing in Stage 1 affects you. The API contract remains the backend's `docs/06-backend-api.md`.

**Data engineering:** the forecast is expected as a Parquet artifact written to a `forecasts/` location. Portable `ml/prepare|train|evaluate|inference.py` scripts taking paths as arguments (per `docs/05` section 8) will wrap cleanly into SageMaker later if we get there. Please avoid importing web application code in those scripts.

**Backend:** see the three open decisions above, and note the Bedrock rule in section 3.1.

---

## 9. Cost reference

A common question: does AWS keep charging while nobody is using it?

**Continuous — accrues hourly whether or not you touch it:**
storage (S3 per GB-month, DynamoDB, CloudWatch Logs retention), and always-on compute (SageMaker endpoints and notebook instances, RDS, NAT Gateways, Elastic IPs, EBS volumes).

**Per-use — costs nothing when idle:**
Athena queries, Lambda invocations, Step Functions transitions, S3 requests, EventBridge events, Bedrock tokens, SageMaker training jobs.

At this project's data scale (a few MB, roughly 49k rows in the largest topic), Stage 2's sleeping cost is **a few cents per month**, because it contains no always-on compute at all.

**The things that actually burn money are specific and avoidable.** None are in the plan, and creating any of them should be a deliberate, flagged decision:

- SageMaker real-time endpoints and notebook instances
- NAT Gateways
- RDS instances
- Unassociated Elastic IPs

Three guardrails are built into the plan: the Budgets stack deploys before any data resource, `make aws-teardown` gives one-command cleanup behind a confirmation prompt, and the preflight checker flags any always-on resource it finds in the account.

Figures above are estimates for the Tokyo region and should be confirmed against the AWS pricing calculator before anyone relies on them.

---

## 10. Environment setup for AWS work

Region: **ap-northeast-1 (Tokyo)** — nearest to the team, and it has Bedrock.

```bash
# AWS CLI v2
aws --version

# CDK CLI (already installed in this repo via npm)
npx cdk --version

# Credentials — prefer IAM Identity Center
aws configure sso
# or, with an IAM user that has MFA enabled
aws configure

# One-time per account and region, before the first deploy
npx cdk bootstrap aws://<account-id>/ap-northeast-1
```

Secrets never belong in committed files. Use environment variables, SSM Parameter Store, or Secrets Manager. `.env` and `node_modules/` are already gitignored.

---

## 11. Where the detail lives

The full Stage 1 requirements, with acceptance criteria and a glossary explaining every AWS term used, are in the project spec for `aws-stage1-foundation`. Ask me for a walkthrough rather than reading it cold — it is written for implementation precision, not for onboarding.

Related approved architecture documents:

- `docs/01-system-architecture.md` — port definitions, offline and AWS architectures, provider config
- `docs/07-project-structure.md` — repository layout, adapter filenames, ownership boundaries, dependency rules
- `docs/08-quality-security-observability.md` — IAM role separation, query controls, AWS cost controls
- `docs/09-implementation-plan.md` — the overall phase plan and the AWS phase outline
- `docs/10-demo-and-evaluation.md` — demo narrative, end-to-end acceptance tests, resilience checklist

---

## 12. Next steps in the AWS lane

1. Review the Stage 1 requirements and settle the three open decisions in section 7
2. Produce the Stage 1 design and task list
3. Implement Stage 1 (zero cost, no account needed)
4. Rehearse Stage 2 against a personal account for a few dollars, well before 9/12
5. On 9/12 morning: run preflight against the provided account, then `make hackathon-bootstrap`
6. Before the event closes: run the data export
