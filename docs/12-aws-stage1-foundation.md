# AWS Stage 1 Foundation

> Status: implemented. Deploys nothing, spends nothing.
> Audience: every workstream. This is what the AWS foundation provides, what it
> deliberately leaves out, and which command to run when something looks wrong.

## What this feature is

Stage 1 is the zero-cost foundation of the AWS integration. It delivers the port
Protocols, a reusable contract-test harness, a CDK application that synthesizes
but never deploys, and runnable verification scripts. Nothing here creates an AWS
resource. Running `uv run pytest` on a clean checkout requires no AWS credential
and incurs no AWS charge.

## Delivered artifacts

| Artifact | Path | Purpose |
|---|---|---|
| Port Protocols | `src/youth_compass/ports/` | The seam between application logic and infrastructure |
| Domain errors | `src/youth_compass/domain/errors.py` | Error types that cross a port boundary |
| Contract-test harness | `tests/contract/` | One suite every adapter must satisfy, backed by Moto |
| Reference adapters | `tests/contract/reference/` | In-memory implementations that prove the harness |
| CDK application | `infra/` | Budget-and-tags infrastructure, synthesized only |
| Preflight checker | `scripts/aws_preflight.py` | Ten-second account-readiness check |
| Smoke tester | `scripts/aws_smoke_test.py` | End-to-end round-trip verification with cleanup |
| Data exporter | `scripts/aws_export.py` | Pulls S3 and Glue data local before account suspension |
| Bootstrap driver | `scripts/aws_bootstrap.py` | Empty account to verified stack in one command |
| Teardown driver | `scripts/aws_teardown.py` | Destroy stacks behind an account-number confirmation |
| Provider config | `configs/local.yaml`, `configs/aws.example.yaml` | Swap infrastructure by configuration, not code |
| LocalStack compose | `docker-compose.yml` | Optional manual exploration; the suite uses Moto |
| Dependency changes | `pyproject.toml` | boto3, moto, aws-cdk-lib, constructs in the dev group |

## Commands

Targets marked (creds) require resolvable AWS credentials. Only the bootstrap,
teardown, export, and preflight paths touch a real account, and only bootstrap
and teardown can change it.

| Command | Creds | Can charge | Success output | Exit |
|---|---|---|---|---|
| `make aws-preflight` | yes | no | pass/fail/warn/skip table | 0 pass, non-zero on fail |
| `make aws-synth` | no | no | one CloudFormation template per stack | 0 on success |
| `make aws-smoke` | no | no | per-step table, `0.00 USD` | 0 pass, non-zero on fail |
| `make aws-export` | yes | no | exported/skipped/failed counts, manifest path | 0, non-zero on failure |
| `make hackathon-bootstrap` | yes | yes | per-step changed/unchanged summary | 0, non-zero on failure |
| `make aws-teardown` | yes | yes | stacks destroyed after confirmation | 0, non-zero on cancel |

`make hackathon-bootstrap ASSUME_YES=1` skips the confirmation prompt for
unattended runs. `make aws-synth` accepts `ENV=dev|demo|hackathon`.

## Deferred services

Amazon Bedrock, Amazon SageMaker AI, and Amazon Bedrock AgentCore carry no Stage 1
construct, adapter, or deployed resource. Cost avoidance is the reason. They
arrive in Stage 3. The preflight checker only reads their readiness; it issues no
inference, training, tuning, or deployment call.

The competition rules restrict foundation models to Amazon Bedrock and Amazon
SageMaker AI (「僅限使用 Amazon Bedrock、SageMaker AI 的基礎模型」). Amazon Bedrock
is therefore mandatory for the final submission, and per-account Bedrock model
access must be enabled before a model can be used. The preflight checker reports
that access as a warning, never a hard failure.

## What Stage 1 does not deliver

| Absent in Stage 1 | Arrives in |
|---|---|
| Any AWS adapter implementation (S3, Glue, Athena, ...) | Stage 2 |
| Any deployed stack | Stage 2 |
| Foundation-model integration | Stage 3 |

## Moto fidelity boundary

The smoke tester runs against Moto by default. Moto does not execute Amazon
Athena SQL and runs a simplified Step Functions interpreter, so in Moto mode the
Athena and Step Functions steps verify this tester's own orchestration against
seeded results, not AWS SQL semantics or real state transitions. Those rows are
labelled `(simulated)`. Real behaviour is verified only under `--real`, which is
a Stage 2 rehearsal against a personal account.

## Port amendment procedure

The port Protocols are a Stage 1 proposal. The backend workstream may amend them:

1. The backend workstream owner approves the signature change.
2. Update `src/youth_compass/ports/<module>.py`, its payload models, and
   `docs/01-system-architecture.md` section 5.
3. Update the reference adapter under `tests/contract/reference/`.
4. The Contract_Test_Suite must pass against the amended signature before merge.

## Competition-day constraints that shaped the design

The organizer hands over a fresh AWS account on the morning of 9/12, suspends it
after the competition, and requires each team to back up its own data. The
bootstrap driver is the response to the handover constraint: it takes an empty
account to a verified stack in one command. The data exporter is the response to
the suspension constraint: it pulls all S3 and Glue data local before shutdown.
