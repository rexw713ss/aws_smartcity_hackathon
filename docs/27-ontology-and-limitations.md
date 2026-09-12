# Local ontology and the data-limitation audit

Two problems sit between a correct number and a usable one.

The first is naming. The same district is written 淡水區, Tamsui, Danshui, or Đạm Thủy depending on
who is asking, while every table in the curated layer is keyed `12`. A question that spells the
place differently from the data used to return no rows.

The second is meaning. A figure can be perfectly grounded and still mislead: it may be two quarters
old, cover 27 of 29 districts, or count people whose household registration is in a district rather
than people who live there. None of that is visible in the number itself.

## 1. Local ontology

`youth_compass.ontology` is the one place that maps a human spelling onto a canonical identifier.

### Places

`resolve_district_name` returns the canonical `District` plus the language that matched, or nothing.
The canonical resolver in `youth_compass.mapping.geography` runs first, so ingestion behaviour is
unchanged; the multilingual table is consulted only when that returns nothing.

| Spelling | Resolves to | Matched as |
|---|---|---|
| `12`, `1.0` | 淡水區 | code |
| `淡水區`, `新北市淡水區` | 淡水區 | zh_hant |
| `Tamsui`, `tamsui district`, `Danshui` | 淡水區 | english |
| `Đạm Thủy`, `dam thuy`, `DAM-THUY` | 淡水區 | vietnamese |
| `Taipei`, `site-banqiao-station` | nothing | — |

Matching is exact after folding case, diacritics, separators, and administrative affixes. Fuzzy and
substring matching are deliberately absent: guessing that an unknown string means a district would
silently attribute statistics to the wrong place. Registration of an ambiguous alias fails at import
time rather than at query time.

### Scoping a question to the district it names

Entity identifiers reach the copilot only as an API parameter. A person typing "the youth population
trend in Sanxia District" supplies none, so without this step the answer covers all 29 districts and
the named place is silently ignored. `extract_districts` reads the place out of the question text,
which is what makes the typed question and the typed parameter equivalent.

| Question | Scope |
|---|---|
| `What is the youth population trend in Sanxia District?` | `["11"]` |
| `Xu hướng dân số thanh niên ở Tam Hiệp thế nào?` | `["11"]` |
| `三峽區的青年人口趨勢如何？` | `["11"]` |
| `Compare Banqiao and Linkou from 2023 to 2025` | `["01", "17"]` |
| `Compare the youth population trend by district from 2023 to 2025` | `[]` |

Chinese names are matched as substrings, because the script has no word separators. Latin text is
matched word by word, trying the two-word form first so a Vietnamese name is not split in half.
Districts are returned in the order they were written, and the tool trace records the scope as
`resolve_local_ontology`.

Extraction runs before session scope is applied, so a district the person just named wins over the
one carried by the previous turn. Two cases are deliberately left alone.

- **An explicit parameter always wins.** A caller that named entity identifiers meant those.
- **A decision plan is never narrowed.** It ranks the candidates its profile defines, which are
  sites and slugs rather than districts, so a district code would empty the ranking.

Two properties follow from that, and both are relied on downstream.

- **Non-destructive.** The copilot never rewrites the identifier a caller supplied. Tools match on
  canonical identity instead, so a reader keeps seeing the name they typed while the query reaches
  the right rows. The tool trace records the resolution as `resolve_local_ontology`.
- **Safely expandable.** `district_spellings` widens one identifier into every spelling of the same
  district. The precomputed forecast adapter uses it to filter an artifact that may be keyed either
  way, and still judges completeness per requested district.

### Population basis

Taiwanese district statistics are published on two incompatible bases.

| Basis | Counts | Typical source wording |
|---|---|---|
| `registered_household` | People whose 戶籍 is in the district | 戶籍, 設籍, registered population |
| `resident` | Usual residents | 常住, 現住, resident population |
| `unknown` | Not stated by the catalog | — |

Commuter and student districts differ substantially between the two, so a series measured on one
basis must never be compared with, divided by, or ranked against a series measured on the other.

`resolve_registration_basis` reads the basis from catalog text only: the dataset topic, its
identifier, the metric code, and the source URI. It never infers a basis from a topic name, and text
naming both bases resolves to `unknown` rather than picking one. A wrong assumption here silently
corrupts every derived rate, so an honest "not recorded" is the safer answer.

## 2. Limitation audit

Every answered response carries a `limitations` block built by `DataLimitationsBuilder` from
evidence the answer already used. Nothing in it is estimated, interpolated, or inferred.

```json
{
  "schema_version": "1.0",
  "freshness": [
    {"citation_id": "data-1", "dataset_id": "marriage", "dataset_version": "v1",
     "published_at": "2026-03-12T00:00:00Z", "age_days": 184}
  ],
  "coverage": {
    "region_scheme": "new_taipei_district",
    "expected_entity_count": 29,
    "observed_entity_count": 27,
    "missing_entity_names": ["貢寮區", "烏來區"],
    "unmapped_entity_ids": []
  },
  "registration_basis": "registered_household",
  "notes": ["These counts are registered household population (戶籍人口): …"]
}
```

**Freshness** reports publication age per citation, not per answer. One response can mix a marriage
series published two quarters ago with a housing snapshot published this week, and the reader needs
to see both. Age is publication lag, not collection lag: a dataset published today can still
describe last year's reporting period. A source dated after the request clock floors at zero rather
than reporting a negative age.

**Coverage** compares the districts an answer covers against the districts it implied. A question
that named districts is judged against exactly those; a question that named none asked about the
city, so all 29 districts are the denominator. Entities outside the boundary set are listed in
`unmapped_entity_ids` rather than counted as coverage. When nothing in the answer is a district the
block is omitted, because a coverage ratio would be meaningless.

**Notes** always open with the population-basis caveat for the resolved basis, including the
`unknown` case. A note is added when the series contains values the ingestion pipeline flagged as
estimated, such as an age band split by youth weight rather than reported directly.

## Reading it in the interface

The conversation pane renders the block under each answer as a collapsed "Data limitations" section:
the basis label, one line per source with its age, the coverage ratio with the districts that are
missing, and the notes. The map repeats the coverage sentence, so an unshaded area reads as absent
evidence rather than as a zero.

## What this does not do

- It does not date the reporting period a dataset describes, only when that version was published.
- It does not detect that two datasets disagree; it only reports how old and how complete each is.
- It does not assign a basis the catalog never stated, and it will say so instead.
