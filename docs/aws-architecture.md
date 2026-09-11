# AWS Architecture — New Taipei Youth Compass

> Region: ap-northeast-1 (Tokyo) | Account: 330177109233

## AWS Services Architecture

```mermaid
graph TB
    subgraph S3["Amazon S3 — Data Lake"]
        S3_IN["📥 incoming/<br/>Raw uploaded CSVs"]
        S3_QUA["🚫 quarantined/<br/>Failed validation"]
        S3_STD["🔄 standardized/<br/>Canonical dimensions added"]
        S3_CUR["✅ curated/<br/>Published analytical tables<br/>(Parquet, versioned)"]
        S3_FC["📈 forecasts/<br/>Prediction artifacts"]
        S3_META["📋 metadata/<br/>Quality reports, lineage"]
    end

    subgraph Compute["Serverless Compute"]
        LAMBDA["AWS Lambda<br/>(ARM64 Graviton)<br/>Runs profile_csv +<br/>analyze_mapping"]
        SFN["AWS Step Functions<br/>Ingestion Workflow:<br/>profile → map → validate →<br/>⏸ approval pause →<br/>transform → quality → publish"]
    end

    subgraph Analytics["Analytics & Catalog"]
        GLUE["AWS Glue<br/>Data Catalog<br/>Table schemas for<br/>curated Parquet"]
        DDB["Amazon DynamoDB<br/>App metadata:<br/>approval status,<br/>quality score,<br/>version pointer"]
        ATHENA["Amazon Athena<br/>SQL over curated/<br/>Typed QuerySpec only<br/>Scanned-bytes capped"]
    end

    subgraph Events["Event-Driven"]
        EB["Amazon EventBridge<br/>Audit events:<br/>dataset.published<br/>mapping.reviewed<br/>dataset.quarantined"]
    end

    subgraph Security["IAM & Cost Controls"]
        WRITE["Write_Role<br/>Lambda + Step Functions<br/>Can write curated/"]
        COPILOT["Copilot_Role<br/>Athena only<br/>❌ DENIED PutObject +<br/>DeleteObject on curated/"]
        BUDGET["AWS Budgets<br/>$10/mo dev<br/>$20/mo demo<br/>$50/mo hackathon<br/>Alerts at 80% + 100%"]
    end

    subgraph Stage3["Stage 3 — Deferred"]
        BEDROCK["Amazon Bedrock<br/>Foundation models<br/>(mandatory per rules)"]
        SAGEMAKER["Amazon SageMaker<br/>Forecast training +<br/>model registry"]
        AGENTCORE["Bedrock AgentCore<br/>Agent hosting +<br/>MCP Gateway"]
    end

    %% Ingestion flow
    S3_IN -->|"S3 event"| EB
    EB -->|"triggers"| SFN
    SFN -->|"invokes"| LAMBDA
    SFN -->|"on success"| S3_CUR
    SFN -->|"on failure"| S3_QUA
    SFN -->|"intermediate"| S3_STD

    %% Catalog + metadata
    SFN -->|"register schema"| GLUE
    SFN -->|"update metadata"| DDB

    %% Audit
    SFN -->|"emits"| EB
    LAMBDA -->|"emits"| EB

    %% Query path
    ATHENA -->|"scans"| S3_CUR
    ATHENA -->|"reads schema"| GLUE

    %% IAM boundaries
    WRITE -.->|"assumed by"| LAMBDA
    WRITE -.->|"assumed by"| SFN
    COPILOT -.->|"assumed by"| ATHENA

    %% Cost
    BUDGET -.->|"monitors"| S3
    BUDGET -.->|"monitors"| Compute
    BUDGET -.->|"monitors"| Analytics

    %% Stage 3 connections (deferred)
    BEDROCK -.->|"Stage 3"| LAMBDA
    SAGEMAKER -.->|"Stage 3"| S3_FC
    AGENTCORE -.->|"Stage 3"| ATHENA

    %% Styling
    classDef deployed fill:#d4edda,stroke:#28a745,stroke-width:2px
    classDef deferred fill:#fff3cd,stroke:#ffc107,stroke-width:2px,stroke-dasharray: 5 5
    classDef iam fill:#fce4ec,stroke:#e91e63,stroke-width:2px
    classDef cost fill:#e8eaf6,stroke:#3f51b5,stroke-width:2px

    class S3_IN,S3_QUA,S3_STD,S3_CUR,S3_FC,S3_META deployed
    class LAMBDA,SFN deployed
    class GLUE,DDB,ATHENA deployed
    class EB deployed
    class BEDROCK,SAGEMAKER,AGENTCORE deferred
    class WRITE,COPILOT iam
    class BUDGET cost
```

## Ingestion Data Flow

```mermaid
sequenceDiagram
    participant S3In as S3 incoming/
    participant EB as EventBridge
    participant SFN as Step Functions
    participant Lambda as Lambda
    participant Reviewer as Human Reviewer
    participant S3Cur as S3 curated/
    participant S3Qua as S3 quarantined/
    participant Glue as Glue Catalog
    participant DDB as DynamoDB

    S3In->>EB: ObjectCreated event
    EB->>SFN: Start workflow
    SFN->>Lambda: Profile CSV
    Lambda-->>SFN: DatasetProfile
    SFN->>Lambda: Analyze mapping
    Lambda-->>SFN: MappingAnalysis

    alt Low confidence
        SFN->>Reviewer: ⏸ Pause (waitForTaskToken)
        Reviewer->>SFN: Approve or Reject
    end

    alt Approved
        SFN->>Lambda: Transform + Quality
        SFN->>S3Cur: Publish Parquet
        SFN->>Glue: Register schema
        SFN->>DDB: Update version pointer
        SFN->>EB: dataset.published
    else Rejected or Failed
        SFN->>S3Qua: Quarantine
        SFN->>EB: dataset.quarantined
    end
```

## Security Boundary

```mermaid
graph LR
    subgraph Write["Write_Role (workflow service)"]
        W_SFN["Step Functions"]
        W_LAMBDA["Lambda"]
        W_S3["S3: write standardized/,<br/>curated/, forecasts/, metadata/"]
        W_GLUE["Glue: create/update tables"]
        W_DDB["DynamoDB: read + write"]
    end

    subgraph Read["Copilot_Role (read-only)"]
        R_ATHENA["Athena"]
        R_S3["S3 curated/: READ ONLY"]
        R_DDB["DynamoDB: READ ONLY"]
    end

    DENY["🚫 EXPLICIT DENY<br/>s3:PutObject<br/>s3:DeleteObject<br/>on curated/*"]

    R_ATHENA --> R_S3
    R_ATHENA --> R_DDB
    R_ATHENA -.- DENY

    classDef deny fill:#fde8e8,stroke:#c53030,stroke-width:3px
    class DENY deny
```

## Service Cost Summary

| Service | Billing model | Cost when idle |
|---|---|---|
| Amazon S3 (6 buckets) | per GB/month + per request | ~$0 at current scale |
| AWS Glue Data Catalog | per object cataloged | free tier |
| Amazon DynamoDB (on-demand) | per read/write request | $0 |
| Amazon Athena | $5 per TB scanned | $0 |
| AWS Lambda (ARM64) | per invocation + duration | $0 |
| AWS Step Functions | per state transition | $0 |
| Amazon EventBridge | per event published | $0 |
| AWS Budgets | free | free |
| AWS IAM | free | free |
| **Amazon Bedrock** *(Stage 3)* | per input/output token | $0 |
| **Amazon SageMaker** *(Stage 3)* | per instance-hour | $0 when no job |
| **Bedrock AgentCore** *(Stage 3)* | hosting cost | deferred |
