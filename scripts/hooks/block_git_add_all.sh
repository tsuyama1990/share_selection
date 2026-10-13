#!/usr/bin/env bash
# PreToolUse(Bash): forbid staging everything; stage explicit paths instead.
cmd=$(jq -r '.tool_input.command // ""')
if printf '%s' "$cmd" | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+add[[:space:]]+([^;&|]*[[:space:]])?(-A|--all|\.)([[:space:]]|$|[;&|])'; then
  echo "Blocked: 'git add -A/--all/.' is not allowed in this repo. Stage explicit paths, then check 'git status'." >&2
  exit 2
fi
exit 0
