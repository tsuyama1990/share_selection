#!/usr/bin/env bash
# Usage: check_budget_increase.sh <base-ref>
# Fail if max_source_lines grew vs <base-ref> without a "Budget-Increase:" line in a commit message of base..HEAD.
set -euo pipefail
cd "$(dirname "$0")/.."
base=${1:?usage: check_budget_increase.sh <base-ref>}
get() { sed -nE 's/^max_source_lines *= *([0-9]+).*/\1/p'; }
old=$(git show "$base:pyproject.toml" 2>/dev/null | get || true)
new=$(get < pyproject.toml)
if [ -z "$old" ] || [ "$new" -le "$old" ]; then
  exit 0
fi
if git log --format=%B "$base..HEAD" | grep -q '^Budget-Increase:'; then
  exit 0
fi
echo "max_source_lines rose $old -> $new without a 'Budget-Increase:' line in any commit message of $base..HEAD" >&2
exit 1
