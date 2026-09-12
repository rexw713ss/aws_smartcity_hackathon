# Chart motion and AI frontend handoff

## Implemented plan

1. Keep text, numbers, filters, and chart axes stationary. Retain Lenis document
   scrolling and the isolated, illustrative 3D city.
2. Start line/area plots completely blank, draw through a shared left-to-right
   mask over 2.2 seconds, then stop. Re-run for changed data, with a manual
   **Replay draw** control on population trends. Offscreen/hidden-tab draws pause;
   returning to a completed chart does not restart it. Reduced motion shows the
   complete data immediately, with the existing explicit app-only opt-in intact.
3. Add a context-aware assistant: chart shortcuts, suggested questions, source
   evidence, limitations, downloadable briefs, and explicit dashboard actions.
4. Connect through the repository's existing copilot contract, with validation,
   cancellation, timeout, retry, and isolated district/year/chart conversations.

## What works without a backend

The sidebar's **AI assistant** and each **Ask about this chart** button open an
inline workspace. Default **CSV preview · no AI connected** mode calculates
facts from the same loaded CSV values as the dashboard. It makes no AI requests
and does not interpret free-form prompts. There is no simulated thinking delay,
fake streaming, invented confidence score, or fabricated prediction.

Suggested tasks: summarize a chart, identify its largest displayed value, and
explain limitations. Saved text briefs retain preview/AI attribution, source
periods, evidence, and warnings. This is not an AI-generated-chart implementation:
the current backend contract returns explanations and dashboard actions, not
arbitrary chart specifications.

## Connect the backend

The server bootstrap currently implements only /health; the following copilot
routes are **documented but must still be implemented by the backend team**.
No backend code was changed for this frontend work.

Create frontend/.env.local using .env.example, set the public API base, and
restart Vite:

    VITE_COPILOT_API_BASE=http://127.0.0.1:8000/api/v1

On user submission the frontend sends:

    POST /api/v1/copilot/sessions
    Content-Type: application/json

    {}

Expected session response:

    { "sessionId": "ses_example" }

Then POST /api/v1/copilot/chat with application/json:

    {
      "sessionId": "ses_example",
      "message": "Summarize this chart",
      "dashboardContext": {
        "selectedDistricts": ["0"],
        "period": { "start": "2011-12", "end": "2026-07" },
        "activeMetric": "youth_population",
        "activePanel": "population-trend"
      }
    }

These values are an example of the current citywide population view, not static
defaults sent for every chart. Source records are retrieved by the backend;
the browser sends aggregate identifiers/context, not whole CSVs or personal data.

Return the synchronous structured response from ../docs/04-agentic-ai.md:

    {
      "answer": "An evidence-backed explanation.",
      "evidence": [{
        "datasetId": "fact_youth_population_monthly",
        "datasetVersion": "your-real-release-id",
        "metric": "youth_population",
        "period": "2026-07",
        "districtCode": "0",
        "value": 1234,
        "unit": "persons",
        "isEstimated": false
      }],
      "warnings": ["Example only: return actual limitations for the result."],
      "dashboardActions": [{ "type": "OPEN_PANEL", "value": "population-trend" }]
    }

**1234 is a schema example, not a population claim.** The UI validates response
types, finite numbers, sizes, and action shapes; it cannot independently certify
that an AI answer or evidence is factually correct. Empty evidence is explicitly
flagged. Answer strings render as plain React text, never executable HTML.

## Context mapping to confirm with backend teammates

| Frontend panel | activeMetric | Period and scope |
| --- | --- | --- |
| population-trend | youth_population | First to selected snapshot; youth 15–39 |
| age-structure | youth_age_distribution | Selected snapshot month; youth 15–39 |
| education-levels | education_distribution | Latest annual release at/before selected year; all recorded residents |
| marriage-status | youth_marriage_distribution | Latest annual release at/before selected year; youth 15–39 |
| migration-forecast | outbound_migration | Fixed 2026 Jan–Dec; all-age outbound moves |

District codes are strings from the cleaned CSV: "0" citywide, "1"–"29"
districts. Action responses also accept zero-padded numeric district codes. The
backend should map these identifiers to its canonical catalog, rather than
assuming the CSV uses a different coding scheme.

Annual education/marriage query bounds are January–December, not a claim that
the source records specify those months. The UI displays the release year in
evidence and explains that the CSV does not supply a reference month.
Education before 2017 / marriage before 2019 are unavailable, never filled with
zero-valued AI facts. Migration does not reveal destination districts or unique
individuals and is not youth-specific.

The five metric identifiers above are frontend integration identifiers. The
existing backend documents do not enumerate every catalog metric; agree these
mappings before enabling the production API.

## Dashboard actions and safety

Actions are presented as buttons and never automatically executed.

- OPEN_PANEL: allowlisted existing dashboard IDs; forecast aliases
  migration-forecast.
- SELECT_DISTRICTS: one district from the current CSV; multi-district actions
  show an unsupported explanation because this dashboard has a single selection.
- SET_PERIOD: an exact published snapshot month (identical start/end); arbitrary
  ranges are explicitly unsupported by the current year-only filter.
- SET_METRIC: one of the five mapped metrics.

Responses accept type or action as the per-action discriminator, reflecting
the two examples in the existing docs. Unsupported action types reject the
response; unsupported values are shown but cannot be applied.

Requests time out after 30 seconds and responses are bounded to 256 KB. Cancel,
clear, context changes, and unmount abort pending requests. Late responses cannot
replace a different context's answer. A failure or cancellation discards the
server session ID so retry cannot accidentally continue a half-finished turn.
The backend still owns server-side cancellation/resource limits.

## Backend responsibilities / next milestones

- Implement sessions/chat, LLM orchestration, typed analytics tools, evidence
  retrieval, forecasting/model provenance, and factual checks.
- Enforce authentication, authorization, rate limits, input safety, session
  retention, and privacy on the server.
- Configure CORS for the actual frontend origin (localhost:5173 and/or
  127.0.0.1:5173). Client uses same-origin credentials only. Prefer a same-origin
  authenticated gateway for production; do not expose provider keys in Vite.
- Implement SSE progress using the documented event protocol if desired. This
  frontend milestone uses synchronous JSON, not fake token streaming.
- If AI-generated charts are wanted next, agree a bounded chart specification
  with metric, units, period, source evidence, and allowlisted chart types before
  implementing a renderer. Never execute model-supplied JavaScript or JSX.

## Verification

    npx tsc --noEmit
    npm run build
    npm run test:e2e

Motion tests verify zero-width → half-width → finished masks and unchanged plot
geometry/axis text. Assistant tests cover preview honesty, real source context,
missing releases, export, the mocked API payload, retry, cancel, stale responses,
malformed actions, and user-approved district selection on desktop and mobile.
Mocked API tests validate the frontend integration, not a working AI backend.
