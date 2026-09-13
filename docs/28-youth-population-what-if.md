# Youth population What-if

> Status: agent-driven impact-chain vertical slice implemented

## Goal

The primary interface is now the conversation, not a standalone plus/minus form. The agent
answers a bounded decision question: if a stated number of young people enter or leave one
New Taipei district by a target year, what downstream evidence is required before an
infrastructure recommendation can be made?

It does not claim that housing, fertility, or another policy causes migration,
and it does not convert population into house prices or capacity demand using invented
coefficients.

## Agent execution chain

For a question such as “If 2,000 young people move to Linkou before 2030, what infrastructure
should be funded?”, the registered tool plan is:

1. `search_tools`: select only tools registered for the requested operations;
2. `search_catalog`: look for already-published compatible evidence;
3. `simulate_scenario`: compare the explicit shock with the district cohort baseline;
4. `assess_capacity`: enumerate the housing and public-service metrics required
   for each downstream link;
5. `discover_sources`: search only configured, allowlisted official sources for missing
   metrics;
6. `recommend_investment`: rank actions only when the capacity chain is complete; otherwise
   record a `withheld` outcome.

The API returns this as `impact_analysis`, including grounded findings, exact data gaps,
recommendations (when supported), confidence, and the complete tool trace. The frontend opens
an Impact tab automatically and renders the same chain.

## Data and method

The source is `data/source/01_人口/_全部年度_全區.csv`, New Taipei Civil Affairs monthly
household-registration data by district and single-year age. The engine:

1. selects the latest complete same-month snapshot for all 29 districts;
2. calculates each district's recent same-month cohort transition rate by comparing ages
   17–34 in one year with ages 18–35 in the next;
3. uses the median recent rate as that district's baseline and ages the observed cohorts
   forward to the target year;
4. compares that baseline with an explicit scenario path.

Since `docs/31`, the baseline uses the forecast's per-age cohort change ratios and snapshot
month, so it equals the published forecast; the district rate above is the one a scenario
adjusts, scaling every age's ratio by the same factor.

The transition rate combines migration, mortality, and registration changes. It is a
descriptive benchmark, not an identified causal effect. The source measures registered
household population rather than usual residence.

## Primary scenario operations

- `match_top_quartile_retention`: raise a district to at least the observed 75th-percentile benchmark;
- `match_city_retention`: raise a district to at least the observed median across the 29 districts;
- `retention_rate_change`: change annual cohort retention by stated percentage points;
- `annual_net_migration`: add a stated recurring annual youth inflow or outflow.

Legacy one-off arithmetic and district-transfer operators remain accepted by the API for
compatibility but are no longer the main What-if interface.

Targets are limited to the observed year through ten years ahead, and never beyond 2043.
That boundary matches the known fact that the 18–35 cohort through 2043 was already born by
the 2025 anchor, so future fertility variants do not create a useful district lever in this
horizon.

## APIs

The conversation entry point is:

`POST /api/v1/copilot/query`

```json
{
  "question": "Nếu thêm 2.000 thanh niên chuyển đến Linkou trước 2030, nên đầu tư hạ tầng gì?"
}
```

The structured scenario endpoint remains available as a lower-level compatibility API:

`POST /api/v1/copilot/what-if`

```json
{
  "targetYear": 2030,
  "adjustments": [
    {
      "districtId": "Linkou",
      "operation": "match_top_quartile_retention"
    }
  ]
}
```

Scenario and impact calculations run in the backend. The browser renders returned values and
never supplies an impact coefficient or calculates a recommendation.

## Evidence boundary

The observed age counts are official. Cohort transition rates, city median, top-quartile
benchmark, and projections are derived. The selected benchmark, retention change, or annual
migration value is a user assumption. No scenario result is labelled as an official forecast.
Source discovery returns candidates for approval; finding a source is not the same as having a
compatible published metric. Until capacity, utilization, and age-compatible demand evidence
are available, the investment recommendation remains explicitly withheld.

The national NDC 2026–2075 projection can later be added as a versioned national anchor. It
must not be described as an official district projection or used to invent district-level
fertility, mortality, or migration assumptions.
