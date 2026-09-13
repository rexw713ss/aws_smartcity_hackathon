# System diagrams

Two checked diagrams, rendered with [Archify](https://github.com/tt-a1i/archify). The
`.json` files are the source of truth; the `.html` files are generated, self-contained,
and safe to open or share directly.

| Diagram | Source | Answers |
|---|---|---|
| Deployed runtime | `youth-compass-runtime.architecture.json` | What is actually deployed, and how a question reaches published evidence |
| One grounded turn | `youth-compass-turn.workflow.json` | How a single question is classified, executed, narrated — and every way it refuses |

Two diagrams rather than one, because the first attempt mixed deployed services with
`youth_compass.ports` protocols and Archify's `deployment-ownership` profile correctly
rejected it: a port is a code-level abstraction, so it has no region and no security
group. The runtime map now shows only deployed components; the turn diagram shows the
logical pipeline.

## Regenerating

Archify is not a project dependency — it is a rendering tool run on demand.

```bash
git clone --depth 1 https://github.com/tt-a1i/archify.git /tmp/archify
cd /tmp/archify/archify && npm install --silent   # ajv, for schema validation

D=<repo>/docs/diagrams
node bin/archify.mjs validate architecture $D/youth-compass-runtime.architecture.json --quality showcase
node bin/archify.mjs deliver  architecture $D/youth-compass-runtime.architecture.json $D/youth-compass-runtime.html --quality showcase
node bin/archify.mjs validate workflow     $D/youth-compass-turn.workflow.json --quality showcase
node bin/archify.mjs deliver  workflow     $D/youth-compass-turn.workflow.json     $D/youth-compass-turn.html --quality showcase
```

Both sources pass `--quality showcase` with 9/9 artifact checks and zero composition
errors or warnings. `validate` is worth running before `deliver`: it checks geometry as
well as schema, and reports exact fixes — overlapping labels, edges crossing unrelated
nodes, shared corridors, non-orthogonal segments, and sublabels too small to read at a
1440px viewport.

## Named views

Each diagram ships guided views, reachable with `#view=<id>`:

- **Runtime** — `question-path`, `model-calls`, `state`, `publish-path`
- **Turn** — `happy-path`, `refusals`, `model-boundary`

## Keeping them honest

The numbers on the cards are measured, not estimated, and come from the local data root:

- `1153 ms → 23 ms` and `1.4 MB → 0 bytes` — a repeated question, before and after the
  version-keyed cache
- `94% smaller prompt` — `grounded_facts_json` fell from 127,226 to 7,318 characters on a
  1,044-point series once the whole series stopped being dumped into the compose call

If the agent's structure changes, update the `.json` and re-run `deliver`. A diagram that
describes code that no longer exists is the same failure the `routed_plan` had before it
was actually executed.
