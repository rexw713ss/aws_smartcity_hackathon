# CDK application (synthesize only, never deployed in Stage 1)

This app declares cost-control infrastructure that is reviewed as synthesized
CloudFormation and deployed later. Stage 1 runs `cdk synth` only; nothing here
creates an AWS resource.

## Stacks

| Stack | Purpose | Resources |
|---|---|---|
| `YouthCompass-<env>-Budget` | Monthly cost budget with 80% and 100% actual-spend email alerts | one `AWS::Budgets::Budget` |

The data stack referenced by `make hackathon-bootstrap` is a Stage 2 delivery and
is not defined here yet.

## Context environments

| Environment | Stack prefix | Monthly budget |
|---|---|---|
| `dev` | `YouthCompass-dev` | 10 USD |
| `demo` | `YouthCompass-demo` | 20 USD |
| `hackathon` | `YouthCompass-hackathon` | 50 USD |

An environment name other than these three is an error; `cdk synth` writes no
template and exits non-zero.

## Required context and environment variables

| Input | Source | Required | Notes |
|---|---|---|---|
| `env` | `-c env=<name>` | yes | one of `dev`, `demo`, `hackathon` |
| `budgetEmail` | `-c budgetEmail=<addr>` | yes (or the env var) | notification address; context preferred |
| `YOUTH_COMPASS_BUDGET_EMAIL` | environment variable | fallback for `budgetEmail` | kept out of version control |
| `region` | `-c region=<region>` | no | defaults to `CDK_DEFAULT_REGION`, then `ap-northeast-1` |
| `account` | `-c account=<id>` | no | supplied at deploy time, never committed |

The notification address is never written to a committed file. `cdk.context.json`,
which the CLI caches `-c` values into, is gitignored.

## Synthesize each environment

```bash
cd infra
cdk synth -c env=dev       -c budgetEmail=you@example.com
cdk synth -c env=demo      -c budgetEmail=you@example.com
cdk synth -c env=hackathon -c budgetEmail=you@example.com
```

No AWS credentials are required to synthesize.
