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
| `data_table` | Universal fallback and exact values | Sortable accessible table |

The backend currently returns:

- decision answer: ranking bar, top-candidate contribution bar, and ranking table;
- observation answer: trend line, optional comparison bar, and observation table;
- dataset discovery: coverage table;
- missing-data acquisition: source-candidate table.

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

