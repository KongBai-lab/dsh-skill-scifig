# -*- coding: utf-8 -*-
"""sci — 科研出版级图表内核（Science / Nature 规范）。

模块：
  fonts      字体回退链、文本度量与绘制（sans-serif）
  mathtext   $...$ 极简数学排版（上下标/希腊字母/分式/根式/矩阵/分段函数）
  palettes   Okabe-Ito / viridis / cividis
  style      期刊 profile、mm↔px 换算、合规检查器
  primitives 图元（线/虚线/标记/误差棒/置信带/箭头/参考线）
  axes       坐标轴系统（四面框/主次刻度/log/反转/轴标题/图例/多面板）
  contour    等高线（marching squares）
  vector     矢量出口（SVG 1.1 / PDF 1.4，文字转路径）

corner / skymap 依赖 sciplot.Figure，**不能**在这个 __init__ 里 import
（否则形成 sciplot <-> sci 的循环导入）。用法：
    from sci.corner import corner_figure
    from sci.skymap import skymap_figure
"""
from . import (fonts, mathtext, palettes, style, primitives, axes,  # noqa: F401
               contour, vector)

__all__ = ["fonts", "mathtext", "palettes", "style", "primitives", "axes",
           "contour", "vector"]
