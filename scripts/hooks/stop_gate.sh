#!/usr/bin/env bash
# Stop: if code/config/tests changed and are uncommitted, the quality gates must pass before stopping.
input=$(cat)
[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0
cd "$(dirname "$0")/../.."
changed=$(git status --porcelain -- src main.py tests config.yaml pyproject.toml)
[ -z "$changed" ] && exit 0
if ! out=$(scripts/gate.sh 2>&1); then
  printf 'Quality gate failed for uncommitted changes. Fix the root cause (no suppression), then finish.\n%s\n' "$(printf '%s' "$out" | tail -40)" >&2
  exit 2
fi
exit 0
