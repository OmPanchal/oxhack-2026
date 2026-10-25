#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"
export PYTHONPATH="$script_dir/backend${PYTHONPATH:+:$PYTHONPATH}"
output="multi-region-data-$(date -u +%Y%m%dT%H%M%SZ)"
exec python3 -m app.forecasting.collect_locations --config multi-region-collection.json --output "$output" "$@"
