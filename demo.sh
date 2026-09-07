#!/usr/bin/env bash
# Rebuild the tracked demo page from synthetic data. No GitHub access needed.
set -euo pipefail
cd "$(dirname "$0")"
python3 demo/generate.py
python3 -m mergeprint.build --raw demo/raw.json --config demo/config.json --out docs/index.html --demo
