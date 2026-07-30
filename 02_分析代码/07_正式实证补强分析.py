#!/usr/bin/env python3
"""正式执行七流域年度整块bootstrap、max-statistic置换与敏感性分析。"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_DIR / "01_数据" / "处理后数据" / "七流域_2006-2020_日尺度标准化数据.csv"
SOURCE_TABLE_DIR = PROJECT_DIR / "03_分析结果" / "表"
RESULT_DIR = PROJECT_DIR / "03_分析结果" / "正式分析"
TABLE_DIR = RESULT_DIR / "表"
LOG_DIR = RESULT_DIR / "日志"

MASTER_SEED = 20260728
BOOT_REPS = int(os.environ.get("HYDRO_BOOT_REPS", "2000"))
NULL_REPS = int(os.environ.get("HYDRO_NULL_REPS", "2000"))
HYDRO_BOOT_REPS = int(os.environ.get("HYDRO_SUMMARY_BOOT_REPS", "5000"))
MAX_LAG = 20
PRIMARY_MAX_LAG = 15
WORKERS = max(1, min(int(os.environ.get("HYDRO_WORKERS", "5")), os.cpu_count() or 1))

BASIN_ORDER = ["Ganjiang", "Fuhe", "Xinjiang", "Xiushui", "Liaohe", "Le'anhe", "Changjiang"]
BASIN_CN = {
    "Ganjiang": "赣江",
    "Fuhe": "抚河",
    "Xinjiang": "信江",
    "Xiushui": "修水",
    "Liaohe": "潦河",
    "Le'anhe": "乐安河",
    "Changjiang": "昌江",
}
SEASONS = ["All", "Spring", "Summer", "Autumn", "Winter"]
SEASON_MONTHS = {
    "Spring": [3, 4, 5],
    "Summer": [6, 7, 8],
    "Autumn": [9, 10, 11],
    "Winter": [12, 1, 2],
}
SEASON_MAP = {
    1: "Winter",
    2: "Winter",
    3: "Spring",
    4: "Spring",
    5: "Spring",
    6: "Summer",
    7: "Summer",
    8: "Summer",
    9: "Autumn",
    10: "Autumn",
    11: "Autumn",
    12: "Winter",
}

CONFIGS = [
    {
        "config_id": "main_month_median_spearman",
        "start": "2006-01-01",
        "end": "2019-12-31",
        "deseason": "month_median",
        "correlation": "spearman",
        "modifier": "none",
        "basins": BASIN_ORDER,
    },
    {
        "config_id": "full2020_month_median_spearman",
        "start": "2006-01-01",
        "end": "2020-12-31",
        "deseason": "month_median",
        "correlation": "spearman",
        "modifier": "none",
        "basins": BASIN_ORDER,
    },
    {
        "config_id": "main_smooth_doy_spearman",
        "start": "2006-01-01",
        "end": "2019-12-31",
        "deseason": "smooth_doy31",
        "correlation": "spearman",
        "modifier": "none",
        "basins": BASIN_ORDER,
    },
    {
        "config_id": "main_raw_spearman",
        "start": "2006-01-01",
        "end": "2019-12-31",
        "deseason": "raw",
        "correlation": "spearman",
        "modifier": "none",
        "basins": BASIN_ORDER,
    },
    {
        "config_id": "main_month_median_pearson",
        "start": "2006-01-01",
        "end": "2019-12-31",
        "deseason": "month_median",
        "correlation": "pearson",
        "modifier": "none",
        "basins": BASIN_ORDER,
    },
    {
        "config_id": "main_ganjiang_extreme_missing",
        "start": "2006-01-01",
        "end": "2019-12-31",
        "deseason": "month_median",
        "correlation": "spearman",
        "modifier": "ganjiang_2019_05_19_missing",
        "basins": ["Ganjiang"],
    },
]


def stable_seed(*parts: object) -> int:
    payload = "|".join(str(part) for part in (MASTER_SEED, *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**32)


def average_ranks(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    starts = np.r_[0, np.flatnonzero(sorted_values[1:] != sorted_values[:-1]) + 1]
    ends = np.r_[starts[1:], len(values)]
    average = (starts + 1 + ends) / 2.0
    ranked_sorted = np.repeat(average, ends - starts)
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = ranked_sorted
    return ranks


def pearson_corr(x: np.ndarray, y: np.ndarray) -> float:
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 3:
        return np.nan
    x_valid = np.asarray(x[valid], dtype=float)
    y_valid = np.asarray(y[valid], dtype=float)
    x_centered = x_valid - x_valid.mean()
    y_centered = y_valid - y_valid.mean()
    denominator = np.sqrt(np.dot(x_centered, x_centered) * np.dot(y_centered, y_centered))
    if denominator == 0:
        return np.nan
    return float(np.dot(x_centered, y_centered) / denominator)


def correlation(x: np.ndarray, y: np.ndarray, method: str) -> float:
    valid = np.isfinite(x) & np.isfinite(y)
    if valid.sum() < 3:
        return np.nan
    x_valid = np.asarray(x[valid], dtype=float)
    y_valid = np.asarray(y[valid], dtype=float)
    if method == "spearman":
        return pearson_corr(average_ranks(x_valid), average_ranks(y_valid))
    if method == "pearson":
        return pearson_corr(x_valid, y_valid)
    raise ValueError(f"未知相关方法：{method}")


def smooth_calendar_climatology(frame: pd.DataFrame, column: str) -> np.ndarray:
    reference = pd.to_datetime("2000-" + frame["date"].dt.strftime("%m-%d"))
    calendar_index = reference.dt.dayofyear.to_numpy() - 1
    climatology = np.full(366, np.nan, dtype=float)
    values = frame[column].to_numpy(dtype=float)
    for day in range(366):
        day_values = values[calendar_index == day]
        climatology[day] = np.nanmean(day_values) if np.isfinite(day_values).any() else np.nan
    if not np.isfinite(climatology[59]):
        climatology[59] = np.nanmean([climatology[58], climatology[60]])
    padded = np.r_[climatology[-15:], climatology, climatology[:15]]
    smoothed = np.convolve(padded, np.ones(31, dtype=float) / 31.0, mode="valid")
    return smoothed[calendar_index]


def prepare_basin(raw: pd.DataFrame, config: dict, basin_en: str) -> pd.DataFrame:
    frame = raw.loc[
        raw["basin_en"].eq(basin_en) & raw["date"].between(config["start"], config["end"])
    ].copy()
    frame = frame.sort_values("date").reset_index(drop=True)
    frame["precipitation"] = frame["precipitation_mm_inferred"].astype(float)
    frame["runoff"] = frame["runoff_depth_mm_inferred"].astype(float)
    if config["modifier"] == "ganjiang_2019_05_19_missing":
        target = frame["date"].eq(pd.Timestamp("2019-05-19"))
        if basin_en != "Ganjiang" or target.sum() != 1:
            raise AssertionError("赣江极端值敏感性目标记录异常")
        frame.loc[target, "precipitation"] = np.nan

    if config["deseason"] == "month_median":
        month = frame["date"].dt.month
        frame["p_work"] = frame["precipitation"] - frame.groupby(month)[
            "precipitation"
        ].transform("median")
        frame["q_work"] = frame["runoff"] - frame.groupby(month)["runoff"].transform(
            "median"
        )
    elif config["deseason"] == "smooth_doy31":
        frame["p_work"] = frame["precipitation"] - smooth_calendar_climatology(
            frame, "precipitation"
        )
        frame["q_work"] = frame["runoff"] - smooth_calendar_climatology(frame, "runoff")
    elif config["deseason"] == "raw":
        frame["p_work"] = frame["precipitation"]
        frame["q_work"] = frame["runoff"]
    else:
        raise ValueError(f"未知去季节方法：{config['deseason']}")
    frame["season"] = frame["date"].dt.month.map(SEASON_MAP)
    return frame


def expected_season_dates(year: int, season: str) -> pd.DatetimeIndex:
    if season == "Spring":
        return pd.date_range(f"{year}-03-01", f"{year}-05-31", freq="D")
    if season == "Summer":
        return pd.date_range(f"{year}-06-01", f"{year}-08-31", freq="D")
    if season == "Autumn":
        return pd.date_range(f"{year}-09-01", f"{year}-11-30", freq="D")
    if season == "Winter":
        return pd.date_range(f"{year - 1}-12-01", f"{year}-02-{pd.Timestamp(year, 2, 1).days_in_month}", freq="D")
    return pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")


def make_blocks(frame: pd.DataFrame, season: str) -> list[dict]:
    working = frame.copy()
    if season == "Winter":
        working = working.loc[working["date"].dt.month.isin(SEASON_MONTHS[season])].copy()
        working["block_year"] = working["date"].dt.year + working["date"].dt.month.eq(12).astype(int)
    else:
        if season != "All":
            working = working.loc[working["date"].dt.month.isin(SEASON_MONTHS[season])].copy()
        working["block_year"] = working["date"].dt.year

    blocks = []
    for block_year, group in working.groupby("block_year", sort=True):
        group = group.sort_values("date")
        expected = expected_season_dates(int(block_year), season)
        if len(group) != len(expected) or not pd.DatetimeIndex(group["date"]).equals(expected):
            continue
        blocks.append(
            {
                "label": int(block_year),
                "date": group["date"].to_numpy(),
                "p": group["p_work"].to_numpy(dtype=float),
                "q": group["q_work"].to_numpy(dtype=float),
            }
        )
    if not blocks:
        raise AssertionError(f"{season}没有完整时间块")
    return blocks


def lag_pairs(block: dict, lag: int) -> tuple[np.ndarray, np.ndarray]:
    if lag == 0:
        return block["p"], block["q"]
    return block["p"][:-lag], block["q"][lag:]


def observed_curve(blocks: list[dict], method: str, max_lag: int = MAX_LAG) -> np.ndarray:
    values = np.full(max_lag + 1, np.nan, dtype=float)
    for lag in range(max_lag + 1):
        pairs = [lag_pairs(block, lag) for block in blocks]
        x = np.concatenate([pair[0] for pair in pairs])
        y = np.concatenate([pair[1] for pair in pairs])
        values[lag] = correlation(x, y, method)
    return values


def bootstrap_curves(
    blocks: list[dict], method: str, reps: int, seed: int, max_lag: int = MAX_LAG
) -> np.ndarray:
    pair_blocks = []
    for lag in range(max_lag + 1):
        pair_blocks.append([lag_pairs(block, lag) for block in blocks])
    rng = np.random.default_rng(seed)
    output = np.full((reps, max_lag + 1), np.nan, dtype=np.float32)
    for rep in range(reps):
        selected = rng.integers(0, len(blocks), size=len(blocks))
        for lag in range(max_lag + 1):
            pairs = pair_blocks[lag]
            x = np.concatenate([pairs[index][0] for index in selected])
            y = np.concatenate([pairs[index][1] for index in selected])
            output[rep, lag] = correlation(x, y, method)
    return output


def format_lag_ranges(lags: np.ndarray) -> str:
    if len(lags) == 0:
        return ""
    ranges = []
    start = previous = int(lags[0])
    for value in map(int, lags[1:]):
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ";".join(ranges)


def summarize_window(
    observed: np.ndarray,
    bootstrap: np.ndarray,
    max_lag: int,
    metadata: dict,
) -> tuple[dict, list[dict]]:
    observed_window = observed[: max_lag + 1]
    bootstrap_window = bootstrap[:, : max_lag + 1]
    observed_best_lag = int(np.nanargmax(observed_window))
    observed_max = float(observed_window[observed_best_lag])
    best_lags = np.nanargmax(bootstrap_window, axis=1)
    best_values = np.nanmax(bootstrap_window, axis=1)
    counts = np.bincount(best_lags, minlength=max_lag + 1)
    mode_lag = int(np.flatnonzero(counts == counts.max())[0])
    mode_probability = float(counts[mode_lag] / len(best_lags))
    lag_low, lag_high = np.quantile(best_lags, [0.025, 0.975])
    interval_width = float(lag_high - lag_low)
    stability = "稳定" if mode_probability >= 0.50 and interval_width <= 3.0 else "不稳定"
    near_001 = np.flatnonzero(observed_max - observed_window <= 0.01 + 1e-12)
    near_002 = np.flatnonzero(observed_max - observed_window <= 0.02 + 1e-12)
    peak_low, peak_median, peak_high = np.quantile(best_values, [0.025, 0.5, 0.975])
    summary = {
        **metadata,
        "search_max_lag_days": max_lag,
        "observed_best_lag_days": observed_best_lag,
        "observed_max_correlation": observed_max,
        "bootstrap_max_correlation_median": float(peak_median),
        "bootstrap_max_correlation_ci025": float(peak_low),
        "bootstrap_max_correlation_ci975": float(peak_high),
        "bootstrap_best_lag_mode_days": mode_lag,
        "bootstrap_mode_probability": mode_probability,
        "bootstrap_best_lag_ci025": float(lag_low),
        "bootstrap_best_lag_ci975": float(lag_high),
        "bootstrap_best_lag_ci_width_days": interval_width,
        "near_peak_001_lag_ranges": format_lag_ranges(near_001),
        "near_peak_002_lag_ranges": format_lag_ranges(near_002),
        "stability_class": stability,
        "bootstrap_reps": len(bootstrap),
    }
    probabilities = [
        {
            **metadata,
            "search_max_lag_days": max_lag,
            "lag_days": lag,
            "probability": float(counts[lag] / len(best_lags)),
            "bootstrap_reps": len(bootstrap),
        }
        for lag in range(max_lag + 1)
    ]
    return summary, probabilities


def analyze_task(input_file: str, config: dict, basin_en: str) -> dict:
    raw = pd.read_csv(input_file, parse_dates=["date"])
    frame = prepare_basin(raw, config, basin_en)
    curve_rows = []
    peak_rows = []
    probability_rows = []
    yearly_rows = []
    for season in SEASONS:
        blocks = make_blocks(frame, season)
        observed = observed_curve(blocks, config["correlation"])
        seed = stable_seed(config["config_id"], basin_en, season, "bootstrap")
        boot = bootstrap_curves(blocks, config["correlation"], BOOT_REPS, seed)
        metadata = {
            "config_id": config["config_id"],
            "basin_en": basin_en,
            "basin_cn": BASIN_CN[basin_en],
            "season": season,
            "block_count": len(blocks),
            "correlation_method": config["correlation"],
            "deseason_method": config["deseason"],
        }
        curve_low = np.quantile(boot, 0.025, axis=0)
        curve_median = np.quantile(boot, 0.5, axis=0)
        curve_high = np.quantile(boot, 0.975, axis=0)
        for lag in range(MAX_LAG + 1):
            curve_rows.append(
                {
                    **metadata,
                    "lag_days": lag,
                    "observed_correlation": float(observed[lag]),
                    "bootstrap_correlation_median": float(curve_median[lag]),
                    "bootstrap_correlation_ci025": float(curve_low[lag]),
                    "bootstrap_correlation_ci975": float(curve_high[lag]),
                    "bootstrap_reps": BOOT_REPS,
                }
            )
        for window in (10, 15, 20):
            summary, probabilities = summarize_window(observed, boot, window, metadata)
            peak_rows.append(summary)
            probability_rows.extend(probabilities)

        for block in blocks:
            block_curve = observed_curve([block], config["correlation"], PRIMARY_MAX_LAG)
            best_lag = int(np.nanargmax(block_curve))
            yearly_rows.append(
                {
                    **metadata,
                    "block_year": block["label"],
                    "best_lag_days": best_lag,
                    "max_correlation": float(block_curve[best_lag]),
                }
            )
    return {
        "config_id": config["config_id"],
        "basin_en": basin_en,
        "curve_rows": curve_rows,
        "peak_rows": peak_rows,
        "probability_rows": probability_rows,
        "yearly_rows": yearly_rows,
    }


def transformed_null_blocks(
    blocks: list[dict], rng: np.random.Generator, method: str, block_length: int = 30
) -> list[dict]:
    transformed = []
    for block in blocks:
        p = block["p"]
        if method == "annual_circular_shift":
            if len(p) <= 62:
                raise AssertionError("年度块长度不足以避开0-30天移位邻域")
            shift = int(rng.integers(31, len(p) - 30))
            p_null = np.roll(p, shift)
        elif method == "within_year_30d_block_permutation":
            pieces = [p[start : start + block_length] for start in range(0, len(p), block_length)]
            order = rng.permutation(len(pieces))
            p_null = np.concatenate([pieces[index] for index in order])[: len(p)]
        else:
            raise ValueError(f"未知零假设构造方法：{method}")
        transformed.append({**block, "p": p_null})
    return transformed


def maxstat_task(input_file: str, basin_en: str) -> dict:
    raw = pd.read_csv(input_file, parse_dates=["date"])
    baseline = CONFIGS[0]
    frame = prepare_basin(raw, baseline, basin_en)
    blocks = make_blocks(frame, "All")
    observed = observed_curve(blocks, "spearman", PRIMARY_MAX_LAG)
    observed_max = float(np.nanmax(observed))
    observed_best = int(np.nanargmax(observed))
    null_rows = []
    summary_rows = []
    for null_method in ("annual_circular_shift", "within_year_30d_block_permutation"):
        rng = np.random.default_rng(stable_seed(basin_en, null_method, "maxstat"))
        null_maxima = np.full(NULL_REPS, np.nan, dtype=float)
        for rep in range(NULL_REPS):
            null_blocks = transformed_null_blocks(blocks, rng, null_method)
            null_curve = observed_curve(null_blocks, "spearman", PRIMARY_MAX_LAG)
            null_maxima[rep] = np.nanmax(null_curve)
        exceedances = int(np.sum(null_maxima >= observed_max))
        empirical_p = float((1 + exceedances) / (NULL_REPS + 1))
        summary_rows.append(
            {
                "basin_en": basin_en,
                "basin_cn": BASIN_CN[basin_en],
                "null_method": null_method,
                "observed_best_lag_days": observed_best,
                "observed_max_correlation": observed_max,
                "null_max_median": float(np.quantile(null_maxima, 0.5)),
                "null_max_q95": float(np.quantile(null_maxima, 0.95)),
                "null_max_q99": float(np.quantile(null_maxima, 0.99)),
                "exceedances": exceedances,
                "empirical_p_maxstat": empirical_p,
                "monte_carlo_se": float(np.sqrt(empirical_p * (1 - empirical_p) / (NULL_REPS + 1))),
                "null_reps": NULL_REPS,
            }
        )
        null_rows.extend(
            {
                "basin_en": basin_en,
                "basin_cn": BASIN_CN[basin_en],
                "null_method": null_method,
                "replicate": rep + 1,
                "null_max_correlation": float(value),
            }
            for rep, value in enumerate(null_maxima)
        )
    return {"basin_en": basin_en, "summary_rows": summary_rows, "null_rows": null_rows}


def bh_adjust(p_values: pd.Series) -> np.ndarray:
    values = p_values.to_numpy(dtype=float)
    order = np.argsort(values)
    ranked = values[order]
    adjusted_ranked = ranked * len(values) / np.arange(1, len(values) + 1)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted = np.empty(len(values), dtype=float)
    adjusted[order] = np.minimum(adjusted_ranked, 1.0)
    return adjusted


def hydro_summaries(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scenarios = [
        ("main_2006_2019_raw", "2006-01-01", "2019-12-31", False),
        ("full_2006_2020_raw", "2006-01-01", "2020-12-31", False),
        ("main_ganjiang_2019_05_19_missing", "2006-01-01", "2019-12-31", True),
    ]
    annual_frames = []
    seasonal_frames = []
    for scenario, start, end, drop_extreme in scenarios:
        data = raw.loc[raw["date"].between(start, end)].copy()
        data["precipitation"] = data["precipitation_mm_inferred"].astype(float)
        data["runoff"] = data["runoff_depth_mm_inferred"].astype(float)
        if drop_extreme:
            mask = data["basin_en"].eq("Ganjiang") & data["date"].eq(pd.Timestamp("2019-05-19"))
            data.loc[mask, "precipitation"] = np.nan
        data["year"] = data["date"].dt.year
        data["season"] = data["date"].dt.month.map(SEASON_MAP)
        annual = (
            data.groupby(["basin_en", "basin_cn", "year"], as_index=False)
            .agg(
                precipitation_mm=("precipitation", lambda x: x.sum(min_count=1)),
                runoff_depth_mm=("runoff", lambda x: x.sum(min_count=1)),
                precipitation_valid_days=("precipitation", "count"),
                runoff_valid_days=("runoff", "count"),
            )
        )
        annual["runoff_coefficient"] = annual["runoff_depth_mm"] / annual["precipitation_mm"]
        annual["scenario"] = scenario
        annual_frames.append(annual)
        seasonal = (
            data.groupby(["basin_en", "basin_cn", "year", "season"], as_index=False)
            .agg(
                precipitation_mm=("precipitation", lambda x: x.sum(min_count=1)),
                runoff_depth_mm=("runoff", lambda x: x.sum(min_count=1)),
            )
        )
        seasonal["scenario"] = scenario
        seasonal_frames.append(seasonal)

    annual_all = pd.concat(annual_frames, ignore_index=True)
    seasonal_all = pd.concat(seasonal_frames, ignore_index=True)
    overall_rows = []
    seasonal_rows = []
    for (scenario, basin_en, basin_cn), group in annual_all.groupby(
        ["scenario", "basin_en", "basin_cn"], sort=False
    ):
        row = {
            "scenario": scenario,
            "basin_en": basin_en,
            "basin_cn": basin_cn,
            "years": int(group["year"].nunique()),
            "mean_annual_precipitation_mm": float(group["precipitation_mm"].mean()),
            "mean_annual_runoff_depth_mm": float(group["runoff_depth_mm"].mean()),
            "mean_annual_runoff_coefficient": float(group["runoff_coefficient"].mean()),
            "ratio_of_mean_annual_runoff_to_precipitation": float(
                group["runoff_depth_mm"].mean() / group["precipitation_mm"].mean()
            ),
        }
        if scenario == "main_2006_2019_raw":
            rng = np.random.default_rng(stable_seed(basin_en, "hydro_annual_bootstrap"))
            values = group[
                ["precipitation_mm", "runoff_depth_mm", "runoff_coefficient"]
            ].to_numpy(dtype=float)
            selected = rng.integers(0, len(values), size=(HYDRO_BOOT_REPS, len(values)))
            means = values[selected].mean(axis=1)
            for index, name in enumerate(
                ["mean_annual_precipitation_mm", "mean_annual_runoff_depth_mm", "mean_annual_runoff_coefficient"]
            ):
                low, high = np.quantile(means[:, index], [0.025, 0.975])
                row[f"{name}_ci025"] = float(low)
                row[f"{name}_ci975"] = float(high)
            row["bootstrap_reps"] = HYDRO_BOOT_REPS
        overall_rows.append(row)

    for (scenario, basin_en, basin_cn), group in seasonal_all.groupby(
        ["scenario", "basin_en", "basin_cn"], sort=False
    ):
        pivot_p = group.pivot(index="year", columns="season", values="precipitation_mm")
        pivot_q = group.pivot(index="year", columns="season", values="runoff_depth_mm")
        season_order = ["Spring", "Summer", "Autumn", "Winter"]
        pivot_p = pivot_p.reindex(columns=season_order)
        pivot_q = pivot_q.reindex(columns=season_order)
        p_total = float(np.nansum(pivot_p.to_numpy()))
        q_total = float(np.nansum(pivot_q.to_numpy()))
        bootstrap_fraction_p = bootstrap_fraction_q = bootstrap_coefficient = None
        if scenario == "main_2006_2019_raw":
            rng = np.random.default_rng(stable_seed(basin_en, "hydro_season_bootstrap"))
            selected = rng.integers(0, len(pivot_p), size=(HYDRO_BOOT_REPS, len(pivot_p)))
            p_samples = pivot_p.to_numpy(dtype=float)[selected].sum(axis=1)
            q_samples = pivot_q.to_numpy(dtype=float)[selected].sum(axis=1)
            bootstrap_fraction_p = p_samples / p_samples.sum(axis=1, keepdims=True)
            bootstrap_fraction_q = q_samples / q_samples.sum(axis=1, keepdims=True)
            bootstrap_coefficient = q_samples / p_samples
        for index, season in enumerate(season_order):
            p_season = float(np.nansum(pivot_p[season].to_numpy()))
            q_season = float(np.nansum(pivot_q[season].to_numpy()))
            row = {
                "scenario": scenario,
                "basin_en": basin_en,
                "basin_cn": basin_cn,
                "season": season,
                "precipitation_fraction": p_season / p_total,
                "runoff_fraction": q_season / q_total,
                "seasonal_runoff_coefficient": q_season / p_season,
            }
            if bootstrap_fraction_p is not None:
                row["precipitation_fraction_ci025"], row["precipitation_fraction_ci975"] = map(
                    float, np.quantile(bootstrap_fraction_p[:, index], [0.025, 0.975])
                )
                row["runoff_fraction_ci025"], row["runoff_fraction_ci975"] = map(
                    float, np.quantile(bootstrap_fraction_q[:, index], [0.025, 0.975])
                )
                row["seasonal_runoff_coefficient_ci025"], row[
                    "seasonal_runoff_coefficient_ci975"
                ] = map(float, np.quantile(bootstrap_coefficient[:, index], [0.025, 0.975]))
                row["bootstrap_reps"] = HYDRO_BOOT_REPS
            seasonal_rows.append(row)
    return annual_all, pd.DataFrame(overall_rows), pd.DataFrame(seasonal_rows)


def build_quality_table() -> pd.DataFrame:
    audit = pd.read_csv(SOURCE_TABLE_DIR / "01_原始Excel数据审计总表.csv")
    areas = pd.read_csv(SOURCE_TABLE_DIR / "03_流量换算公式与面积审计.csv")
    anomalies = pd.read_csv(SOURCE_TABLE_DIR / "04_极端值复核清单_未作删除.csv")
    rows = []
    for basin_en in BASIN_ORDER:
        basin_audit = audit.loc[audit["basin_en"].eq(basin_en)]
        basin_area = areas.loc[areas["basin_en"].eq(basin_en)].iloc[0]
        basin_anomalies = anomalies.loc[anomalies["basin_cn"].eq(BASIN_CN[basin_en])]
        rows.append(
            {
                "basin_en": basin_en,
                "basin_cn": BASIN_CN[basin_en],
                "files_audited": len(basin_audit),
                "all_dates_complete": bool(basin_audit["date_sequence_complete"].all()),
                "missing_values": int(basin_audit["missing_values"].sum()),
                "negative_values": int(basin_audit["negative_values"].sum()),
                "precip_extreme_gt200_count": int(
                    (basin_anomalies["variable"] == "precipitation_mm_inferred").sum()
                ),
                "runoff_extreme_gt50_count": int(
                    (basin_anomalies["variable"] == "runoff_depth_mm_inferred").sum()
                ),
                "formula_area_km2": basin_area["area_km2_from_formula"],
                "runoff_unit_status": basin_area["runoff_depth_unit_status"],
                "precip_unit_status": "P_UNIT_INFERRED",
                "shared_2020_precipitation_risk": True,
                "station_identity_verified": False,
                "metadata_risk_note": (
                    "潦河无流量换算公式链；坐标元数据存在冲突"
                    if basin_en == "Liaohe"
                    else "降水单位未在原表明示；具体站点身份未验证"
                ),
            }
        )
    return pd.DataFrame(rows)


def curve_excluding_season(frame: pd.DataFrame, excluded: str) -> np.ndarray:
    values = np.full(PRIMARY_MAX_LAG + 1, np.nan, dtype=float)
    full_blocks = make_blocks(frame, "All")
    for lag in range(PRIMARY_MAX_LAG + 1):
        x_parts = []
        y_parts = []
        for block in full_blocks:
            dates = pd.DatetimeIndex(block["date"])
            if lag == 0:
                x = block["p"]
                y = block["q"]
                p_dates = dates
                q_dates = dates
            else:
                x = block["p"][:-lag]
                y = block["q"][lag:]
                p_dates = dates[:-lag]
                q_dates = dates[lag:]
            p_season = pd.Series(p_dates.month).map(SEASON_MAP).to_numpy()
            q_season = pd.Series(q_dates.month).map(SEASON_MAP).to_numpy()
            keep = (p_season != excluded) & (q_season != excluded)
            x_parts.append(x[keep])
            y_parts.append(y[keep])
        values[lag] = correlation(np.concatenate(x_parts), np.concatenate(y_parts), "spearman")
    return values


def seasonal_overlap(probabilities: pd.DataFrame) -> pd.DataFrame:
    source = probabilities.loc[
        probabilities["config_id"].eq("main_month_median_spearman")
        & probabilities["search_max_lag_days"].eq(PRIMARY_MAX_LAG)
        & probabilities["season"].ne("All")
    ]
    rows = []
    for basin_en in BASIN_ORDER:
        basin = source.loc[source["basin_en"].eq(basin_en)]
        for first, second in itertools.combinations(SEASONS[1:], 2):
            first_p = basin.loc[basin["season"].eq(first)].sort_values("lag_days")[
                "probability"
            ].to_numpy()
            second_p = basin.loc[basin["season"].eq(second)].sort_values("lag_days")[
                "probability"
            ].to_numpy()
            rows.append(
                {
                    "basin_en": basin_en,
                    "basin_cn": BASIN_CN[basin_en],
                    "season_1": first,
                    "season_2": second,
                    "lag_distribution_overlap": float(np.minimum(first_p, second_p).sum()),
                }
            )
    return pd.DataFrame(rows)


def leave_one_season_table(raw: pd.DataFrame, baseline_peaks: pd.DataFrame) -> pd.DataFrame:
    rows = []
    baseline = CONFIGS[0]
    for basin_en in BASIN_ORDER:
        frame = prepare_basin(raw, baseline, basin_en)
        base = baseline_peaks.loc[baseline_peaks["basin_en"].eq(basin_en)].iloc[0]
        near_lags = set()
        for token in str(base["near_peak_002_lag_ranges"]).split(";"):
            if not token:
                continue
            if "-" in token:
                start, end = map(int, token.split("-"))
                near_lags.update(range(start, end + 1))
            else:
                near_lags.add(int(token))
        for excluded in SEASONS[1:]:
            curve = curve_excluding_season(frame, excluded)
            best = int(np.nanargmax(curve))
            rows.append(
                {
                    "basin_en": basin_en,
                    "basin_cn": BASIN_CN[basin_en],
                    "excluded_season": excluded,
                    "baseline_best_lag_days": int(base["observed_best_lag_days"]),
                    "leave_one_season_best_lag_days": best,
                    "lag_change_days": best - int(base["observed_best_lag_days"]),
                    "leave_one_season_max_correlation": float(curve[best]),
                    "within_baseline_near_peak_002": best in near_lags,
                }
            )
    return pd.DataFrame(rows)


def select_config_rows(
    frame: pd.DataFrame,
    config_id: str,
    search_window: int,
    season: str | None = "All",
    basins: list[str] | None = None,
) -> pd.DataFrame:
    mask = frame["config_id"].eq(config_id) & frame["search_max_lag_days"].eq(search_window)
    if season is not None:
        mask &= frame["season"].eq(season)
    selected = frame.loc[mask].copy()
    if basins is not None:
        selected = selected.loc[selected["basin_en"].isin(basins)].copy()
    return selected


def build_sensitivity_tables(
    peaks: pd.DataFrame, probabilities: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mappings = [
        ("baseline", "基准：2006-2019月份中位数异常Spearman，0-15天", "main_month_median_spearman", 15, BASIN_ORDER),
        ("include_2020", "加入2020年共同降水序列", "full2020_month_median_spearman", 15, BASIN_ORDER),
        ("ganjiang_extreme_missing", "赣江2019-05-19降水设缺失", "main_ganjiang_extreme_missing", 15, ["Ganjiang"]),
        ("smooth_doy31", "31日日历日平滑气候态异常Spearman", "main_smooth_doy_spearman", 15, BASIN_ORDER),
        ("raw_spearman", "原始序列Spearman", "main_raw_spearman", 15, BASIN_ORDER),
        ("month_median_pearson", "月份中位数异常Pearson", "main_month_median_pearson", 15, BASIN_ORDER),
        ("lag_window_0_10", "搜索窗0-10天", "main_month_median_spearman", 10, BASIN_ORDER),
        ("lag_window_0_20", "搜索窗0-20天", "main_month_median_spearman", 20, BASIN_ORDER),
        ("exclude_liaohe", "排除潦河后的六流域", "main_month_median_spearman", 15, [b for b in BASIN_ORDER if b != "Liaohe"]),
    ]
    peak_parts = []
    probability_parts = []
    baseline_peak = select_config_rows(peaks, "main_month_median_spearman", 15).set_index("basin_en")
    baseline_prob = select_config_rows(
        probabilities, "main_month_median_spearman", 15
    ).set_index(["basin_en", "lag_days"])

    for scenario_id, label, config_id, window, basins in mappings:
        selected_peaks = select_config_rows(peaks, config_id, window, basins=basins)
        selected_prob = select_config_rows(probabilities, config_id, window, basins=basins)
        if scenario_id == "ganjiang_extreme_missing":
            other_peaks = select_config_rows(
                peaks,
                "main_month_median_spearman",
                15,
                basins=[basin for basin in BASIN_ORDER if basin != "Ganjiang"],
            )
            other_prob = select_config_rows(
                probabilities,
                "main_month_median_spearman",
                15,
                basins=[basin for basin in BASIN_ORDER if basin != "Ganjiang"],
            )
            selected_peaks = pd.concat([selected_peaks, other_peaks], ignore_index=True)
            selected_prob = pd.concat([selected_prob, other_prob], ignore_index=True)
        selected_peaks = selected_peaks.copy()
        selected_peaks["scenario_id"] = scenario_id
        selected_peaks["scenario_label"] = label
        selected_prob = selected_prob.copy()
        selected_prob["scenario_id"] = scenario_id
        selected_prob["scenario_label"] = label
        peak_parts.append(selected_peaks)
        probability_parts.append(selected_prob)

    sensitivity = pd.concat(peak_parts, ignore_index=True)
    scenario_probabilities = pd.concat(probability_parts, ignore_index=True)
    sensitivity["observed_rho_rank_desc"] = sensitivity.groupby("scenario_id")[
        "observed_max_correlation"
    ].rank(method="min", ascending=False)
    sensitivity["mode_lag_rank_asc"] = sensitivity.groupby("scenario_id")[
        "bootstrap_best_lag_mode_days"
    ].rank(method="min", ascending=True)

    overlaps = []
    for row in sensitivity.itertuples():
        scenario_p = scenario_probabilities.loc[
            scenario_probabilities["scenario_id"].eq(row.scenario_id)
            & scenario_probabilities["basin_en"].eq(row.basin_en)
        ].set_index("lag_days")["probability"]
        baseline_p = baseline_prob.loc[row.basin_en]["probability"]
        union_lags = sorted(set(scenario_p.index) | set(baseline_p.index))
        overlap = sum(min(float(scenario_p.get(lag, 0.0)), float(baseline_p.get(lag, 0.0))) for lag in union_lags)
        base = baseline_peak.loc[row.basin_en]
        observed_delta = int(row.observed_best_lag_days - base["observed_best_lag_days"])
        mode_delta = int(row.bootstrap_best_lag_mode_days - base["bootstrap_best_lag_mode_days"])
        if (
            observed_delta == 0
            and mode_delta == 0
            and overlap >= 0.75
            and row.stability_class == base["stability_class"]
        ):
            status = "完全一致"
        elif abs(observed_delta) <= 1 and overlap >= 0.50:
            status = "基本稳定"
        else:
            status = "明显改变"
        overlaps.append(
            {
                "scenario_id": row.scenario_id,
                "basin_en": row.basin_en,
                "lag_distribution_overlap_vs_baseline": overlap,
                "observed_best_lag_change_days": observed_delta,
                "bootstrap_mode_lag_change_days": mode_delta,
                "conclusion_stability": status,
            }
        )
    sensitivity = sensitivity.merge(pd.DataFrame(overlaps), on=["scenario_id", "basin_en"])
    return sensitivity, scenario_probabilities


def write_csv(frame: pd.DataFrame, filename: str) -> None:
    frame.to_csv(TABLE_DIR / filename, index=False, encoding="utf-8-sig", float_format="%.10g")


def main() -> None:
    started = time.time()
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(INPUT_FILE, parse_dates=["date"])
    if len(raw) != 38353 or raw["basin_en"].nunique() != 7:
        raise AssertionError("标准化输入数据规模不符合冻结记录")

    tasks = [
        (config, basin_en)
        for config in CONFIGS
        for basin_en in config["basins"]
    ]
    results = []
    if WORKERS == 1:
        for index, (config, basin_en) in enumerate(tasks, start=1):
            results.append(analyze_task(str(INPUT_FILE), config, basin_en))
            print(f"BOOTSTRAP完成 {index}/{len(tasks)}: {config['config_id']} {basin_en}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=WORKERS) as executor:
            future_map = {
                executor.submit(analyze_task, str(INPUT_FILE), config, basin_en): (
                    config["config_id"],
                    basin_en,
                )
                for config, basin_en in tasks
            }
            for index, future in enumerate(as_completed(future_map), start=1):
                config_id, basin_en = future_map[future]
                results.append(future.result())
                print(f"BOOTSTRAP完成 {index}/{len(tasks)}: {config_id} {basin_en}", flush=True)

    curves = pd.DataFrame([row for result in results for row in result["curve_rows"]])
    peaks = pd.DataFrame([row for result in results for row in result["peak_rows"]])
    probabilities = pd.DataFrame(
        [row for result in results for row in result["probability_rows"]]
    )
    yearly = pd.DataFrame([row for result in results for row in result["yearly_rows"]])

    sort_columns = ["config_id", "basin_en", "season"]
    curves = curves.sort_values(sort_columns + ["lag_days"]).reset_index(drop=True)
    peaks = peaks.sort_values(sort_columns + ["search_max_lag_days"]).reset_index(drop=True)
    probabilities = probabilities.sort_values(
        sort_columns + ["search_max_lag_days", "lag_days"]
    ).reset_index(drop=True)
    yearly = yearly.sort_values(sort_columns + ["block_year"]).reset_index(drop=True)

    baseline_peaks = select_config_rows(peaks, "main_month_median_spearman", 15, season=None)
    baseline_overall = baseline_peaks.loc[baseline_peaks["season"].eq("All")].copy()
    baseline_seasonal = baseline_peaks.loc[baseline_peaks["season"].ne("All")].copy()
    baseline_curves = curves.loc[
        curves["config_id"].eq("main_month_median_spearman") & curves["lag_days"].le(15)
    ].copy()
    baseline_probabilities = probabilities.loc[
        probabilities["config_id"].eq("main_month_median_spearman")
        & probabilities["search_max_lag_days"].eq(15)
    ].copy()
    baseline_yearly = yearly.loc[yearly["config_id"].eq("main_month_median_spearman")].copy()

    overlaps = seasonal_overlap(probabilities)
    leave_one = leave_one_season_table(raw, baseline_overall)
    sensitivity, sensitivity_probabilities = build_sensitivity_tables(peaks, probabilities)

    print("开始max-statistic零假设置换", flush=True)
    null_results = []
    if WORKERS == 1:
        for basin_en in BASIN_ORDER:
            null_results.append(maxstat_task(str(INPUT_FILE), basin_en))
            print(f"MAXSTAT完成: {basin_en}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=WORKERS) as executor:
            future_map = {
                executor.submit(maxstat_task, str(INPUT_FILE), basin_en): basin_en
                for basin_en in BASIN_ORDER
            }
            for future in as_completed(future_map):
                basin_en = future_map[future]
                null_results.append(future.result())
                print(f"MAXSTAT完成: {basin_en}", flush=True)
    maxstat = pd.DataFrame([row for result in null_results for row in result["summary_rows"]])
    null_distribution = pd.DataFrame(
        [row for result in null_results for row in result["null_rows"]]
    )
    maxstat = maxstat.sort_values(["null_method", "basin_en"]).reset_index(drop=True)
    null_distribution = null_distribution.sort_values(
        ["null_method", "basin_en", "replicate"]
    ).reset_index(drop=True)
    maxstat["fdr_bh_q"] = maxstat.groupby("null_method", group_keys=False)[
        "empirical_p_maxstat"
    ].transform(lambda values: bh_adjust(values))
    maxstat["passes_fdr_005"] = maxstat["fdr_bh_q"] <= 0.05

    annual_raw, hydro_overall, hydro_seasonal = hydro_summaries(raw)
    quality = build_quality_table()

    hydro_baseline = hydro_overall.loc[hydro_overall["scenario"].eq("main_2006_2019_raw")]
    hydro_seasonal_baseline = hydro_seasonal.loc[
        hydro_seasonal["scenario"].eq("main_2006_2019_raw")
    ]

    write_csv(quality, "01_数据质量与元数据风险总表.csv")
    write_csv(hydro_baseline, "02a_年尺度水文统计_主分析.csv")
    write_csv(hydro_seasonal_baseline, "02b_季节水文统计_主分析.csv")
    write_csv(annual_raw, "02c_逐年水文统计_全部敏感性.csv")
    write_csv(baseline_overall, "03a_整体相关峰值滞后Bootstrap.csv")
    write_csv(
        baseline_probabilities.loc[baseline_probabilities["season"].eq("All")],
        "03b_整体最佳滞后概率分布.csv",
    )
    write_csv(
        baseline_curves.loc[baseline_curves["season"].eq("All")],
        "03c_整体相关曲线Bootstrap区间.csv",
    )
    write_csv(baseline_seasonal, "04a_分季节相关峰值滞后Bootstrap.csv")
    write_csv(
        baseline_probabilities.loc[baseline_probabilities["season"].ne("All")],
        "04b_分季节最佳滞后概率分布.csv",
    )
    write_csv(
        baseline_curves.loc[baseline_curves["season"].ne("All")],
        "04c_分季节相关曲线Bootstrap区间.csv",
    )
    write_csv(overlaps, "04d_季节间滞后分布重叠.csv")
    write_csv(baseline_yearly, "04e_逐年及逐冬季最佳滞后.csv")
    write_csv(leave_one, "04f_留一季节整体峰值敏感性.csv")
    write_csv(maxstat, "05a_max-statistic选择校正结果.csv")
    write_csv(null_distribution, "05b_max-statistic零假设分布.csv")
    write_csv(sensitivity, "06a_敏感性结论稳定性矩阵.csv")
    write_csv(sensitivity_probabilities, "06b_敏感性最佳滞后概率分布.csv")
    write_csv(hydro_overall, "06c_敏感性年尺度水文指标.csv")
    write_csv(hydro_seasonal, "06d_敏感性季节水文指标.csv")
    write_csv(curves, "90_全部场景相关曲线Bootstrap区间.csv")
    write_csv(peaks, "91_全部场景相关峰值Bootstrap汇总.csv")
    write_csv(probabilities, "92_全部场景最佳滞后概率分布.csv")

    params = {
        "analysis_version": "formal_v1",
        "freeze_date": "2026-07-28",
        "master_seed": MASTER_SEED,
        "bootstrap_reps": BOOT_REPS,
        "null_reps": NULL_REPS,
        "hydro_summary_bootstrap_reps": HYDRO_BOOT_REPS,
        "workers": WORKERS,
        "primary_period": ["2006-01-01", "2019-12-31"],
        "sensitivity_period_end": "2020-12-31",
        "primary_search_lags": [0, 15],
        "sensitivity_search_lags": [[0, 10], [0, 20]],
        "near_peak_thresholds": [0.01, 0.02],
        "stable_mode_probability_min": 0.50,
        "stable_ci_width_days_max": 3.0,
        "null_methods": ["annual_circular_shift", "within_year_30d_block_permutation"],
        "input_file": str(INPUT_FILE.relative_to(PROJECT_DIR)),
        "input_sha256": hashlib.sha256(INPUT_FILE.read_bytes()).hexdigest(),
    }
    (TABLE_DIR / "00_正式分析参数.json").write_text(
        json.dumps(params, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    elapsed = time.time() - started
    log = {
        "status": "completed",
        "elapsed_seconds": elapsed,
        "bootstrap_tasks": len(tasks),
        "bootstrap_reps_per_task_season": BOOT_REPS,
        "null_reps_per_basin_method": NULL_REPS,
        "output_csv_count": len(list(TABLE_DIR.glob("*.csv"))),
    }
    (LOG_DIR / "正式分析运行摘要.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"正式分析完成，耗时{elapsed:.1f}秒，表目录：{TABLE_DIR}", flush=True)


if __name__ == "__main__":
    main()
