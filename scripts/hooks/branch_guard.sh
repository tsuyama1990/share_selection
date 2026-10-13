#!/usr/bin/env bash
# PreToolUse(Edit|Write|NotebookEdit|Bash git commit): no direct work on main. Branch first.
input=$(cat)
root="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
branch=$(git -C "$root" branch --show-current)
case "$branch" in main|master) ;; *) exit 0 ;; esac
tool=$(printf '%s' "$input" | jq -r '.tool_name')
if [ "$tool" = "Bash" ]; then
  printf '%s' "$input" | jq -r '.tool_input.command' | grep -Eq '(^|[;&|[:space:]])git[[:space:]]+commit' || exit 0
else
  path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // ""')
  case "$path" in "$root"/*) ;; *) exit 0 ;; esac
fi
echo "Blocked: on '$branch'. Create a branch first (git checkout -b <type>/<topic>), work and commit there, then merge with --no-ff once the done criteria are verified." >&2
exit 2
