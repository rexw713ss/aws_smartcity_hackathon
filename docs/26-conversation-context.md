# Conversation context for follow-up questions

## Why a session exists

Each `POST /api/v1/copilot/query` used to be answered in isolation, so a natural follow-up
lost the scope the previous turn had established:

| Follow-up | What must be inherited |
| --- | --- |
| `Còn Linkou thì sao?` | metric, time range, and analysis plan; the entity is replaced |
| `So với năm ngoái?` | metric and entities; the time range is replaced |
| `Chỉ lấy nhóm 20-29 tuổi.` | metric, entities, and time range; an age filter is added |

A session supplies only the missing fields. It never overrides anything the new question
states for itself.

## What the session stores

`ConversationContext` is a frozen Pydantic model holding the structured output of the
previous turn and nothing else:

| Field | Meaning |
| --- | --- |
| `session_id` | Opaque `ses_<32 hex>` identifier generated server-side |
| `revision` | Monotonic turn counter; an out-of-order write is discarded |
| `objective` | Short decomposition objective |
| `subject_terms`, `metric_terms`, `entity_ids` | Resolved analytical scope |
| `time_expression` | Period expression the observation tools already understand |
| `filters` | Allowlisted `AnalysisFilters`: an age band and a gender code |
| `operations` | The typed `AnalysisOperation` plan |
| `updated_at` | Timestamp used for expiry and eviction |

No transcript, prompt, model reasoning, answer text, or source URI is retained. A shared
contract suite runs every binding through the same cases, so no adapter can quietly retain
more or inherit differently.

Only a turn that actually answered is remembered. A scope that found no evidence is
discarded, because inheriting it would leave the session permanently unable to answer.

## Storage

`conversation.provider` selects the store; `conversation.ttl_minutes` and
`conversation.max_sessions` bound it.

| Provider | Behaviour |
| --- | --- |
| `memory` (default) | Process-local, thread-safe, evicts the least recently updated session past the cap. Correct for the CLI, the test suite, and a single-instance server. |
| `dynamodb` | Records in the shared metadata table under a `ses#<session_id>` namespace, expired by the table's native `expires_at` TTL and guarded by a conditional write on `revision`. |

The `memory` provider loses a session on restart, and on a multi-instance deployment a
follow-up routed to another instance is answered as a first turn. The API Lambda therefore
sets `conversation.provider: dynamodb` with the metadata table, since Lambda scales to many
concurrent instances.

A durable store is remote and can be unavailable. Both the read and the write are tolerant:
a failed read answers the turn without inherited scope, a failed write leaves the answer
intact, and each logs a warning. A session-store outage degrades follow-ups rather than
failing every request.

## Resolution rules

`ConversationContextResolver` is deterministic; no model call participates. Model-assisted
decomposition stays off by default for the reason recorded in `ModelSettings`, so follow-up
handling must not depend on it.

A live session may fill omitted fields when any of three independent signals holds, so an
unlisted phrasing is never a dead end:

1. An explicit marker in English, Vietnamese, or Traditional Chinese, such as `what about`
   or `còn ... thì sao`.
2. The decomposition would otherwise dead-end in a clarification request. Inheriting a known
   scope is strictly better than answering nothing. This is what resolves a bare `Linkou?`.
3. The question is a refinement of at most five words that changes one axis and leaves the
   others unstated. A question that states its own metric, entity, and period is
   self-contained and inherits nothing, however short it is.

Given inheritance, the merge rules are:

1. Entities come from the new question first; otherwise from a previously named entity, an
   explicit `what about X` / `còn X` mention, or a bare name when the decomposer recognized
   no metric in the question; otherwise the previous entities stand. A captured name is
   resolved through `youth_compass.ontology`, so `Lâm Khẩu`, `Linkou`, and `林口區` all reach
   rows keyed `17`. A bare phrase counts only when the ontology recognizes it, because
   `So với năm ngoái?` has the same shape as a bare place name. A name behind an explicit
   marker is kept verbatim when unrecognized, so the failure reports the place actually asked
   for rather than a truncated fragment.
2. A new time expression, age band, or gender replaces the stored one; an omitted one is
   inherited. A one-sided bound such as `under 25` replaces the whole stored range rather
   than keeping a lower bound that would contradict it.
3. The stored plan is adopted only when the new decomposition asked for clarification. A
   self-sufficient decomposition keeps its own objective and operations.

When inheritance changes the resolved query, the response `tool_trace` reports
`conversation_context` with outcome `applied`.

A one-sided age bound requires an explicit age cue such as `tuổi`, `ages`, or `歲`, so
`from 2020 to 2024` is read as a period and never as an age range. Naming both genders is
treated as the whole population rather than as a filter.

## Filtering canonical breakdowns

Canonical facts sit at age-band and gender grain, and `age_lower`, `age_upper`, and
`gender_code` are all nullable. The two filters reach the data differently, and the difference
matters on a real dataset:

- **Gender** is an equality filter pushed into the `QuerySpec`, so the engine drops rows
  before grouping. Projecting it as a grouping dimension instead multiplied the returned rows
  and tripped the 100000-row guard on the published 182700-row population dataset.
- **Age** is a band, which equality cannot express, so the two bound columns are projected and
  containment is applied after the scan. A row survives only when its band is fully contained
  in the requested scope, so a citywide total or a wider band is never split into an invented
  number.

An unfiltered question projects neither, keeping the narrower scan it already had. A gender
filter accepts only an exact canonical code from the `mapping.gender` vocabulary. When a
filter removes every row, the turn fails closed with `insufficient_data` and a warning naming
the filter that did it:

| Filter | Warning |
| --- | --- |
| Age | `the dataset has no age band contained in the requested age scope` |
| Gender | `the dataset has no rows broken down by the requested gender` |

An applied filter is never silent. It appears in the `query_observations` trace summary, in
the grounded facts, and in the composed answer, so a reader can see which population the
numbers describe.

## API contract

```http
POST /api/v1/copilot/query
Content-Type: application/json

{
  "question": "Còn Linkou thì sao?",
  "sessionId": "ses_0123456789abcdef0123456789abcdef"
}
```

`sessionId` is optional. The response always returns `session_id`; a request without one
starts a new session. An expired or unknown identifier is treated as a first turn rather than
an error, so the client can keep reusing the value it holds. A turn that ends in
`unsupported_question` with a clarification request is not stored, so an unanswered question
cannot poison later scope.

The React frontend and the Streamlit dashboard both keep the returned identifier and send it
with the next question.

## Verification

The shared `ConversationContextStore` contract runs against both the in-memory and the
DynamoDB binding, the latter under moto. It covers round-trip, absence, revision ordering,
session isolation, and the promise that no conversational text is retained. Unit tests cover
the resolver's three follow-up signals, the age and gender parsers, the year-range false
positive, store expiry and eviction, and the two failure-tolerance paths.
