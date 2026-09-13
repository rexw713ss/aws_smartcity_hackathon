# AWS Architecture — New Taipei Youth Policy

> Region: **us-east-1** (N. Virginia) · Environment: `hackathon` · Account: `765996595659`
>
> **This document describes what is actually deployed**, not the original plan. Services that
> exist only in the planning documents are listed in [§6 Not deployed](#6-not-deployed).
> The drawable version is `docs/aws-architecture.drawio`.

## 1. System Architecture

```mermaid
graph TB
    PUBLIC["Browser<br/>(public / judge)"]
    REVIEWER["Human reviewer"]

    subgraph Edge["Public surface"]
        CF["Amazon CloudFront<br/>OAC, HTTPS redirect,<br/>SPA deep links"]
        SITE["S3 site bucket<br/>private, React/Vite build"]
        FURL["Lambda Function URL<br/>AuthType NONE,<br/>RESPONSE_STREAM"]
        SM["AWS Secrets Manager<br/>write-endpoint shared secret"]
    end

    subgraph Api["API Lambda — ARM64, 1024 MB, 90 s, reserved concurrency 20"]
        APILAMBDA["FastAPI + Lambda Web Adapter<br/>LangGraph agent runs in-process"]
    end

    subgraph Ingest["Event-driven ingestion"]
        S3IN["S3 incoming/<br/>presigned POST, 30-day expiry,<br/>EventBridge enabled"]
        EB["Amazon EventBridge<br/>Object Created, prefix incoming/"]
        UPLOADFN["Lambda upload-event<br/>256 MB, 30 s<br/>one execution per upload"]
        SFN["Step Functions Standard<br/>analyze → confidence gate →<br/>waitForTaskToken → publish / quarantine"]
        XFORMFN["Lambda transform<br/>1024 MB, 5 min, ARM64<br/>no Bedrock access"]
    end

    subgraph Lake["Data lake and catalog"]
        S3LAKE["S3 zones<br/>standardized/ curated/<br/>quarantined/ (90 d) metadata/<br/>forecasts/ (created, unused)"]
        GLUE["AWS Glue Data Catalog<br/>youth_compass_hackathon"]
        ATHENA["Amazon Athena<br/>workgroup-enforced<br/>1 GiB scan cap"]
        DDB["Amazon DynamoDB<br/>job state, task tokens,<br/>conversation (TTL)"]
    end

    subgraph AI["AI"]
        BEDROCK["Amazon Bedrock<br/>us.anthropic.claude-sonnet-4-6<br/>inference profile"]
    end

    subgraph Gov["Governance"]
        BUDGET["AWS Budgets<br/>50 USD/month, 80% + 100%"]
        CW["Amazon CloudWatch<br/>logs and metrics"]
    end

    PUBLIC -->|"HTTPS"| CF
    CF -->|"OAC signed read"| SITE
    PUBLIC -->|"XHR, streaming"| FURL
    FURL --> APILAMBDA
    APILAMBDA -->|"cached 5 min"| SM
    PUBLIC -->|"presigned POST"| S3IN

    S3IN -->|"Object Created"| EB
    EB -->|"rule target"| UPLOADFN
    UPLOADFN -->|"StartExecution, idempotent"| SFN
    SFN -->|"analyze / transform"| XFORMFN

    REVIEWER -->|"approve / reject + token"| APILAMBDA
    APILAMBDA -->|"SendTaskSuccess / Failure"| SFN

    XFORMFN -->|"publish or quarantine"| S3LAKE
    XFORMFN -->|"register table"| GLUE
    XFORMFN -->|"job state, version"| DDB

    APILAMBDA -->|"query"| ATHENA
    APILAMBDA -->|"job + conversation state"| DDB
    APILAMBDA -->|"inference"| BEDROCK
    ATHENA -->|"schema"| GLUE
    ATHENA -->|"scan curated/, read-only"| S3LAKE

    BUDGET -.->|"monitors"| Lake & Api & AI
    CW -.->|"collects"| Api & Ingest & ATHENA

    classDef storage fill:#d4edda,stroke:#28a745,stroke-width:2px
    classDef compute fill:#cce5ff,stroke:#004085,stroke-width:2px
    classDef analytics fill:#e2e3f1,stroke:#383d6e,stroke-width:2px
    classDef ai fill:#fff3cd,stroke:#856404,stroke-width:2px
    classDef event fill:#d1ecf1,stroke:#0c5460,stroke-width:2px
    classDef edge fill:#ede7f6,stroke:#8c4fff,stroke-width:2px
    classDef obs fill:#f0f0f0,stroke:#6c757d,stroke-width:2px

    class S3IN,S3LAKE,SITE storage
    class APILAMBDA,UPLOADFN,XFORMFN compute
    class GLUE,DDB,ATHENA analytics
    class BEDROCK ai
    class EB,SFN event
    class CF,FURL,SM edge
    class CW,BUDGET obs
```

## 2. Ingestion Data Flow

Mapping is **deterministic confidence scoring**. No model is called on this path — the transform
Lambda holds no Bedrock permission at all.

```mermaid
sequenceDiagram
    participant B as Browser
    participant API as API Lambda
    participant S3In as S3 incoming/
    participant EB as EventBridge
    participant UP as upload-event Lambda
    participant SFN as Step Functions
    participant TX as transform Lambda
    participant R as Human reviewer
    participant Lake as S3 curated/ or quarantined/
    participant Glue as Glue Catalog
    participant DDB as DynamoDB

    B->>API: POST /api/v1/uploads (write token)
    API-->>B: presigned POST fields + jobId
    B->>S3In: multipart POST, file last
    S3In-->>B: 204
    S3In->>EB: Object Created (incoming/)
    EB->>UP: rule target
    UP->>SFN: StartExecution (idempotent on job id)

    SFN->>TX: action=analyze
    TX-->>SFN: profile + mapping confidence

    alt analysis failed (status=error)
        SFN->>TX: action=transform, approved=false
        TX->>Lake: quarantine with reason
    else confidence >= 0.95
        SFN->>TX: action=transform, approved=true
        TX->>Lake: publish curated Parquet
        TX->>Glue: register table schema
        TX->>DDB: job published, version pointer
    else confidence below 0.95 or absent
        SFN->>TX: action=await_approval (waitForTaskToken)
        TX->>DDB: persist task token
        Note over SFN: execution suspended, no hourly charge
        R->>API: POST /ingestion-jobs/{id}/decision
        API->>SFN: SendTaskSuccess / SendTaskFailure
        SFN->>TX: publish or quarantine
    end
```

## 3. Query and Copilot Path

The agent runs **in-process inside the API Lambda**. There is no AgentCore runtime and no MCP
Gateway.

```mermaid
graph LR
    subgraph ApiLambda["API Lambda (single process)"]
        FASTAPI["FastAPI routes"]
        AGENT["LangGraph agent<br/>planning + answering"]
        TOOLS["Typed tool layer<br/>QuerySpec, feature reads"]
    end

    ATHENA["Amazon Athena<br/>1 GiB scan cap"]
    GLUE["Glue Catalog"]
    S3C["S3 curated/<br/>READ ONLY"]
    DDB["DynamoDB<br/>conversation + job state"]
    BEDROCK["Amazon Bedrock<br/>Claude Sonnet 4.6"]

    FASTAPI --> AGENT
    AGENT --> TOOLS
    AGENT -->|"inference"| BEDROCK
    TOOLS -->|"StartQueryExecution"| ATHENA
    TOOLS -->|"session context"| DDB
    ATHENA -->|"schema"| GLUE
    ATHENA -->|"scan"| S3C

    classDef agent fill:#fff3cd,stroke:#856404,stroke-width:2px
    classDef query fill:#e2e3f1,stroke:#383d6e,stroke-width:2px
    class FASTAPI,AGENT,TOOLS agent
    class ATHENA,GLUE,S3C query
```

## 4. Security Boundary

The boundary that actually applies is each function's own execution role. `Write_Role` and
`Copilot_Role` are deployed in the Data stack but **no principal assumes them yet** — the
planned role separation is not wired up.

```mermaid
graph TB
    subgraph ApiRole["API Lambda execution role"]
        A1["S3 curated/: READ ONLY"]
        A2["S3 incoming/: read + write"]
        A3["Athena + Glue: read"]
        A4["Bedrock: the configured model only, not *"]
        A5["states:SendTaskSuccess / SendTaskFailure"]
        A6["Secrets Manager: the write secret only"]
    end

    subgraph XformRole["transform Lambda execution role"]
        X1["S3 standardized/ curated/ quarantined/: read + write"]
        X2["glue:CreateTable / UpdateTable / GetTable<br/>scoped to this database, no delete"]
        X3["DynamoDB: read + write"]
    end

    subgraph UploadRole["upload-event Lambda execution role"]
        U1["S3 incoming/: read"]
        U2["states:StartExecution"]
    end

    subgraph Unwired["Deployed but unassumed"]
        W["Write_Role"]
        C["Copilot_Role<br/>explicit DENY s3:PutObject, s3:DeleteObject on curated/*"]
    end

    classDef deny fill:#fde8e8,stroke:#c53030,stroke-width:2px
    classDef idle fill:#f0f0f0,stroke:#999999,stroke-width:2px,stroke-dasharray: 5 5
    class A1 deny
    class W,C idle
```

Other enforced guardrails:

- **Athena workgroup** sets `enforce_work_group_configuration=true`, so the 1 GiB scan cap and
  the result location cannot be overridden per query.
- **Site bucket** blocks all public access and is reachable only through CloudFront via OAC.
- **CORS** allows only the CloudFront origin; `GET`, `POST`, `OPTIONS` only.
- **Write endpoints** require `X-Youth-Compass-Token`. If the secret cannot be read the guard
  fails closed with 503 — an unreachable secret store never becomes an unguarded write path.
- **No VPC, no NAT, no always-on compute.** Everything is request-billed.

## 5. Service Inventory

| Service | Purpose | Cost model |
|---|---|---|
| **Amazon CloudFront** | SPA delivery, OAC to a private bucket, HTTPS redirect | per request + GB out |
| **Amazon S3** | Site bucket + 6 data-lake zones, versioned, public access blocked | per GB + per request |
| **AWS Lambda** | API (Function URL, response streaming), upload-event, transform — all ARM64 | per request + GB-second |
| **AWS Step Functions** | Standard workflow with `waitForTaskToken` approval pause | per state transition |
| **Amazon EventBridge** | S3 Object Created rule scoped to `incoming/` | per event |
| **AWS Glue Data Catalog** | Table schemas for curated Parquet | per object cataloged |
| **Amazon Athena** | SQL over curated Parquet, workgroup-enforced 1 GiB cap | per TB scanned |
| **Amazon DynamoDB** | Job state, workflow task tokens, conversation context (TTL) | per request (on-demand) |
| **Amazon Bedrock** | Copilot inference, single configured model | per token |
| **AWS Secrets Manager** | Write-endpoint shared secret, stack-generated | per secret + per call |
| **Amazon CloudWatch** | Lambda and Athena logs and metrics | per GB ingested |
| **AWS Budgets** | 50 USD/month, alerts at 80% and 100% | free |
| **AWS IAM** | Per-function execution roles | free |

## 6. Not deployed

Present in the planning documents and the earlier diagram, absent from every stack:

| Claimed | Reality |
|---|---|
| **Amazon SageMaker** — forecast training, model registry, batch transform | No construct in any stack. `config.py` has a `SAGEMAKER` enum value and `forecasting/baseline.py` calls it "a future SageMaker batch job"; the forecast ships as a precomputed artifact. |
| **Bedrock AgentCore** — LangGraph hosting, MCP Gateway | No construct. The agent runs in-process in the API Lambda. |
| **Bedrock-assisted schema mapping** | The transform Lambda is granted no Bedrock permission. Mapping is deterministic confidence scoring. |
| **OpenTelemetry → CloudWatch distributed traces** | Not wired. CloudWatch logs and metrics only. |
| **`forecasts/` write path** | The bucket is created and `Write_Role` can write it, but nothing does; `YOUTH_COMPASS_FORECAST__PROVIDER=local`. |
| **`Write_Role` / `Copilot_Role` enforcing the boundary** | Both deployed, neither assumed by any principal. |
| **Region ap-northeast-1 (Tokyo)** | Deployed in **us-east-1**. `infra/environments.py` still defaults to `ap-northeast-1`; the deploy passes `-c region=us-east-1` and the Makefile defaults `YOUTH_COMPASS_REGION` to `us-east-1`. |

## 7. Related documents

- `docs/21-api-deployment.md` — live endpoints, redeploy steps, frontend integration
- `docs/aws-workstream-status.md` — overall AWS status and remaining gaps
- `docs/06-backend-api.md` — API contract
- `docs/aws-architecture.drawio` — the drawable diagram (Traditional Chinese)
