#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run_baseline_case.sh <case_yaml> [--max-rounds N] [--session-id ID]

Examples:
  scripts/run_baseline_case.sh tests/v1.5_testset/v1_5_001.yaml
  scripts/run_baseline_case.sh tests/v1.5_testset/v1_5_001.yaml --max-rounds 2
  scripts/run_baseline_case.sh tests/v1.5_testset/v1_5_001.yaml --session-id S-MY-CASE-001
EOF
}

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' is required but not found in PATH." >&2
  exit 2
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

case_yaml="$1"
shift

max_rounds=""
session_id=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-rounds)
      if [[ $# -lt 2 ]]; then
        echo "Error: --max-rounds requires a value." >&2
        exit 2
      fi
      max_rounds="$2"
      shift 2
      ;;
    --session-id)
      if [[ $# -lt 2 ]]; then
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
    *)
      echo "Error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$case_yaml" ]]; then
  echo "Error: case file not found: $case_yaml" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
case_yaml_abs="$(cd "$(dirname "$case_yaml")" && pwd)/$(basename "$case_yaml")"

query="$(
  uv run python - "$case_yaml_abs" <<'PY'
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

cmd=(
  uv run python -m valuator.core.run_pipeline
  --query "$query"
)

if [[ -n "$max_rounds" ]]; then
  cmd+=(--max-rounds "$max_rounds")
fi
if [[ -n "$session_id" ]]; then
  cmd+=(--session-id "$session_id")
fi

cd "$repo_root"
"${cmd[@]}"
