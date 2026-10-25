# Multi-region AWS price export for Person 1

This exporter requests 89 days of observed AWS Spot prices and verified hardware
metadata for the same **96 instance candidates** used in the Stockholm v3 export,
across **12 regions**. These are candidate requests, not a claim that every type
is offered, every region is permitted, or every pool has 89 days of history.

Configured regions: Stockholm (`eu-north-1`), Ireland (`eu-west-1`), London
(`eu-west-2`), Frankfurt (`eu-central-1`), Paris (`eu-west-3`), N. Virginia
(`us-east-1`), Ohio (`us-east-2`), Oregon (`us-west-2`), Canada Central
(`ca-central-1`), Singapore (`ap-southeast-1`), Sydney (`ap-southeast-2`), and
Tokyo (`ap-northeast-1`). GPU/CPU candidates, resource counts, original instance
prices and AZ/product identities are preserved. No pricing data is aggregated
across incompatible pools. No capacity, interruption probabilities, model
predictions, execution or provisioning is generated.

## CloudShell instructions

1. Download `multi-region-collector.zip` from this project and upload it using
   AWS CloudShell's **Actions → Upload file**. Upload the ZIP before running unzip.
2. Run:

```sh
cd ~
unzip multi-region-collector.zip
cd multi-region-collector
bash run.sh
```

Python 3.11+ and boto3 are required. CloudShell supplies its signed-in AWS session;
no access keys need to be copied into the bundle. If boto3 is missing, install it
with `python3 -m pip install --user boto3`, then rerun `bash run.sh`.

The script prints progress per region/instance and ends with **DOWNLOAD THIS FILE**
followed by an absolute ZIP path. Use **Actions → Download file**, paste that exact
path, then provide the downloaded ZIP for local import/validation. Keep the shell
open while it runs. Each invocation uses a fresh timestamped output name.

To collect a smaller/custom set instead:

```sh
bash run.sh --regions us-east-1,us-west-2,eu-west-1,eu-central-1
```

Changing the CloudShell UI region is not required: boto3 creates an EC2 client for
each configured target region. For local use, add `--profile your-profile` after
setting up that profile yourself. You can edit `multi-region-collection.json` to
reduce hardware candidates or days. `--end 2026-10-25T00:00:00Z` freezes a specific
UTC end hour only while its start remains within AWS's preceding 90-day limit.

## Permissions: the previous blocker

The prior account returned `UnauthorizedOperation` outside Stockholm. This
script cannot override IAM policies, session policies, permission boundaries,
organization restrictions, or account region settings. Permission to open
CloudShell is not proof that EC2 read calls are allowed in all target regions.

The bundle contains `read-only-policy.json`, also available as
[multi-region-read-policy.json](multi-region-read-policy.json), for the AWS account
administrator to review. It allows only these actions in the twelve requested
regions:

- `ec2:DescribeSpotPriceHistory`
- `ec2:DescribeInstanceTypes`
- `ec2:DescribeInstanceTypeOfferings`

The script does not attach this policy, change account settings or rent resources.
An additional Allow policy cannot cancel an applicable explicit Deny. If these
calls remain denied, the administrator must address the effective restriction or
provide an authorized export/account. Editing the collection script cannot fix it.
The condition's region list must also be updated if the administrator approves
other regions beyond those in the supplied policy.

Optional permission check for N. Virginia (read-only dry run):

```sh
aws ec2 describe-spot-price-history --region us-east-1 --instance-types g4dn.xlarge --product-descriptions Linux/UNIX --max-results 5 --dry-run
```

`DryRunOperation` is the expected permitted response and still has a nonzero CLI
exit code. `UnauthorizedOperation` means that check was denied. The two metadata
actions also need permission; a successful price dry run alone is insufficient.

## Output, storage and honest coverage

All regions use the same fixed UTC start/end window. The existing paginated,
checksummed collector verifies instance metadata before normalizing GPU/vCPU unit
prices. It isolates denied/not-offered/empty hardware pairs and retains explicit
exclusions. Raw SDK messages/credentials are not written to receipts.

The original uncompressed one-region export was about 155 MB locally; multiplying
that by twelve is unsuitable for CloudShell's 1 GB persistent home quota. This
wrapper expands **one region at a time in scratch storage**, compresses and CRC-
checks it, saves its regional ZIP, and cleans only that run's own temporary folder
before proceeding. Completed regional ZIPs remain if a later collection fails.
Actual storage use varies with data volume; it does not reserve or guarantee disk
space. No existing exports are deleted. The final outer ZIP stores the compressed
regional ZIPs without recompressing them.

The final download contains:

```text
multi-region-data-<UTC timestamp>/
  requested-config.json
  receipt.json
  eu-north-1.zip
  eu-west-1.zip
  ...
```

Each regional ZIP contains its own `receipt.json`, raw `spot-collection/`, verified
`resource-metadata/`, and per-pair `shards/`, in the same format as the earlier
expanded collector. A denied region still gets a small diagnostic ZIP. The outer
receipt records regions that actually yielded prices, error-code counts, pair
counts and SHA-256 hashes. `PARTIAL` is not complete global coverage. One collected
region does not establish multi-location access. If no usable data exists, the
CLI exits with code 2 after saving the diagnostic archive.

Raw events are exported; hourly expansion happens locally after download to avoid
inflating CloudShell storage. Import/retraining and evaluation for new regions
remain separate Person 1 steps. The currently served models/configuration are
unchanged and will not magically support previously unseen regional pools.

## Verification and sources

Offline tests exercise common cutoffs, nested archive integrity and hashes,
CPU/GPU identities, denied/no-data regions, redaction, scratch cleanup, disk
failure and preservation of completed exports. No live AWS requests were made
while packaging the script; successful regions depend on your actual credentials.

AWS documentation: [Spot price history API](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeSpotPriceHistory.html),
[instance metadata API](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypes.html),
[offerings API](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeInstanceTypeOfferings.html),
[IAM evaluation rules](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic_policy-eval-denyallow.html),
and [CloudShell storage limits](https://docs.aws.amazon.com/cloudshell/latest/userguide/limits.html).
