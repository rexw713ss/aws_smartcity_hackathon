# AWS Integration Review

> Reviewed commit: `7b04adf`
> Owner: AWS integration workstream
> Scope: review only; the backend workstream does not modify AWS adapters in this milestone.

## Release recommendation

Stage 2 is a useful adapter and infrastructure scaffold, but it is not ready for a
real-account demo until the blockers below are closed. Moto contract tests prove
the port shape; they do not prove Athena SQL safety or a real Step Functions
callback lifecycle.

## Blockers

### AWS-01 — Athena SQL construction permits injection

Severity: **Critical**

`adapters/aws/athena_query.py` interpolates filter values and identifiers into SQL.
An empty allowlist currently disables validation, while filter and order-by fields
are not checked against the dimension allowlist.

Acceptance criteria:

- Fail closed when an allowlist is absent or empty.
- Validate tables, selected fields, filter fields, and order-by fields.
- Reject identifiers outside a strict canonical identifier grammar.
- Encode literals without direct string interpolation.
- Add malicious table, column, order-by, and string-filter test cases.

### AWS-02 — Step Functions failures are reported as successful jobs

Severity: **Critical**

`adapters/aws/step_functions_runner.py` suppresses every `ClientError`, creates a
fake callback token, and stores status only in process memory. Approval does not
call `send_task_success` or `send_task_failure`.

Acceptance criteria:

- A failed `start_execution` raises a domain error and creates no successful job.
- Callback tokens come from the running state machine and are stored durably.
- Approval resumes the waiting task through the Step Functions API.
- State survives Lambda/container restarts.
- At least one real-account rehearsal covers start, pause, approve, and reject.

### AWS-03 — Unapproved versions can become published

Severity: **High**

`adapters/aws/glue_catalog.py` moves the `__published__` pointer for every
registered record, including received, quarantined, and rejected versions.

Acceptance criteria:

- Registering a non-published version never changes the live pointer.
- Publication uses a conditional/transactional pointer update.
- The previous pointer remains available for rollback.
- Tests cover received, rejected, quarantined, published, and rollback cases.

## Required before integration

### AWS-04 — Transform Lambda is not an S3 ingestion worker

The handler accepts only a local `source_path` and performs profile/mapping. It
does not download an S3 object, execute the full transformation, publish Parquet,
or update the catalog.

Acceptance criteria:

- Accept the agreed ingestion event containing a source URI and job ID.
- Read source bytes through `ObjectStore` or an S3 adapter.
- Invoke the backend application use case rather than reimplementing domain logic.
- Publish standardized/curated artifacts and persist the resulting manifest.

### AWS-05 — DataStack permissions do not support the documented workflow

The ingestion role cannot read `incoming`, write `quarantined`, or update Glue.
The stack also does not provision the Lambda/Step Functions integration described
by the Stage 2 narrative.

Acceptance criteria:

- Grant only the required incoming, quarantine, standardized, curated, metadata,
  DynamoDB, Glue, and event permissions.
- Provision and connect the worker, workflow, triggers, and log groups.
- Retain curated and metadata resources outside disposable development stacks.

### AWS-06 — S3 operational failures are disguised as missing objects

`AccessDenied`, throttling, and service failures are translated to
`ObjectNotFoundError` or `False`.

Acceptance criteria:

- Return not-found only for the documented missing-key codes.
- Translate other failures to an explicit domain operation error.
- Restrict scheme-qualified URIs to the configured bucket.
- Verify the stored SHA-256 when reading an object.

## Quality gate

The reviewed branch had two Ruff failures:

- `SIM105` in `adapters/aws/step_functions_runner.py`;
- `F401` in `tests/contract/conftest.py`.

The AWS workstream should make `ruff check`, `ruff format --check`, `mypy`, and the
offline test suite pass before asking the backend workstream to integrate again.
