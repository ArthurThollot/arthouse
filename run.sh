#!/bin/bash
# Manual entry point. Builds once, then serves output/index.html locally
# with a Refresh button on the page -- nothing runs automatically or on a
# schedule; data only changes when you load the page or click Refresh.
set -euo pipefail
cd "$(dirname "$0")"
uv run python serve.py "$@"
