#!/usr/bin/env sh
set -eu

usage() {
  cat <<'EOF'
Usage:
  scripts/run_baseline_case.sh [case_yaml] [--max-rounds N] [--session-id ID]

Examples:
  scripts/run_baseline_case.sh
  scripts/run_baseline_case.sh tests/v1.5_testset/v1_5_001.yaml
  scripts/run_baseline_case.sh tests/v1.5_testset/v1_5_001.yaml --max-rounds 2
  scripts/run_baseline_case.sh tests/v1.5_testset/v1_5_001.yaml --session-id S-MY-CASE-001
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

case_yaml=""
max_rounds=""
session_id=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --max-rounds)
      if [ "$#" -lt 2 ]; then
        echo "Error: --max-rounds requires a value." >&2
        exit 2
      fi
      max_rounds="$2"
      shift 2
      ;;
    --session-id)
      if [ "$#" -lt 2 ]; then
        echo "Error: --session-id requires a value." >&2
        exit 2
      fi
      session_id="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      echo "Error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [ -n "$case_yaml" ]; then
        echo "Error: multiple case files are not supported." >&2
        usage >&2
        exit 2
      fi
      case_yaml="$1"
      shift
      ;;
  esac
done

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

run_single_case() {
  case_yaml_path="$1"
  if [ ! -f "$case_yaml_path" ]; then
    echo "Error: case file not found: $case_yaml_path" >&2
    return 2
  fi

  case_yaml_abs="$(CDPATH= cd -- "$(dirname -- "$case_yaml_path")" && pwd)/$(basename -- "$case_yaml_path")"

  query="$(
    "$python_bin" - "$case_yaml_abs" <<'PY'
import sys
from pathlib import Path

import yaml

case_path = Path(sys.argv[1])
try:
    data = yaml.safe_load(case_path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"Error: failed to parse YAML: {case_path} ({exc})", file=sys.stderr)
    raise SystemExit(2)

if not isinstance(data, dict):
    print(f"Error: YAML root must be a mapping: {case_path}", file=sys.stderr)
    raise SystemExit(2)

query = data.get("query")
if not isinstance(query, str) or not query.strip():
    print(f"Error: missing or empty 'query' in {case_path}", file=sys.stderr)
    raise SystemExit(2)

sys.stdout.write(query)
PY
)"

  cd "$repo_root"
  if [ -n "$max_rounds" ] && [ -n "$session_id" ]; then
    "$python_bin" -m valuator.core.run_pipeline --query "$query" --max-rounds "$max_rounds" --session-id "$session_id"
  elif [ -n "$max_rounds" ]; then
    "$python_bin" -m valuator.core.run_pipeline --query "$query" --max-rounds "$max_rounds"
  elif [ -n "$session_id" ]; then
    "$python_bin" -m valuator.core.run_pipeline --query "$query" --session-id "$session_id"
  else
    "$python_bin" -m valuator.core.run_pipeline --query "$query"
  fi
}

if [ -z "$case_yaml" ]; then
  cases_dir="$repo_root/tests/v1.5_testset"
  if [ ! -d "$cases_dir" ]; then
    echo "Error: cases directory not found: $cases_dir" >&2
    exit 2
  fi

  case_list="$(mktemp)"
  find "$cases_dir" -maxdepth 1 -type f -name '*.yaml' | sort > "$case_list"
  if [ ! -s "$case_list" ]; then
    rm -f "$case_list"
    echo "Error: no YAML case files found in: $cases_dir" >&2
    exit 2
  fi

  run_failed=0
  while IFS= read -r file_path; do
    [ -n "$file_path" ] || continue
    echo "============================================================"
    echo "Running case: $file_path"
    base_session="$session_id"
    if [ -n "$base_session" ]; then
      case_id="$(basename -- "$file_path" .yaml)"
      session_id="${base_session}-${case_id}"
    fi
    if ! run_single_case "$file_path"; then
      run_failed=1
    fi
    session_id="$base_session"
  done < "$case_list"
  rm -f "$case_list"
  exit "$run_failed"
fi

run_single_case "$case_yaml"
