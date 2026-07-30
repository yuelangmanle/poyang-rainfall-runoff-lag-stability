#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(ggplot2)
  library(dplyr)
  library(tidyr)
  library(patchwork)
  library(scales)
  library(grid)
})

args_all <- commandArgs(trailingOnly = FALSE)
file_arg <- grep("^--file=", args_all, value = TRUE)
if (length(file_arg) != 1) stop("无法确定绘图脚本路径", call. = FALSE)

script_path <- normalizePath(sub("^--file=", "", file_arg[[1]]))
project_dir <- dirname(dirname(script_path))
table_dir <- file.path(project_dir, "03_分析结果", "正式分析", "表")
source(file.path(project_dir, "02_分析代码", "15_投稿级结构重构公共样式.R"))

if (!dir.exists(table_dir)) {
  stop(sprintf("正式结果表目录不存在：%s", table_dir), call. = FALSE)
}

read_table <- function(name) {
  path <- file.path(table_dir, name)
  if (!file.exists(path)) stop(sprintf("缺少正式结果表：%s", path), call. = FALSE)
  read.csv(path, fileEncoding = "UTF-8-BOM", check.names = FALSE)
}

basin_levels <- c("赣江", "抚河", "信江", "修水", "潦河", "乐安河", "昌江")
season_levels <- c("Spring", "Summer", "Autumn", "Winter")
season_labels <- c(Spring = "春", Summer = "夏", Autumn = "秋", Winter = "冬")

panel_title_theme <- theme(
  plot.title = element_text(
    size = FONT_TEXT_PT,
    face = "bold",
    hjust = 0.5,
    margin = margin(b = 3)
  )
)

parse_requested_figures <- function() {
  arg <- grep("^--figures=", commandArgs(trailingOnly = TRUE), value = TRUE)
  if (!length(arg)) return(1:4)
  values <- as.integer(strsplit(sub("^--figures=", "", arg[[1]]), ",")[[1]])
  if (anyNA(values) || any(!values %in% 1:4)) {
    stop("--figures仅支持1,2,3,4", call. = FALSE)
  }
  unique(values)
}

basin_y <- function(x) {
  length(basin_levels) - match(as.character(x), basin_levels) + 1
}

composition_rects <- function(data, value_col) {
  data %>%
    mutate(
      basin_cn = factor(basin_cn, levels = basin_levels),
      season = factor(season, levels = season_levels),
      value = .data[[value_col]],
      basin_y = basin_y(basin_cn)
    ) %>%
    arrange(basin_y, season) %>%
    group_by(basin_cn, basin_y) %>%
    mutate(xmax = cumsum(value), xmin = lag(xmax, default = 0)) %>%
    ungroup()
}

build_composition_band <- function(data, value_col, title, show_y, show_legend) {
  rects <- composition_rects(data, value_col)
  ggplot(rects) +
    geom_rect(
      aes(
        xmin = xmin,
        xmax = xmax,
        ymin = basin_y - 0.34,
        ymax = basin_y + 0.34,
        fill = season
      ),
      colour = "white",
      linewidth = 0.35
    ) +
    scale_fill_manual(values = season_palette, labels = season_labels) +
    scale_x_continuous(
      limits = c(0, 1),
      breaks = c(0, 0.5, 1),
      labels = c("0", "50", "100"),
      expand = c(0, 0)
    ) +
    scale_y_continuous(
      limits = c(0.5, 7.5),
      breaks = seq_along(basin_levels),
      labels = rev(basin_levels),
      expand = c(0, 0)
    ) +
    labs(title = title, x = "占比（%）", y = NULL, fill = "季节组成") +
    theme_submission() +
    panel_title_theme +
    theme(
      axis.text.y = if (show_y) element_text() else element_blank(),
      axis.ticks.y = if (show_y) element_line() else element_blank(),
      axis.line.y = if (show_y) element_line() else element_blank(),
      legend.position = if (show_legend) "top" else "none",
      plot.margin = margin(4, 3, 4, 3)
    )
}

build_figure_1 <- function() {
  seasonal <- read_table("02b_季节水文统计_主分析.csv") %>%
    mutate(
      basin_cn = factor(basin_cn, levels = basin_levels),
      season = factor(season, levels = season_levels),
      basin_y = basin_y(basin_cn),
      delta = runoff_fraction - precipitation_fraction,
      delta_pp = 100 * delta,
      text_colour = ifelse(
        abs(delta_pp) >= 6.2,
        "white",
        palette_submission[["charcoal"]]
      ),
      highlight = (basin_cn == "昌江" & season == "Summer") |
        (basin_cn == "修水" & season == "Winter") |
        (basin_cn == "信江" & season == "Summer")
    )

  left <- build_composition_band(
    seasonal, "precipitation_fraction", "降水组成", TRUE, TRUE
  )
  right <- build_composition_band(
    seasonal, "runoff_fraction", "径流组成", FALSE, FALSE
  )

  max_abs <- max(abs(seasonal$delta_pp), na.rm = TRUE)
  center <- ggplot(seasonal, aes(x = season, y = basin_y)) +
    geom_hline(
      yintercept = seq_along(basin_levels),
      colour = palette_submission[["lightgray"]],
      linewidth = 0.35
    ) +
    geom_point(
      aes(size = abs(delta_pp), fill = delta_pp),
      shape = 21,
      colour = "white",
      stroke = 0.6
    ) +
    geom_point(
      data = subset(seasonal, highlight),
      shape = 21,
      fill = NA,
      colour = palette_submission[["charcoal"]],
      size = 8.2,
      stroke = 0.75
    ) +
    geom_text(
      aes(label = sprintf("%+.1f", delta_pp), colour = text_colour),
      size = pt_to_mm(FONT_NOTE_PT),
      show.legend = FALSE
    ) +
    scale_colour_identity() +
    scale_x_discrete(labels = season_labels, expand = expansion(add = 0.45)) +
    scale_y_continuous(
      limits = c(0.5, 7.5),
      breaks = seq_along(basin_levels),
      labels = NULL,
      expand = c(0, 0)
    ) +
    scale_size_area(
      max_size = 7.8,
      limits = c(0, max_abs),
      breaks = c(2, 5, 9),
      name = "差值幅度（百分点）"
    ) +
    scale_fill_gradient2(
      low = palette_submission[["blue"]],
      mid = "#F4F5F6",
      high = palette_submission[["vermillion"]],
      midpoint = 0,
      limits = c(-max_abs, max_abs),
      oob = scales::squish,
      name = "径流−降水（百分点）"
    ) +
    labs(title = "季节分配差值", x = NULL, y = NULL) +
    theme_submission() +
    panel_title_theme +
    theme(
      axis.ticks.y = element_blank(),
      axis.line.y = element_blank(),
      legend.position = "top",
      legend.box = "horizontal",
      plot.margin = margin(4, 3, 4, 3)
    ) +
    guides(
      fill = guide_colourbar(
        order = 1,
        display = "rectangles",
        title.position = "top",
        barwidth = unit(21, "mm"),
        barheight = unit(2.2, "mm")
      ),
      size = guide_legend(order = 2, title.position = "top")
    )

  (left | center | right) +
    plot_layout(widths = c(1.05, 2.8, 1.05), guides = "collect") +
    plot_annotation(tag_levels = "a", tag_prefix = "(", tag_suffix = ")") &
    theme(
      legend.position = "top",
      legend.box = "horizontal",
      plot.tag = element_text(size = FONT_PANEL_PT, face = "bold")
    )
}

prepare_ridge_data <- function(curve) {
  ridge_scale <- 1.45
  curve %>%
    mutate(
      basin_cn = factor(basin_cn, levels = basin_levels),
      basin_base = basin_y(basin_cn),
      y = basin_base + observed_correlation * ridge_scale,
      ymin = basin_base + bootstrap_correlation_ci025 * ridge_scale,
      ymax = basin_base + bootstrap_correlation_ci975 * ridge_scale
    )
}

parse_lag_range <- function(x) {
  values <- as.integer(strsplit(as.character(x), "-")[[1]])
  if (anyNA(values) || !length(values) || length(values) > 2) {
    stop(sprintf("无法解析近峰范围：%s", x), call. = FALSE)
  }
  if (length(values) == 1) return(values)
  seq(min(values), max(values))
}

build_figure_2 <- function() {
  ridge <- prepare_ridge_data(
    read_table("03c_整体相关曲线Bootstrap区间.csv")
  )
  if (max(ridge$ymax - ridge$basin_base, na.rm = TRUE) >= 0.75) {
    stop("统一相关系数缩放造成相邻层叠区间遮挡", call. = FALSE)
  }

  peaks <- read_table("03a_整体相关峰值滞后Bootstrap.csv") %>%
    mutate(
      basin_cn = factor(basin_cn, levels = basin_levels),
      basin_base = basin_y(basin_cn),
      near_peak_lag = lapply(near_peak_001_lag_ranges, parse_lag_range)
    )
  near_peak_curve <- peaks %>%
    select(basin_cn, near_peak_lag) %>%
    tidyr::unnest_longer(near_peak_lag, values_to = "lag_days") %>%
    mutate(lag_days = as.integer(lag_days)) %>%
    inner_join(ridge, by = c("basin_cn", "lag_days"))
  peak_points <- peaks %>%
    select(basin_cn, observed_best_lag_days) %>%
    inner_join(ridge, by = "basin_cn") %>%
    filter(lag_days == observed_best_lag_days)

  probability_nonzero <- read_table("03b_整体最佳滞后概率分布.csv") %>%
    filter(probability > 0) %>%
    mutate(
      basin_cn = factor(basin_cn, levels = basin_levels),
      basin_base = basin_y(basin_cn)
    )
  peak_modes <- peaks %>%
    transmute(basin_cn, basin_base, mode_lag = bootstrap_best_lag_mode_days)
  report_labels <- peaks %>%
    transmute(
      basin_cn,
      basin_base,
      label = case_when(
        as.character(basin_cn) == "潦河" ~ "1 d｜元数据风险",
        as.character(basin_cn) %in% c("抚河", "信江", "乐安河", "昌江") ~
          "2 d｜集中",
        as.character(basin_cn) == "赣江" ~ "4–5 d｜近峰",
        as.character(basin_cn) == "修水" ~ "3–10 d｜宽分布",
        TRUE ~ ""
      )
    )

  figure_2_labels <- c("滞后（d）", "最佳滞后（d）", report_labels$label)
  stopifnot(!any(grepl("汇流时间|因果响应时间|滔后", figure_2_labels)))

  p_curve <- ggplot(ridge) +
    geom_hline(
      yintercept = seq_along(basin_levels),
      colour = "#E7E9EC",
      linewidth = 0.4
    ) +
    geom_ribbon(
      aes(x = lag_days, ymin = ymin, ymax = ymax, group = basin_cn),
      fill = palette_submission[["blue_light"]],
      alpha = 0.58
    ) +
    geom_line(
      aes(x = lag_days, y = y, group = basin_cn),
      colour = palette_submission[["blue_dark"]],
      linewidth = 0.8
    ) +
    geom_line(
      data = near_peak_curve,
      aes(x = lag_days, y = y, group = basin_cn),
      colour = palette_submission[["vermillion"]],
      linewidth = 1.65,
      lineend = "round"
    ) +
    geom_point(
      data = peak_points,
      aes(x = lag_days, y = y),
      shape = 21,
      fill = "white",
      colour = palette_submission[["vermillion"]],
      size = 2.0,
      stroke = 0.7
    ) +
    annotate(
      "segment",
      x = 14.55,
      xend = 14.55,
      y = 0.54,
      yend = 0.54 + 0.20 * 1.45,
      colour = palette_submission[["charcoal"]],
      linewidth = 0.6
    ) +
    annotate(
      "text",
      x = 14.20,
      y = 0.54 + 0.10 * 1.45,
      label = "ρ=0.20",
      hjust = 1,
      size = pt_to_mm(FONT_NOTE_PT)
    ) +
    scale_x_continuous(
      breaks = seq(0, 15, 3),
      limits = c(0, 15),
      expand = c(0, 0)
    ) +
    scale_y_continuous(
      breaks = seq_along(basin_levels),
      labels = rev(basin_levels),
      limits = c(0.45, 7.75),
      expand = c(0, 0)
    ) +
    labs(
      x = "滞后（d）",
      y = NULL,
      title = "相关曲线、Bootstrap区间与近峰"
    ) +
    theme_submission() +
    panel_title_theme +
    theme(legend.position = "none")

  p_prob <- ggplot(probability_nonzero, aes(x = lag_days, y = basin_base)) +
    geom_hline(
      yintercept = seq_along(basin_levels),
      colour = "#E7E9EC",
      linewidth = 0.4
    ) +
    geom_point(
      aes(size = probability),
      shape = 21,
      fill = "white",
      colour = palette_submission[["blue_dark"]],
      stroke = 0.55
    ) +
    geom_segment(
      data = peak_modes,
      aes(
        x = mode_lag,
        xend = mode_lag,
        y = basin_base - 0.24,
        yend = basin_base + 0.24
      ),
      colour = palette_submission[["vermillion"]],
      linewidth = 0.75
    ) +
    geom_text(
      data = report_labels,
      aes(x = 15.8, label = label),
      hjust = 0,
      size = pt_to_mm(FONT_NOTE_PT)
    ) +
    scale_x_continuous(
      breaks = seq(0, 15, 3),
      limits = c(0, 29.5),
      expand = c(0, 0)
    ) +
    scale_y_continuous(
      breaks = seq_along(basin_levels),
      labels = NULL,
      limits = c(0.45, 7.75),
      expand = c(0, 0)
    ) +
    scale_size_area(
      max_size = 4.2,
      breaks = c(0.25, 0.50, 1),
      name = "峰位概率"
    ) +
    labs(x = "最佳滞后（d）", y = NULL, title = "峰位概率与报告层级") +
    theme_submission() +
    panel_title_theme +
    theme(
      axis.ticks.y = element_blank(),
      axis.line.y = element_blank(),
      legend.position = "top"
    )

  (p_curve | p_prob) +
    plot_layout(widths = c(2.35, 1), guides = "collect") +
    plot_annotation(tag_levels = "a", tag_prefix = "(", tag_suffix = ")") &
    theme(
      legend.position = "top",
      plot.tag = element_text(size = FONT_PANEL_PT, face = "bold")
    )
}

build_figure_3 <- function() {
  seasonal_peaks <- read_table("04a_分季节相关峰值滞后Bootstrap.csv") %>%
    mutate(
      season = factor(season, levels = season_levels),
      basin_cn = factor(basin_cn, levels = basin_levels),
      stability_class = factor(stability_class, levels = c("稳定", "不稳定"))
    )

  season_counts <- seasonal_peaks %>%
    group_by(season) %>%
    summarise(unstable_n = sum(stability_class == "不稳定"), .groups = "drop") %>%
    arrange(season)
  basin_counts <- seasonal_peaks %>%
    group_by(basin_cn) %>%
    summarise(unstable_n = sum(stability_class == "不稳定"), .groups = "drop") %>%
    arrange(basin_cn)
  stopifnot(
    identical(as.integer(season_counts$unstable_n), c(1L, 1L, 2L, 6L)),
    basin_counts$unstable_n[basin_counts$basin_cn == "修水"] == 4,
    basin_counts$unstable_n[basin_counts$basin_cn == "潦河"] == 0
  )

  seasonal_peaks <- seasonal_peaks %>%
    mutate(
      basin_y = basin_y(basin_cn),
      probability_class = cut(
        bootstrap_mode_probability,
        breaks = c(-Inf, 0.50, 0.80, Inf),
        right = FALSE,
        labels = c("<0.50", "0.50–0.80", "≥0.80")
      )
    )
  background_grid <- tidyr::expand_grid(
    season = factor(season_levels, levels = season_levels),
    xiushui_y = basin_y("修水")
  )
  boundary_marks <- bind_rows(
    seasonal_peaks %>%
      filter(bootstrap_best_lag_ci025 <= 0) %>%
      mutate(boundary_x = 0),
    seasonal_peaks %>%
      filter(bootstrap_best_lag_ci975 >= 15) %>%
      mutate(boundary_x = 15)
  )

  p_main <- ggplot(seasonal_peaks, aes(y = basin_y)) +
    geom_rect(
      data = subset(background_grid, season == "Winter"),
      aes(xmin = -Inf, xmax = Inf, ymin = 0.5, ymax = 7.5),
      inherit.aes = FALSE,
      fill = "#F2F4F5"
    ) +
    geom_rect(
      data = background_grid,
      aes(
        xmin = -Inf,
        xmax = Inf,
        ymin = xiushui_y - 0.36,
        ymax = xiushui_y + 0.36
      ),
      inherit.aes = FALSE,
      fill = "#F7F1EF"
    ) +
    geom_vline(
      xintercept = c(5, 10),
      colour = palette_submission[["lightgray"]],
      linewidth = 0.4
    ) +
    geom_segment(
      aes(
        x = bootstrap_best_lag_ci025,
        xend = bootstrap_best_lag_ci975,
        yend = basin_y,
        colour = stability_class
      ),
      linewidth = 0.85,
      lineend = "round"
    ) +
    geom_point(
      aes(
        x = bootstrap_best_lag_mode_days,
        shape = stability_class,
        fill = stability_class,
        colour = stability_class,
        size = probability_class
      ),
      stroke = 0.7
    ) +
    geom_point(
      data = boundary_marks,
      aes(x = boundary_x, y = basin_y),
      inherit.aes = FALSE,
      shape = 24,
      fill = "white",
      colour = palette_submission[["vermillion"]],
      size = 1.65,
      stroke = 0.7
    ) +
    facet_grid(
      cols = vars(season),
      labeller = labeller(season = as_labeller(season_labels))
    ) +
    scale_x_continuous(
      breaks = c(0, 5, 10, 15),
      limits = c(0, 15),
      expand = expansion(mult = c(0.025, 0.025))
    ) +
    scale_y_continuous(
      breaks = seq_along(basin_levels),
      labels = rev(basin_levels),
      limits = c(0.5, 7.5),
      expand = c(0, 0)
    ) +
    scale_shape_manual(values = c("稳定" = 21, "不稳定" = 23)) +
    scale_colour_manual(
      values = c(
        "稳定" = palette_submission[["blue_dark"]],
        "不稳定" = palette_submission[["vermillion"]]
      )
    ) +
    scale_fill_manual(
      values = c("稳定" = palette_submission[["blue"]], "不稳定" = "white")
    ) +
    scale_size_manual(
      values = c("<0.50" = 1.5, "0.50–0.80" = 2.1, "≥0.80" = 2.8)
    ) +
    labs(
      x = "最佳相关滞后（d）",
      y = NULL,
      shape = "峰位稳定性",
      size = "众数概率"
    ) +
    theme_submission() +
    theme(
      legend.position = "top",
      panel.spacing.x = unit(2.2, "mm"),
      strip.text = element_text(size = FONT_TEXT_PT, face = "bold")
    ) +
    guides(
      colour = "none",
      fill = "none",
      shape = guide_legend(
        order = 1,
        override.aes = list(
          size = c(2.2, 2.2),
          fill = c(palette_submission[["blue"]], "white"),
          colour = c(
            palette_submission[["blue_dark"]],
            palette_submission[["vermillion"]]
          )
        )
      ),
      size = guide_legend(
        order = 2,
        override.aes = list(shape = 21, fill = "white")
      )
    )

  p_top <- ggplot(season_counts, aes(x = 1, y = unstable_n)) +
    geom_col(
      width = 0.56,
      fill = palette_submission[["vermillion"]],
      alpha = 0.74
    ) +
    geom_text(
      aes(y = unstable_n + 0.35, label = unstable_n),
      vjust = 0,
      size = pt_to_mm(FONT_TEXT_PT),
      family = LATIN_FONT,
      fontface = "bold"
    ) +
    facet_grid(
      cols = vars(season),
      labeller = labeller(season = as_labeller(season_labels))
    ) +
    scale_x_continuous(
      limits = c(0.5, 1.5),
      breaks = NULL,
      expand = c(0, 0)
    ) +
    scale_y_continuous(
      breaks = c(0, 3, 6),
      limits = c(0, 8.0),
      expand = c(0, 0)
    ) +
    labs(x = NULL, y = "不稳定数", title = "各季不稳定组合数") +
    theme_submission() +
    panel_title_theme +
    theme(
      axis.text.x = element_blank(),
      axis.ticks.x = element_blank(),
      axis.title.x = element_blank(),
      legend.position = "none",
      panel.spacing.x = unit(2.2, "mm"),
      strip.text = element_blank(),
      strip.background = element_blank(),
      plot.margin = margin(4, 5, 0, 5)
    )

  basin_counts <- basin_counts %>% mutate(basin_y = basin_y(basin_cn))
  p_right <- ggplot(basin_counts, aes(y = basin_y)) +
    geom_segment(
      aes(x = 0, xend = unstable_n, yend = basin_y),
      colour = palette_submission[["midgray"]],
      linewidth = 0.8
    ) +
    geom_point(
      aes(x = unstable_n),
      shape = 21,
      fill = "white",
      colour = palette_submission[["vermillion"]],
      size = 2.1,
      stroke = 0.65
    ) +
    geom_text(
      aes(x = unstable_n + 0.22, label = unstable_n),
      hjust = 0,
      size = pt_to_mm(FONT_NOTE_PT)
    ) +
    scale_x_continuous(
      breaks = 0:4,
      limits = c(-0.28, 4.65),
      expand = c(0, 0)
    ) +
    scale_y_continuous(
      breaks = seq_along(basin_levels),
      labels = NULL,
      limits = c(0.5, 7.5),
      expand = c(0, 0)
    ) +
    labs(x = "不稳定季节数", y = NULL) +
    theme_submission() +
    theme(
      axis.ticks.y = element_blank(),
      axis.line.y = element_blank(),
      legend.position = "none"
    )

  layout_design <- "
AB
CD
"
  p_top + plot_spacer() + p_main + p_right +
    plot_layout(
      design = layout_design,
      widths = c(6.2, 1),
      heights = c(0.24, 1),
      guides = "collect"
    ) &
    theme(legend.position = "top")
}

build_figure_4 <- function() {
  sensitivity <- read_table("06a_敏感性结论稳定性矩阵.csv")
  scenario_ids <- c(
    "include_2020",
    "ganjiang_extreme_missing",
    "exclude_liaohe",
    "separator",
    "smooth_doy31",
    "raw_spearman",
    "month_median_pearson",
    "lag_window_0_10",
    "lag_window_0_20"
  )
  scenario_labels <- c(
    "加入2020",
    "赣江极端值缺失",
    "排除潦河",
    "",
    "日历日平滑异常",
    "原始Spearman",
    "Pearson",
    "窗口0–10 d",
    "窗口0–20 d"
  )

  baseline <- sensitivity %>%
    filter(scenario_id == "baseline") %>%
    select(basin_cn, baseline_mode = bootstrap_best_lag_mode_days)

  transition <- tidyr::expand_grid(
    scenario_id = scenario_ids,
    basin_cn = basin_levels
  ) %>%
    left_join(
      sensitivity %>% filter(scenario_id != "baseline"),
      by = c("scenario_id", "basin_cn")
    ) %>%
    left_join(baseline, by = "basin_cn") %>%
    mutate(
      basin_cn = factor(basin_cn, levels = basin_levels),
      conclusion_stability = factor(
        conclusion_stability,
        levels = c("完全一致", "基本稳定", "明显改变")
      ),
      scenario_y = length(scenario_ids) - match(scenario_id, scenario_ids) + 1,
      changed = !is.na(bootstrap_best_lag_mode_days) &
        bootstrap_best_lag_mode_days != baseline_mode
    )

  valid_transition <- subset(transition, !is.na(bootstrap_best_lag_mode_days))
  changed_transition <- subset(valid_transition, changed)
  unchanged_transition <- subset(valid_transition, !changed)

  p_transition <- ggplot(transition, aes(y = scenario_y)) +
    geom_rect(
      data = subset(transition, scenario_id == "month_median_pearson"),
      aes(xmin = -Inf, xmax = Inf, ymin = scenario_y - 0.44, ymax = scenario_y + 0.44),
      inherit.aes = FALSE,
      fill = "#FAF0ED"
    ) +
    geom_hline(
      yintercept = 6,
      colour = palette_submission[["lightgray"]],
      linewidth = 0.55
    ) +
    geom_segment(
      data = changed_transition,
      aes(
        x = baseline_mode,
        xend = bootstrap_best_lag_mode_days,
        yend = scenario_y,
        colour = conclusion_stability,
        linetype = conclusion_stability
      ),
      arrow = arrow(length = unit(1.05, "mm"), type = "closed"),
      linewidth = 0.7
    ) +
    geom_point(
      data = valid_transition,
      aes(x = baseline_mode, colour = conclusion_stability),
      shape = 21,
      fill = "white",
      size = 2.05,
      stroke = 0.65
    ) +
    geom_point(
      data = changed_transition,
      aes(
        x = bootstrap_best_lag_mode_days,
        fill = conclusion_stability,
        colour = conclusion_stability
      ),
      shape = 21,
      size = 1.85,
      stroke = 0.6
    ) +
    geom_point(
      data = unchanged_transition,
      aes(
        x = bootstrap_best_lag_mode_days,
        fill = conclusion_stability,
        colour = conclusion_stability
      ),
      shape = 21,
      size = 0.9,
      stroke = 0.45
    ) +
    geom_text(
      data = subset(
        transition,
        scenario_id == "exclude_liaohe" & basin_cn == "潦河"
      ),
      aes(x = 7.5, label = "N/A"),
      size = pt_to_mm(FONT_NOTE_PT)
    ) +
    facet_grid(cols = vars(basin_cn)) +
    scale_x_continuous(
      breaks = c(0, 5, 10, 15),
      limits = c(0, 15),
      expand = expansion(mult = c(0.035, 0.035))
    ) +
    scale_y_continuous(
      breaks = length(scenario_ids) - match(scenario_ids, scenario_ids) + 1,
      labels = scenario_labels,
      limits = c(0.5, length(scenario_ids) + 0.5),
      expand = c(0, 0)
    ) +
    scale_colour_manual(
      values = stability_palette,
      breaks = names(stability_palette),
      limits = names(stability_palette),
      drop = FALSE,
      name = "综合分类"
    ) +
    scale_fill_manual(
      values = stability_palette,
      breaks = names(stability_palette),
      limits = names(stability_palette),
      drop = FALSE,
      name = "综合分类"
    ) +
    scale_linetype_manual(
      values = c("完全一致" = "solid", "基本稳定" = "22", "明显改变" = "solid"),
      breaks = names(stability_palette),
      limits = names(stability_palette),
      drop = FALSE,
      name = "综合分类"
    ) +
    labs(x = "Bootstrap众数峰位（d）", y = NULL) +
    theme_submission() +
    theme(
      legend.position = "top",
      panel.spacing.x = unit(1.4, "mm"),
      strip.text = element_text(size = FONT_NOTE_PT, face = "bold"),
      axis.text.x = element_text(size = FONT_NOTE_PT - 0.3)
    ) +
    guides(
      fill = "none",
      linetype = "none",
      colour = guide_legend(
        override.aes = list(
          linetype = c("solid", "22", "solid"),
          shape = 21,
          fill = unname(stability_palette),
          size = 2
        )
      )
    )

  change_summary <- transition %>%
    filter(scenario_id != "separator") %>%
    group_by(scenario_id, scenario_y) %>%
    summarise(
      changed_n = sum(conclusion_stability == "明显改变", na.rm = TRUE),
      denominator = sum(!is.na(conclusion_stability)),
      .groups = "drop"
    ) %>%
    mutate(label = sprintf("%d/%d", changed_n, denominator))

  stopifnot(
    change_summary$changed_n[change_summary$scenario_id == "raw_spearman"] == 2,
    change_summary$changed_n[change_summary$scenario_id == "month_median_pearson"] == 5,
    all(
      change_summary$changed_n[
        !change_summary$scenario_id %in% c("raw_spearman", "month_median_pearson")
      ] == 0
    )
  )

  p_summary <- ggplot(change_summary, aes(y = scenario_y)) +
    geom_rect(
      data = subset(change_summary, scenario_id == "month_median_pearson"),
      aes(xmin = -Inf, xmax = Inf, ymin = scenario_y - 0.44, ymax = scenario_y + 0.44),
      inherit.aes = FALSE,
      fill = "#FAF0ED"
    ) +
    geom_hline(
      yintercept = 6,
      colour = palette_submission[["lightgray"]],
      linewidth = 0.55
    ) +
    geom_rect(
      aes(
        xmin = 0,
        xmax = changed_n,
        ymin = scenario_y - 0.28,
        ymax = scenario_y + 0.28
      ),
      fill = palette_submission[["vermillion"]],
      alpha = 0.72
    ) +
    geom_text(
      aes(x = pmax(changed_n, 0.12) + 0.18, label = label),
      hjust = 0,
      size = pt_to_mm(FONT_NOTE_PT)
    ) +
    scale_x_continuous(
      breaks = c(0, 2, 5, 7),
      limits = c(0, 7.8),
      expand = c(0, 0)
    ) +
    scale_y_continuous(
      limits = c(0.5, length(scenario_ids) + 0.5),
      breaks = NULL,
      expand = c(0, 0)
    ) +
    labs(x = "明显改变数", y = NULL) +
    theme_submission() +
    theme(
      axis.line.y = element_blank(),
      axis.ticks.y = element_blank(),
      legend.position = "none"
    )

  (p_transition | p_summary) +
    plot_layout(widths = c(6.2, 1), guides = "collect") &
    theme(legend.position = "top")
}

requested <- parse_requested_figures()
figure_specs <- list(
  `1` = list(build = build_figure_1, stem = "01_季节水文指纹", height = 110),
  `2` = list(build = build_figure_2, stem = "02_总体响应层叠证据", height = 150),
  `3` = list(build = build_figure_3, stem = "03_季节稳定性图谱", height = 118),
  `4` = list(build = build_figure_4, stem = "04_基准情景峰位转移", height = 135)
)

for (number in requested) {
  spec <- figure_specs[[as.character(number)]]
  save_structural_figure(
    spec$build(),
    file.path(V2_PREVIEW_DIR, spec$stem),
    spec$height
  )
}

cat(sprintf("结构重构版预览图已生成：%s\n", paste(requested, collapse = ",")))
