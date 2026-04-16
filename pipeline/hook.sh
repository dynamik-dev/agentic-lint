#!/usr/bin/env bash
set -euo pipefail

# Agentic Lint -- PostToolUse hook for Claude Code
# Fires on Edit/Write. Runs the two-phase lint pipeline.
# On block (exit 2), violations are printed to stderr per Claude Code hook contract.
# On evaluate, the semantic payload is injected via hookSpecificOutput.additionalContext.
# On pass, exits 0 silently.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
OLD_STRING=$(echo "$INPUT" | jq -r '.tool_input.old_string // empty')
NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.new_string // empty')

# For Write calls, old_string is empty and new_string is the full file content.
if [[ "$TOOL_NAME" == "Write" ]]; then
  NEW_STRING=$(echo "$INPUT" | jq -r '.tool_input.content // empty')
fi

if [[ -z "$FILE_PATH" || ! -f "$FILE_PATH" ]]; then
  exit 0
fi

# Walk up from the file to find .agentic-lint.yml
PROJECT_DIR="$FILE_PATH"
CONFIG=""
while [[ "$PROJECT_DIR" != "/" ]]; do
  PROJECT_DIR="$(dirname "$PROJECT_DIR")"
  if [[ -f "$PROJECT_DIR/.agentic-lint.yml" ]]; then
    CONFIG="$PROJECT_DIR/.agentic-lint.yml"
    break
  fi
done

if [[ -z "$CONFIG" ]]; then
  exit 0
fi

# Pass the edit details as JSON to the pipeline so it can build a real
# line-numbered unified diff against the file on disk.
PAYLOAD=$(jq -n \
  --arg tool "$TOOL_NAME" \
  --arg file "$FILE_PATH" \
  --arg old "$OLD_STRING" \
  --arg new "$NEW_STRING" \
  '{tool_name: $tool, file_path: $file, old_string: $old, new_string: $new}')

# Run the pipeline. Capture stdout separately from stderr so we can
# decide how to surface them to the agent.
STDOUT_FILE=$(mktemp)
STDERR_FILE=$(mktemp)
trap 'rm -f "$STDOUT_FILE" "$STDERR_FILE"' EXIT

set +e
echo "$PAYLOAD" | python3 "$SCRIPT_DIR/pipeline.py" "$CONFIG" "$FILE_PATH" \
  >"$STDOUT_FILE" 2>"$STDERR_FILE"
EXIT_CODE=$?
set -e

# Blocked: propagate exit 2 with violation text on stderr.
# Claude Code treats stderr on exit 2 as feedback the agent must address.
if [[ $EXIT_CODE -eq 2 ]]; then
  cat "$STDERR_FILE" >&2
  exit 2
fi

RESULT=$(cat "$STDOUT_FILE")
if [[ -z "$RESULT" ]]; then
  exit 0
fi

STATUS=$(echo "$RESULT" | jq -r '.status // "pass"')

if [[ "$STATUS" == "pass" ]]; then
  exit 0
fi

# Evaluate: inject the full JSON payload as additionalContext so the
# agentic-lint skill can parse and act on it.
if [[ "$STATUS" == "evaluate" ]]; then
  CTX="AGENTIC LINT SEMANTIC EVALUATION REQUIRED:

$(echo "$RESULT" | jq -c '.')"
  jq -n --arg ctx "$CTX" '{
    "hookSpecificOutput": {
      "hookEventName": "PostToolUse",
      "additionalContext": $ctx
    }
  }'
fi

exit 0
