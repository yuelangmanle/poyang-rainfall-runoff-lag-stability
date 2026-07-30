#!/usr/bin/env Rscript

style_path <- tryCatch(sys.frame(1)$ofile, error = function(e) NULL)
if (is.null(style_path) || length(style_path) != 1 || !nzchar(style_path)) {
  args_all <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args_all, value = TRUE)
  if (length(file_arg) != 1) stop("无法确定样式脚本路径", call. = FALSE)
  style_path <- normalizePath(sub("^--file=", "", file_arg[[1]]))
} else {
  style_path <- normalizePath(style_path)
}

project_dir <- dirname(dirname(style_path))
source(file.path(project_dir, "02_分析代码", "11_投稿级图件公共样式.R"))

V2_PREVIEW_DIR <- file.path(
  project_dir, "03_分析结果", "投稿级图预览", "结构重构版"
)

season_palette <- c(
  Spring = "#8FC7B8",
  Summer = "#E8C46A",
  Autumn = "#D58B72",
  Winter = "#8FAFC8"
)

stability_palette <- c(
  "完全一致" = "#477A92",
  "基本稳定" = "#C89B45",
  "明显改变" = "#B85B45"
)

safe_v2_stem <- function(stem) {
  dir.create(V2_PREVIEW_DIR, recursive = TRUE, showWarnings = FALSE)
  root <- normalizePath(V2_PREVIEW_DIR, winslash = "/", mustWork = TRUE)
  candidate <- normalizePath(stem, winslash = "/", mustWork = FALSE)
  if (!startsWith(candidate, paste0(root, "/"))) {
    stop("结构重构版图件只能写入独立预览目录", call. = FALSE)
  }
  candidate
}

save_structural_figure <- function(plot, stem, height_mm) {
  stem <- safe_v2_stem(stem)
  width_in <- FIGURE_WIDTH_MM / 25.4
  height_in <- height_mm / 25.4

  svglite::svglite(
    paste0(stem, ".svg"),
    width = width_in,
    height = height_in,
    bg = "white",
    system_fonts = list(sans = ZH_FONT)
  )
  print(plot)
  grDevices::dev.off()

  grDevices::cairo_pdf(
    paste0(stem, ".pdf"),
    width = width_in,
    height = height_in,
    family = ZH_FONT,
    onefile = FALSE,
    bg = "white"
  )
  print(plot)
  grDevices::dev.off()

  ragg::agg_png(
    paste0(stem, ".png"),
    width = FIGURE_WIDTH_MM,
    height = height_mm,
    units = "mm",
    res = 600,
    background = "white",
    scaling = 1
  )
  print(plot)
  grDevices::dev.off()

  invisible(paste0(stem, c(".pdf", ".svg", ".png")))
}
