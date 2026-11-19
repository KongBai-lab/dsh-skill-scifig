# -*- coding: utf-8 -*-
"""sciplot — 科研出版级图表（Science / Nature 规范）。

设计目标：一次调用出一张能直接投稿的数据图。
  · 期刊规格内置（Nature 89 mm / Science 90 mm、字号线宽下限、色盲友好色板）
  · 必备要素自动化（四面框、内向刻度、轴标题带单位、误差棒、图例、合规检查）
  · 图种：fit（数据+拟合+残差）、lightcurve（天文光变曲线）

用法（轨 B，需要计算数据时）：
    from sciplot import Figure
    fig = Figure(profile="nature", size="single")
    ax = fig.axes(xlim=(0, 10), ylim=(0, 1), xlabel="相位", ylabel="归一化流量")
    plot_series(ax, x, y, yerr=e, marker="circle", label="观测")
    plot_series(ax, xm, ym, linestyle="--", label="模型")
    ax.legend(...)
    fig.save("out.png")

用法（轨 A，一行出图）：
    from sciplot import figure_fit
    figure_fit(x, y, yerr=e, model=(xm, ym), xlabel="x", ylabel="y", out="fit.png")
"""
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import raster  # noqa: E402
from sci import fonts, mathtext, palettes  # noqa: E402
from sci import style as stylemod  # noqa: E402
from sci.axes import Axes  # noqa: E402
from sci import primitives  # noqa: E402

MM = 1.0 / 25.4  # 1 inch = 25.4 mm


# ============================================================ Figure

class Figure:
    """一张图 = 一个 Canvas + 若干 Axes。尺寸按期刊 profile 的 mm 给定。"""

    def __init__(self, profile="nature", size="single", width_mm=None, height_mm=None,
                 dpi=None, ss=2, bg=(255, 255, 255), backend="raster"):
        """backend: "raster"（默认，行为与旧版完全一致）| "svg" | "pdf"。

        矢量后端改用 sci.vector.VectorCanvas（同一套逻辑像素布图，绘制代码零改动），
        输出用 fig.canvas.save_svg(path) / fig.canvas.save_pdf(path)；
        PNG 由光栅画布生成，矢量画布没有像素缓冲。
        """
        self.style = stylemod.get(profile)
        self.dpi = dpi or self.style["dpi"]
        self.ss = ss
        self.bg = bg
        self.backend = backend or "raster"
        if width_mm is None:
            width_mm = (self.style["double_mm"] if size in ("double", "two")
                        else self.style["single_mm"])
        if height_mm is None:
            height_mm = width_mm * 0.75
        self.width_mm = float(width_mm)
        self.height_mm = min(float(height_mm), self.style["max_height_mm"])
        self.W = stylemod.mm2px(self.width_mm, self.dpi)
        self.H = stylemod.mm2px(self.height_mm, self.dpi)
        if self.backend in ("svg", "pdf", "vector"):
            from sci.vector import VectorCanvas        # 延迟导入：光栅路径不加载矢量模块
            self.canvas = VectorCanvas(self.W, self.H, bg=bg, dpi=self.dpi)
        else:
            self.canvas = raster.Canvas(self.W, self.H, bg=bg, ss=ss)
        self.axes_list = []
        self._series = []
        self._cmap = None
        self._grid = False

    # ---------- 布局 ----------
    def margins(self, left=None, right=None, top=None, bottom=None):
        """边距（mm）。默认给足 y 轴标题 + 刻度标签的空间。"""
        st = self.style
        d = {
            "left": left if left is not None else 17.0,
            "right": right if right is not None else 2.5,
            "top": top if top is not None else 2.5,
            "bottom": bottom if bottom is not None else 11.0,
        }
        return tuple(stylemod.mm2px(d[k], self.dpi) for k in ("left", "right", "top", "bottom"))

    def axes_in_mm(self, rect_mm, xlim, ylim, **kw):
        """按 mm 坐标放一个 Axes：rect_mm = (x0, y0, x1, y1)，y 从顶往下。

        xlabel / ylabel 可作为关键字直接传（Axes 构造器不接受它们，
        这里取出来在构造后调用 set_xlabel/set_ylabel）。
        """
        xlabel = kw.pop("xlabel", None)
        ylabel = kw.pop("ylabel", None)
        x0, y0, x1, y1 = rect_mm
        box = (stylemod.mm2px(x0, self.dpi), stylemod.mm2px(y0, self.dpi),
               stylemod.mm2px(x1, self.dpi), stylemod.mm2px(y1, self.dpi))
        ax = Axes(self.canvas, box, xlim, ylim, style=self.style, dpi=self.dpi, **kw)
        if xlabel:
            ax.set_xlabel(xlabel)
        if ylabel:
            ax.set_ylabel(ylabel)
        self.axes_list.append(ax)
        return ax

    def axes(self, xlim, ylim, left=17.0, right=2.5, top=2.5, bottom=11.0, **kw):
        """按边距占满剩余区域放一个 Axes（最常用）。"""
        return self.axes_in_mm((left, top, self.width_mm - right, self.height_mm - bottom),
                               xlim, ylim, **kw)

    def grid(self, nrows, ncols, xlim, ylim, gap_mm=(5.0, 5.0),
             left=17.0, right=2.5, top=2.5, bottom=11.0, share_ylabels=False, **kw):
        """多面板网格，返回二维列表 [[Axes]]。"""
        gw, gh = gap_mm
        x0, x1 = left, self.width_mm - right
        y0, y1 = top, self.height_mm - bottom
        cw = (x1 - x0 - gw * (ncols - 1)) / ncols
        ch = (y1 - y0 - gh * (nrows - 1)) / nrows
        out = []
        for r in range(nrows):
            row = []
            for c in range(ncols):
                rx0 = x0 + c * (cw + gw)
                ry0 = y0 + r * (ch + gh)
                ax = self.axes_in_mm((rx0, ry0, rx0 + cw, ry0 + ch), xlim, ylim, **kw)
                row.append(ax)
            out.append(row)
        return out

    def two_panel(self, xlim, ylim, ylim_res, ratio=3.0, gap_mm=0.6,
                  left=17.0, right=2.5, top=2.5, bottom=11.0,
                  main_kw=None, res_kw=None):
        """主图 + 残差图（上下叠放，残差高度 = 主图 / ratio）。返回 (主, 残差)。

        注意：两个面板的参数**分开传**。残差轴永远不跟主图一起反转/取对数
        （星等轴反转时，残差轴仍应是正常的线性轴）。
        """
        usable_h = self.height_mm - top - bottom - gap_mm
        res_h = usable_h / (ratio + 1.0)
        main_h = usable_h - res_h
        ax_main = self.axes_in_mm((left, top, self.width_mm - right, top + main_h),
                                  xlim, ylim, **dict(main_kw or {}))
        ax_res = self.axes_in_mm((left, top + main_h + gap_mm, self.width_mm - right,
                                  self.height_mm - bottom), xlim, ylim_res,
                                 **dict(res_kw or {}))
        return ax_main, ax_res

    # ---------- 记录（给检查器用） ----------
    def note_series(self, color, dash=None, marker=None, label=None):
        self._series.append({"color": palettes.hexstr(color), "dash": dash,
                             "marker": marker, "label": label})

    def set_cmap(self, name):
        self._cmap = name

    def set_grid(self, on=True):
        self._grid = on

    # ---------- 检查与保存 ----------
    def check(self, extra=None):
        st = self.style
        xlabel = ylabel = ""
        for a in self.axes_list:
            xl = getattr(a, "_xlabel", "") or ""
            yl = getattr(a, "_ylabel", "") or ""
            if xl:
                xlabel = xl
            if yl:
                ylabel = yl
        info = {
            "width_px": self.W, "height_px": self.H, "dpi": self.dpi,
            "xlabel": xlabel, "ylabel": ylabel,
            "fonts_pt": list(st["pt"].values()),
            "lines_pt": list(st["lw"].values()) + list(st["tick_len_pt"].values()),
            "cmap": self._cmap, "grid": self._grid,
            "series": list(self._series) + [x for a in self.axes_list
                                            for x in getattr(a, "_series", [])],
            # 按面板分组：颜色唯一编码的判定必须在同一坐标轴内进行
            "panels": ([list(self._series)] if self._series else [])
                      + [list(getattr(a, "_series", [])) for a in self.axes_list],
        }
        if extra:
            info.update(extra)
        return stylemod.check(info, st)

    def report(self, extra=None):
        return stylemod.format_report(self.check(extra))

    def save(self, path, check=True):
        """按扩展名选出口：.png（光栅）/ .svg / .pdf（矢量）。

        矢量后端必须用 backend="svg" 或 "pdf" 创建 Figure——光栅画布没有矢量信息，
        不能事后转换。
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        ext = path.lower().rsplit(".", 1)[-1] if "." in os.path.basename(path) else "png"
        if ext in ("svg", "pdf"):
            fn = getattr(self.canvas, "save_" + ext, None)
            if fn is None:
                raise RuntimeError(
                    "当前后端是 %r，不能输出 .%s；请用 Figure(backend=%r) 创建"
                    % (getattr(self.canvas, "backend", "raster"), ext, ext))
            fn(path)
        else:
            self.canvas.png(path)
        if check:
            rep = self.report()
            if "[error]" in rep or "[warn]" in rep:
                print(rep)
        return path


# ============================================================ 数据绘制

# dash 只支持 (on, off) 两段循环；"-." 这里退化成短划线
_LINESTYLES = {"-": None, "--": (4.0, 2.2), ":": (1.2, 1.8), "-.": (4.0, 1.6), "none": None}


def _is_line(linestyle):
    return linestyle not in ("none", "", None)


def _dash_of(linestyle):
    return _LINESTYLES.get(linestyle)


def _in_box(px, py, box, pad=1.5):
    x0, y0, x1, y1 = box
    return (x0 - pad <= px <= x1 + pad) and (y0 - pad <= py <= y1 + pad)


def _clip_segments(pts, box, pad=1.5):
    """把像素折线按绘图区边界剪开：越界段不画，避免线穿过轴标题/刻度标签。

    返回若干段连续点列（每段 ≥2 点）。纯过滤会跨越界点连直线，所以必须断段。
    """
    x0, y0, x1, y1 = box
    segs, cur = [], []
    for (px, py) in pts:
        inside = (x0 - pad <= px <= x1 + pad) and (y0 - pad <= py <= y1 + pad)
        if inside:
            cur.append((px, py))
        else:
            if len(cur) > 1:
                segs.append(cur)
            cur = []
    if len(cur) > 1:
        segs.append(cur)
    return segs


def plot_series(ax, x, y, yerr=None, xerr=None, marker=None, linestyle="-",
                color="#0072B2", lw_pt=None, ms_pt=None, label=None,
                fill=None, zorder=2, clip=True):
    """画一组数据：折线 + 误差棒 + 标记。返回实际用的 (color, dash, marker)。"""
    c = ax.canvas
    st = ax.style
    dpi = ax.dpi
    color = palettes.hexstr(color)
    lw = stylemod.pt2px(lw_pt if lw_pt is not None else st["lw"]["data"], dpi)
    ew = stylemod.pt2px(st["lw"]["err"], dpi)
    ms_pt = ms_pt if ms_pt is not None else 3.0          # 数据点直径（pt），论文常用 3–4 pt
    ms = stylemod.pt2px(ms_pt, dpi) / 2.0                # 转半径（px）
    dash = _dash_of(linestyle)

    pts = [(ax.px(xi), ax.py(yi)) for xi, yi in zip(x, y)]

    if fill is not None:
        lo, hi = fill
        xs_px = [ax.px(xi) for xi in x]
        # 真半透明：叠在已有内容上按 alpha 混合（画布不支持时自动退回预混色）
        primitives.band_alpha(c, xs_px, [ax.py(v) for v in hi],
                              [ax.py(v) for v in lo], palettes.rgb(color), alpha=0.22)

    if _is_line(linestyle) and len(pts) > 1:
        segs = _clip_segments(pts, ax.box) if clip else [pts]
        for seg in segs:
            primitives.polyline(c, seg, palettes.rgb(color), lw, dash=dash)

    if yerr is not None:
        for xi, yi, ei in zip(x, y, yerr):
            if clip and not _in_box(ax.px(xi), ax.py(yi), ax.box):
                continue
            ey = ei if not isinstance(ei, (tuple, list)) else None
            lo = yi - (ey if ey is not None else ei[0])
            hi = yi + (ey if ey is not None else ei[1])
            primitives.errorbar_v(c, ax.px(xi), ax.py(lo), ax.py(hi), palettes.rgb(color),
                                  w=ew, cap=2.2)
    if xerr is not None:
        for xi, yi, ei in zip(x, y, xerr):
            ey = ei if not isinstance(ei, (tuple, list)) else None
            primitives.errorbar_h(c, ax.py(yi), ax.px(xi - ey), ax.px(xi + ey),
                                  palettes.rgb(color), w=ew, cap=2.2)

    _note_series(ax, color, dash, marker, label, hollow=bool(marker) and _hollow(marker))
    if marker:
        for xi, yi in zip(x, y):
            if clip and not _in_box(ax.px(xi), ax.py(yi), ax.box):
                continue
            primitives.marker(c, marker, ax.px(xi), ax.py(yi), ms,
                              fill=(255, 255, 255) if _hollow(marker) else palettes.rgb(color),
                              edge=palettes.rgb(color), ew=ew)
    return color, dash, marker


def _hollow(marker):
    return marker in ("circle", "square", "triangle", "diamond", "hexagon")


def _note_series(ax, color, dash, marker, label, hollow=False):
    """把一条序列登记到 ax 上，供 Figure.check() 做「颜色不得唯一编码」检查。"""
    lst = getattr(ax, "_series", None)
    if lst is None:
        lst = []
        ax._series = lst
    lst.append({"color": palettes.hexstr(color), "dash": dash, "marker": marker,
                "label": label, "hollow": hollow})


def plot_model(ax, x, y, color="#000000", linestyle="--", lw_pt=None, label=None):
    c = ax.canvas
    st = ax.style
    lw = stylemod.pt2px(lw_pt if lw_pt is not None else st["lw"]["data"], ax.dpi)
    pts = [(ax.px(xi), ax.py(yi)) for xi, yi in zip(x, y)]
    for seg in _clip_segments(pts, ax.box):
        primitives.polyline(c, seg, palettes.rgb(palettes.hexstr(color)), lw,
                            dash=_dash_of(linestyle))
    _note_series(ax, color, _dash_of(linestyle), None, label)
    return color, _dash_of(linestyle), None


# ============================================================ 2D 数据（热图 / 等高线 / 色标）

def _fmt_num(v, step):
    if v == 0:
        return "0"
    if abs(step) >= 1 and abs(step - round(step)) < 1e-9:
        return "%d" % round(v)
    d = max(0, -int(math.floor(math.log10(abs(step)))))
    s = ("%.*f" % (d, v)).rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def _zrange(z, vmin, vmax):
    flat = [v for row in z for v in row if v is not None]
    if not flat:
        return 0.0, 1.0
    return (min(flat) if vmin is None else vmin,
            max(flat) if vmax is None else vmax)


def _even_axis(v):
    """判断一维坐标是否等距（热图快速路径的前提）。"""
    n = len(v)
    if n < 3:
        return True
    d = v[1] - v[0]
    if abs(d) < 1e-30:
        return False
    for i in range(1, n - 1):
        if abs((v[i + 1] - v[i]) - d) > abs(d) * 1e-6:
            return False
    return True


def plot_heatmap(ax, xs, ys, z, cmap="viridis", vmin=None, vmax=None):
    """二维网格热图。xs 长度 nx、ys 长度 ny、z 为 ny×nx。

    返回 (vmin, vmax)，传给 Fig.colorbar() 画色标。
    规则网格走批量写缓冲的快速路径（比逐格快一个数量级），
    非均匀网格自动退回逐格填充。
    """
    c = ax.canvas
    ny, nx = len(ys), len(xs)
    vmin, vmax = _zrange(z, vmin, vmax)
    span = (vmax - vmin) or 1.0
    table = palettes.lut(cmap, 256)

    def _col(v):
        if v is None:
            return (255, 255, 255)
        k = int((v - vmin) / span * 255.0)
        return table[0 if k < 0 else (255 if k > 255 else k)]

    dx = (xs[1] - xs[0]) if nx > 1 else 1.0
    dy = (ys[1] - ys[0]) if ny > 1 else 1.0
    px0 = ax.px(xs[0] - dx / 2.0)
    px1 = ax.px(xs[-1] + dx / 2.0)
    py_top = ax.py(ys[-1] + dy / 2.0)
    py_bot = ax.py(ys[0] - dy / 2.0)
    w = int(round(px1 - px0))
    h = int(round(py_bot - py_top))

    fast = (getattr(c, "image_rgb", None) is not None and w > 2 and h > 2
            and _even_axis(xs) and _even_axis(ys)
            and px0 >= 0 and py_top >= 0 and px0 + w <= c.w and py_top + h <= c.h)
    if fast:
        # 每个格子行的 1x RGB 行
        row_cache = {}
        for j in range(ny):
            rb = bytearray()
            prev = 0
            for i in range(nx):
                xr = int(round(w * (i + 1) / nx))
                wpx = xr - prev
                prev = xr
                if wpx > 0:
                    rb += bytes(_col(z[j][i])) * wpx
            row_cache[j] = bytes(rb)
        rows = []
        for j in range(ny - 1, -1, -1):        # y 越大越靠屏幕上方
            hy0 = int(round(h * (ny - 1 - j) / ny))
            hy1 = int(round(h * (ny - j) / ny))
            for _ in range(max(1, hy1 - hy0)):
                rows.append(row_cache[j])
        c.image_rgb(px0, py_top, w, len(rows), rows)
        return vmin, vmax

    # 慢速路径：非均匀网格 / 越界 → 逐格填充
    xb = [(xs[i] + xs[i + 1]) / 2.0 for i in range(nx - 1)]
    yb = [(ys[j] + ys[j + 1]) / 2.0 for j in range(ny - 1)]
    xedges = ([xs[0] - (xb[0] - xs[0])] if nx > 1 else [xs[0] - 0.5]) + xb + \
             ([xs[-1] + (xs[-1] - xb[-1])] if nx > 1 else [xs[0] + 0.5])
    yedges = ([ys[0] - (yb[0] - ys[0])] if ny > 1 else [ys[0] - 0.5]) + yb + \
             ([ys[-1] + (ys[-1] - yb[-1])] if ny > 1 else [ys[0] + 0.5])
    for j in range(ny):
        py0, py1 = ax.py(yedges[j]), ax.py(yedges[j + 1])
        for i in range(nx):
            v = z[j][i]
            if v is None:
                continue
            px_a, px_b = ax.px(xedges[i]), ax.px(xedges[i + 1])
            c.rect(min(px_a, px_b), min(py0, py1), max(px_a, px_b), max(py0, py1), _col(v))
    return vmin, vmax


def plot_contour(ax, xs, ys, z, levels=None, n=6, cmap=None, color="#333333",
                 lw_pt=0.8, labels=False, label_fmt="%.3g", label_size_pt=None):
    """等高线（marching squares）。levels=None 时自动取 nice 阈值。

    cmap 给定时按阈值取色（低→高），否则统一用 color。
    labels=True 时在每条等值线的最长一段上标数值（带白描边，不压线）。
    返回实际用的 levels。
    """
    from sci import contour as ct
    c = ax.canvas
    if levels is None:
        levels = ct.auto_levels(z, n) or [0.0]
    lw = stylemod.pt2px(lw_pt, ax.dpi)
    lo, hi = levels[0], levels[-1]
    span = (hi - lo) or 1.0
    lab_pt = label_size_pt if label_size_pt is not None else ax.style["pt"]["annot"]
    lab_px = stylemod.pt2px(lab_pt, ax.dpi)
    for lv, polys in ct.lines(xs, ys, z, levels):
        col = palettes.colormap(cmap, (lv - lo) / span) if cmap else palettes.rgb(color)
        for poly in polys:
            pts = [(ax.px(x), ax.py(y)) for (x, y) in poly]
            if len(pts) >= 2:
                primitives.polyline(c, pts, col, lw)
        if labels and polys:
            # 每个阈值只在最长的一段上标一次，避免密集处糊成一片
            best = max(polys, key=len)
            mid = best[len(best) // 2]
            txt = label_fmt % lv
            px, py = ax.px(mid[0]), ax.py(mid[1])
            tw = fonts.text_width(txt, lab_px)
            # 白底衬把线打断（标准做法），否则等值线会从数字中间穿过
            c.rect(px - tw / 2.0 - lab_px * 0.28, py - lab_px * 0.80,
                   px + tw / 2.0 + lab_px * 0.28, py + lab_px * 0.28, (255, 255, 255))
            mathtext.draw(c, txt, px, py + lab_px * 0.30, lab_px, col, align="center")
    return levels


def plot_scatter_c(ax, x, y, c, s=None, cmap="viridis", vmin=None, vmax=None,
                   marker="circle", ms_pt=3.0, edge_pt=0.6,
                   smin_pt=None, smax_pt=None, size_scale="area"):
    """多维散点：**颜色编码第三维、大小编码第四维**（气泡图）。

    这是"想画 3D 但投稿不要 3D"时的标准替代方案：
    3D 散点会让读者误判距离关系，而 2D + 颜色 + 大小保留全部信息且可精确读数。

    c : 第三维值（决定颜色），配合 fig.colorbar 用
    s : 第四维值（决定点面积，可选）。None 时所有点等大
    size_scale : "area"（面积正比于 s，气泡图惯例）| "diameter"（直径正比于 s）

    返回 (vmin, vmax) —— 直接传给 fig.colorbar(...)
    """
    cc = ax.canvas
    r0 = stylemod.pt2px(ms_pt, ax.dpi) / 2.0
    ew = stylemod.pt2px(edge_pt, ax.dpi)
    vals = [v for v in c if v is not None]
    lo = min(vals) if vmin is None else vmin
    hi = max(vals) if vmax is None else vmax
    span = (hi - lo) or 1.0

    r_of = None
    if s is not None:
        sv = [v for v in s if v is not None]
        slo, shi = (min(sv), max(sv)) if sv else (0.0, 1.0)
        sspan = (shi - slo) or 1.0
        d_min = stylemod.pt2px(smin_pt if smin_pt is not None else ms_pt * 0.45, ax.dpi)
        d_max = stylemod.pt2px(smax_pt if smax_pt is not None else ms_pt * 2.6, ax.dpi)

        def r_of(si):
            t = (si - slo) / sspan
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            d = (math.sqrt(t) if size_scale == "area" else t)
            return (d_min + (d_max - d_min) * d) / 2.0

    for xi, yi, ci, si in zip(x, y, c, s if s is not None else [None] * len(x)):
        if ci is None:
            continue
        px, py = ax.px(xi), ax.py(yi)
        if not _in_box(px, py, ax.box):     # 越界点不画，避免压在轴标题上
            continue
        col = palettes.colormap(cmap, (ci - lo) / span)
        r = r_of(si) if (r_of is not None and si is not None) else r0
        primitives.marker(cc, marker, px, py, r, col, (0, 0, 0), ew)
    return lo, hi


def size_legend(ax, values, label="", x_frac=0.03, y_frac=0.05,
                ms_pt=3.0, smin_pt=None, smax_pt=None,
                color="#555555", n=3, size_scale="area"):
    """给大小编码加参考图例：几个不同直径的空心圆 + 对应数值。

    x_frac / y_frac 是相对绘图区的左下角位置（0-1）。
    """
    cc = ax.canvas
    st = ax.style
    pt = lambda v: stylemod.pt2px(v, st["dpi"]) if False else stylemod.pt2px(v, ax.dpi)
    slo, shi = min(values), max(values)
    sspan = (shi - slo) or 1.0
    d_min = stylemod.pt2px(smin_pt if smin_pt is not None else ms_pt * 0.45, ax.dpi)
    d_max = stylemod.pt2px(smax_pt if smax_pt is not None else ms_pt * 2.6, ax.dpi)
    lab_px = stylemod.pt2px(st["pt"]["annot"], ax.dpi)

    picks = ([slo + sspan * (i / (n - 1.0)) for i in range(n)] if n > 1 else [shi])

    def _radius(v):
        t = (v - slo) / sspan
        d = (math.sqrt(t) if size_scale == "area" else t)
        return (d_min + (d_max - d_min) * d) / 2.0

    # 先量出整条图例的总宽，再钳位到绘图区内（不然会像踩坑一样被右边界截断）
    total_w = 0.0
    for v in picks:
        total_w += _radius(v) * 2.0 + lab_px * 0.5 + fonts.text_width("%.3g" % v, lab_px) + lab_px * 1.3
    x0 = ax.box[0] + (ax.box[2] - ax.box[0]) * x_frac
    x0 = min(x0, ax.box[2] - total_w - lab_px * 0.6)
    x0 = max(x0, ax.box[0] + lab_px * 0.6)
    y0 = ax.box[3] - (ax.box[3] - ax.box[1]) * y_frac
    y0 = max(y0, ax.box[1] + d_max / 2.0 + lab_px * 1.6)
    col = palettes.rgb(color)
    cx = x0
    for v in picks:
        r = _radius(v)
        primitives.circle(cc, cx + r, y0 - r, r, (255, 255, 255), edge=col, ew=1.0)
        mathtext.draw(cc, "%.3g" % v, cx + r * 2 + lab_px * 0.5, y0 - r + lab_px * 0.35,
                      lab_px, (0, 0, 0))
        cx += r * 2 + lab_px * 0.5 + fonts.text_width("%.3g" % v, lab_px) + lab_px * 1.3
    if label:
        mathtext.draw(cc, label, x0, y0 - (d_max / 2) - lab_px * 0.8,
                      lab_px, (0, 0, 0))


def add_colorbar(fig, ax, cmap="viridis", vmin=0.0, vmax=1.0, label="",
                 width_mm=3.5, pad_mm=2.0, nticks=5, label_side="right"):
    """在 ax 右侧画竖直色标条（连续色板 + 刻度 + 轴标题）。

    注意：调用前要给 ax 右边留出空间——fig.axes(..., right=24) 或
    fig.axes_with_colorbar()。返回色条矩形 (x0, y0, x1, y1)。
    """
    c = fig.canvas
    dpi = fig.dpi
    st = fig.style
    pt = lambda v: stylemod.pt2px(v, dpi)
    x0 = ax.box[2] + stylemod.mm2px(pad_mm, dpi)
    x1 = x0 + stylemod.mm2px(width_mm, dpi)
    y0, y1 = ax.box[1], ax.box[3]

    # 竖直渐变：逐行填色（色板采样密度 = 像素行数）
    h = max(2, int(round(y1 - y0)))
    for k in range(h):
        t = 1.0 - (k + 0.5) / h
        c.rect(x0, y0 + k, x1, y0 + k + 1, palettes.colormap(cmap, t))

    # 边框
    bw = pt(st["lw"]["axis"])
    for (a, b, d, e) in ((x0, y0, x1, y0), (x0, y1, x1, y1),
                         (x0, y0, x0, y1), (x1, y0, x1, y1)):
        c.line(a, b, d, e, (0, 0, 0), bw)

    # 刻度与标签
    ticks, step = Axes.nice_ticks(vmin, vmax, nticks)
    size = pt(st["pt"]["tick_label"])
    span = (vmax - vmin) or 1.0
    for t in ticks:
        if not (vmin - 1e-12 <= t <= vmax + 1e-12):
            continue
        ty = y1 - (t - vmin) / span * (y1 - y0)
        c.line(x1, ty, x1 + pt(2.0), ty, (0, 0, 0), bw)
        mathtext.draw(c, _fmt_num(t, step), x1 + pt(3.2), ty + size * 0.35,
                      size, (0, 0, 0))

    # 色标标题（旋转，放右侧）
    if label:
        mathtext.draw_rotated(c, label, x1 + pt(20), (y0 + y1) / 2.0,
                              pt(st["pt"]["axis_label"]), (0, 0, 0))
    return (x0, y0, x1, y1)


def _figure_colorbar(self, ax, **kw):
    return add_colorbar(self, ax, **kw)


Figure.colorbar = _figure_colorbar


def _figure_axes_cb(self, xlim, ylim, cmap_mm=24.0, **kw):
    """带右侧色标空间的 Axes（right 自动加宽到能放下 colorbar）。"""
    kw.setdefault("right", cmap_mm)
    return self.axes(xlim, ylim, **kw)


Figure.axes_with_colorbar = _figure_axes_cb


# ============================================================ 图种：fit

def figure_fit(x, y, yerr=None, model=None, residual=True, ratio=3.0,
               xlabel="x", ylabel="y", xlim=None, ylim=None,
               legend_loc="upper left", title=None, profile="nature",
               size="single", width_mm=None, height_mm=None, out="fig_fit.png",
               marker="circle", linestyle="none", color="#0072B2",
               model_color="#000000", model_style="--", residual_ylabel=None,
               invert_x=False, invert_y=False, xscale="linear", yscale="linear",
               verbose=True):
    """数据 + 拟合 + 残差：物理/天文最通用的图种。

    model 传 (x_model, y_model)；给出 model 且 residual=True 时自动画残差面板。
    """
    fig = Figure(profile=profile, size=size, width_mm=width_mm, height_mm=height_mm)
    if xlim is None:
        xlim = (min(x), max(x))
    if ylim is None:
        lo, hi = min(y), max(y)
        pad = (hi - lo) * 0.12 or 1.0
        ylim = (lo - pad, hi + pad)

    if residual and model is not None:
        ylim_res = _residual_lim(x, y, yerr, model)
        ax, axr = fig.two_panel(
            xlim, ylim, ylim_res, ratio=ratio,
            main_kw=dict(xscale=xscale, yscale=yscale,
                         invert_x=invert_x, invert_y=invert_y),
            res_kw=dict(invert_x=invert_x))
        ax_res = axr
    else:
        ax = fig.axes(xlim, ylim, xscale=xscale, yscale=yscale,
                      invert_x=invert_x, invert_y=invert_y)
        ax_res = None

    entries = []
    if model is not None:
        mx, my = model
        plot_model(ax, mx, my, color=model_color, linestyle=model_style)
        entries.append({"kind": "line", "color": palettes.hexstr(model_color),
                        "label": "Model", "dash": _dash_of(model_style), "marker": None})
    col, dash, mk = plot_series(ax, x, y, yerr=yerr, marker=marker,
                                linestyle=linestyle, color=color)
    entries.append({"kind": "marker" if linestyle == "none" else "line+marker",
                    "color": col, "label": "Data", "dash": dash, "marker": mk,
                    "hollow": bool(mk) and _hollow(mk)})
    fig.note_series(col, dash, mk, "Data")

    ax.set_ylabel(ylabel)
    if ax_res is None:
        ax.set_xlabel(xlabel)
    if title:
        mathtext.draw(fig.canvas, title, fig.W / 2, stylemod.pt2px(8, fig.dpi) * 1.6,
                      stylemod.pt2px(fig.style["pt"]["title"], fig.dpi), (0, 0, 0), align="center")

    if ax_res is not None:
        mx, my = model
        res = [yi - _interp(mx, my, xi) for xi, yi in zip(x, y)]
        if yerr is not None:
            res = [r / (e or 1e-30) for r, e in zip(res, yerr)]
            ylab = residual_ylabel or "Residual ($\\sigma$)"
        else:
            ylab = residual_ylabel or "Residual"
        plot_series(ax_res, x, res, marker="circle", linestyle="none", color=color, ms_pt=2.6)
        primitives.hline(fig.canvas, ax_res.box[0], ax_res.box[2], ax_res.py(0),
                         (140, 140, 140), stylemod.pt2px(0.5, fig.dpi))
        ax_res.set_xlabel(xlabel)
        ax_res.set_ylabel(ylab)
        ax_res.draw()
        ax.draw(xticklabels=False, xlabel=False)
    else:
        ax.draw()

    # 图例最后画，压在数据与轴框之上
    if legend_loc and len(entries) > 1:
        ax.legend(entries, loc=legend_loc)

    fig.save(out, check=verbose)
    return fig


def _residual_lim(x, y, yerr, model):
    mx, my = model
    res = [yi - _interp(mx, my, xi) for xi, yi in zip(x, y)]
    if yerr is not None:
        res = [r / (e or 1e-30) for r, e in zip(res, yerr)]
    m = max(abs(v) for v in res) or 1.0
    return (-m * 1.25, m * 1.25)


def _interp(xs, ys, xv):
    """线性插值（xs 可单调递增）。"""
    if len(xs) < 2:
        return ys[0]
    if xs[0] > xs[-1]:
        xs, ys = xs[::-1], ys[::-1]
    if xv <= xs[0]:
        return ys[0]
    if xv >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= xv:
            lo = mid
        else:
            hi = mid
    t = (xv - xs[lo]) / (xs[hi] - xs[lo]) if xs[hi] != xs[lo] else 0.0
    return ys[lo] + (ys[hi] - ys[lo]) * t


# ============================================================ 图种：lightcurve

def figure_lightcurve(time, mag, err=None, model=None, residual=True,
                      xlabel=None, ylabel=None, time_unit="MJD",
                      invert_y=True, profile="nature", size="single",
                      width_mm=None, height_mm=None, out="fig_lightcurve.png",
                      marker="circle", color="#0072B2", model_color="#000000",
                      legend_loc="upper left", residual_ylabel=None,
                      time_offset="auto", verbose=True):
    """天文光变曲线：星等轴反向（越亮越靠上）、误差棒、模型、残差。

    time 一般是 MJD；mag 是星等（数值越小越亮），所以默认 invert_y=True。
    若传的是流量而非星等，请设 invert_y=False。

    time_offset="auto"：MJD 这类大数（>1000）、而观测跨度只有几天时，自动减去
    起始时刻，轴标题写成 "Time (MJD - 60311.25 d)"。这是天文图的标准做法——
    否则刻度标签会挤成 60311.240 / 60311.245 / ... 一串长数字。
    也可传具体数值强制偏移，或传 None/0 关闭。
    """
    t_off = 0.0
    if time_offset == "auto":
        t0 = round(float(time[0]), 2)
        span = abs(max(time) - min(time)) or 1e-9
        if abs(t0) > 1000 and span < 1.0:
            t_off = t0
    elif isinstance(time_offset, (int, float)) and time_offset:
        t_off = float(time_offset)
    if t_off:
        time = [t - t_off for t in time]
        if model is not None:
            model = ([x - t_off for x in model[0]], model[1])

    if xlabel is None:
        if t_off:
            xlabel = "Time (%s $-$ %.2f d)" % (time_unit, t_off)
        else:
            xlabel = "Time (%s)" % time_unit
    if ylabel is None:
        ylabel = "Magnitude" if invert_y else "Flux"
    return figure_fit(
        time, mag, yerr=err, model=model, residual=residual,
        xlabel=xlabel, ylabel=ylabel, invert_y=invert_y,
        marker=marker, color=color, model_color=model_color,
        profile=profile, size=size, width_mm=width_mm, height_mm=height_mm,
        out=out, legend_loc=legend_loc, residual_ylabel=residual_ylabel,
        verbose=verbose)
