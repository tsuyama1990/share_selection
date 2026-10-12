#!/usr/bin/env bash
# Run every quality gate (same as CI). Exit non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run ruff check .
uv run ruff format --check .
uv run mypy src main.py
uv run pytest -q
