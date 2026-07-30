#!/usr/bin/env python3
"""验证正式分析的重复次数、行数、概率约束、点估计和图形完整性。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_DIR / "01_数据" / "处理后数据" / "七流域_2006-2020_日尺度标准化数据.csv"
ANALYSIS_SCRIPT = PROJECT_DIR / "02_分析代码" / "07_正式实证补强分析.py"
RESULT_DIR = PROJECT_DIR / "03_分析结果" / "正式分析"
TABLE_DIR = RESULT_DIR / "表"
FIGURE_DIR = RESULT_DIR / "图"
MANIFEST_PATH = RESULT_DIR / "正式分析核心产物哈希清单.csv"

BASINS = ["Ganjiang", "Fuhe", "Xinjiang", "Xiushui", "Liaohe", "Le'anhe", "Changjiang"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"PNG签名无效：{path.name}")
        length = struct.unpack(">I", handle.read(4))[0]
        if handle.read(4) != b"IHDR" or length != 13:
            raise AssertionError(f"PNG缺少IHDR：{path.name}")
        return struct.unpack(">II", handle.read(8))


def read_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(TABLE_DIR / name)


def load_analysis_module():
    spec = importlib.util.spec_from_file_location("formal_analysis", ANALYSIS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def core_files() -> list[Path]:
    files = sorted(TABLE_DIR.glob("*.csv")) + [TABLE_DIR / "00_正式分析参数.json"]
    return [path for path in files if path.exists()]


def build_manifest() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "relative_path": str(path.relative_to(PROJECT_DIR)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in core_files()
        ]
    )


def validate(compare_manifest: bool, write_manifest: bool) -> None:
    params = json.loads((TABLE_DIR / "00_正式分析参数.json").read_text(encoding="utf-8"))
    assert params["bootstrap_reps"] >= 2000
    assert params["null_reps"] >= 2000
    assert params["hydro_summary_bootstrap_reps"] >= 2000
    assert params["master_seed"] == 20260728
    assert params["input_sha256"] == sha256_file(INPUT_FILE)

    expected_rows = {
        "01_数据质量与元数据风险总表.csv": 7,
        "02a_年尺度水文统计_主分析.csv": 7,
        "02b_季节水文统计_主分析.csv": 28,
        "02c_逐年水文统计_全部敏感性.csv": 301,
        "03a_整体相关峰值滞后Bootstrap.csv": 7,
        "03b_整体最佳滞后概率分布.csv": 112,
        "03c_整体相关曲线Bootstrap区间.csv": 112,
        "04a_分季节相关峰值滞后Bootstrap.csv": 28,
        "04b_分季节最佳滞后概率分布.csv": 448,
        "04c_分季节相关曲线Bootstrap区间.csv": 448,
        "04d_季节间滞后分布重叠.csv": 42,
        "04e_逐年及逐冬季最佳滞后.csv": 483,
        "04f_留一季节整体峰值敏感性.csv": 28,
        "05a_max-statistic选择校正结果.csv": 14,
        "05b_max-statistic零假设分布.csv": 28000,
        "06a_敏感性结论稳定性矩阵.csv": 62,
        "06b_敏感性最佳滞后概率分布.csv": 992,
        "06c_敏感性年尺度水文指标.csv": 21,
        "06d_敏感性季节水文指标.csv": 84,
        "90_全部场景相关曲线Bootstrap区间.csv": 3780,
        "91_全部场景相关峰值Bootstrap汇总.csv": 540,
        "92_全部场景最佳滞后概率分布.csv": 8640,
    }
    for filename, expected in expected_rows.items():
        frame = read_csv(filename)
        assert len(frame) == expected, f"{filename}应为{expected}行，实际{len(frame)}"

    peaks = read_csv("03a_整体相关峰值滞后Bootstrap.csv")
    seasonal_peaks = read_csv("04a_分季节相关峰值滞后Bootstrap.csv")
    assert (peaks["bootstrap_reps"] >= 2000).all()
    assert (seasonal_peaks["bootstrap_reps"] >= 2000).all()
    assert set(peaks["basin_en"]) == set(BASINS)
    assert (peaks["search_max_lag_days"] == 15).all()
    assert set(seasonal_peaks["season"]) == {"Spring", "Summer", "Autumn", "Winter"}
    winter_blocks = seasonal_peaks.loc[seasonal_peaks["season"].eq("Winter"), "block_count"]
    assert (winter_blocks == 13).all()
    other_blocks = seasonal_peaks.loc[seasonal_peaks["season"].ne("Winter"), "block_count"]
    assert (other_blocks == 14).all()

    for filename in [
        "03b_整体最佳滞后概率分布.csv",
        "04b_分季节最佳滞后概率分布.csv",
        "92_全部场景最佳滞后概率分布.csv",
    ]:
        frame = read_csv(filename)
        keys = ["config_id", "basin_en", "season", "search_max_lag_days"]
        sums = frame.groupby(keys)["probability"].sum()
        assert np.allclose(sums.to_numpy(), 1.0, atol=1e-8), f"{filename}概率和不为1"

    maxstat = read_csv("05a_max-statistic选择校正结果.csv")
    assert (maxstat["null_reps"] >= 2000).all()
    expected_p = (1 + maxstat["exceedances"]) / (maxstat["null_reps"] + 1)
    assert np.allclose(maxstat["empirical_p_maxstat"], expected_p, atol=1e-12, rtol=0)
    lower_bound = 1 / (maxstat["null_reps"] + 1)
    assert (maxstat["empirical_p_maxstat"] >= lower_bound - 1e-12).all()
    assert (maxstat["empirical_p_maxstat"] <= 1).all()
    assert maxstat["fdr_bh_q"].between(0, 1).all()
    nulls = read_csv("05b_max-statistic零假设分布.csv")
    null_counts = nulls.groupby(["basin_en", "null_method"]).size()
    assert (null_counts == params["null_reps"]).all()

    sensitivity = read_csv("06a_敏感性结论稳定性矩阵.csv")
    assert set(sensitivity["conclusion_stability"]) <= {"完全一致", "基本稳定", "明显改变"}
    assert sensitivity["lag_distribution_overlap_vs_baseline"].between(0, 1).all()

    module = load_analysis_module()
    raw = pd.read_csv(INPUT_FILE, parse_dates=["date"])
    expected_point = peaks.set_index("basin_en")
    for basin_en in BASINS:
        frame = module.prepare_basin(raw, module.CONFIGS[0], basin_en)
        curve = module.observed_curve(module.make_blocks(frame, "All"), "spearman", 15)
        best = int(np.nanargmax(curve))
        assert best == int(expected_point.loc[basin_en, "observed_best_lag_days"])
        assert np.isclose(
            curve[best], expected_point.loc[basin_en, "observed_max_correlation"], atol=1e-9
        )

    figures = [
        "01_七流域季节降水与径流占比.png",
        "02_整体相关曲线及Bootstrap区间.png",
        "03_整体最佳滞后Bootstrap概率分布.png",
        "04_分季节滞后点区间图.png",
        "05_敏感性场景主要结论变化.png",
    ]
    for filename in figures:
        path = FIGURE_DIR / filename
        assert path.exists() and path.stat().st_size > 20_000, f"图形缺失或过小：{filename}"
        width, height = png_dimensions(path)
        assert width >= 2000 and height >= 1400, f"图形尺寸不足：{filename} {width}x{height}"

    current_manifest = build_manifest()
    if compare_manifest:
        assert MANIFEST_PATH.exists(), "缺少首次运行哈希清单，无法执行复现比较"
        previous = pd.read_csv(MANIFEST_PATH).sort_values("relative_path").reset_index(drop=True)
        current = current_manifest.sort_values("relative_path").reset_index(drop=True)
        pd.testing.assert_frame_equal(previous, current, check_dtype=False)
    if write_manifest:
        current_manifest.to_csv(MANIFEST_PATH, index=False, encoding="utf-8-sig")

    print("验证通过：正式分析重复次数、表格行数和概率约束均符合冻结记录。")
    print("验证通过：七流域点估计已从标准化日数据独立重算并一致。")
    print("验证通过：两类max-statistic零假设分布和5张正式PNG图齐全。")
    if compare_manifest:
        print("复现通过：核心表格与首次正式运行的SHA-256清单完全一致。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare-manifest", action="store_true")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    validate(args.compare_manifest, args.write_manifest)


if __name__ == "__main__":
    main()
