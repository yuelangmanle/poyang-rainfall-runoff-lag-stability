#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(ggplot2)
  library(grid)
  library(ragg)
  library(svglite)
  library(systemfonts)
})

choose_installed_font <- function(env_name, candidates) {
  available <- unique(systemfonts::system_fonts()$family)
  requested <- Sys.getenv(env_name, unset = "")
  if (nzchar(requested)) {
    if (!requested %in% available) {
      stop(sprintf("环境变量%s指定的字体未安装：%s", env_name, requested), call. = FALSE)
    }
    return(requested)
  }
  matches <- candidates[candidates %in% available]
  if (!length(matches)) {
    stop(sprintf("未找到可用字体，请通过%s指定已安装字体", env_name), call. = FALSE)
  }
  matches[[1]]
}

ZH_FONT <- choose_installed_font(
  "HYDRO_ZH_FONT",
  c("Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC",
    "WenQuanYi Zen Hei", "PingFang SC", "SimHei")
)
LATIN_FONT <- choose_installed_font(
  "HYDRO_LATIN_FONT",
  c("Helvetica", "Arial", "Liberation Sans", "DejaVu Sans")
)
FIGURE_WIDTH_MM <- 178
FONT_PANEL_PT <- 9
FONT_AXIS_PT <- 8.5
FONT_TEXT_PT <- 8
FONT_NOTE_PT <- 7.5

palette_submission <- c(
  blue_dark = "#1F4E6D",
  blue = "#2F78A1",
  blue_light = "#A9C9DA",
  teal = "#3A8D86",
  vermillion = "#C85A3A",
  amber = "#D7A43B",
  charcoal = "#30343B",
  midgray = "#7C838C",
  lightgray = "#E7E9EC",
  offwhite = "#F7F8F9"
)

font_path <- function(family) {
  path <- systemfonts::match_fonts(family)$path[[1]]
  if (!nzchar(path) || !file.exists(path)) {
    stop(sprintf("未找到字体：%s", family), call. = FALSE)
  }
  path
}

invisible(font_path(ZH_FONT))
invisible(font_path(LATIN_FONT))

theme_submission <- function(base_family = ZH_FONT) {
  theme_classic(base_size = FONT_TEXT_PT, base_family = base_family) +
    theme(
      text = element_text(family = base_family, colour = palette_submission[["charcoal"]]),
      axis.line = element_line(linewidth = 0.45, colour = palette_submission[["charcoal"]]),
      axis.ticks = element_line(linewidth = 0.4, colour = palette_submission[["charcoal"]]),
      axis.ticks.length = unit(1.6, "mm"),
      axis.title = element_text(size = FONT_AXIS_PT),
      axis.text = element_text(size = FONT_NOTE_PT, colour = palette_submission[["charcoal"]]),
      strip.background = element_blank(),
      strip.text = element_text(size = FONT_TEXT_PT, face = "bold", margin = margin(b = 2)),
      legend.position = "top",
      legend.justification = "left",
      legend.direction = "horizontal",
      legend.title = element_text(size = FONT_TEXT_PT),
      legend.text = element_text(size = FONT_NOTE_PT),
      legend.key.height = unit(3.1, "mm"),
      legend.key.width = unit(4.3, "mm"),
      legend.spacing.x = unit(1.1, "mm"),
      legend.box.spacing = unit(0.6, "mm"),
      panel.grid = element_blank(),
      plot.title = element_blank(),
      plot.subtitle = element_blank(),
      plot.caption = element_blank(),
      plot.tag = element_text(size = FONT_PANEL_PT, face = "bold", colour = "black"),
      plot.tag.position = c(0.005, 0.995),
      plot.margin = margin(4, 5, 4, 5)
    )
}

theme_heatmap <- function(base_family = ZH_FONT) {
  theme_submission(base_family) +
    theme(
      axis.line = element_blank(),
      axis.ticks = element_blank(),
      panel.border = element_blank(),
      legend.position = "bottom",
      plot.margin = margin(3, 4, 3, 4)
    )
}

hex_luminance <- function(hex) {
  rgb <- grDevices::col2rgb(hex) / 255
  as.numeric(0.299 * rgb[1, ] + 0.587 * rgb[2, ] + 0.114 * rgb[3, ])
}

pt_to_mm <- function(pt) {
  pt / 72.27 * 25.4
}

safe_output_stem <- function(stem) {
  out_dir <- dirname(stem)
  if (basename(out_dir) != "投稿级图预览") {
    stop("预览图只能写入03_分析结果/投稿级图预览", call. = FALSE)
  }
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  normalizePath(stem, winslash = "/", mustWork = FALSE)
}

save_submission_figure <- function(plot, stem, height_mm) {
  stem <- safe_output_stem(stem)
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
