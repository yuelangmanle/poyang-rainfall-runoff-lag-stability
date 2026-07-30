#!/usr/bin/env python3
"""验证公开复现包的输入、正式结果表和论文最终四图。"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
PROCESSED = PROJECT_DIR / "01_数据" / "处理后数据" / "七流域_2006-2020_日尺度标准化数据.csv"
PARAMETERS = PROJECT_DIR / "03_分析结果" / "正式分析" / "表" / "00_正式分析参数.json"
TABLE_DIR = PARAMETERS.parent
FIGURE_DIR = PROJECT_DIR / "03_分析结果" / "投稿级图预览" / "结构重构版"
ANALYSIS_FIGURE_DIR = PROJECT_DIR / "03_分析结果" / "正式分析" / "图"

FIGURE_STEMS = (
    "01_季节水文指纹",
    "02_总体响应层叠证据",
    "03_季节稳定性图谱",
    "04_基准情景峰位转移",
)
ANALYSIS_FIGURES = (
    "01_七流域季节降水与径流占比.png",
    "02_整体相关曲线及Bootstrap区间.png",
    "03_整体最佳滞后Bootstrap概率分布.png",
    "04_分季节滞后点区间图.png",
    "05_敏感性场景主要结论变化.png",
)

EXPECTED_TABLE_ROWS = {
    "01_数据质量与元数据风险总表.csv": 7,
    "02a_年尺度水文统计_主分析.csv": 7,
    "02b_季节水文统计_主分析.csv": 28,
    "03a_整体相关峰值滞后Bootstrap.csv": 7,
    "03b_整体最佳滞后概率分布.csv": 112,
    "03c_整体相关曲线Bootstrap区间.csv": 112,
    "04a_分季节相关峰值滞后Bootstrap.csv": 28,
    "04b_分季节最佳滞后概率分布.csv": 448,
    "04c_分季节相关曲线Bootstrap区间.csv": 448,
    "05a_max-statistic选择校正结果.csv": 14,
    "06a_敏感性结论稳定性矩阵.csv": 62,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"PNG签名无效：{path}")
        length = struct.unpack(">I", handle.read(4))[0]
        if handle.read(4) != b"IHDR" or length != 13:
            raise AssertionError(f"PNG缺少IHDR：{path}")
        return struct.unpack(">II", handle.read(8))


def validate(mode: str) -> None:
    assert PROCESSED.exists(), f"缺少标准化数据：{PROCESSED}"
    daily = pd.read_csv(PROCESSED)
    assert len(daily) == 7 * 5479, f"标准化数据行数异常：{len(daily)}"
    assert daily["basin_en"].nunique() == 7
    assert daily["date"].min() == "2006-01-01"
    assert daily["date"].max() == "2020-12-31"

    checksum_file = PROCESSED.with_suffix(PROCESSED.suffix + ".sha256")
    if checksum_file.exists() and mode == "formal":
        expected = checksum_file.read_text(encoding="utf-8").split()[0]
        assert sha256(PROCESSED) == expected, "标准化数据SHA-256与冻结值不一致"

    params = json.loads(PARAMETERS.read_text(encoding="utf-8"))
    if mode == "formal":
        assert params["bootstrap_reps"] == 2000
        assert params["null_reps"] == 2000
        assert params["hydro_summary_bootstrap_reps"] == 5000
        assert params["master_seed"] == 20260728
    else:
        assert 1 <= params["bootstrap_reps"] < 2000
        assert 1 <= params["null_reps"] < 2000
        assert 1 <= params["hydro_summary_bootstrap_reps"] < 5000

    for filename, rows in EXPECTED_TABLE_ROWS.items():
        path = TABLE_DIR / filename
        assert path.exists(), f"缺少正式结果表：{path}"
        observed = len(pd.read_csv(path))
        assert observed == rows, f"{filename}行数异常：{observed} != {rows}"

    for filename in ANALYSIS_FIGURES:
        path = ANALYSIS_FIGURE_DIR / filename
        assert path.exists() and path.stat().st_size > 1024, f"缺少基础分析图：{path}"
        width, height = png_dimensions(path)
        assert width >= 1500 and height >= 900, f"基础分析图分辨率不足：{filename} {width}x{height}"

    if mode == "formal":
        for stem in FIGURE_STEMS:
            for suffix in (".png", ".pdf", ".svg"):
                path = FIGURE_DIR / f"{stem}{suffix}"
                assert path.exists() and path.stat().st_size > 1024, f"缺少或空图件：{path}"
            width, height = png_dimensions(FIGURE_DIR / f"{stem}.png")
            assert width >= 4000 and height >= 2500, f"图件分辨率不足：{stem} {width}x{height}"
            assert (FIGURE_DIR / f"{stem}.pdf").read_bytes().startswith(b"%PDF-")
            assert b"<svg" in (FIGURE_DIR / f"{stem}.svg").read_bytes()[:1000]

    figure_message = "4幅最终图" if mode == "formal" else "5幅基础分析图"
    print(f"公开复现包验证通过：mode={mode}，7个流域，{len(EXPECTED_TABLE_ROWS)}张核心表，{figure_message}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("formal", "smoke"), default="formal")
    args = parser.parse_args()
    validate(args.mode)


if __name__ == "__main__":
    main()
