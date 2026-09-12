# Reusable Feature and Decision Layer

> Status: offline contracts, district resolution, feature building, Parquet materialization,
> and DuckDB retrieval implemented

## 1. Goal

New decision questions must reuse integrated data instead of creating a separate
data pipeline for every use case. The architecture separates source integration,
canonical entities, reusable features, and decision-specific policies.

```text
source connectors and uploads
            |
canonical entities and observations
            |
reusable, versioned features
            |
decision profile + constraints
            |
deterministic ranking or optimization
            |
agent explanation with evidence
```

The first implementation is intentionally independent of DuckDB, Athena, APIs,
and an LLM. It establishes contracts those adapters can share.

## 2. Implemented contracts

`youth_compass.decisioning` now provides:

- `FeatureDefinition`: semantic identity, entity type, unit, spatial and temporal
  grain, aggregation, source metric dependencies, and valid bounds;
- `FeatureValue`: one entity's value with dataset-version evidence;
- `DecisionProfile`: weighted criteria, optimization directions, and hard
  constraints for one use case;
- `FeatureRegistry` and `DecisionProfileRegistry`: stable resolution by code and
  version;
- `DecisionScoringEngine`: deterministic constraint evaluation, min-max
  normalization, optional-feature weight normalization, ranking, and per-feature
  score contributions;
- `CanonicalLocation`: point, site, grid-cell, and administrative-area identity
  with WGS84 coordinates, H3 identity, hierarchy, aliases, and validity dates;
- `FeatureProvider`: typed lookup by feature, entity, quality threshold, and
  point-in-time cutoff;
- `FeatureParquetMaterializer` and `DuckDBFeatureProvider`: immutable local
  snapshots and latest-value retrieval with evidence round-tripping;
- `NewTaipeiDistrictResolver`: stable location IDs for all 29 districts with
  deterministic code and name alias resolution;
- `CanonicalObservationFeatureBuilder`: allowlisted aggregation of a registered
  source metric at district grain, with period selection, unit/scope checks, and
  catalog-to-Parquet lineage verification;
- `SQLiteFeatureCatalog`: immutable feature-materialization history and a safe
  published pointer, plus agent discovery by text, tags, entity type, spatial and
  temporal grain, supported filters, time coverage, freshness, and quality;
- `ComposableFeatureBuilder`: entity-aligned ratios and min-max normalization
  over reusable features, with explicit zero-denominator policy and merged evidence;
- `AnalysisPlan` and `AnalysisPlanValidator`: typed multi-dataset inputs,
  pre-aggregations and joins with allowlisted aggregation functions, connectivity
  checks, grain-aware cardinality verification, and unconditional rejection of an
  effective many-to-many join.

Feature contracts and stored values now carry separate versions. A decision run
therefore identifies both the semantic feature definition and the immutable source
materializations used to calculate it.

The scorer does not invent missing required values. A candidate with missing
required features or a failed hard constraint is marked ineligible. Every score
contribution retains the evidence used to calculate its input feature.

## 3. Reuse across decisions

Two reference profiles demonstrate the boundary:

| Decision | Candidate type | Reusable features | Specific features |
|---|---|---|---|
| Home buying | residential location | transit accessibility | property cost, amenities, environmental risk |
| EV charger placement | charger site | transit accessibility | EV demand, parking, grid accessibility, charger competition |

Adding a decision normally means registering a new `DecisionProfile`. Add a new
feature only when the required signal does not already exist. Build a dedicated
materialized mart only when spatial joins, route calculations, or repeated query
latency justify it.

## 4. Next integration slice

The current builders derive direct aggregates, ratios, and normalized scores. They
do not yet calculate distance, network travel time, composite weighted signals, or
spatial joins. The next slice should implement:

1. a location resolver that assigns coordinates, administrative containment,
   aliases, and H3 cells to source records;
2. composable feature builders for spatial joins, composite scores, and
   travel-time calculations;
3. a DuckDB execution adapter for validated analysis plans, retaining the current
   typed boundary and result limits;
4. API endpoints for listing profiles, discovering feature capabilities,
   inspecting evidence, and scoring supplied
   candidates;
5. source connectors for discovery, snapshots, pagination, and scheduled refresh.

Optimization such as capacitated EV charger location-allocation will be a separate
engine behind the same feature and evidence contracts. The weighted scorer is the
auditable baseline, not a replacement for that optimization step.
