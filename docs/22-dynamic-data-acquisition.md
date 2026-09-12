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

## In the conversation

A response that stops for lack of data is answered in the chat as a second assistant turn. It
states what is missing from `impact_analysis.data_gaps` or `data_requirement`, suggests the top
source candidate for the reader to accept or reject, and offers two ways to supply the data
instead. No source table is drawn in the insight pane.

| Reader choice | Endpoint | What the backend accepts |
|---|---|---|
| Accept the suggestion | `POST /api/v1/copilot/acquisitions` | A configured `candidateId` only |
| Upload a file | `POST /api/v1/datasets/upload` | CSV, JSON, or Excel up to 25 MiB; write token when configured |
| Paste a link | `POST /api/v1/copilot/acquisitions/link` | An HTTPS URL on `acquisition.link_allowed_hosts` |

`GET /api/v1/copilot/intake-options` tells the chat which link hosts are allowed and the upload
limit, so the reader sees the rule before trying.

The agent's connectors still never take a URL. A pasted link comes from a person, and
`AllowlistedLinkFetcher` fetches it with the same HTTPS, host, redirect, credential, content-type,
and size rules as a configured source. Only the path is the reviewer's choice. The format comes
from the path suffix, then a `/csv/` or `/json/` path segment, then the declared content type; a
link that states none of these is refused with a request to upload the file. Every path ends in
the same approval-gated ingestion workflow, and nothing is published without approval.

## Connector policy

`AllowlistedHttpSourceConnector` enforces:

- HTTPS and an explicit hostname allowlist;
- no IP-literal hosts, embedded credentials, or agent-supplied URLs;
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
5. Add an “approve and continue analysis” control once a submitted job is published.
