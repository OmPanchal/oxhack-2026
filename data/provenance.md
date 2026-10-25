# Data provenance — Person 1

`scenarios/demo.json` is a hand-authored, SIMULATED UI/contract fixture.
It contains no historical cloud observations, trained predictions, execution outcomes,
or benchmark results. Prices are illustrative USD per resource unit-hour.

Before adding real datasets record source URL, retrieval time (UTC), license,
resource/unit mapping, observation interval, missing-data handling, and chronological
train/validation/test cutoffs. Do not commit credentials or large raw datasets.

## Live AWS observations — verified 25 October 2026

Source: Amazon EC2 `DescribeSpotPriceHistory`, `DescribeInstanceTypes` and
`DescribeInstanceTypeOfferings`, accessed through the application's read-only
boto3 adapter. Documentation: https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html

- Verified retrieval: `2026-10-25T00:26:08.530645Z`, region `eu-north-1`.
- Filter: `g4dn.xlarge` (T4), `g5.xlarge` (A10G), Linux/UNIX.
- Five returned quotes retain instance/AZ, effective time and observation time.
  Whole-instance USD/hour is normalized by the actual GPU count for comparisons.
- `/api/market` exposes the minimum-price region/GPU index, not a fixed SKU/AZ
  series or executable allocation. It can change underlying instance/AZ.
- Quotes refresh on a roughly 60-second cache; scheduling uses hourly UTC slots.
  Historical retention, hourly sampling and training suitability still need audit.
- Capacity and carbon are unavailable (`null`); no inventory or risk labels are
  inferred. Prices are OBSERVED. Persistence forecasts are baseline predictions,
  not trained ML results; replay capacities/shocks remain SIMULATED.
- This live check did not create a licensed historical dataset, define evaluation
  cutoffs or establish redistribution rights. Record applicable AWS terms and
  dataset handling before publishing/exporting data or training/evaluating on it.

No keys, session tokens or authentication links are recorded here.
