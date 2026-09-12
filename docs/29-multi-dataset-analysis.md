# Multi-dataset analysis

## What it answers

A question that names two subjects is answered from two published tables, not
one. The executor queries each table separately, validates that the two can be
aligned, inner-joins them on canonical district identity and reporting period,
and returns one narrative with one citation per dataset.

```
question naming two subjects
  -> resolve subjects to catalog datasets
  -> inspect_dataset + query_observations, once per dataset
  -> validate_analysis_plan   (one-to-one join on entity_id and period)
  -> align_period_granularity (only when the inputs disagree)
  -> join_observations        (exact intersection)
  -> explain_lineage          (one citation per dataset version)
```

## Reaching it from any language

The catalog stores an English topic slug, but questions arrive in Traditional
Chinese, Vietnamese, and English. A dataset is selected when the question names
its identifier, its topic, or any curated spelling of that topic:

| Question | Datasets selected |
| --- | --- |
| `Compare population and employment by district` | population, employment |
| `So sánh dân số và thất nghiệp theo quận` | population, employment |
| `比較各區人口與就業` | population, employment |
| `各區教育程度與所得的關係` | education, income |

The vocabulary is `youth_compass.ontology.topics`, the single place that maps
spellings onto a canonical slug, mirroring how `ontology.districts` handles
place names. Only spellings written down there count. A Latin spelling must
match whole words so `income` is not found inside an unrelated token, and a Han
spelling is matched by containment because written Chinese has no word
boundaries; the longer spelling wins, so `教育程度` resolves to education rather
than to the substring `教育`. Nothing is inferred from broad concepts: a
question naming one subject still reads one table.

## Aligning the reporting period

Published tables do not share a calendar. The local population register reports
monthly; the education table reports yearly. An exact period key would never
intersect, so the finer input is collapsed to each year's closing month before
the join.

That is the correct reading for a point-in-time count such as a population
register, and the wrong reading for a within-year total such as births. The
choice is therefore never silent: the response carries an
`align_period_granularity` trace step, and the answer states which input was
moved, which months were kept, and that the result reads as a point-in-time
count rather than a within-year total.

Datasets counting different populations are flagged the same way. Youth-specific
and district-context tables can be joined, but the answer says so, because the
two columns are not two measurements of the same group.

## Failing closed

No partial answer is produced when the inputs cannot be combined, and the reason
names the cause rather than reporting a bare absence:

| Cause | Reported reason |
| --- | --- |
| An input is not published at the required quality | `requested datasets are not published at the required quality: <ids>` |
| The validator rejects the plan | `The requested datasets cannot be joined safely at their validated grain.` |
| No district in common | `datasets cover no district in common` |
| Districts overlap but no period does | `datasets share districts but no common reporting period` |

A dataset version that changes while the analysis runs aborts the turn, so a
combined answer never mixes two versions of the same table.

## Output

The response carries `multi_dataset_analysis` with the metric each dataset
contributed and the joined rows, one `EvidenceCitation` per dataset version with
excerpt rows, and a joined data table visualization. Values are formatted with
digit grouping, so a six-figure count reads as `485,000`.

## Verification

Unit tests cover the subject vocabulary: every curated spelling resolves, no
spelling is claimed by two subjects, an unlisted phrase resolves to nothing, and
a Latin spelling is not found inside a longer word. Integration tests drive the
API through the join in all three languages, assert that a single-subject
question still reads one table, that a finer input is aligned and the alignment
is stated, and that datasets sharing no district are refused with that reason.
