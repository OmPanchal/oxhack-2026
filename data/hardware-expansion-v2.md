# Additional GPU and CPU collection support

The [v2 profile](hardware-collection-v2.json) requests **32 instance types**:
13 GPU instance candidates and 19 CPU instance candidates. It targets Stockholm,
the region accessible during the previous run, instead of repeating 35 known
denied requests elsewhere. Regions remain configurable when account access changes.

GPU candidates cover G4ad, G4dn, G5, G5g, G6, G6e, P3, P4d, P5 and P5en,
including selected larger multi-GPU instance sizes. CPU candidates cover Intel,
AMD and Graviton variants across the M, C and R families. See the exact list in
the profile; names are collection candidates, not a promise of regional offerings,
available capacity, Spot history or trained forecast support.

Sources for candidate families: AWS's
[accelerated computing specifications](https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html),
[GPU instance overview](https://aws.amazon.com/ec2/instance-types/accelerated-computing/)
and [instance-type families](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-types.html).
The collector checks actual provider metadata and current offerings at runtime.

## CloudShell

Upload `hardware-collector-v2.zip` to CloudShell first, then run:

```sh
cd ~
unzip hardware-collector-v2.zip
cd hardware-collector-v2
PYTHONPATH=backend python3 -m app.forecasting.collect_expanded \
  --config expanded-collection.json --output hardware-data-v2
python3 -m zipfile -c hardware-data-v2.zip hardware-data-v2
```

Download `hardware-collector-v2/hardware-data-v2.zip` and provide that export for
local validation, preparation and evaluation. Python 3.11+ and boto3 are required;
if missing, install boto3 with `python3 -m pip install --user boto3`.
No ML libraries are needed in CloudShell. Collection is read-only, lasts 89 days,
and uses a fixed UTC end hour recorded in the receipt. No instances are launched.

Unsupported, empty and denied combinations are recorded explicitly. A `PARTIAL`
result is valid for review; if everything fails (`NO_DATA`), the command exits 2.
Create the ZIP only after reviewing the collection's final message. Use fresh
directory names for repeated runs; existing exports are never overwritten.

## Hardware handling

- Raw hardware metadata now retains optional `supportedArchitectures` and
  `processorManufacturer` from the provider. Absent fields remain null. Older
  exports continue to normalize without them.
- CPU architecture is retained with instance identity; ARM and x86 are not claimed
  to be interchangeable. Architecture compatibility is not added to the shared
  Job/API contract or execution adapter by this change. Scheduling ARM workloads
  requires the integration owner to enforce image/workload compatibility.
- Multi-GPU prices are divided by verified GPU count; CPU prices by verified vCPU
  count. Original instance prices and whole-instance allocation sizes remain intact.
- Partitioned GPUs and mixed GPU models/memory remain explicitly rejected because
  the existing unit contract cannot represent them correctly. Other accelerator
  categories such as Trainium and Inferentia are outside CPU/GPU support here.

This expands collection/metadata support. It does not fabricate forecasts for
unseen hardware or train a new model before real data exists. Existing services
fall back to persistence for unsupported pools. Default forecasting, API contracts,
execution and previously saved evaluation results remain unchanged.

Validation: **34 focused tests and 13 subtests passed**, covering existing collection
and reconstruction plus architecture validation, unknown architectures, 1/4/8-GPU
and 8/32-vCPU conversion, exact whole-instance costs, and rejection of fractional
instance allocations. All hardware responses in these tests are synthetic.

The new archive includes only collector sources, the v2 profile and these
instructions. It contains no credentials, historical datasets, trained models or
virtual environment. The previous collector bundle and export remain preserved.
