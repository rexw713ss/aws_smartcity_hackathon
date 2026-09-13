# Requirements Document

## Introduction

Stage 2 of the AWS integration plan for **New Taipei Youth Policy** builds the cheap real-AWS layer on top of the zero-cost Stage 1 foundation. Stage 1 delivered the port Protocols that pin the seam between domain logic and infrastructure, a contract-test harness backed by in-memory reference adapters, a CDK budget stack that synthesizes but never deploys, and a set of readiness scripts. Stage 2 plugs real AWS services into those ports: Amazon S3 behind ObjectStore, AWS Glue plus Amazon DynamoDB behind DataCatalog, Amazon Athena behind QueryEngine, AWS Step Functions behind WorkflowRunner, and Amazon EventBridge behind EventBus. It also adds the CDK data stack those adapters need, packages the existing deterministic transforms as an AWS Lambda function, and assembles the Step Functions ingestion workflow with a human-approval callback.

The design is shaped by the same two hard external facts as Stage 1, sharpened by the calendar. The competition runs 9/12 through 9/13 2026, six days away, in region ap-northeast-1 (Tokyo). Unlike Stage 1, the engineer has a personal AWS account available now for rehearsal and is willing to spend single-digit dollars proving the flow works before the organizer's account appears on competition morning. Every service Stage 2 introduces is therefore chosen to be billed per use rather than per hour: nothing runs when no one is ingesting or querying, and the budget alarms from Stage 1 deploy before any data resource so a runaway cost trips an alert on the first dollar.

Stage 2 must not weaken the guarantees Stage 1 established. The contract-test suite is the acceptance bar: every new adapter is bound to its Port's existing contract class through a `register_*` factory, with zero edits to any contract class body, and must pass under Moto before any real-account test runs. Domain code stays free of AWS: no module under `src/youth_compass/` may import `boto3`, the guard test that enforces this keeps passing, and no `botocore.ClientError` may escape a port boundary — adapters translate every technology-specific exception into the domain error hierarchy from `src/youth_compass/domain/errors.py`. The 328 tests already passing must all keep passing. Amazon Bedrock, Amazon SageMaker AI, and Amazon Bedrock AgentCore remain out of scope, deferred to Stage 3.

## Glossary

### Architecture terms

- **Port**: A Python `Protocol` (structural interface) declaring the operations the application needs from infrastructure without naming any concrete technology. Ports live in `src/youth_compass/ports/`.
- **Adapter**: A concrete implementation of a Port for one technology. Stage 2 adds AWS adapters under `adapters/aws/`, alongside the offline adapters in `adapters/local/`.
- **Ports_And_Adapters_Rule**: The dependency-direction rule from `docs/07-project-structure.md` section 13. Code under `src/youth_compass/domain/`, `application/`, and `ports/` is forbidden from importing `boto3`, `aws-cdk-lib`, `constructs`, `moto`, `fastapi`, or any module under `adapters/`.
- **Contract_Test_Suite**: The single reusable pytest suite in `tests/contract/` that asserts behaviour required of every implementation of a given Port. The AWS adapter and the local adapter run the same class so the two are provably interchangeable.
- **Adapter_Registry**: The per-Port factory registries in `tests/contract/registry.py`. Binding an adapter to its contract class is one decorated zero-argument factory (`register_object_store`, `register_catalog`, `register_query_engine`, `register_workflow_runner`, `register_event_bus`, and their siblings) that returns a context manager yielding a fresh adapter instance.
- **Domain_Error**: One of the exception types in `src/youth_compass/domain/errors.py` (`ObjectNotFoundError`, `DatasetNotFoundError`, `QueryNotPermittedError`, `QueryExecutionError`, `WorkflowStateError`, and their siblings). Every failure crossing a port boundary is raised as one of these; adapter-internal `botocore`, `OSError`, and similar exceptions must never propagate through a port.
- **Deterministic_Transform**: The existing backend functions `profile_csv` (in `src/youth_compass/ingestion/csv_profiler.py`) and `analyze_mapping` (in `src/youth_compass/mapping/engine.py`), which produce the same output for the same input with no dependence on wall-clock time, randomness, or network state.
- **Provider_Selection**: The configuration-driven mechanism from `docs/01-system-architecture.md` section 6 that chooses which Adapter satisfies each Port, using YAML keys such as `storage.provider: s3` or `query.provider: athena`.

### AWS terms

- **Amazon_S3**: AWS object storage, addressed by bucket and key. Billed per request and per byte stored, with no hourly charge, which is why it backs the ObjectStore Port.
- **Amazon_S3_Versioning**: A bucket setting that retains prior versions of an object when a key is overwritten or deleted, so a mistaken write or delete can be recovered rather than losing data.
- **Public_Access_Block**: The Amazon_S3 account and bucket setting that denies all forms of public access, ensuring no data zone is inadvertently exposed to the internet.
- **Lifecycle_Rule**: An Amazon_S3 configuration that transitions or expires objects on an age schedule, used here to cap storage cost by aging out transient data zones.
- **AWS_Glue**: The AWS managed metadata catalog and ETL service. Its Data Catalog holds table and column schemas; Stage 2 uses only the catalog, not Glue ETL jobs, so there is no hourly charge.
- **Glue_Database**: A namespace within the AWS_Glue Data Catalog that groups related table definitions.
- **Amazon_DynamoDB**: A serverless key-value and document store. In on-demand (pay-per-request) capacity mode it has no provisioned hourly charge, so it holds application metadata that Glue schemas do not model.
- **On_Demand_Capacity**: The Amazon_DynamoDB billing mode that charges per read and write request with no provisioned throughput reservation, keeping an idle table free.
- **Amazon_Athena**: A serverless query service that runs SQL directly over Amazon_S3 data. It is billed per byte scanned, which is why the adapter enforces a scanned-bytes cap.
- **AWS_Lambda**: The AWS serverless compute service that runs a function per invocation with no idle charge. Stage 2 packages the Deterministic_Transforms as a Lambda function.
- **ARM64**: The 64-bit ARM processor architecture (`arm64` / Graviton on AWS_Lambda). `docs/01-system-architecture.md` section 8 requires ARM64 compatibility; the Lambda package and every dependency it bundles must run on it.
- **AWS_Step_Functions**: The AWS serverless workflow orchestrator. A workflow is defined as a State_Machine and billed per state transition, with no cost while idle.
- **State_Machine**: The AWS_Step_Functions definition of an ordered set of states (tasks, choices, waits, and terminal states) describing one workflow.
- **Callback_Token**: An opaque token AWS_Step_Functions issues for a task started with the `waitForTaskToken` integration. The State_Machine suspends until an external caller returns the token with a success or failure result, which is how a human decision resumes a paused workflow.
- **Wait_For_Task_Token**: The AWS_Step_Functions service-integration pattern that pauses a task until the Callback_Token is returned, incurring no charge during the wait.
- **Amazon_EventBridge**: The AWS serverless event bus. Publishers put events; rules route matching events to targets. Billed per event published, with no idle charge, it backs the EventBus Port.
- **IAM_Role**: An AWS Identity and Access Management identity carrying a permission policy, assumed by a service or principal to obtain scoped, temporary credentials.
- **Least_Privilege**: The security principle that a role is granted only the permissions its task requires and no more. Stage 2 separates a write role from a read-only role so the query path cannot mutate curated data.
- **Parquet**: A columnar on-disk file format. Storing curated data as Parquet in Amazon_S3 lets Amazon_Athena scan only the columns a query needs, reducing scanned bytes and therefore cost.
- **Moto**: A Python library that intercepts `boto3` calls and simulates AWS services in memory, requiring no credentials, no network, and no cost. It is the execution environment for the Contract_Test_Suite and the smoke test.
- **Amazon_Bedrock / Amazon SageMaker AI / Amazon Bedrock AgentCore**: The AWS managed model, training, and agent services. All three are deferred to Stage 3 and must appear in no Stage 2 construct or resource.

### System names used in acceptance criteria

- **Data_Stack**: The AWS_CDK stack, added to the application rooted at `infra/`, that defines the Amazon_S3 buckets, Glue_Database, Amazon_DynamoDB table, and IAM_Roles the adapters use.
- **Data_Zones**: The six logical Amazon_S3 storage areas — incoming, quarantined, standardized, curated, forecasts, and metadata — that partition the data lake by processing stage.
- **Write_Role**: The IAM_Role the ingestion workflow service assumes, permitted to write to the standardized, curated, forecasts, and metadata zones.
- **Copilot_Role**: The read-only IAM_Role the policy copilot assumes, denied `s3:PutObject` and `s3:DeleteObject` on curated paths.
- **S3_Store_Adapter**: The Amazon_S3 implementation of the ObjectStore Port at `adapters/aws/s3_store.py`.
- **Glue_Catalog_Adapter**: The AWS_Glue plus Amazon_DynamoDB implementation of the DataCatalog Port at `adapters/aws/glue_catalog.py`.
- **Athena_Query_Adapter**: The Amazon_Athena implementation of the QueryEngine Port at `adapters/aws/athena_query.py`.
- **EventBridge_Bus_Adapter**: The Amazon_EventBridge implementation of the EventBus Port at `adapters/aws/eventbridge_bus.py`.
- **Transform_Lambda**: The AWS_Lambda function that calls the Deterministic_Transforms `profile_csv` and `analyze_mapping`.
- **Ingestion_Workflow**: The AWS_Step_Functions State_Machine implementing the WorkflowRunner Port, from file arrival through publish.
- **Bootstrap_Target**: The `make hackathon-bootstrap` Makefile target and the targets it chains, delivered in Stage 1.
- **Smoke_Tester**: The command-line program `scripts/aws_smoke_test.py`, delivered in Stage 1.
- **Data_Exporter**: The command-line program `scripts/aws_export.py`, delivered in Stage 1.

## Requirements

### Requirement 1: Deploy the data-lake stack with least-privilege IAM roles

**User Story:** As the AWS engineer, I want a CDK data stack that declares every bucket, catalog namespace, metadata table, and access role the adapters need, with the write path and the query path separated by role, so that the day the real account appears I deploy a known-good, cost-guarded data lake instead of assembling one under time pressure.

#### Acceptance Criteria

1. THE Data_Stack SHALL be an AWS_CDK stack added to the application rooted at `infra/`, extending the existing `infra/app.py` entry point, that `cdk synth` executes for each of the `dev`, `demo`, and `hackathon` context environments and that terminates with a zero exit status when every required context value is present.
2. THE Data_Stack SHALL define exactly one Amazon_S3 bucket for each of the six Data_Zones — incoming, quarantined, standardized, curated, forecasts, and metadata — and SHALL name no other Amazon_S3 bucket.
3. THE Data_Stack SHALL enable Amazon_S3_Versioning and a Public_Access_Block that denies all public access on every one of the six Data_Zone buckets.
4. THE Data_Stack SHALL attach a Lifecycle_Rule to the incoming and quarantined buckets that expires objects after a bounded age, and SHALL document the age chosen for each.
5. THE Data_Stack SHALL define exactly one Glue_Database and exactly one Amazon_DynamoDB table, and SHALL configure that table in On_Demand_Capacity mode with no provisioned read or write capacity.
6. THE Data_Stack SHALL define exactly two IAM_Roles, a Write_Role and a Copilot_Role, and SHALL grant each only the permissions its task requires under Least_Privilege.
7. THE Data_Stack SHALL grant the Write_Role permission to write objects to the standardized, curated, forecasts, and metadata buckets, and SHALL grant the Copilot_Role read access to the curated bucket.
8. THE Copilot_Role SHALL be denied `s3:PutObject` and `s3:DeleteObject` on every curated-zone path, and the Data_Stack SHALL include a CDK assertion test proving that the synthesized Copilot_Role policy contains an explicit deny for those two actions on the curated paths and grants neither of them.
9. THE Data_Stack SHALL include a CDK assertion test proving that the Write_Role and the Copilot_Role are distinct roles and that the Copilot_Role holds no permission to write or delete any curated-zone object.
10. WHEN `cdk synth` is executed for any of the three context environments with no AWS credentials present in the environment, THE Data_Stack SHALL write its CloudFormation template to the local output directory, SHALL terminate with a zero exit status within 120 seconds, and SHALL invoke no AWS API that creates, updates, or deletes a resource.
11. THE Data_Stack SHALL apply all four mandatory Cost_Allocation_Tags (`Project`, `Environment`, `Owner`, `CostCenter`) inherited from the Stage 1 `TaggedStack` base, and SHALL include an assertion test proving every synthesized resource-bearing stack carries the four tags with non-empty values.
12. THE Data_Stack SHALL contain no Always_On_Resource — no NAT Gateway, no Amazon RDS instance, no unassociated Elastic IP, and no Amazon SageMaker AI endpoint or notebook — and no construct for Amazon_Bedrock, Amazon SageMaker AI, or Amazon Bedrock AgentCore, and SHALL include an assertion test proving the synthesized template contains zero resources of those types.
13. THE Bootstrap_Target SHALL deploy the Stage 1 budget stack before the Data_Stack, so that the cost alarms exist before any data resource is created.

### Requirement 2: Implement the S3 ObjectStore adapter

**User Story:** As the AWS engineer, I want an Amazon S3 adapter that satisfies the ObjectStore contract exactly as the local adapter does, so that swapping `storage.provider` from `filesystem` to `s3` changes where bytes live without changing any caller.

#### Acceptance Criteria

1. THE S3_Store_Adapter SHALL be defined at `adapters/aws/s3_store.py` and SHALL implement the ObjectStore Port methods `put`, `get`, `list`, and `exists` with the parameter names and return types declared in `src/youth_compass/ports/object_store.py`.
2. WHEN `put` is called, THE S3_Store_Adapter SHALL write the content to Amazon_S3 under the given key, SHALL return the scheme-qualified URI of the stored object, and SHALL record a content checksum for the stored bytes.
3. WHEN `get` is called for a URI that was never written, THE S3_Store_Adapter SHALL raise `ObjectNotFoundError` and SHALL NOT allow a `botocore.ClientError` or any other technology-specific exception to propagate.
4. THE S3_Store_Adapter SHALL translate every `botocore` and operating-system exception raised by its underlying calls into the Domain_Error type declared by the ObjectStore Port before it crosses the port boundary.
5. WHEN `put` writes the same key twice, THE S3_Store_Adapter SHALL leave exactly one readable object carrying the later content, and a subsequent `list` of that key's prefix SHALL return the key exactly once.
6. THE S3_Store_Adapter SHALL be bound to the Stage 1 ObjectStore Contract_Test_Suite by a single factory registered with `@register_object_store("s3-moto")` in `tests/contract/`, requiring zero edits to the ObjectStore contract class body.
7. WHEN the Contract_Test_Suite runs against the `s3-moto` binding, THE S3_Store_Adapter SHALL route every `boto3` call to Moto, SHALL read no AWS credentials from the environment or from `~/.aws/`, and SHALL report zero failed, errored, or skipped contract cases.
8. THE S3_Store_Adapter SHALL be covered by an opt-in real-account integration test that is skipped by default, runs only when an explicit environment variable or marker selects it, and exercises `put`, `get`, `list`, and `exists` against a real Amazon_S3 bucket in `ap-northeast-1`.
9. THE `adapters/aws/` package SHALL not be imported by any module under `src/youth_compass/`, and the Stage 1 guard test asserting no `boto3` import under `src/youth_compass/` SHALL continue to pass.

### Requirement 3: Implement the Glue + DynamoDB DataCatalog adapter

**User Story:** As the AWS engineer, I want a catalog adapter that keeps schemas in Glue and application metadata in DynamoDB while satisfying the DataCatalog contract, so that the domain registers and retrieves datasets without knowing two AWS services sit behind the Port, and a bad publish can be rolled back without deleting data.

#### Acceptance Criteria

1. THE Glue_Catalog_Adapter SHALL be defined at `adapters/aws/glue_catalog.py` and SHALL implement the DataCatalog Port methods `register`, `get`, and `search_compatible` with the parameter names and return types declared in `src/youth_compass/ports/catalog.py`.
2. WHEN `register` is called, THE Glue_Catalog_Adapter SHALL store the dataset's column schema in the Glue_Database and SHALL store the application metadata — approval status, quality score, mapping version, and the published-version pointer — in the Amazon_DynamoDB table.
3. WHEN `get` is called for a `dataset_id` that was never registered, THE Glue_Catalog_Adapter SHALL raise `DatasetNotFoundError` and SHALL NOT allow a `botocore.ClientError` or any other technology-specific exception to propagate.
4. WHEN `register` is called twice with the same identifier, THE Glue_Catalog_Adapter SHALL leave exactly one retrievable record carrying the later field values, matching the DataCatalog contract.
5. THE Glue_Catalog_Adapter SHALL maintain a published-version pointer in the Amazon_DynamoDB table such that repointing it to an earlier version restores that version as published without deleting any prior version's schema or data.
6. THE Glue_Catalog_Adapter SHALL translate every `botocore` exception raised by its Glue and DynamoDB calls into the Domain_Error type declared by the DataCatalog Port before it crosses the port boundary.
7. THE Glue_Catalog_Adapter SHALL be bound to the Stage 1 DataCatalog Contract_Test_Suite by a single factory registered with `@register_catalog(...)` in `tests/contract/`, requiring zero edits to the DataCatalog contract class body.
8. WHEN the Contract_Test_Suite runs against the Glue_Catalog_Adapter binding, THE adapter SHALL route every `boto3` call to Moto, SHALL read no AWS credentials from the environment or from `~/.aws/`, and SHALL report zero failed, errored, or skipped contract cases.

### Requirement 4: Implement the Athena QueryEngine adapter with guardrails

**User Story:** As the AWS engineer, I want an Athena adapter that renders the typed QuerySpec into SQL entirely inside the adapter and refuses anything outside the allowlist or over the cost cap, so that the copilot can ask analytical questions without any caller, including the copilot, ever submitting raw SQL or running away with the scan bill.

#### Acceptance Criteria

1. THE Athena_Query_Adapter SHALL be defined at `adapters/aws/athena_query.py` and SHALL implement the QueryEngine Port method `execute` with the parameter names and return types declared in `src/youth_compass/ports/query_engine.py`.
2. THE Athena_Query_Adapter SHALL render the typed `QuerySpec` into Amazon_Athena SQL entirely within the adapter, and no SQL string SHALL be accepted from, or returned to, any caller across the port boundary.
3. WHEN `execute` receives a `QuerySpec` naming a table, metric, or dimension outside the configured allowlist, THE Athena_Query_Adapter SHALL raise `QueryNotPermittedError`, SHALL return no rows, and SHALL run no Amazon_Athena query.
4. THE Athena_Query_Adapter SHALL enforce the `max_rows` limit from the `QuerySpec`, a configurable query timeout, and a configurable scanned-bytes cap, and IF a permitted query reaches the timeout or would scan at or above the cap, THEN THE adapter SHALL raise `QueryExecutionError` reporting the limit that was reached.
5. WHEN a permitted query fails to execute for a reason other than the allowlist, THE Athena_Query_Adapter SHALL raise `QueryExecutionError` and SHALL NOT allow a `botocore.ClientError` or any other technology-specific exception to propagate.
6. WHEN an identical `QuerySpec` is executed twice against unchanged data, THE Athena_Query_Adapter SHALL return the same row count, identical row values in identical order, and identical column names in identical order, matching the QueryEngine contract.
7. THE Athena_Query_Adapter SHALL populate the `scanned_bytes` field of the returned `QueryResult` with the byte count Amazon_Athena reports for the query.
8. THE Athena_Query_Adapter SHALL be bound to the Stage 1 QueryEngine Contract_Test_Suite by a single factory registered with `@register_query_engine(...)` in `tests/contract/`, requiring zero edits to the QueryEngine contract class body, and SHALL report zero failed, errored, or skipped contract cases while routing every `boto3` call to Moto.

### Requirement 5: Implement the EventBridge EventBus adapter

**User Story:** As the AWS engineer, I want an EventBridge adapter that publishes and delivers the audit event vocabulary the system already speaks, so that domain events reach subscribers in production the same way they do in the in-memory reference bus.

#### Acceptance Criteria

1. THE EventBridge_Bus_Adapter SHALL be defined at `adapters/aws/eventbridge_bus.py` and SHALL implement the EventBus Port methods `publish` and `subscribe` with the parameter names and return types declared in `src/youth_compass/ports/event_bus.py`.
2. THE EventBridge_Bus_Adapter SHALL carry the dotted audit event vocabulary fixed in `docs/08-quality-security-observability.md` section 6 as each event's `event_type`, unchanged across publish and delivery.
3. WHEN an event is published, THE EventBridge_Bus_Adapter SHALL deliver it to every handler subscribed to that event's type in publish order, and SHALL deliver no event to a handler subscribed to a different type, matching the EventBus contract.
4. THE EventBridge_Bus_Adapter SHALL translate every `botocore` exception raised by its Amazon_EventBridge calls into the Domain_Error hierarchy before it crosses the port boundary.
5. THE EventBridge_Bus_Adapter SHALL be bound to the Stage 1 EventBus Contract_Test_Suite by a single factory registered with `@register_event_bus(...)` in `tests/contract/`, requiring zero edits to the EventBus contract class body.
6. WHEN the Contract_Test_Suite runs against the EventBridge_Bus_Adapter binding, THE adapter SHALL route every `boto3` call to Moto, SHALL read no AWS credentials from the environment or from `~/.aws/`, and SHALL report zero failed, errored, or skipped contract cases.

### Requirement 6: Package the deterministic transforms for Lambda (ARM64)

**User Story:** As the AWS engineer, I want the profiling and mapping logic packaged as an ARM64 Lambda function that calls the existing backend code rather than reimplementing it, so that the workflow runs the exact logic the local CLI runs and produces byte-identical results.

#### Acceptance Criteria

1. THE Transform_Lambda SHALL be an AWS_Lambda handler that calls the existing Deterministic_Transforms `profile_csv` (from `src/youth_compass/ingestion/csv_profiler.py`) and `analyze_mapping` (from `src/youth_compass/mapping/engine.py`), and SHALL contain no reimplementation of the profiling or mapping logic.
2. THE Transform_Lambda package SHALL be built for the ARM64 architecture required by `docs/01-system-architecture.md` section 8, and every dependency it bundles SHALL provide an installable distribution for CPython 3.12 on ARM64.
3. WHEN the packaged Transform_Lambda handler is invoked on the `tests/fixtures/employment_unfamiliar.csv` fixture, THE handler SHALL produce output byte-identical to the output the local CLI produces from the same input.
4. THE Transform_Lambda SHALL be covered by a test that invokes the packaged handler on `tests/fixtures/employment_unfamiliar.csv` and asserts byte-identical equality with the local CLI output for that fixture.
5. THE Transform_Lambda SHALL translate every failure it surfaces across a port boundary into the Domain_Error hierarchy, and SHALL allow no `botocore` or other technology-specific exception to escape as the handler's error contract.
6. THE Transform_Lambda handler code SHALL live under `adapters/aws/` and SHALL not be imported by any module under `src/youth_compass/`, keeping the Ports_And_Adapters_Rule intact.

### Requirement 7: Build the Step Functions ingestion workflow with a human-approval callback

**User Story:** As the AWS engineer, I want a Step Functions state machine that carries a file from arrival to publish, pausing for a human decision at the confidence gate and routing failures to quarantine, so that the ingestion workflow the WorkflowRunner Port promises actually runs in AWS with a real approval pause and never corrupts published data on a failed run.

#### Acceptance Criteria

1. THE Ingestion_Workflow SHALL be an AWS_Step_Functions State_Machine whose states, in order, are profile, map, validate, a confidence gate, an approval pause, transform, quality, and publish, with failure transitions routing to the quarantined zone.
2. THE Ingestion_Workflow SHALL implement the WorkflowRunner Port methods `start_ingestion` and `resume_after_approval` with the parameter names and return types declared in `src/youth_compass/ports/workflow_runner.py`.
3. WHEN a `QuerySpec`-style confidence gate determines that human approval is required, THE Ingestion_Workflow SHALL suspend at the approval state using the Wait_For_Task_Token pattern and SHALL remain suspended, incurring no per-hour charge, until a reviewer returns the Callback_Token with a decision.
4. WHEN a reviewer resumes a suspended workflow through `resume_after_approval` with an approving `ApprovalDecision`, THE Ingestion_Workflow SHALL proceed from the approval state to transform, quality, and publish; and with a rejecting decision it SHALL route the job to the quarantined zone.
5. WHEN `resume_after_approval` is called with a `job_id` that is unknown or already settled, THE Ingestion_Workflow SHALL raise `WorkflowStateError`, matching the WorkflowRunner Port contract.
6. IF any state in the workflow fails, THEN THE Ingestion_Workflow SHALL route the job to the quarantined zone and SHALL leave the curated zone unchanged.
7. THE published dataset in the curated zone SHALL be byte-identical before and after a failed ingestion of a different file, so a failed run of one file cannot alter another file's published data.
8. THE Ingestion_Workflow SHALL auto-start on arrival of an object in the incoming bucket, triggered through Amazon_S3 event notification or an Amazon_EventBridge rule, requiring no manual start for a normal ingestion.
9. THE Ingestion_Workflow SHALL be bound to the Stage 1 WorkflowRunner Contract_Test_Suite by a single factory registered with `@register_workflow_runner(...)` in `tests/contract/`, requiring zero edits to the WorkflowRunner contract class body, and SHALL report zero failed, errored, or skipped contract cases while routing every `boto3` call to Moto.
10. THE Ingestion_Workflow definition SHALL incur no AWS_Step_Functions or AWS_Lambda charge while no ingestion is in progress, consistent with the per-use cost constraint.

### Requirement 8: Wire the bootstrap flow end to end and rehearse

**User Story:** As the AWS engineer with a personal account and six days before the competition, I want the one-command bootstrap to complete all five steps against a real account and the smoke and export commands to exercise the deployed data path, so that I rehearse the entire flow before 9/12 instead of debugging it on stage.

#### Acceptance Criteria

1. WHEN the operator invokes `make hackathon-bootstrap` against an account with the Data_Stack available, THE Bootstrap_Target SHALL complete all five steps in order — Preflight_Checker, CDK bootstrap, budget stack deployment, Data_Stack deployment, Smoke_Tester — where previously it correctly errored at the missing data-stack step.
2. THE Bootstrap_Target SHALL deploy the budget stack before the Data_Stack, so the cost alarms exist before any data resource is created.
3. WHEN the Smoke_Tester is invoked with the `--real` flag against the deployed Data_Stack, THE Smoke_Tester SHALL exercise the deployed data path — writing to and reading from a Data_Zone bucket, registering and retrieving a catalog record, and running one guarded Amazon_Athena query — and SHALL clean up every resource it created.
4. WHEN the Data_Exporter is invoked against the deployed buckets, THE Data_Exporter SHALL copy every object from the selected Data_Zone buckets and export the Glue_Database and its table definitions, writing a manifest of what was exported.
5. THE whole flow — bootstrap, smoke test, and export — SHALL be rehearsable end to end on the engineer's personal AWS account in `ap-northeast-1` before 9/12 2026, at a total cost within single-digit US dollars.
6. WHEN `uv run pytest` is executed at the repository root, THE existing 328 tests SHALL all continue to pass, and every Stage 2 adapter SHALL run its Port's Contract_Test_Suite under Moto with zero failed, errored, or skipped cases.
7. THE repository SHALL document Stage 2 by updating `docs/12-aws-stage1-foundation.md` or adding a new Stage 2 document under `docs/`, recording for every artifact this feature delivers its repository-relative file path and a one-sentence purpose, covering the Data_Stack, the four AWS adapters, the Transform_Lambda, and the Ingestion_Workflow.
8. THE Data_Stack, the adapters, the Transform_Lambda, and the Ingestion_Workflow SHALL contain no construct or call for Amazon_Bedrock, Amazon SageMaker AI, or Amazon Bedrock AgentCore, keeping those services deferred to Stage 3.
