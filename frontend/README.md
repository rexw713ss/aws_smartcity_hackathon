# 新北青策 — decision assistant frontend

A chat-first client for the grounded copilot. The conversation leads; charts,
citations, and the tool trace support it from the right pane.

## Contract

This client is typed against **`../contracts/api/openapi.json`** — the generated
backend contract — not against the design documents. Regenerate that file with
`uv run python scripts/export_openapi.py` and re-check `src/lib/copilot.ts`
whenever the copilot response changes.

Endpoints used:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/copilot/query` | The one grounded entry point |
| `GET` | `/api/v1/copilot/capabilities` | Tools this runtime advertises |
| `POST` | `/api/v1/copilot/acquisitions` | Submit one configured `candidateId` for review |

Request bodies use camelCase aliases (`entityIds`, `candidateId`); response
bodies are the domain contracts in snake_case (`tool_trace`, `visualization_id`).
That asymmetry is the backend's, and `src/lib/copilot.ts` matches it exactly.

## What this client does not do

It never recalculates a ranking, a change, or a percentage. The backend decides
the chart type, the field encodings, and every value; `ChartView` only draws
them. A response that breaks the published contract is rejected and shown as an
error rather than rendered. Answer strings render as plain React text, never as
markup.

## Run it

```bash
npm install
npm run dev
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so the browser makes
same-origin requests and the backend needs no CORS middleware. Point it
elsewhere with `YOUTH_COMPASS_API_ORIGIN`. Start the backend with `make local-api`
and materialize a feature snapshot with `make demo-features` first.

```bash
npm run typecheck   # tsc --noEmit
npm run build       # typecheck + production bundle
npm run test:e2e    # Playwright, mocked API (needs a browser installed)
```

## District map

The **Map** tab draws the 29 New Taipei districts and shades the ones the current
answer actually named, with Ember intensity set by the backend's own figure.
Clicking or focusing a district reads out that figure, its rank, and which
visualization it came from; a district the answer did not mention says so rather
than borrowing a neighbour's number.

Entity identifiers are resolved through `src/lib/districts.ts` by **exact** match
on a zero-padded code (`01`), a canonical Chinese name (`板橋區`), or a lowercase
English slug (`banqiao`) — the three shapes the backend actually emits. Anything
else, including sites like `site-banqiao-station`, is listed as unplaceable.
Substring matching is deliberately absent: guessing that a site named after a
district sits inside it would be an unfounded spatial join.

`districts.ts` is generated. After changing the backend dictionary or swapping
the atlas, run:

```bash
uv run python -m scripts.generate_district_dictionary
```

`tests/unit/test_district_dictionary.py` fails if the committed file drifts. It
also pins the trap the generator exists to avoid: the atlas `number` field is
alphabetical by English name, so atlas 2 is 板橋區 while backend code `02` is
三重區. Joining on `number` would mislabel every district silently.

## Design

The visual system is **Ventriloc** (`DESIGN.md`): editorial data observatory on
warm paper, ~95% achromatic, with Ember Orange as functional punctuation. Tokens
live in `src/base.css`; the component layer is `src/index.css`.

Four documented adaptations, each marked `ADAPTED` in `src/base.css`:

1. **Dark theme** — Ventriloc ships light only. The dark set is derived from the
   Graphite family, preserving hue roles and lifting Ember for contrast.
2. **Chart series palette** — Ember + Brass give two strokes; a multi-series line
   needs five. Extended within the warm and achromatic gamut only, alternating
   chromatic and achromatic so adjacent series separate by hue *and* lightness.
3. **Density** — 40px card padding and 80px section gaps are built for a
   marketing page; compressed to 20px/20px for a two-pane working tool.
4. **CJK** — district names and backend labels stay Traditional Chinese when a
   question is asked in Chinese. No latin display face covers Han characters, so
   those elements use Noto Sans TC and opt out of the -0.02em latin tracking.

PolySans is commercial; the system's own substitute, **Space Grotesk** at weight
400, is used instead. Ember is never a button fill — the dark Graphite button is
the primary action, per the component spec.
