# Youth population forecast

> Status: phases 1 and 2 implemented (model, backtest, calibrated intervals, agent answer,
> shared What-if baseline, S3 reader, observed history)
> Replaces the log-linear trend as the published forecast for `population_count`.
> Run `make forecast` to regenerate `data/forecasts/`.

## Goal

Answer "how many young people (18–35) will each New Taipei district have over the next five
years, why, and how far can that number be trusted?" The forecast must be reproducible from a
cited source, explain where the change comes from, carry an uncertainty interval backed by past
errors, and refuse to publish when it does not beat a trivial baseline.

## Why a cohort method rather than a trend

Nearly everyone who will be 18–35 in five years already lives in the district today, aged
13–30. A cohort method moves those people forward one year of age at a time; a trend line
cannot see that a small cohort of teenagers is about to reach 18. For horizons shorter than
18 years no one who is not yet born can enter the youth band, so no fertility assumption is
needed.

## Method

### Official reference

The National Development Council projects Taiwan's population with the cohort-component
method, starting from year-end single-year-age household-registration counts
(國發會《中華民國人口推估（2024年至2070年）》, 2024, 參、一 and 附錄一). For ages 1–99:

```text
P(x, t) = P(x−1, t−1) · S(x, t) + M(x, t)
```

where `S` is the survival probability and `M` the net international migration at age `x`.

### Cohort change ratios (Hamilton–Perry)

District-level survival and migration inputs are not published, so this project uses the
Hamilton–Perry variant, which estimates their combined effect from two successive counts
(Hamilton & Perry 1962; Baker, Swanson & Tayman 2021). A cohort change ratio is
algebraically equivalent to the balancing equation: `CCR = S + M / P`.

For district `d`, single year of age `a`, and snapshot year `y`:

```text
CCR(d, a, y)  = P(d, a+1, y+1) / P(d, a, y)
CCR̂(d, a)     = median of CCR(d, a, y) over the most recent window of consecutive year pairs
P(d, a+k, O+k) = P(d, a, O) · CCR̂(d, a) · CCR̂(d, a+1) · … · CCR̂(d, a+k−1)
Youth(d, O+k)  = Σ P(d, a, O+k)  for a = 18 … 35
```

Hamilton–Perry requires the projection step to be divisible by the age-group width and
accepts population-registry data (Baker, Swanson & Tayman 2021). Single years of age with a
one-year step meet both conditions.

### Decomposition

The same projection splits exactly into three parts, so every forecast carries its reason:

```text
entering    = Σ P(d, a, O)  for a = 18−k … 17     people who reach 18 by O+k
ageing_out  = Σ P(d, a, O)  for a = 36−k … 35     people who pass 35 by O+k
net_change  = Youth(d, O+k) − (Youth(d, O) + entering − ageing_out)
```

`net_change` is the change beyond ageing: migration, mortality, and registration changes
together. It must not be labelled "migration" alone.

### Deviations from textbook Hamilton–Perry

| Point | Textbook | This project | Basis |
|---|---|---|---|
| Ratio estimate | Two counts | Median of the recent window of annual pairs | Project choice for robustness to one abnormal year; no direct citation |
| Youngest ages | Child-woman ratio | Not needed | Horizon ≤ 18 years, so no newborn reaches 18 |
| Decomposition | Not part of the method | Entering / ageing out / net change | Follows from the balancing equation (國發會 附錄一) |

## Evidence and trust

### Temporal backtest

The generator re-runs every candidate model from past origins using only data available at
that origin and compares each prediction with the observed value
(Williams & Goodman 1971). Candidates:

- `naive`: the latest observed youth count;
- `loglinear`: the existing log-linear trend (`youth_compass.forecasting.baseline`);
- `cohort`: the cohort change ratio model above.

Per horizon the model card reports mean absolute percentage error (MAPE), the 90th percentile
absolute percentage error, and mean signed percentage error (bias).

### Acceptance gate

A forecast is published only when the selected model beats `naive` at every horizon. The
selected model is the candidate with the lowest mean district MAPE across horizons. If no
candidate passes, the generator exits non-zero and the previous artifact stays in place.

### Empirical intervals

Intervals come from the selected model's backtest errors, not from a distributional
assumption (Williams & Goodman 1971; Rayer, Smith & Tayman 2009, who apply the idea to
county total-population forecasts). With relative error `e = (predicted − actual) / actual`
and `a` the 90th percentile of `|e|` for the same horizon and size class, the interval for a
new prediction `p` is:

```text
lower = p / (1 + a),  upper = p / (1 − a)
```

Districts with fewer than 10,000 residents form their own size class because small-area
forecast errors rise rapidly below that size (Wilson et al. 2021). A class with fewer than
10 errors borrows the pooled errors for its horizon. The target is that 80% of outcomes fall
inside the interval.

### Interval calibration

Coverage is measured in pseudo-real time. An interval for a forecast made at origin `t` is
built only from past forecasts whose target year is at or before `t`, the errors that were
actually knowable then, and then checked against what happened. The first implementation
reported 73.6% "holdout" coverage by fitting on origins up to 2022 and testing 2023–2025, but
those fitting errors included outcomes up to 2026 that were not knowable in 2023.

Measured in pseudo-real time over 899 outcomes (2026-09-13):

| Interval method | All | 1 yr | 2 yr | 3 yr | 5 yr | Small areas | Origins ≥ 2022 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Signed q10/q90 per class (phase 1) | 63.6% | 68.2% | 62.5% | 67.2% | 52.9% | 66.7% | 63.4% |
| Signed q05/q95 per class | 73.2% | 78.9% | 73.3% | 78.2% | 57.5% | 78.5% | 74.1% |
| \|e\| 80th percentile per class | 76.1% | 74.3% | 72.8% | 77.6% | 82.8% | 72.0% | 69.0% |
| **\|e\| 90th percentile per class (published)** | **85.5%** | **85.1%** | **85.8%** | **86.2%** | **87.4%** | **82.3%** | **80.7%** |
| \|e\| 90th percentile pooled | 86.3% | 86.6% | 85.8% | 85.1% | 85.1% | 71.0% | 82.4% |

Separate lower and upper quantiles under-covered badly: each tail is estimated from a few
dozen errors that are correlated, because the 29 districts share each origin year. One
absolute-error quantile uses both tails' evidence. The 90th percentile was chosen as the
lowest level that meets the 80% target in every horizon, in small areas, and for the most
recent origins; pooling across size classes fails small areas (71%). The level was selected
on this same evaluation, so the table is evidence for the choice rather than an independent
test of it. Every answer states the measured coverage, and warns when it falls below target.

### Known behaviour from the literature

- Hamilton–Perry projections tend to be biased upward, and a simple extrapolation of the
  total can be more accurate than Hamilton–Perry for the total alone
  (Baker, Swanson & Tayman 2021). The model card therefore reports bias and keeps the trend
  as a competing candidate.
- Complex projection models are generally not more accurate than simple ones for small
  areas (Smith 1997; Smith, Tayman & Swanson 2013), which is why no learned model is used.

## Published result

Run of 2026-09-13 on the registration source, base period 2026-07, 11 backtest origins
(2014–2025 without 2017), 29 districts.

District MAPE / 90th percentile absolute error / bias, in percent:

| Horizon | naive-last-value | loglinear-baseline-v1 | **cohort-change-ratio-v1** |
|---|---|---|---|
| 1 year | 2.42 / 4.28 / +2.24 | 1.13 / 2.44 / +0.27 | **0.81 / 1.75 / +0.11** |
| 2 years | 4.92 / 8.37 / +4.62 | 1.84 / 4.13 / +0.51 | **1.34 / 3.01 / +0.24** |
| 3 years | 7.39 / 12.28 / +6.98 | 2.61 / 5.76 / +0.73 | **1.77 / 4.00 / +0.30** |
| 4 years | 9.77 / 16.13 / +9.26 | 3.63 / 7.52 / +1.25 | **2.26 / 5.03 / +0.57** |
| 5 years | 12.34 / 20.54 / +11.71 | 4.57 / 9.20 / +1.68 | **2.88 / 6.63 / +0.91** |

- The gate passed and selected the cohort model.
- Bias is positive at every horizon, as Baker, Swanson & Tayman (2021) report for
  Hamilton–Perry.
- Intervals contain 85.5% of 899 outcomes in pseudo-real time, 84–87% at every horizon, and
  82.3% in districts under 10,000 residents; see "Interval calibration".

Five-year forecast to 2031-07:

| District | 2026-07 | + reaching 18 | − passing 35 | Change beyond ageing | 2031 | Interval |
|---|---:|---:|---:|---:|---:|---|
| Banqiao 板橋 | 106,473 | 24,862 | 35,209 | −814 | 95,312 | 90,676–100,448 |
| Tamsui 淡水 | 42,708 | 7,885 | 14,630 | +6,606 | 42,569 | 40,498–44,863 |
| Linkou 林口 | 27,415 | 7,964 | 9,423 | +1,901 | 27,857 | 26,502–29,358 |
| Shimen 石門 (small) | 2,134 | 308 | 659 | −258 | 1,525 | 1,382–1,701 |
| Pingxi 平溪 (small) | 546 | 63 | 162 | −9 | 438 | 397–488 |
| City total | 832,214 | 169,323 | 277,487 | +13,448 | 737,498 | not additive |

District intervals are not summed into a city interval, because district errors are not
independent.

## Copilot behaviour

- A forecast question returns the line with its interval, preceded by up to five years of
  observed values for the same snapshot month (a zero-width band, so the path fans out only
  where it stops being measured); the drivers as a signed bar for one district or a table for
  several; the backtest accuracy at the answered horizon against the naive baseline; and
  warnings for districts under 10,000 residents or intervals that under-cover.
- The history read is traced as `query_observations`; if it fails, the forecast is still
  answered and the failure is recorded.
- A question about forecast accuracy (`QuestionFocus.FORECAST_ACCURACY`) leads with the
  backtest and interval coverage at every horizon.
- The answer grader admits the drivers, the backtest and coverage figures, and the 18/35
  age bounds as grounded numbers.

## What-if baseline

The What-if engine (`docs/28`) reads the same registration snapshots through
`youth_compass.forecasting.registration` and ages cohorts with the same per-age ratios, so its
baseline equals the published forecast for every district and year; on the 2026-07 data all 29
districts match exactly for 2031. Scenario retention operations still adjust one aggregate
17–34 → 18–35 retention rate per district. An adjustment from rate `r` to `r'` scales every
age's ratio by `r' / r`, which scales a `k`-year projection by `(r' / r)^k`, the same effect
the previous single-rate engine applied.

## Deployment

The deployed API reads the forecast from S3 (`forecast.provider: s3`): the ApiStack points
it at `population/` in the forecasts bucket and grants read on that prefix only. The adapter
keeps one downloaded copy per artifact ETag and re-checks the ETag every
`refresh_seconds` (300 by default). Before this change the API advertised `forecast_metric`
with `provider: local` against a file the Lambda package never contained.

The forecast is refreshed two ways, both through `youth_compass.forecasting.publication`:

- **After an upload publishes.** The ingestion workflow runs `RefreshForecast` after
  `Publish`. The step reads the raw upload, because the curated `population` table keeps
  only ages 18–35 and the cohort model needs younger ages. An upload that is not a
  single-year-age registration file, or whose forecast fails the acceptance gate, is
  reported as `skipped` and leaves the previous forecast in place. Errors are caught into a
  `Pass` state, so a forecast problem never fails the ingestion. The function may write only
  `population/*` in the forecasts bucket.
- **By hand.** `make forecast-publish-aws YOUTH_COMPASS_FORECAST_BUCKET=<bucket>` runs the
  local backtest and gate, then uploads the validated model card and artifact, card first.

What-if is served on AWS from `data/source/01_人口/registration.parquet`, a 1 MB extract of
the 54 MB registration CSV that `scripts/build_lambda.py` writes into the API package. It
holds the single-year-age rows summed over gender and reads to identical snapshots.

## Limitations stated with every answer

- The forecast continues recent conditions. New housing or policy can break it.
- The source counts registered household population (戶籍人口), not usual residents. The
  backtest compares registration with registration and cannot detect that gap.
- A forecast is not causal evidence for any policy.

## Data and lineage

- Source: `data/source/01_人口/_全部年度_全區.csv`, New Taipei Civil Affairs monthly
  single-year-age registration by district. Its SHA-256 is recorded in the model card and
  equals the `source_sha256` of the published `population` dataset.
- The published `population` dataset keeps only ages 18–35, but the cohort method needs ages
  down to `18 − horizon`, so the generator reads the source file directly.
- Snapshot month: the latest month covering all 29 districts and ages 0–35. Every year uses
  that same month, so a forecast for year `Y` means the count in that month of `Y`.
- ROC year 106 (2017) is absent; ratio pairs spanning the gap are skipped, never imputed.

## Artifacts

`make forecast` writes, validates, and atomically promotes:

| File | Content |
|---|---|
| `data/forecasts/current.parquet` | The forecast schema from `docs/25-precomputed-forecast-agent.md`, plus `base_period`, `base_value`, `entering`, `ageing_out`, `net_change`, `size_class` |
| `data/forecasts/model-card.json` | Method, parameters, source hash, backtest table for every candidate, gate result, interval widths, pseudo-real-time coverage by horizon and size class, limitations, references |

The forecast service ignores columns it does not know, so older readers keep working.

## Implementation plan

### Phase 1 — implemented

1. `youth_compass.forecasting.cohort`: IO-free ratio estimation, projection, decomposition.
2. `youth_compass.forecasting.evaluation`: backtest runner, error summaries, acceptance gate,
   empirical intervals and their coverage.
3. `ml/youth_population_forecast.py` and `make forecast`: read the source, run the backtest,
   select, publish the artifact and model card atomically.
4. `ForecastPoint.components` and `ForecastResult.evaluation` as optional port fields; the
   Parquet reader fills them when the artifact and model card carry them.
5. Copilot: the forecast answer states the drivers and backtest accuracy, warns for small
   districts, and draws a driver chart; the answer grader accepts those grounded numbers.

### Phase 2 — implemented

1. Interval calibration re-tested in pseudo-real time; intervals switched to the absolute
   error quantile, with coverage reported per horizon and size class.
2. What-if reads its baseline from the shared registration reader and ratios.
3. `adapters/aws/s3_forecast_artifact.py`, `forecast.provider: s3`, ApiStack wiring, and
   `make forecast-publish-aws`.
4. Observed same-month history drawn in front of the forecast line.

5. Automatic forecast refresh after an upload publishes, and What-if packaged for AWS.

## References

Verified on 2026-09-13.

- Baker, J., Swanson, D. A., & Tayman, J. (2021). The accuracy of Hamilton–Perry population
  projections for census tracts in the United States. *Population Research and Policy
  Review*, 40(6), 1341–1354. https://doi.org/10.1007/s11113-020-09601-y
- Baker, J., Swanson, D. A., Tayman, J., & Tedrow, L. M. (2017). *Cohort change ratios and
  their applications*. Springer. https://doi.org/10.1007/978-3-319-53745-0
- Cannan, E. (1895). The probability of a cessation of the growth of population in England
  and Wales during the next century. *The Economic Journal*, 5(20), 505–515.
- Hamilton, C. H., & Perry, J. (1962). A short method for projecting population by age from
  one decennial census to another. *Social Forces*, 41(2), 163–170.
- Keyfitz, N. (1981). The limits of population forecasting. *Population and Development
  Review*, 7(4), 579–593 (some indexes list the last page as 594).
- Leslie, P. H. (1945). On the use of matrices in certain population mathematics.
  *Biometrika*, 33(3), 183–212.
- Rayer, S., Smith, S. K., & Tayman, J. (2009). Empirical prediction intervals for county
  population forecasts. *Population Research and Policy Review*, 28(6), 773–793.
- Smith, S. K. (1997). Further thoughts on simplicity and complexity in population projection
  models. *International Journal of Forecasting*, 13(4), 557–565.
- Smith, S. K., Tayman, J., & Swanson, D. A. (2013). *A practitioner's guide to state and local
  population projections*. Springer. https://doi.org/10.1007/978-94-007-7551-0
- Swanson, D. A., Schlottmann, A., & Schmidt, R. (2010). Forecasting the population of census
  tracts by age and sex: An example of the Hamilton–Perry method in action. *Population
  Research and Policy Review*, 29(1), 47–63.
- Whelpton, P. K. (1936). An empirical method of calculating future population. *Journal of
  the American Statistical Association*, 31(195), 457–473.
- Williams, W. H., & Goodman, M. L. (1971). A simple method for the construction of empirical
  confidence limits for economic forecasts. *Journal of the American Statistical
  Association*, 66(336), 752–754. https://doi.org/10.1080/01621459.1971.10482340
- Wilson, T., Grossman, I., Alexander, M., Rees, P., & Temple, J. (2021). Methods for small
  area population forecasts: State-of-the-art and research needs. *Population Research and
  Policy Review*, 41(3), 865–898. https://doi.org/10.1007/s11113-021-09671-6
- 國家發展委員會 (2024)。《中華民國人口推估（2024年至2070年）》。ISBN 978-626-7522-22-6。
