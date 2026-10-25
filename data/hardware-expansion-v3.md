# Larger GPU and CPU collection profile

The [v3 profile](hardware-collection-v3.json) requests **96 distinct instance types**:
**39 GPU instance candidates and 57 CPU instance candidates** in Stockholm.
It includes every candidate from v2, plus larger configurations and additional
GPU families. Old profiles, bundles, exports and model results are preserved.

The GPU list adds further G4ad/G4dn, G5, G6 and G6e configurations, P4de, P5e,
and P6-B200/P6-B300 candidates. The CPU list includes xlarge, 2xlarge and 4xlarge
sizes for each of the 19 M/C/R families already in v2, spanning Intel, AMD and ARM.
AWS's [accelerated computing specifications](https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html)
document the accelerator instance candidates. Actual regional offerings, hardware
metadata and Spot history are checked by the collector; this list does not imply
that all 96 combinations are offered or have usable history in Stockholm.

## CloudShell steps

Upload `hardware-collector-v3.zip` first. Use this bundle instead of v2 for the
larger run; it already includes v2's candidates.

```sh
cd ~
unzip hardware-collector-v3.zip
cd hardware-collector-v3
PYTHONPATH=backend python3 -m app.forecasting.collect_expanded \
  --config expanded-collection.json --output hardware-data-v3
python3 -m zipfile -c hardware-data-v3.zip hardware-data-v3
```

After the collection completes, download
`hardware-collector-v3/hardware-data-v3.zip` and provide it for local validation
and model evaluation. Python 3.11+ and boto3 are required. If boto3 is absent, run
`python3 -m pip install --user boto3`. The bundle needs no ML dependencies.

This makes read-only metadata and history requests; it does not rent even the
largest listed instance. It collects 89 days relative to a fixed UTC end hour,
isolates per-pair errors and preserves successful shards. Review the receipt:
unsupported, empty or denied candidates are explicitly reported. Use a fresh
output name on repeat runs. Additional regions remain configurable but require
account access; the prior export denied all requested regions outside Stockholm.

## Meaning of broader support

All existing metadata/unit safeguards remain in place: verified GPU/vCPU counts,
architecture metadata, original instance prices, whole-instance allocations and
distinct AZ/instance identities. Partitioned GPUs and unsupported accelerator
categories are still rejected. More instance sizes provide broader coverage,
but prices across related sizes may be correlated and should not be counted as
independent evidence of forecast quality.

This expands the requested collection scope, not trained model coverage. New
forecasts require actual imported observations and a chronological evaluation.
No existing result, default forecast mode, API contract or reserved final-test
period was changed. See [v2 hardware handling](hardware-expansion-v2.md) and
[the previous evaluation](expanded-evaluation.md) for those boundaries.
