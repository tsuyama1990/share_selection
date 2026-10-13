#!/usr/bin/env bash
# Stop: uncommitted src/tests/config changes must pass the gates. After MAX_BLOCKS failed
# attempts in a session, stop anyway but tell the user the work is NOT done.
MAX_BLOCKS=3
input=$(cat)
cd "$(dirname "$0")/../.."
session=$(printf '%s' "$input" | jq -r '.session_id // "unknown"')
counter="$(git rev-parse --git-dir)/claude-stop-blocks-$session"
[ -z "$(git status --porcelain -- src main.py tests config.yaml pyproject.toml)" ] && { rm -f "$counter"; exit 0; }
if out=$(scripts/gate.sh 2>&1); then rm -f "$counter"; exit 0; fi
count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$count" > "$counter"
if [ "$count" -ge "$MAX_BLOCKS" ]; then
  rm -f "$counter"
  jq -n --arg m "NOT DONE: quality gates still fail after $MAX_BLOCKS attempts. Report what fails and what was tried; the user decides next steps." '{systemMessage:$m}'
  exit 0
fi
printf 'Quality gate failed (attempt %s/%s). Fix the root cause (no suppression), then finish.\n%s\n' "$count" "$MAX_BLOCKS" "$(printf '%s' "$out" | tail -40)" >&2
exit 2
