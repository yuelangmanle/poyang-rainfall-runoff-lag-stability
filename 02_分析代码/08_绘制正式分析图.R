#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(ggplot2)
  library(dplyr)
  library(tidyr)
})

args <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args, value = TRUE)
script_path <- normalizePath(sub("^--file=", "", file_arg[1]))
project_dir <- dirname(dirname(script_path))
table_dir <- file.path(project_dir, "03_分析结果", "正式分析", "表")
figure_dir <- file.path(project_dir, "03_分析结果", "正式分析", "图")
dir.create(figure_dir, recursive = TRUE, showWarnings = FALSE)
source(file.path(project_dir, "02_分析代码", "11_投稿级图件公共样式.R"))

read_table <- function(name) {
  read.csv(file.path(table_dir, name), fileEncoding = "UTF-8-BOM", check.names = FALSE)
}

save_png <- function(plot, name, width, height) {
  png(
    file.path(figure_dir, name),
    width = width,
    height = height,
    res = 200,
    type = "cairo"
  )
  print(plot)
  dev.off()
}

basin_levels <- c("赣江", "抚河", "信江", "修水", "潦河", "乐安河", "昌江")
season_levels <- c("Spring", "Summer", "Autumn", "Winter")
season_labels <- c(Spring = "春", Summer = "夏", Autumn = "秋", Winter = "冬")
season_colors <- c(Spring = "#4C956C", Summer = "#2F6B8A", Autumn = "#D99A2B", Winter = "#7A7A7A")

base_theme <- theme_minimal(base_size = 11, base_family = ZH_FONT) +
  theme(
    panel.grid.minor = element_blank(),
    strip.text = element_text(face = "bold"),
    axis.text = element_text(color = "#222222"),
    plot.title = element_text(face = "bold", size = 14),
    plot.subtitle = element_text(color = "#555555"),
    legend.position = "top"
  )

seasonal <- read_table("02b_季节水文统计_主分析.csv") %>%
  mutate(
    basin_cn = factor(basin_cn, levels = basin_levels),
    season = factor(season, levels = season_levels)
  )

season_long <- seasonal %>%
  select(basin_cn, season, precipitation_fraction, runoff_fraction) %>%
  pivot_longer(
    cols = c(precipitation_fraction, runoff_fraction),
    names_to = "variable",
    values_to = "fraction"
  ) %>%
  mutate(
    variable = recode(variable, precipitation_fraction = "降水", runoff_fraction = "径流"),
    variable = factor(variable, levels = c("降水", "径流"))
  )

p1 <- ggplot(season_long, aes(x = basin_cn, y = fraction, fill = season)) +
  geom_col(width = 0.74, color = "white", linewidth = 0.25) +
  facet_wrap(~variable, ncol = 1) +
  scale_fill_manual(values = season_colors, labels = season_labels, name = "季节") +
  scale_y_continuous(labels = function(x) sprintf("%.0f%%", x * 100), expand = expansion(mult = c(0, 0.04))) +
  labs(
    title = "七流域降水与径流的季节分配",
    subtitle = "主分析期：2006-2019年；柱内各季节占比之和为100%",
    x = NULL,
    y = "季节占比"
  ) +
  base_theme
save_png(p1, "01_七流域季节降水与径流占比.png", 2200, 1700)

curve <- read_table("03c_整体相关曲线Bootstrap区间.csv") %>%
  mutate(basin_cn = factor(basin_cn, levels = basin_levels))

p2 <- ggplot(curve, aes(x = lag_days, y = observed_correlation)) +
  geom_ribbon(
    aes(ymin = bootstrap_correlation_ci025, ymax = bootstrap_correlation_ci975),
    fill = "#A8C7D8",
    alpha = 0.55
  ) +
  geom_line(color = "#1F596F", linewidth = 0.75) +
  geom_point(color = "#C85A32", size = 1.25) +
  facet_wrap(~basin_cn, ncol = 3, scales = "free_y") +
  scale_x_continuous(breaks = seq(0, 15, 3)) +
  labs(
    title = "月份中位数去季节后的降水-径流相关曲线",
    subtitle = "阴影为年度整块bootstrap 95%区间；正滞后表示Q(t+k)",
    x = "滞后（天）",
    y = "Spearman相关系数"
  ) +
  base_theme +
  theme(legend.position = "none")
save_png(p2, "02_整体相关曲线及Bootstrap区间.png", 2400, 1800)

probability <- read_table("03b_整体最佳滞后概率分布.csv") %>%
  mutate(basin_cn = factor(basin_cn, levels = basin_levels))

p3 <- ggplot(probability, aes(x = lag_days, y = probability)) +
  geom_col(fill = "#2F6B8A", width = 0.8) +
  geom_hline(yintercept = 0.5, color = "#C85A32", linetype = "dashed", linewidth = 0.5) +
  facet_wrap(~basin_cn, ncol = 3) +
  scale_x_continuous(breaks = seq(0, 15, 3)) +
  scale_y_continuous(labels = function(x) sprintf("%.0f%%", x * 100), limits = c(0, 1)) +
  labs(
    title = "整体最佳相关滞后的bootstrap概率分布",
    subtitle = "虚线为预设稳定性门槛：众数概率0.50",
    x = "最佳滞后（天）",
    y = "概率"
  ) +
  base_theme +
  theme(legend.position = "none")
save_png(p3, "03_整体最佳滞后Bootstrap概率分布.png", 2400, 1800)

season_peak <- read_table("04a_分季节相关峰值滞后Bootstrap.csv") %>%
  mutate(
    basin_cn = factor(basin_cn, levels = basin_levels),
    season = factor(season, levels = season_levels),
    stability_class = factor(stability_class, levels = c("稳定", "不稳定"))
  )

p4 <- ggplot(
  season_peak,
  aes(
    x = season,
    y = bootstrap_best_lag_mode_days,
    ymin = bootstrap_best_lag_ci025,
    ymax = bootstrap_best_lag_ci975,
    color = stability_class
  )
) +
  geom_linerange(linewidth = 0.65) +
  geom_point(size = 2.2) +
  facet_wrap(~basin_cn, ncol = 3) +
  scale_x_discrete(labels = season_labels) +
  scale_y_continuous(breaks = seq(0, 15, 3), limits = c(0, 15)) +
  scale_color_manual(values = c("稳定" = "#2D7D46", "不稳定" = "#C45A35"), drop = FALSE) +
  labs(
    title = "分季节最佳相关滞后的稳定性",
    subtitle = "点为bootstrap众数，线为最佳滞后95%中心区间",
    x = "季节",
    y = "滞后（天）",
    color = "稳定性"
  ) +
  base_theme
save_png(p4, "04_分季节滞后点区间图.png", 2400, 1800)

sensitivity <- read_table("06a_敏感性结论稳定性矩阵.csv") %>%
  filter(scenario_id != "baseline") %>%
  mutate(
    basin_cn = factor(basin_cn, levels = basin_levels),
    scenario_short = recode(
      scenario_id,
      include_2020 = "加入2020",
      ganjiang_extreme_missing = "赣江极端值缺失",
      smooth_doy31 = "日历日平滑异常",
      raw_spearman = "原始Spearman",
      month_median_pearson = "Pearson",
      lag_window_0_10 = "窗口0-10天",
      lag_window_0_20 = "窗口0-20天",
      exclude_liaohe = "排除潦河"
    ),
    scenario_short = factor(
      scenario_short,
      levels = c(
        "加入2020", "赣江极端值缺失", "日历日平滑异常", "原始Spearman",
        "Pearson", "窗口0-10天", "窗口0-20天", "排除潦河"
      )
    ),
    conclusion_stability = factor(
      conclusion_stability,
      levels = c("完全一致", "基本稳定", "明显改变")
    )
  )

p5 <- ggplot(
  sensitivity,
  aes(x = basin_cn, y = scenario_short, fill = conclusion_stability)
) +
  geom_tile(color = "white", linewidth = 0.7) +
  geom_text(aes(label = bootstrap_best_lag_mode_days), size = 3.3) +
  scale_fill_manual(
    values = c("完全一致" = "#B8D8BE", "基本稳定" = "#F2D38A", "明显改变" = "#E59B86"),
    na.value = "#E6E6E6",
    drop = FALSE
  ) +
  labs(
    title = "敏感性场景下相关峰值滞后结论变化",
    subtitle = "格内数字为bootstrap众数滞后（天）；空格表示该场景不适用",
    x = NULL,
    y = NULL,
    fill = "相对基准"
  ) +
  base_theme +
  theme(panel.grid = element_blank(), axis.text.x = element_text(angle = 30, hjust = 1))
save_png(p5, "05_敏感性场景主要结论变化.png", 2400, 1500)

cat("正式分析图已写入：", figure_dir, "\n")
