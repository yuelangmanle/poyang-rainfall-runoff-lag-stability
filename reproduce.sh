#!/bin/zsh
set -euo pipefail

REPO_DIR="${0:A:h}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
R_BIN="${R_BIN:-Rscript}"
MODE="${1:-formal}"

if [[ "$MODE" != "formal" && "$MODE" != "smoke" ]]; then
  print -u2 "用法：$0 [formal|smoke]"
  exit 2
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "找不到Python运行时：$PYTHON_BIN"
  exit 1
fi
if ! command -v "$R_BIN" >/dev/null 2>&1 && [[ ! -x "$R_BIN" ]]; then
  print -u2 "找不到R运行时：$R_BIN"
  exit 1
fi

run_pipeline() {
  local project_dir="$1"
  local validation_mode="$2"
  cd "$project_dir"

  "$PYTHON_BIN" -m py_compile \
    "02_分析代码/01_下载并校验Mendeley核心数据.py" \
    "02_分析代码/02_审计并标准化七流域日数据.py" \
    "02_分析代码/07_正式实证补强分析.py" \
    "02_分析代码/09_验证正式分析产物.py" \
    "02_分析代码/19_验证公开复现包.py"

  "$PYTHON_BIN" "02_分析代码/01_下载并校验Mendeley核心数据.py"
  "$PYTHON_BIN" "02_分析代码/02_审计并标准化七流域日数据.py"
  "$PYTHON_BIN" "02_分析代码/07_正式实证补强分析.py"
  "$R_BIN" "02_分析代码/08_绘制正式分析图.R"

  if [[ "$validation_mode" == "formal" ]]; then
    "$R_BIN" "02_分析代码/16_绘制投稿级结构重构预览图.R"
    "$PYTHON_BIN" "02_分析代码/09_验证正式分析产物.py" --compare-manifest
    "$PYTHON_BIN" "02_分析代码/19_验证公开复现包.py" --mode formal
  else
    "$PYTHON_BIN" "02_分析代码/19_验证公开复现包.py" --mode smoke
  fi
}

if [[ "$MODE" == "formal" ]]; then
  run_pipeline "$REPO_DIR" formal
else
  smoke_dir="$(mktemp -d "${TMPDIR:-/tmp}/poyang-lag-smoke.XXXXXX")"
  trap 'rm -rf "$smoke_dir"' EXIT INT TERM
  mkdir -p "$smoke_dir/01_数据/处理后数据"
  cp -R "$REPO_DIR/02_分析代码" "$smoke_dir/02_分析代码"
  export HYDRO_BOOT_REPS="${HYDRO_BOOT_REPS:-40}"
  export HYDRO_NULL_REPS="${HYDRO_NULL_REPS:-40}"
  export HYDRO_SUMMARY_BOOT_REPS="${HYDRO_SUMMARY_BOOT_REPS:-60}"
  export HYDRO_WORKERS="${HYDRO_WORKERS:-2}"
  run_pipeline "$smoke_dir" smoke
fi
