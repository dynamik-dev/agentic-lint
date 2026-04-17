#!/usr/bin/env bash
# Run the bully pipeline against every source file in this repo.
# Dogfooding: the tool should lint itself cleanly.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

CONFIG="$REPO_DIR/.bully.yml"
if [[ ! -f "$CONFIG" ]]; then
  echo "no .bully.yml at repo root -- skipping dogfood"
  exit 0
fi

fail=0
err_file=$(mktemp)
trap 'rm -f "$err_file"' EXIT

# macOS default bash (3.2) lacks mapfile, so stream from find into a loop.
while IFS= read -r file; do
  if ! python3 pipeline/pipeline.py --config "$CONFIG" --file "$file" >/dev/null 2>"$err_file"; then
    echo "-- $file"
    cat "$err_file"
    fail=1
  fi
done < <(
  find \
    pipeline \
    skills \
    scripts \
    docs \
    examples \
    -type f \
    \( -name "*.py" -o -name "*.sh" -o -name "*.md" -o -name "*.yml" -o -name "*.yaml" \) \
    ! -path "*/.pytest_cache/*" \
    ! -path "*/__pycache__/*" \
    ! -path "*/.bully/*" \
    2>/dev/null
)

exit $fail
