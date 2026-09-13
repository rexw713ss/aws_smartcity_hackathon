# Insightful visualizations

> Status: stages 1-6 implemented and wired through the observation answer path.
> Outstanding: a `stacked_bar` template (no part dimension is published yet), the
> model-proposed `VisualizationIntent` of stage 5, and a CLI entry point for the stage 6
> rubric.

Doc 23 defines *what* a `VisualizationSpec` is. This document defines *how the agent decides
which spec to build, in which unit, and whether that spec is worth showing at all*.

## Problem

The builders in `src/youth_compass/agent/visualization.py` append every spec they can construct,
gated only by cardinality checks (`ranking_is_useful` at :79 counts rows; `comparison_is_useful`
at :215 counts rows). Three consequences:

1. **No data inspection.** A rich `DatasetProfile` exists (`src/youth_compass/ingestion/csv_profiler.py`)
   but it profiles the *raw file at ingest*. At answer time the agent sees only
   `DatasetInspection.quality_score` — one float. It cannot tell a flat series from a trending one,
   nor a partial final period from a real decline.
2. **No unit decision.** `unit_code` passes through untouched, so districts of wildly different
   population are compared in absolute counts, which restates their size rather than their behaviour.
3. **No selection or evaluation.** Nothing scores a candidate chart, and nothing rejects a weak one.

Spatial intent is additionally detected by a regex over the raw question (`_wants_map` at :612),
which fires on the word "quận"/"區" even for a single-district trend question.

## Target pipeline

```
observations / decision / forecast result
  → 1. profile_series          deterministic shape, distribution, signal, issues
  → 2. choose_measure          raw | index_100 | pct_change | yoy_change | share_of_total | per_1000
  → 3. build candidates        every defensible spec, deterministic rows
  → 4. score and select        informativeness + intent fit + redundancy penalty → 0..2 specs
  → 5. headline and annotate   model proposes under an allowlist; code supplies every number
  → 6. evaluate                rubric, in evals and optionally as a runtime gate
```

Stages 1–4 are deterministic and testable without a model. Stage 5 is the only model step and
follows the existing `AnswerDraft` contract: the model may choose and phrase, never compute.

## Stage 1 — Result profiling (`agent/data_shape.py`)

`profile_series(series) -> SeriesProfile`, computed from the rows an answer actually used.

| Group | Fields |
|---|---|
| Structure | `entity_count`, `period_count`, `granularity` (`year`/`month`/`mixed`/`unknown`), `coverage_ratio`, `periods` |
| Temporal coverage | `expected_monthly_points`, `missing_monthly_points`, `monthly_coverage_ratio`, `plot_interval_months` |
| Distribution | `value_min`, `value_max`, `value_median`, `spread_ratio` (max/min across entities in the latest shared period), `coefficient_of_variation` |
| Signal | `net_change_ratio` per entity (`|last - first| / first`), `signal_to_noise` (`|net change| / stdev of first differences`), `is_flat`, `direction` |
| Issues | `tuple[DataIssue]` with a stable `code`, severity, and affected entities/periods |

Issue codes (reusing the vocabulary of `domain/profiles.ProfileWarning`):

- `DUPLICATE_OBSERVATION` — two values for the same (entity, period).
- `NEGATIVE_COUNT` — a negative value on a count metric.
- `PARTIAL_LATEST_PERIOD` — the newest period is reported by materially fewer entities than the
  previous one; a line drawn through it shows a fabricated cliff.
- `LEVEL_SHIFT` — a single-step change far outside the series' own step distribution, which usually
  means a definition change rather than a real event.
- `SPARSE_COVERAGE` — `coverage_ratio` below the point where a multi-series line is honest.

Unmapped entities and the estimated-value share are exposed as plain fields
(`unmapped_entity_ids`, `estimated_point_ratio`) rather than issues: `limitations.py` already
narrates both, and selection needs them as inputs, not as a second caveat.

The profile feeds stages 2–4 and the internal agent trace. It never modifies a value, and
`limitations.py` remains the owner of freshness and coverage reporting.

For monthly data, the profiler expands each entity's first-to-last calendar span before counting
coverage, so a month absent from every returned row is still detected. It selects the smallest
cadence among month, quarter, half-year, year, and two-year blocks that both fits the chart budget
and avoids gratuitous gaps. A coarser point is the last actually published observation in that
bucket—not an interpolation or average—and retains `source_period` for the tooltip. Empty coarse
buckets do not create synthetic null rows; their missingness remains available in the trace.

## Stage 2 — Measure selection (`agent/measures.py`)

`choose_measure(profile, decomposition) -> Measure{transform, unit_code, label, rationale}`.

| Transform | Chosen when |
|---|---|
| `raw` | One entity, or entities of comparable magnitude (`spread_ratio` below threshold) |
| `index_100` | Trend question, ≥2 entities, `spread_ratio` above threshold — levels hide the shape |
| `pct_change` | Change question where the caller asks how fast, not how much |
| `yoy_change` | Monthly granularity spanning ≥2 years, where month-to-month is seasonal noise |
| `share_of_total` | Composition question over parts that sum to a whole |
| `per_1000` | A denominator series is available for every entity shown |

`per_1000` and `per_capita` need a population denominator the observation path does not fetch today;
they stay in the allowlist but are gated on denominator availability and land after stage 4.
`rationale` is surfaced under the chart and passed into the answer context so prose and axis agree.

## Stage 3 — Candidates (`agent/visualization.py`)

Each branch builds a *pool* rather than a final tuple. New templates, added to the doc-23 allowlist:

| Type | Fills the gap | State |
|---|---|---|
| `slope` | Two periods × many entities — the natural "who moved most" chart | Built when a result has exactly two periods and at least three entities |
| `scatter` | The multi-dataset join path, which could only emit a table | Built for a two-dataset join with at least four joined districts |
| Forecast interval | `lower`/`upper` rode in forecast rows and were dropped by `LineView` | `band_lower_field`/`band_upper_field` on the spec, drawn as an area |
| `stacked_bar` | Composition by age band or gender | Not built: no published series carries a part dimension, so there is nothing to stack |

## Stage 4 — Scoring and selection

`select(candidates, profile, decomposition) -> tuple[VisualizationSpec, ...]`, keeping at most two.

- **Intent fit** — from `DecomposedQuery.operations`, entity count, and `time_expression`, replacing
  the `_wants_map` regex.
- **Signal strength** — from stage 1: a bar whose categories are within noise of each other, or a
  line whose `signal_to_noise` is below threshold, scores near zero.
- **Redundancy penalty** — a line and a choropleth of the same period encode one fact; keep one.
- **Rejection is recorded**, not silent: `observation_candidates` returns the pool and
  `select_visualizations` returns both what it kept and what it cut, with a reason for each.
  Wiring those reasons onto `tool_trace` waits for the `service.py` split to settle.

Two rules earn their keep immediately:

- **A single named district never gets a map.** Structure decides (`DecomposedQuery.entity_ids`),
  wording only raises the fit, so "how did Banqiao district change" no longer ships one shaded
  polygon.
- **A line beside a comparison bar must add something.** When every entity moved in one
  direction, first-to-last says it all and the line is cut; when one reversed along the way,
  the bar hides that turn and the line survives.

## Stage 5 — Headline and annotations

`VisualizationSpec` carries `headline`, `annotations`, `reference_lines`, and `focus_entities`,
all computed deterministically from the plotted rows:

- the **headline** states one finding — the entity that moved most, its direction, its size, and
  the periods it moved between — so a card read at a glance carries the point, not just the axes;
- **annotations** mark an interior peak or trough only. An annotation on the first or last point
  repeats what the axis already says;
- a **reference line** draws the median across places in the newest shared period, but only from
  three places up, because two do not describe a middle;
- **focus_entities** dims the rest of the series in the renderer. Nothing is hidden or recomputed.

The model-proposed variant — `VisualizationIntent{template_id, focus_entities, annotation_kinds,
headline}`, validated against the built spec and the `ALLOWED_NUMBER_STRINGS` check in
`answering.py` — is not implemented. The deterministic narrative is the floor it would have to
beat, and it exists first so there is something to compare against.

## Stage 6 — Evaluation

Extend `agent/evals.py` and `scripts/run_agent_evals.py` with a visualization rubric, adapted from
the `VizEvaluator` of microsoft/lida (bugs and aesthetics dropped — no code is generated and the
frontend owns style):

| Dimension | Question |
|---|---|
| Goal compliance | Does the chart answer the question that was asked? |
| Visualization type | Is the template right for this data shape? |
| Data encoding | Are fields on the right channels, with the right scale? |
| Unit appropriateness | Does the measure make the comparison meaningful? |
| Insight strength | Does the chart show something the profile says is actually there? |

Each case declares the expected template, an optional expected measure, an informativeness floor,
and whether a headline is required. `expect_no_chart` makes refusal a gradeable outcome: a case
built on a flat result passes only when the agent actually declined to plot it.

`grade_visualizations` in `agent/viz_evals.py` scores this from the spec and the profile, with no
model in the loop, so it runs in CI. `tests/unit/test_viz_evals.py` runs a small suite through the
production builder.

### The answer suite

Grading the chart alone leaves most of the turn unmeasured, so `agent/answer_evals.py` widens the
same idea to the whole response, over eight dimensions:

| Dimension | Question |
|---|---|
| `status` | Did it answer, or refuse, as the case declared? |
| `grounding` | Does every number in the prose trace to the evidence attached to it? |
| `citation` | Are the expected datasets cited, every reference resolvable, and the evidence actually pointed at? |
| `language` | Is the answer written in the language the question was asked in? |
| `limitations` | Does an answered turn carry a freshness and coverage audit? |
| `tool_trace` | Did the tools the case requires actually run? |
| `visualization` | Did the expected chart appear — or, for `expect_no_chart`, nothing? |
| `disclosure` | Did any forbidden string (`demo_`, `s3://`, a storage path) reach the reader? |

`grounding` deliberately re-derives its allowed numbers from the response's own evidence rather
than reusing the composer's allowlist. One implementation checking its own work proves nothing; two
independent ones disagreeing is a bug report. It also covers the deterministic fallback templates,
which the composer's guard never sees.

Run it with `python -m scripts.run_agent_evals --suite answers` (or `--suite all`).
`tests/integration/test_answer_eval_suite.py` runs the same cases in CI.

## What we take from microsoft/lida, and what we do not

Adopted: the `summarize → goal → generate → evaluate → repair` pipeline shape; the
`Goal{question, visualization, rationale}` structure; the split where deterministic code computes
every statistic and the model only annotates; the evaluator rubric; persona-conditioned goals.

Rejected: *visualizations as code*. LIDA has an LLM emit and execute matplotlib. That breaks the
allowlist-and-grounded-rows contract of doc 23, removes the traceability of every plotted number
back to a citation, and buys flexibility a nine-template allowlist already covers.
