# -*- coding: utf-8 -*-
"""sci/corner.py — MCMC 后验角图（corner plot）。

天文与统计论文里展示 MCMC 采样结果的标准图种：n 个参数排成 n×n 面板矩阵。

布局
    ┌────┬────┬────┐
    │ 1D │    │    │   上三角留空（c < r 的面板不建坐标轴）
    ├────┼────┼────┤
    │ 2D │ 1D │    │   对角线 = 各参数的一维边缘后验直方图（分位线 + 上/下偏标注）
    ├────┼────┼────┤   下三角 = 两两参数的二维联合后验（等高线 + 淡灰散点）
    │ 2D │ 2D │ 1D │
    └────┴────┴────┘
只有外圈标刻度与轴标题：最后一行写 x 标题，第一列写 y 标题。
单栏 89 mm、n=3 时每格约 24 mm，所以字号统一取 profile 的 tick_label × 0.8。

不依赖 numpy / matplotlib / scipy：直方图、平滑、marching-squares 等高线
全部用纯 Python 手写（等高线复用 sci.contour）。

用法：
    from sci.corner import corner_figure
    corner_figure(samples, ["$m_1$", "$m_2$", "$\\Omega_m$"],
                  out="corner.png")
"""
import math

from . import contour as ct  # noqa: E402
from . import palettes, primitives, style as stylemod  # noqa: E402
from .axes import Axes  # noqa: E402
from sciplot import Figure  # noqa: E402

INK = (20, 20, 20)        # 文字 / 中位线
GRAY_LINE = (105, 105, 105)  # 16% / 84% 分位线

# 左下角文字面板的默认排版（mm）：左留 y 刻度标签 + y 轴标题，下留 x 刻度 + x 标题
_MARGIN_L, _MARGIN_R = 12.6, 2.6
_MARGIN_T, _MARGIN_B = 2.6, 10.6
_GAP_MM = 0.9             # 面板间距 mm（太小会两条边框粘住，太大浪费单栏空间）
_FONT_SCALE = 0.8         # 小面板字号 = profile 字号 × 0.8


# ---------------------------------------------------------------- 数值工具

def _quantile(vals, q):
    """样本分位数（线性插值，与 numpy.percentile 默认口径一致）。"""
    xs = sorted(vals)
    n = len(xs)
    if n == 0:
        return 0.0
    if n == 1:
        return float(xs[0])
    pos = min(max(float(q), 0.0), 1.0) * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    f = pos - lo
    return float(xs[lo]) * (1.0 - f) + float(xs[hi]) * f


def _range_of(vals, pct):
    """按百分位区间 [pct[0], pct[1]] 取显示范围；退化时按比例撑开。"""
    lo = _quantile(vals, pct[0] / 100.0)
    hi = _quantile(vals, pct[1] / 100.0)
    if not (hi > lo):
        pad = abs(lo) * 0.01 or 1.0
        lo, hi = lo - pad, hi + pad
    return lo, hi


def _hist1d(vals, lo, hi, nbins):
    """一维直方图计数。范围外的样本丢弃（不堆到端部 bin 造成假尖峰）。"""
    step = (hi - lo) / float(nbins)
    counts = [0.0] * nbins
    for v in vals:
        if v < lo or v > hi:
            continue
        k = int((v - lo) / step)
        if k >= nbins:
            k = nbins - 1
        counts[k] += 1.0
    return counts


def _hist2d(xs, ys, xlo, xhi, ylo, yhi, nbins):
    """二维直方图，返回 z[j][i]（行 = y 方向，列 = x 方向，与 contour.lines 一致）。"""
    sx = (xhi - xlo) / float(nbins)
    sy = (yhi - ylo) / float(nbins)
    z = [[0.0] * nbins for _ in range(nbins)]
    for x, y in zip(xs, ys):
        if x < xlo or x > xhi or y < ylo or y > yhi:
            continue
        i = int((x - xlo) / sx)
        j = int((y - ylo) / sy)
        if i >= nbins:
            i = nbins - 1
        if j >= nbins:
            j = nbins - 1
        z[j][i] += 1.0
    return z


def _gauss_kernel(sigma):
    """一维高斯核（半宽 ceil(2σ)，归一化）。sigma<=0 退化为恒等核。"""
    sigma = float(sigma)
    if sigma <= 1e-9:
        return [1.0]
    rad = max(1, int(math.ceil(2.0 * sigma)))
    w = [math.exp(-0.5 * (k / sigma) ** 2) for k in range(-rad, rad + 1)]
    s = sum(w)
    return [v / s for v in w]


def _convolve1d(arr, kernel):
    """一维卷积，边缘按端点值延拓（不缩小有效范围）。"""
    n = len(arr)
    rad = len(kernel) // 2
    out = [0.0] * n
    for i in range(n):
        acc = 0.0
        for k, wk in enumerate(kernel):
            j = i + k - rad
            if j < 0:
                j = 0
            elif j >= n:
                j = n - 1
            acc += arr[j] * wk
        out[i] = acc
    return out


def _smooth1d(arr, sigma):
    """一维高斯平滑（sigma 以 bin 为单位）；sigma=0 原样返回。"""
    if sigma <= 0:
        return [float(v) for v in arr]
    return _convolve1d([float(v) for v in arr], _gauss_kernel(sigma))


def _smooth2d(z, sigma):
    """二维可分离高斯平滑：先按行、再按列各卷积一次。"""
    if sigma <= 0:
        return [[float(v) for v in row] for row in z]
    kern = _gauss_kernel(sigma)
    ny = len(z)
    nx = len(z[0]) if ny else 0
    rows = [_convolve1d(row, kern) for row in z]
    cols = [[rows[j][i] for j in range(ny)] for i in range(nx)]
    cols = [_convolve1d(col, kern) for col in cols]
    return [[cols[i][j] for i in range(nx)] for j in range(ny)]


def _upsample1d(centers, factor):
    """等距网格中心点线性加密（用于让等高线更平滑）。"""
    n = len(centers)
    if n < 2 or factor <= 1:
        return list(centers)
    m = (n - 1) * factor + 1
    step = (centers[-1] - centers[0]) / float(n - 1)
    return [centers[0] + step * k / float(factor) for k in range(m)]


def _upsample2d(z, factor):
    """双线性插值加密二维网格（marching squares 在粗网格上会有明显折角）。"""
    ny = len(z)
    nx = len(z[0]) if ny else 0
    if factor <= 1 or ny < 2 or nx < 2:
        return [[float(v) for v in row] for row in z]
    my = (ny - 1) * factor + 1
    mx = (nx - 1) * factor + 1
    out = []
    for jj in range(my):
        y = jj / float(factor)
        j0 = int(math.floor(y))
        j1 = min(j0 + 1, ny - 1)
        fy = y - j0
        row = []
        for ii in range(mx):
            x = ii / float(factor)
            i0 = int(math.floor(x))
            i1 = min(i0 + 1, nx - 1)
            fx = x - i0
            v = (z[j0][i0] * (1.0 - fx) * (1.0 - fy)
                 + z[j0][i1] * fx * (1.0 - fy)
                 + z[j1][i0] * (1.0 - fx) * fy
                 + z[j1][i1] * fx * fy)
            row.append(v)
        out.append(row)
    return out


def _shrink_style(st, f):
    """浅拷贝 profile 并按 f 缩放字号 / 刻度长度（pt 子字典必须新建，否则污染全局）。"""
    out = dict(st)
    out["pt"] = {k: float(v) * f for k, v in st["pt"].items()}
    out["tick_len_pt"] = {k: float(v) * f for k, v in st["tick_len_pt"].items()}
    out["lw"] = dict(st["lw"])
    return out


# ---------------------------------------------------------------- 面板绘制

def _draw_joint(ax, xs, ys, xr, yr, nbins, sigma, cmap):
    """下三角面板：二维直方图 → 淡灰散点打底 + 4 级等高线。"""
    c = ax.canvas
    dpi = ax.dpi
    box = ax.box

    # 1) 散点：均匀抽样（最多 ~1200 个），浅灰，保证不糊住等高线
    n = len(xs)
    step = max(1, int(math.ceil(n / 1200.0)))
    r_dot = stylemod.pt2px(0.55, dpi) / 2.0
    dot_col = palettes.mix("#000000", f=0.20)
    for k in range(0, n, step):
        x, y = xs[k], ys[k]
        if x < xr[0] or x > xr[1] or y < yr[0] or y > yr[1]:
            continue
        px, py = ax.px(x), ax.py(y)
        if px < box[0] or px > box[2] or py < box[1] or py > box[3]:
            continue
        primitives.marker(c, "circle", px, py, r_dot, dot_col)

    # 2) 二维直方图 + 平滑 + 加密
    z = _smooth2d(_hist2d(xs, ys, xr[0], xr[1], yr[0], yr[1], nbins), sigma)
    peak = 0.0
    for row in z:
        m = max(row)
        if m > peak:
            peak = m
    if peak <= 0.0:
        return

    sx = (xr[1] - xr[0]) / float(nbins)
    sy = (yr[1] - yr[0]) / float(nbins)
    cx = [xr[0] + (i + 0.5) * sx for i in range(nbins)]
    cy = [yr[0] + (j + 0.5) * sy for j in range(nbins)]
    ux = _upsample1d(cx, 2)
    uy = _upsample1d(cy, 2)
    uz = _upsample2d(z, 2)

    # 3) 等高线：按峰值的固定比例取 4 条（比 nice numbers 更稳，样本量变化时不跳）
    levels = [peak * f for f in (0.12, 0.34, 0.58, 0.82)]
    lines = ct.lines(ux, uy, uz, levels)
    nl = max(1, len(levels) - 1)
    for k, (lv, polys) in enumerate(lines):
        # 低密度（外圈）浅、高密度（内芯）深：取色板暗端一段，白底上对比够
        t = 0.06 + 0.30 * (1.0 - k / float(nl))
        col = palettes.colormap(cmap, t)
        lw = stylemod.pt2px(0.45 + 0.05 * k, dpi)
        for poly in polys:
            pts = [(ax.px(x), ax.py(y)) for (x, y) in poly]
            if len(pts) >= 2:
                primitives.polyline(c, pts, col, lw)


def _draw_marginal(ax, vals, hist, nbins, rng, quantiles, cmap):
    """对角线面板：一维直方图 + 分位竖虚线 + 右上角 +a/−b 标注。"""
    c = ax.canvas
    dpi = ax.dpi
    box = ax.box
    lo, hi = rng
    width = (hi - lo) / float(nbins)
    fill = palettes.mix(palettes.colormap(cmap, 0.55), f=0.30)

    # 直方图柱子（从 y=0 长到计数值）
    for k, h in enumerate(hist):
        if h <= 0.0:
            continue
        x0 = lo + k * width
        px0, px1 = ax.px(x0), ax.px(x0 + width)
        py0, py1 = ax.py(0.0), ax.py(h)
        c.rect(min(px0, px1), min(py0, py1), max(px0, px1), max(py0, py1), fill)

    # 分位竖虚线：中位数深色，其余灰色
    qs = sorted(quantiles)
    qvals = [_quantile(vals, q) for q in qs]
    lw_base = max(1.0, stylemod.pt2px(0.5, dpi))
    for q, qv in zip(qs, qvals):
        px = ax.px(qv)
        if px < box[0] - 0.5 or px > box[2] + 0.5:
            continue
        is_med = abs(q - 0.5) < 1e-9
        col = INK if is_med else GRAY_LINE
        w = lw_base * (1.05 if is_med else 0.85)
        dash = (3.6, 2.2) if is_med else (2.6, 2.2)
        primitives.polyline(c, [(px, box[1]), (px, box[3])], col, w, dash=dash)

    # 右上角：+a / −b（相对中位数的上偏 / 下偏）
    if len(qs) >= 2:
        q_lo, q_hi = qs[0], qs[-1]
        q_mid = qs[len(qs) // 2]
        v_lo = _quantile(vals, q_lo)
        v_hi = _quantile(vals, q_hi)
        v_mid = _quantile(vals, q_mid)
        s = "%+.2f / \u2212%.2f" % (v_hi - v_mid, v_mid - v_lo)
        size = stylemod.pt2px(ax.style["pt"]["annot"], dpi)
        tx = box[2] - 0.30 * size
        ty = box[1] + 1.30 * size
        primitives.text_halo(c, s, tx, ty, size, INK,
                             align="right", halo=(255, 255, 255), r=1.6)


# ---------------------------------------------------------------- 对外接口

def corner_figure(samples, labels, fig=None, profile="nature",
                  size="single", out="corner.png", backend="raster",
                  bins=28, smooth=1, range_pct=(0.5, 99.5),
                  quantiles=(0.16, 0.50, 0.84), cmap="viridis"):
    """MCMC 后验角图。

    参数
      samples : [[v1, v2, ..., vn], ...] 每行一个样本、n 个参数
      labels  : 长度 n 的标签列表（支持 ``$...$`` 数学排版）
      fig     : 复用已有 Figure（None 时自动按面板正方形算高度）
      backend : 输出后端 "raster"（PNG，默认）| "svg" | "pdf"——透传给 Figure；
                fig 给定时该参数被忽略（用 fig 自己的后端）
      bins    : 一维/二维直方图 bin 数（小面板建议 20–40）
      smooth  : 平滑尺度（1 = 推荐默认，二维密度按约 1.5 个 bin 的高斯核平滑；
                0 = 不平滑，数值越大越平滑）
      range_pct : 单参数显示范围用的百分位（默认去掉两端 0.5%）
      quantiles : 对角线上画虚线的分位数；首/末 + 中间项用于 +a/−b 标注
      cmap    : 等高线与直方图配色（viridis / cividis）

    返回 Figure。只建下三角与对角线面板，上三角保持空白。
    """
    # ---------------- 参数校验与预处理 ----------------
    data = [[float(v) for v in row] for row in samples]
    if not data:
        raise ValueError("samples 不能为空")
    ndim = len(data[0])
    if ndim < 1:
        raise ValueError("每个样本至少要有 1 个参数")
    for row in data:
        if len(row) != ndim:
            raise ValueError("samples 每行长度必须一致（%d vs %d）" % (len(row), ndim))
    labels = [str(s) for s in labels]
    if len(labels) != ndim:
        raise ValueError("labels 长度（%d）必须等于参数个数（%d）"
                         % (len(labels), ndim))
    if bins < 4:
        raise ValueError("bins 至少为 4，收到 %r" % (bins,))
    rp = (float(range_pct[0]), float(range_pct[1]))
    if not (0.0 <= rp[0] < rp[1] <= 100.0):
        raise ValueError("range_pct 必须满足 0 <= lo < hi <= 100，收到 %r" % (range_pct,))
    qs = [float(q) for q in quantiles]
    if not qs or min(qs) < 0.0 or max(qs) > 1.0:
        raise ValueError("quantiles 必须落在 [0,1]，收到 %r" % (quantiles,))

    cols = [[row[j] for row in data] for j in range(ndim)]
    rngs = [_range_of(col, rp) for col in cols]
    sigma = max(0.0, float(smooth)) * 1.5

    hists = []
    hmax = 0.0
    for j in range(ndim):
        h = _smooth1d(_hist1d(cols[j], rngs[j][0], rngs[j][1], int(bins)), sigma)
        hists.append(h)
        for v in h:
            if v > hmax:
                hmax = v
    if hmax <= 0.0:
        hmax = 1.0

    # ---------------- 画布与布局 ----------------
    gap = _GAP_MM
    if fig is None:
        st = stylemod.get(profile)
        base_mm = st["double_mm"] if size in ("double", "two") else st["single_mm"]
        pm0 = (base_mm - _MARGIN_L - _MARGIN_R - gap * (ndim - 1)) / float(ndim)
        height_mm = _MARGIN_T + _MARGIN_B + ndim * pm0 + gap * (ndim - 1)
        fig = Figure(profile=profile, size=size, height_mm=height_mm,
                     backend=backend)
    st = fig.style
    dpi = fig.dpi
    small = _shrink_style(st, _FONT_SCALE)

    aw = fig.width_mm - _MARGIN_L - _MARGIN_R
    ah = fig.height_mm - _MARGIN_T - _MARGIN_B
    pm = (aw - gap * (ndim - 1)) / float(ndim)
    pm = min(pm, (ah - gap * (ndim - 1)) / float(ndim))
    pm = max(pm, 4.0)
    grid_mm = ndim * pm + gap * (ndim - 1)
    x_off = _MARGIN_L + (aw - grid_mm) / 2.0
    y_off = _MARGIN_T + (ah - grid_mm) / 2.0

    axes = {}
    for r in range(ndim):
        for c in range(ndim):
            if c > r:                       # 上三角留空（c > r 在右上）
                continue
            rx = x_off + c * (pm + gap)
            ry = y_off + r * (pm + gap)
            rect_mm = (rx, ry, rx + pm, ry + pm)
            box = tuple(stylemod.mm2px(v, dpi) for v in rect_mm)
            if r == c:
                xlim = rngs[r]
                ylim = (0.0, hmax * 1.18)   # 顶部留 15% 给 +a/−b 标注
            else:
                xlim = rngs[c]
                ylim = rngs[r]
            ax = Axes(fig.canvas, box, xlim, ylim, style=small, dpi=dpi)
            fig.axes_list.append(ax)
            axes[(r, c)] = ax

    # ---------------- 面板内容 ----------------
    for (r, c), ax in axes.items():
        if r == c:
            _draw_marginal(ax, cols[r], hists[r], int(bins), rngs[r], qs, cmap)
        else:
            _draw_joint(ax, cols[c], cols[r], rngs[c], rngs[r],
                        int(bins), sigma, cmap)

    # ---------------- 坐标轴（只有外圈标刻度/标题）----------------
    for (r, c), ax in axes.items():
        xlab = labels[c] if r == ndim - 1 else ""
        if r == c:
            ylab = "Counts" if ndim == 1 else ""
        else:
            ylab = labels[r] if c == 0 else ""
        if xlab:
            ax.set_xlabel(xlab)
        if ylab:
            ax.set_ylabel(ylab)
        ax.draw(xticklabels=(r == ndim - 1),
                yticklabels=(c == 0 and (r != c or ndim == 1)),
                xlabel=bool(xlab), ylabel=bool(ylab))

    fig.set_cmap(cmap)
    if out:
        fig.save(out)
    return fig


__all__ = ["corner_figure"]
