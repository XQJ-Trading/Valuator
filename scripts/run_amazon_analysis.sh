#!/usr/bin/env sh
set -eu

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"

python_bin="$repo_root/.venv/bin/python"
if [ ! -x "$python_bin" ]; then
  if command -v python3 >/dev/null 2>&1; then
    python_bin="$(command -v python3)"
  else
    echo "Error: python3 not found and .venv/bin/python is missing." >&2
    exit 2
  fi
fi

exec "$python_bin" \
  "$repo_root/scripts/run_recursive_agent_query.py" \
  --query-file "$repo_root/scripts/queries/amazon_analysis_ko.txt" \
  --model "gemini-3-flash-preview" \
  "$@"
