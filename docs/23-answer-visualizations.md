# Grounded answer visualizations

> Status: backend contract and deterministic builders implemented; frontend renderers pending.

## Contract

Every successful copilot response may include a `visualizations` array. Each item is a
frontend-independent `VisualizationSpec` with schema version `1.0`, an allowlisted type, localized
labels, stable field encodings, inline grounded rows, and citation IDs.

```json
{
  "schema_version": "1.0",
  "visualization_id": "observation-trend",
  "type": "line",
  "title": "population_count 趨勢",
  "x": {"field": "period", "label": "期間", "data_type": "temporal", "unit": null},
  "y": {"field": "value", "label": "數值", "data_type": "quantitative", "unit": "persons"},
  "series_field": "entity_name",
  "columns": [],
  "rows": [
    {"period": "2025", "entity_id": "banqiao", "entity_name": "板橋", "value": 120}
  ],
  "citation_ids": ["data-1"],
  "truncated": false
}
```

## Allowlisted templates

| Type | Backend use | Suggested frontend component |
|---|---|---|
| `line` | Observation trends by entity and period | Multi-series line chart |
| `comparison_bar` | Absolute change across entities | Vertical bar chart |
| `ranking_bar` | Eligible decision candidates by score | Horizontal ranking chart |
| `contribution_bar` | Feature contribution for the top candidate | Horizontal contribution chart |
| `choropleth` | One district-keyed figure per area | Shaded administrative map |
| `data_table` | Universal fallback and exact values | Sortable accessible table |

The backend selects the smallest useful set rather than returning every possible view:

- a ranking bar requires at least two eligible candidates with different scores;
- a contribution bar requires at least two non-zero contributions;
- a line requires at least two distinct periods per entity, and sparse entities are excluded;
- a comparison question prefers one comparison bar when at least two entities are comparable;
- a map requires explicit spatial intent, at least two resolved districts with differing values,
  and a period shared by every district shown;
- observation answers do not duplicate raw rows in an `Observation data` table; when no chart is
  defensible, the answer returns no visualization and the cited evidence remains the data view;
- decision and forecast tables remain available where they add distinct audit information, such as
  ineligible candidates or forecast uncertainty bounds.

To preserve legibility, ranking and comparison bars show at most 12 categories, contribution bars
show at most 10, and line charts show at most 8 series. A limited chart is marked truncated; its
source observations remain accessible from the cited evidence.

Forecasts use the same rules: a single forecast point is a table, not a line, and a forecast map
uses the newest year shared by every district it displays.
- dataset discovery: coverage table;
- missing-data acquisition: source-candidate table.

## Choropleth

A choropleth carries values keyed by canonical district code and names the boundary set they belong
to. It never carries geometry: a renderer joins the rows to whichever boundary file it already holds
for that scheme, so a map costs the same few hundred bytes as a table.

```json
{
  "schema_version": "1.0",
  "visualization_id": "observation-map",
  "type": "choropleth",
  "title": "population_count 趨勢 · 2025",
  "x": {"field": "district_code", "label": "行政區", "data_type": "nominal", "unit": null},
  "y": {"field": "value", "label": "數值", "data_type": "quantitative", "unit": "persons"},
  "region_field": "district_code",
  "region_scheme": "new_taipei_district",
  "columns": [
    {"field": "district_code", "label": "區代碼", "unit": null},
    {"field": "district_name", "label": "行政區", "unit": null},
    {"field": "value", "label": "數值", "unit": "persons"}
  ],
  "rows": [
    {"district_code": "12", "district_name": "淡水區", "entity_id": "淡水區",
     "entity_name": "淡水區", "value": 100.0, "rank": null, "period": "2025"}
  ],
  "citation_ids": ["data-1"],
  "truncated": false
}
```

Four rules keep a map from saying more than the evidence does.

- **One common instant, never a sparse series.** An observation map shades only the newest period
  shared by every mapped district. If there is no common period, no map is returned.
- **Canonical keys only.** Entity identifiers are resolved through the local ontology, so rows keyed
  `淡水區`, `Tamsui`, or `12` all land on district 12.
- **No spatial guessing.** An entity that is not a New Taipei district is dropped from the map and
  reported in `limitations.coverage.unmapped_entity_ids`. Placing a site inside a district would be
  a spatial join this system does not perform.
- **A table fallback ships with it.** Every choropleth carries `columns`, so a renderer without a
  boundary file degrades to exact figures instead of an empty frame.

A spec validates only when the type and the region fields agree: a choropleth must name both
`region_field` and `region_scheme`, and no other type may carry either.

## Safety boundary

`VisualizationBuilder` consumes only validated `CandidateInsight`, `ObservationSeries`,
`EntityComparison`, `DatasetInspection`, and `SourceCandidate` objects. Bedrock cannot emit chart
code or change chart rows. Chart types and field names are allowlisted, citation IDs come from the
grounded response, and each chart/table is capped at 200 rows with an explicit `truncated` flag.

## Frontend handoff

The frontend should switch on `type`, render the provided encodings and rows, and fall back to the
`data_table` item when a chart renderer is unavailable. It should not recalculate ranking, changes,
or percentages. English and Traditional Chinese affect titles and display labels only; stable row
field names remain English identifiers.
