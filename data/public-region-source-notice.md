# Public data attribution

Eric Pauley (University of Wisconsin–Madison), **AWS Spot Price History**,
version **2026-09**, published 1 October 2026. Zenodo.
DOI: [10.5281/zenodo.23082767](https://doi.org/10.5281/zenodo.23082767).

The pinned record's API metadata declares **Creative Commons Attribution 4.0
International (CC-BY-4.0)**. License:
https://creativecommons.org/licenses/by/4.0/.
Original collection software: https://github.com/ericpauley/aws-spot-price-history.

This experiment uses only `2026-08.tsv.zst` and `2026-09.tsv.zst`. Changes made:
filter to five regions, eleven named instance types and Linux/UNIX; retain global
availability-zone IDs; normalize original USD/instance-hour prices using verified
instance GPU/vCPU counts; reconstruct backward-as-of hourly start prices within
each month. No missing months or future windows are filled. Source-adjusted
month-start anchors are retained with their published semantics.

Raw compressed files and the complete source metadata are preserved in
`data/raw/public-spot-import-001/`; published MD5 and local SHA-256 checksums are
recorded in `download-receipt.json`. The filtered event stream and normalized
hourly matrix are preserved in `data/processed/public-region-hourly-001/`.

This attribution applies to the public component. The original Stockholm export
retains its original AWS collection provenance. The author and AWS do not endorse
this model or its predictions. Public historical prices do not establish current
regional capacity or interruption probabilities.
