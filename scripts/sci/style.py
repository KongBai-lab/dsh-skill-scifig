# -*- coding: utf-8 -*-
"""sci/style.py — 期刊 profile、单位换算、合规检查器。

规范来源（已核实，分三档标注）：
  [官] Nature:   单栏 89 mm / 双栏 183 mm / 最大高 170 mm / 图内 5–7 pt /
                 面板字母 8 pt 粗体 / 禁背景网格·阴影·装饰 / 推荐 RGB
  [官] Science:  单栏 90 mm(3.55 in) / 双栏 184 mm(7.25 in) / 轴标签 8 pt、最小 6 pt /
                 线宽 ≥ 0.28 pt / 只收 RGB / 纯黑白线条 1200 dpi
  [官] AAS:      字号 ≥ 6 pt / 线宽 ≥ 0.5 pt / 光栅 ≥ 300 dpi 且宽 ≥ 1000 px
  [经] 通用：300 dpi 彩图、600 dpi 含字线条图、1200 dpi 纯黑白线条

所有尺寸以 mm、字号线宽以 pt 存储，出图时统一换算成像素。
"""
import math

# ---------------------------------------------------------------- profiles

_NATURE = {
    "name": "Nature",
    "single_mm": 89.0,
    "double_mm": 183.0,
    "max_height_mm": 170.0,
    "dpi": 300,
    "min_font_pt": 5.0,
    "min_line_pt": 0.28,
    "pt": {"axis_label": 8.0, "tick_label": 7.0, "legend": 7.0,
           "panel_letter": 8.0, "annot": 7.0, "title": 8.0},
    "lw": {"data": 0.8, "axis": 0.6, "tick": 0.5, "zero": 0.5, "err": 0.8},
    "tick_len_pt": {"major": 3.5, "minor": 1.8},
    "grid": False,            # Nature 明文：禁背景网格
    "decor": False,           # 禁阴影/装饰
    "spines": "all",          # 四面闭合框
    "tick_direction": "in",   # 刻度朝内
    "palette": "okabe",
    "cmap": "viridis",
    "color_only_ok": False,   # 颜色不得作为唯一区分
}

_SCIENCE = {
    "name": "Science",
    "single_mm": 90.0,
    "double_mm": 184.0,
    "max_height_mm": 227.5,
    "dpi": 300,
    "min_font_pt": 6.0,
    "min_line_pt": 0.28,
    "pt": {"axis_label": 8.0, "tick_label": 7.0, "legend": 7.0,
           "panel_letter": 9.0, "annot": 7.0, "title": 8.0},
    "lw": {"data": 0.8, "axis": 0.6, "tick": 0.5, "zero": 0.5, "err": 0.8},
    "tick_len_pt": {"major": 3.5, "minor": 1.8},
    "grid": False,
    "decor": False,
    "spines": "all",
    "tick_direction": "in",
    "palette": "okabe",
    "cmap": "viridis",
    "color_only_ok": False,
}

PROFILES = {"nature": _NATURE, "science": _SCIENCE, "sci": _SCIENCE}
DEFAULT_PROFILE = "nature"


def get(name=None):
    """取 profile（浅拷贝，可直接改）。"""
    key = (name or DEFAULT_PROFILE).lower()
    if key not in PROFILES:
        raise ValueError("未知期刊 profile %r（可用：%s）" % (name, ", ".join(PROFILES)))
    return dict(PROFILES[key])


# ---------------------------------------------------------------- 单位换算

def mm2in(mm):
    return mm / 25.4


def in2mm(i):
    return i * 25.4


def mm2px(mm, dpi):
    return int(round(mm / 25.4 * dpi))


def pt2px(pt, dpi):
    """1 pt = 1/72 inch。"""
    return pt / 72.0 * dpi


def px2pt(px, dpi):
    return px * 72.0 / dpi


def figsize_px(style, size="single", height_mm=None):
    """按 profile 给出画布像素尺寸。size: 'single' | 'double' | 具体 mm 元组。"""
    if isinstance(size, (tuple, list)):
        w_mm, h_mm = float(size[0]), float(size[1])
    else:
        w_mm = style["single_mm"] if size in ("single", "one", "1") else style["double_mm"]
        h_mm = height_mm if height_mm is not None else w_mm * 0.75
        h_mm = min(h_mm, style["max_height_mm"])
    return mm2px(w_mm, style["dpi"]), mm2px(h_mm, style["dpi"]), w_mm, h_mm


# ---------------------------------------------------------------- 合规检查
#
# info 由调用方（sciplot）收集，字段都可缺省：
#   width_px, height_px, dpi, fonts_pt[], lines_pt[], xlabel, ylabel,
#   cmap, palette[], series[] = [{"color","dash","marker","label"}],
#   grid(bool), y_inverted(bool), y_zero_based(bool), is_bar(bool)

ERROR, WARN, OK = "error", "warn", "ok"


def check(info, style=None):
    """返回 [(level, message)]。规则按已核实的期刊硬性要求。"""
    st = style or get()
    out = []
    dpi = info.get("dpi", st["dpi"])
    wpx = info.get("width_px")
    hpx = info.get("height_px")

    # 1) 尺寸与分辨率
    if wpx is not None:
        if wpx < 1000:
            out.append((WARN, "光栅宽 %d px < 1000 px（AAS 官方要求 ≥1000 px）" % wpx))
        if dpi < 300:
            out.append((ERROR, "dpi %s < 300（投稿位图下限）" % dpi))
    if hpx is not None and px2pt(hpx, dpi) / 72.0 * 25.4 > st["max_height_mm"]:
        out.append((WARN, "图高超过 %s mm 上限" % st["max_height_mm"]))

    # 2) 字号
    fonts_pt = [f for f in info.get("fonts_pt", []) if f]
    if fonts_pt:
        mn = min(fonts_pt)
        if mn < st["min_font_pt"]:
            out.append((ERROR, "最小字号 %.1f pt < %s pt 下限（%s）"
                        % (mn, st["min_font_pt"], st["name"])))
        elif mn < 6.0:
            out.append((WARN, "字号 %.1f pt 偏低，成品尺寸下可读性风险" % mn))

    # 3) 线宽
    lines_pt = [l for l in info.get("lines_pt", []) if l]
    if lines_pt:
        mn = min(lines_pt)
        if mn < st["min_line_pt"]:
            out.append((ERROR, "最小线宽 %.2f pt < %.2f pt 下限" % (mn, st["min_line_pt"])))

    # 4) 轴标题（科研图第一硬伤：没有物理量与单位）
    if not info.get("xlabel"):
        out.append((WARN, "缺 x 轴标题（应写“物理量 (单位)”）"))
    if not info.get("ylabel"):
        out.append((WARN, "缺 y 轴标题（应写“物理量 (单位)”）"))

    # 5) 色板
    cmap = (info.get("cmap") or "").lower()
    if cmap in ("jet", "rainbow", "hsv", "gist_rainbow"):
        out.append((ERROR, "色板 %r 不推荐：亮度非单调、色盲不友好、转灰度丢信息" % cmap))

    # 6) 颜色不得作为唯一区分（AAS 官方明文）
    #    必须按「同一面板内」判断：主图 1 条 + 残差图 1 条不算「同图多条」，
    #    否则每个带残差面板的图都会误报。
    series = info.get("series") or []
    panels = info.get("panels")
    if panels is None:
        panels = [series] if series else []
    for ps in panels:
        if len(ps) < 2:
            continue
        if len({(x.get("dash"), x.get("marker")) for x in ps}) == 1:
            out.append((WARN, "同图 %d 条序列仅靠颜色区分（AAS：颜色不得作为唯一编码，"
                        "须配线型或标记）" % len(ps)))
            break

    # 6b) 红绿并置（Science/Nature 明文避免）
    if len(series) >= 2:
        try:
            from .palettes import is_red_green_pair
            if is_red_green_pair([s.get("color", "#000000") for s in series]):
                out.append((WARN, "色板中红/绿并置——色盲不可区分，"
                            "Science 与 Nature 均明确避免（建议换 Okabe-Ito 蓝/朱红）"))
        except Exception:
            pass

    # 7) 网格
    if info.get("grid") and not st["grid"]:
        out.append((WARN, "%s 明文不建议背景网格线" % st["name"]))

    # 8) 截断轴
    if info.get("is_bar") and info.get("y_zero_based") is False:
        out.append((WARN, "柱状图 y 轴未从 0 开始会夸大差异"))

    if not out:
        out.append((OK, "规格检查通过：%s×%s px @%s dpi" % (wpx, hpx, dpi)))
    return out


def format_report(items):
    """检查结果转可读文本。"""
    icon = {ERROR: "[error]", WARN: "[warn] ", OK: "[ok]   "}
    return "\n".join("%s %s" % (icon.get(lv, "[info] "), msg) for lv, msg in items)
