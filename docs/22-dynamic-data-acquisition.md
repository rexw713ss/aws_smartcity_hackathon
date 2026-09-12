# Dynamic data acquisition

> Status: controlled local vertical slice implemented; automatic post-publication replay pending.

## Runtime flow

When a grounded query cannot find compatible published observations or feature values, the
copilot now builds a typed `DataRequirement`. If an enabled connector has a compatible source,
the response status is `acquisition_required` and includes public `source_candidates`.

```text
catalog gap -> data requirement -> discover_sources -> reviewer selects candidate
            -> acquire_source -> existing ingestion workflow -> awaiting approval
            -> mapping/quality review -> curated publication
```

The copilot does not accept a URL from the question or acquisition API. A reviewer submits only a
`candidateId` previously configured in the connector manifest:

```http
POST /api/v1/copilot/acquisitions
Content-Type: application/json

{"candidateId":"ntpc_population","submittedBy":"reviewer@example.com"}
```

The response contains the ingestion job ID. Existing ingestion endpoints provide mapping review,
approval, quality, and publication status.

## Connector policy

`AllowlistedHttpSourceConnector` enforces:

- HTTPS and an explicit hostname allowlist;
- no IP-literal hosts or user-supplied URLs;
- rejection of redirects, preventing a configured URL from bouncing to another host;
- configured candidate IDs, filenames, formats, publishers, and licenses;
- response content-type and maximum download-size limits;
- immutable snapshot handoff to the existing checksum-addressed object store.

CSV, JSON, and Excel candidates enter the same normalization, mapping, quality, and approval
pipeline as manual uploads. Downloaded data is never queried or passed to Bedrock before it is
approved and published.

## Configuration

Acquisition is disabled by default. Copy the `acquisition` block from
`configs/acquisition.example.yaml` into an environment configuration and replace the placeholder
host and URL with verified government endpoints. Every source must use the configured connector
ID and an allowlisted host.

## Remaining slices

1. Persist the original copilot query and replay it exactly once after publication.
2. Add live Taiwan government source manifests after endpoint/license verification.
3. Implement pagination and incremental refresh contracts for API datasets.
4. Map the connector to Lambda/EventBridge and the acquisition state to Step Functions on AWS.
5. Add reviewer UI controls for candidate selection and “approve and continue analysis”.
