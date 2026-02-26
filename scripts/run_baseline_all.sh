#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/run_baseline_all.sh [--cases-dir DIR] [--max-rounds N]

Defaults:
  --cases-dir tests/v1.5_testset

Examples:
  scripts/run_baseline_all.sh
  scripts/run_baseline_all.sh --cases-dir tests/v1.5_testset --max-rounds 2
EOF
}

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: 'uv' is required but not found in PATH." >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
runner="$script_dir/run_baseline_case.sh"

if [[ ! -f "$runner" ]]; then
  echo "Error: runner script not found: $runner" >&2
  exit 2
fi

cases_dir="tests/v1.5_testset"
max_rounds=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cases-dir)
      if [[ $# -lt 2 ]]; then
        echo "Error: --cases-dir requires a value." >&2
        exit 2
      fi
      cases_dir="$2"
      shift 2
      ;;
    --max-rounds)
      if [[ $# -lt 2 ]]; then
        echo "Error: --max-rounds requires a value." >&2
        exit 2
      fi
      max_rounds="$2"
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

cd "$repo_root"

if [[ ! -d "$cases_dir" ]]; then
  echo "Error: cases directory not found: $cases_dir" >&2
  exit 2
fi

case_files=()
while IFS= read -r file_path; do
  case_files+=("$file_path")
done < <(find "$cases_dir" -maxdepth 1 -type f -name '*.yaml' | sort)

if [[ ${#case_files[@]} -eq 0 ]]; then
  echo "Error: no YAML case files found in: $cases_dir" >&2
  exit 2
fi

successes=()
failures=()

run_one() {
  local case_file="$1"
  if [[ -n "$max_rounds" ]]; then
    "$runner" "$case_file" --max-rounds "$max_rounds"
  else
    "$runner" "$case_file"
  fi
}

for case_file in "${case_files[@]}"; do
  echo "============================================================"
  echo "[1/2] Running case: $case_file"
  if run_one "$case_file"; then
    successes+=("$case_file")
    continue
  fi

  echo "[2/2] Retrying case: $case_file"
  if run_one "$case_file"; then
    successes+=("$case_file")
  else
    failures+=("$case_file")
  fi
done

echo "============================================================"
echo "Run summary"
echo "total:   ${#case_files[@]}"
echo "success: ${#successes[@]}"
echo "failed:  ${#failures[@]}"

if [[ ${#successes[@]} -gt 0 ]]; then
  echo "successful cases:"
  for item in "${successes[@]}"; do
    echo "  - $item"
  done
fi

if [[ ${#failures[@]} -gt 0 ]]; then
  echo "failed cases:"
  for item in "${failures[@]}"; do
    echo "  - $item"
  done
  exit 1
fi

exit 0
