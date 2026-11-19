# -*- coding: utf-8 -*-
"""sci/primitives.py — 科研图元库（纯 Python 光栅化：抗锯齿细线 + 无接缝折线）。

为什么需要这一层（而不是直接用 raster.Canvas 的原语）
------------------------------------------------------
1) `Canvas` 只有 ss=2 的超采样（2×2 下采样平均 = 最多 5 级灰阶）。对斜线、细弧、
   0.5 pt 的细边框，成品上仍然能看到阶梯。本文件把线条 / 圆 / 圆环 / 多边形描边
   直接写进 `Canvas` 的超采样缓冲，用「有符号距离场(SDF) → 覆盖率 → source-over
   混色」抗锯齿，等效 4×~8× 超采样；w<1 逻辑像素也能画成正确的浅色细线。
2) `Canvas.line()` 是四边形硬填充、两端平头，折线拐角处相邻两段之间会留下白缝。
   本文件的 `polyline` 在每个内部顶点补一个「直径 = 线宽」的实心圆，缝隙为零；
   虚线按**弧长**切分（不是按顶点分段），跨顶点的虚线段同样在顶点处补圆。

坐标与颜色约定
--------------
* 所有公开 API 收「逻辑像素」（与 `Canvas` 一致），内部统一乘 `Canvas.ss`。
* 颜色：'#RRGGBB' / 'RRGGBB' / (r, g, b)；`fill=None` 表示不填充（只描边或什么都不画）。
* 光栅器没有 alpha 通道：半透明色请用 `sci.palettes.mix(color, bg, f)` 预先混色。

性能
----
所有光栅化都只遍历图元包围盒内的像素，且实心内部用切片 / 快速路径写入。
一张 1800×1200 @ss=2 的科研图（几百个图元）典型耗时 < 1 s。

矢量后端（sci/vector.py）
------------------------
`sci.vector.VectorCanvas` 与光栅画布接口兼容（canvas.vector is True）。本文件
每个有光栅计算的公开图元都在开头检测 `getattr(c, "vector", False)`：命中时走
矢量分支（`c.line` / `c.polygon` / `c.stroke_polygon` / `c.rect`，抗锯齿交给
SVG/PDF 渲染器），不触碰 buf/cw/ch 的 SDF 光栅算法；未命中时光栅代码**一字未改**。
`band`（直接调 c.polygon）、`text_halo`（走 fonts.draw_text → c.polygons）、
`marker` / `arrow_down` / `arrow_up`（分发到上面已带矢量分支的图元）天然同时
支持两种画布，因此没有额外分支。
"""

import bisect
import math

import raster  # noqa: E402

from .palettes import rgb  # noqa: E402
from . import fonts as _fonts  # noqa: E402


__all__ = [
    # 基础
    "seg", "polyline", "hline", "vline", "rect",
    # 标记
    "circle", "square", "triangle", "diamond", "star", "cross", "plus", "marker",
    # 误差与区间
    "errorbar_v", "errorbar_h", "arrow_down", "arrow_up", "band", "span_band",
    # 文本
    "text_halo",
]

_EPS = 1e-9


# ======================================================================
# 内部工具：颜色 / 覆盖率混合
# ======================================================================

def _rgb(color):
    """颜色归一化成 (r, g, b) int 三元组。"""
    if isinstance(color, (tuple, list)):
        return (int(color[0]), int(color[1]), int(color[2]))
    if isinstance(color, str):
        return rgb(color)
    raise TypeError("颜色必须是 '#RRGGBB' 或 (r,g,b)，收到 %r" % (color,))


def _paint(buf, off, col, a):
    """source-over：把颜色 col 以覆盖率 a 混合到 buf[off:off+3]。"""
    cr, cg, cb = col
    r = buf[off]
    g = buf[off + 1]
    b = buf[off + 2]
    buf[off] = int(r + (cr - r) * a + 0.5)
    buf[off + 1] = int(g + (cg - g) * a + 0.5)
    buf[off + 2] = int(b + (cb - b) * a + 0.5)


# ======================================================================
# 内部光栅化：全部在超采样坐标（浮点）下工作
# ======================================================================

def _seg_ss(c, ax, ay, bx, by, col, hw):
    """抗锯齿线段（旋转矩形 SDF 覆盖率），超采样坐标；hw = 半宽（超采样）。

    端点是平头（butt cap）——折线补角、虚线段端点都由调用方决定。
    逐行解析求出「覆盖率非零的 x 区间」，只遍历该区间，避免斜线的包围盒浪费。
    """
    if hw <= 0.0:
        return
    buf = c.buf
    cw = c.cw
    ch = c.ch
    dx = bx - ax
    dy = by - ay
    L = math.sqrt(dx * dx + dy * dy)
    if L < 1e-9:                       # 退化成点
        _disc_ss(c, ax, ay, hw, col)
        return
    ux = dx / L
    uy = dy / L
    nx = -uy                           # 法向
    ny = ux
    kn = hw + 0.5                      # 法向：覆盖率非零半宽（含 1 超采样像素 AA 带）
    # 世界包围盒（超采样）
    wx0 = min(ax, bx) - kn * abs(nx) - 1.0
    wx1 = max(ax, bx) + kn * abs(nx) + 1.0
    wy0 = min(ay, by) - kn * abs(ny) - 1.0
    wy1 = max(ay, by) + kn * abs(ny) + 1.0
    iy0 = int(math.floor(wy0))
    iy1 = int(math.ceil(wy1))
    ix0 = int(math.floor(wx0))
    ix1 = int(math.ceil(wx1))
    if iy0 < 0:
        iy0 = 0
    if ix0 < 0:
        ix0 = 0
    if iy1 > ch - 1:
        iy1 = ch - 1
    if ix1 > cw - 1:
        ix1 = cw - 1
    if iy1 < iy0 or ix1 < ix0:
        return
    cr, cg, cb = col
    nxa = nx if nx >= 0.0 else -nx
    uxa = ux if ux >= 0.0 else -ux
    hl = L * 0.5
    u_lo = -0.5                        # 切向：|u| <= L + 0.5 之外覆盖率为 0
    u_hi = L + 0.5
    for iy in range(iy0, iy1 + 1):
        ry = iy + 0.5 - ay
        # ---- 法向约束 v ∈ [-kn, kn] → px 区间 ----
        bv = ry * ny
        if nxa > _EPS:
            t0 = (-kn - bv) / nx
            t1 = (kn - bv) / nx
            if t0 > t1:
                t0, t1 = t1, t0
            lo = ax + t0
            hi = ax + t1
        else:
            if bv < -kn or bv > kn:
                continue
            lo = -1e30
            hi = 1e30
        # ---- 切向约束 u ∈ [u_lo, u_hi] → px 区间 ----
        bu = ry * uy
        if uxa > _EPS:
            s0 = (u_lo - bu) / ux
            s1 = (u_hi - bu) / ux
            if s0 > s1:
                s0, s1 = s1, s0
            if ax + s0 > lo:
                lo = ax + s0
            if ax + s1 < hi:
                hi = ax + s1
        else:
            if bu < u_lo or bu > u_hi:
                continue
        ixa = int(math.ceil(lo - 0.5))
        ixb = int(math.floor(hi - 0.5))
        if ixa < ix0:
            ixa = ix0
        if ixb > ix1:
            ixb = ix1
        if ixb < ixa:
            continue
        row = iy * cw * 3
        for ix in range(ixa, ixb + 1):
            rx = ix + 0.5 - ax
            u = rx * ux + ry * uy
            v = rx * nx + ry * ny
            du_abs = u - hl
            if du_abs < 0.0:
                du_abs = -du_abs
            qu = du_abs - hl            # 切向有符号距离
            qv = (v if v >= 0.0 else -v) - hw
            if qu <= -0.5 and qv <= -0.5:
                a = 1.0
            elif qu >= 0.5 or qv >= 0.5:
                continue
            else:
                ex = qu if qu > 0.0 else 0.0
                ey = qv if qv > 0.0 else 0.0
                d = math.sqrt(ex * ex + ey * ey)
                mx = qu if qu > qv else qv
                if mx < 0.0:
                    d += mx
                a = 0.5 - d
                if a <= 0.0:
                    continue
                if a > 1.0:
                    a = 1.0
            off = row + ix * 3
            r0 = buf[off]
            g0 = buf[off + 1]
            b0 = buf[off + 2]
            buf[off] = int(r0 + (cr - r0) * a + 0.5)
            buf[off + 1] = int(g0 + (cg - g0) * a + 0.5)
            buf[off + 2] = int(b0 + (cb - b0) * a + 0.5)


def _disc_ss(c, cx, cy, r, col):
    """抗锯齿实心圆盘（半宽=半径 r，超采样）。内部整段用直写，只有边缘带做混合。"""
    if r <= 0.0:
        return
    buf = c.buf
    cw = c.cw
    ch = c.ch
    R = r + 0.5                         # 覆盖率非零半径
    ix0 = int(math.floor(cx - R))
    ix1 = int(math.ceil(cx + R))
    iy0 = int(math.floor(cy - R))
    iy1 = int(math.ceil(cy + R))
    if ix0 < 0:
        ix0 = 0
    if iy0 < 0:
        iy0 = 0
    if ix1 > cw - 1:
        ix1 = cw - 1
    if iy1 > ch - 1:
        iy1 = ch - 1
    if ix1 < ix0 or iy1 < iy0:
        return
    cr, cg, cb = col
    inner = r - 0.5                     # 该半径内覆盖率 == 1
    for iy in range(iy0, iy1 + 1):
        q = iy + 0.5 - cy
        qq = R * R - q * q
        if qq <= 0.0:
            continue
        span = math.sqrt(qq)
        xa = int(math.floor(cx - span))
        xb = int(math.ceil(cx + span))
        if xa < ix0:
            xa = ix0
        if xb > ix1:
            xb = ix1
        if xb < xa:
            continue
        row = iy * cw * 3
        ia = xa
        ib = xa - 1                     # 默认没有实心段
        if inner > 0.0:
            q2 = inner * inner - q * q
            if q2 > 0.0:
                si = math.sqrt(q2)
                ia = int(math.ceil(cx - si - 0.5))
                ib = int(math.floor(cx + si - 0.5))
                if ia < xa:
                    ia = xa
                if ib > xb:
                    ib = xb
        if ib >= ia:                    # 实心段：直接写色
            seg = bytes(col) * (ib - ia + 1)
            off = row + ia * 3
            buf[off:off + len(seg)] = seg
        # 两侧 AA 渐变带
        for za, zb in ((xa, ia - 1), (ib + 1, xb)):
            for ix in range(za, zb + 1):
                dxp = ix + 0.5 - cx
                d = math.sqrt(dxp * dxp + q * q)
                a = R - d
                if a <= 0.0:
                    continue
                if a > 1.0:
                    a = 1.0
                _paint(buf, row + ix * 3, col, a)


def _ring_ss(c, cx, cy, r, col, hw):
    """抗锯齿圆环：中心线半径 r、半宽 hw（都是超采样）。空心标记的描边/圆点边框用。"""
    if hw <= 0.0 or r < 0.0:
        return
    if r <= hw + 0.5:                   # 环内径为负 —— 退化成一个实心圆
        _disc_ss(c, cx, cy, max(r, hw), col)
        return
    buf = c.buf
    cw = c.cw
    ch = c.ch
    Rout = r + hw + 0.5
    Rin = r - hw - 0.5
    ix0 = int(math.floor(cx - Rout))
    ix1 = int(math.ceil(cx + Rout))
    iy0 = int(math.floor(cy - Rout))
    iy1 = int(math.ceil(cy + Rout))
    if ix0 < 0:
        ix0 = 0
    if iy0 < 0:
        iy0 = 0
    if ix1 > cw - 1:
        ix1 = cw - 1
    if iy1 > ch - 1:
        iy1 = ch - 1
    if ix1 < ix0 or iy1 < iy0:
        return
    for iy in range(iy0, iy1 + 1):
        q = iy + 0.5 - cy
        qo = Rout * Rout - q * q
        if qo <= 0.0:
            continue
        span = math.sqrt(qo)
        si = 0.0
        if Rin > 0.0:
            qi = Rin * Rin - q * q
            if qi > 0.0:
                si = math.sqrt(qi)
        row = iy * cw * 3
        for za, zb in ((cx - span, cx - si), (cx + si, cx + span)):
            xa = int(math.ceil(za - 0.5))
            xb = int(math.floor(zb - 0.5))
            if xa < ix0:
                xa = ix0
            if xb > ix1:
                xb = ix1
            if xb < xa:
                continue
            for ix in range(xa, xb + 1):
                dxp = ix + 0.5 - cx
                d = math.sqrt(dxp * dxp + q * q)
                a = hw + 0.5 - (d - r if d > r else r - d)
                if a <= 0.0:
                    continue
                if a > 1.0:
                    a = 1.0
                _paint(buf, row + ix * 3, col, a)


def _rect_fill_ss(c, ax, ay, bx, by, col):
    """抗锯齿轴对齐矩形填充（可分离覆盖率，数学上精确）。

    速度：实心段用字节切片直写，只有上下各 ~2 行、左右各 ~2 列做逐像素混合，
    和 Canvas.rect 同量级，但边缘是完全平滑的。
    """
    if bx <= ax or by <= ay:
        return
    buf = c.buf
    cw = c.cw
    ch = c.ch
    ia = int(math.floor(ax))
    ib = int(math.ceil(bx)) - 1
    if ia < 0:
        ia = 0
    if ib > cw - 1:
        ib = cw - 1
    if ib < ia:
        return
    cov = []                            # 每列 x 覆盖率
    for ix in range(ia, ib + 1):
        a = (ix + 1.0 if ix + 1.0 < bx else bx) - (float(ix) if float(ix) > ax else ax)
        cov.append(a if a > 0.0 else 0.0)
    full_a = -1
    full_b = -1
    for k, a in enumerate(cov):
        if a >= 0.999:
            if full_a < 0:
                full_a = k
            full_b = k
    ya = int(math.floor(ay))
    yb = int(math.ceil(by)) - 1
    if ya < 0:
        ya = 0
    if yb > ch - 1:
        yb = ch - 1
    if yb < ya:
        return
    n = len(cov)
    for iy in range(ya, yb + 1):
        aly = (iy + 1.0 if iy + 1.0 < by else by) - (float(iy) if float(iy) > ay else ay)
        if aly <= 0.0:
            continue
        row = iy * cw * 3
        if aly >= 0.999:                # 整行 y 全覆盖
            if full_a >= 0:
                x0 = ia + full_a
                x1 = ia + full_b + 1
                if x1 > x0:
                    chunk = bytes(col) * (x1 - x0)
                    off = row + x0 * 3
                    buf[off:off + len(chunk)] = chunk
                for k in range(full_a):
                    a = cov[k]
                    if a > 0.0:
                        _paint(buf, row + (ia + k) * 3, col, a)
                for k in range(full_b + 1, n):
                    a = cov[k]
                    if a > 0.0:
                        _paint(buf, row + (ia + k) * 3, col, a)
            else:
                # 没有整列全覆盖（矩形宽度 < 1 超采样像素，如极细的竖条）：整行逐列混色
                for k in range(n):
                    a = cov[k]
                    if a > 0.0:
                        _paint(buf, row + (ia + k) * 3, col, a)
        else:                           # 上下边缘行：整行逐像素
            for k in range(n):
                a = cov[k] * aly
                if a > 0.0:
                    _paint(buf, row + (ia + k) * 3, col, a)


def _rect_ring_ss(c, ax, ay, bx, by, col, hw):
    """抗锯齿矩形边框（中心线在矩形边界上、半宽 hw，超采样）。四个角是直角。"""
    if hw <= 0.0:
        return
    if bx < ax:
        ax, bx = bx, ax
    if by < ay:
        ay, by = by, ay
    buf = c.buf
    cw = c.cw
    ch = c.ch
    R = hw + 0.5                        # |到边界的有符号距离| < R 时覆盖率非零
    cx = (ax + bx) * 0.5
    cy = (ay + by) * 0.5
    hx = (bx - ax) * 0.5
    hy = (by - ay) * 0.5
    ix0 = int(math.floor(ax - R))
    ix1 = int(math.ceil(bx + R))
    iy0 = int(math.floor(ay - R))
    iy1 = int(math.ceil(by + R))
    if ix0 < 0:
        ix0 = 0
    if iy0 < 0:
        iy0 = 0
    if ix1 > cw - 1:
        ix1 = cw - 1
    if iy1 > ch - 1:
        iy1 = ch - 1
    if ix1 < ix0 or iy1 < iy0:
        return
    for iy in range(iy0, iy1 + 1):
        py = iy + 0.5
        dy = py - cy
        if dy < 0.0:
            dy = -dy
        dy -= hy
        row = iy * cw * 3
        if -R < dy < R:
            # 行落在上下边界的 ±R 带内（含矩形内部靠近上下边的部分）：整行都有候选像素
            ranges = ((ax - R, bx + R),)
        elif dy >= R:
            # 行在矩形上下外部：到最近边界的距离 >= dy >= R，整行覆盖率为 0
            continue
        else:
            # dy <= -R：行在矩形内部深处，只有左右两条边框带有覆盖
            ranges = ((cx - hx - R, cx - hx + R), (cx + hx - R, cx + hx + R))
        for lo, hi in ranges:
            xa = int(math.ceil(lo - 0.5))
            xb = int(math.floor(hi - 0.5))
            if xa < ix0:
                xa = ix0
            if xb > ix1:
                xb = ix1
            if xb < xa:
                continue
            for ix in range(xa, xb + 1):
                dx = ix + 0.5 - cx
                if dx < 0.0:
                    dx = -dx
                dx -= hx
                ex = dx if dx > 0.0 else 0.0
                ey = dy if dy > 0.0 else 0.0
                d = math.sqrt(ex * ex + ey * ey)
                mx = dx if dx > dy else dy
                if mx < 0.0:
                    d += mx
                if d < 0.0:
                    d = -d
                a = R - d
                if a <= 0.0:
                    continue
                if a > 1.0:
                    a = 1.0
                _paint(buf, row + ix * 3, col, a)


def _poly_sd_ss(pts, px, py):
    """点到简单多边形的有符号距离（内部为负），超采样坐标。"""
    n = len(pts)
    d2 = 1e30
    inside = False
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        ex = bx - ax
        ey = by - ay
        wx = px - ax
        wy = py - ay
        ee = ex * ex + ey * ey
        if ee <= 0.0:
            t = 0.0
        else:
            t = (wx * ex + wy * ey) / ee
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
        qx = wx - t * ex
        qy = wy - t * ey
        dd = qx * qx + qy * qy
        if dd < d2:
            d2 = dd
        if (ay > py) != (by > py):
            if px < (bx - ax) * (py - ay) / (by - ay) + ax:
                inside = not inside
    d = math.sqrt(d2)
    return -d if inside else d


def _poly_fill_ss(c, pts, col):
    """抗锯齿填充简单多边形（SDF 覆盖率；凹多边形也正确）。"""
    n = len(pts)
    if n < 3:
        return
    buf = c.buf
    cw = c.cw
    ch = c.ch
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ix0 = int(math.floor(min(xs) - 1.0))
    ix1 = int(math.ceil(max(xs) + 1.0))
    iy0 = int(math.floor(min(ys) - 1.0))
    iy1 = int(math.ceil(max(ys) + 1.0))
    if ix0 < 0:
        ix0 = 0
    if iy0 < 0:
        iy0 = 0
    if ix1 > cw - 1:
        ix1 = cw - 1
    if iy1 > ch - 1:
        iy1 = ch - 1
    if ix1 < ix0 or iy1 < iy0:
        return
    for iy in range(iy0, iy1 + 1):
        py = iy + 0.5
        row = iy * cw * 3
        for ix in range(ix0, ix1 + 1):
            d = _poly_sd_ss(pts, ix + 0.5, py)
            a = 0.5 - d
            if a <= 0.0:
                continue
            if a > 1.0:
                a = 1.0
            _paint(buf, row + ix * 3, col, a)


def _poly_stroke_ss(c, pts, col, hw):
    """抗锯齿多边形描边（中心线在多边形边界上、半宽 hw，超采样）。"""
    n = len(pts)
    if n < 3 or hw <= 0.0:
        return
    buf = c.buf
    cw = c.cw
    ch = c.ch
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    R = hw + 0.5
    ix0 = int(math.floor(min(xs) - R))
    ix1 = int(math.ceil(max(xs) + R))
    iy0 = int(math.floor(min(ys) - R))
    iy1 = int(math.ceil(max(ys) + R))
    if ix0 < 0:
        ix0 = 0
    if iy0 < 0:
        iy0 = 0
    if ix1 > cw - 1:
        ix1 = cw - 1
    if iy1 > ch - 1:
        iy1 = ch - 1
    if ix1 < ix0 or iy1 < iy0:
        return
    for iy in range(iy0, iy1 + 1):
        py = iy + 0.5
        row = iy * cw * 3
        for ix in range(ix0, ix1 + 1):
            d = _poly_sd_ss(pts, ix + 0.5, py)
            if d < 0.0:
                d = -d
            a = R - d
            if a <= 0.0:
                continue
            if a > 1.0:
                a = 1.0
            _paint(buf, row + ix * 3, col, a)


def _marker_vec(c, pts, fill, edge, ew):
    """多边形标记的矢量版（与 _marker_poly 语义一致，填充 + 可选描边）。"""
    if fill is not None:
        c.polygon(pts, fill)
    if edge is not None and ew > 0.0:
        c.stroke_polygon(pts, edge, ew)


def _marker_poly(c, pts, fill, edge, ew):
    """多边形标记的「填充 + 可选描边」。pts 为逻辑坐标。

    实心（edge is None）：只填充；空心（edge 有值）：先填充（通常是白色）再描边，
    所以内部是真的空，不会被背景线透过来。
    """
    ss = c.ss
    pts_ss = [(x * ss, y * ss) for (x, y) in pts]
    if fill is not None:
        _poly_fill_ss(c, pts_ss, _rgb(fill))
    if edge is not None:
        _poly_stroke_ss(c, pts_ss, _rgb(edge), max(ew, 0.0) * ss * 0.5)


# ======================================================================
# 基础图元
# ======================================================================

def seg(c, x0, y0, x1, y1, color, w):
    """直线段。w 为逻辑像素线宽（可以 <1）。任意角度都是 SDF 抗锯齿，无阶梯。

    矢量画布（canvas.vector）：直接描边，抗锯齿交给 SVG/PDF 渲染器。
    """
    if getattr(c, "vector", False):
        if w > 0.0:
            c.line(x0, y0, x1, y1, color, w)
        return
    _seg_ss(c, x0 * c.ss, y0 * c.ss, x1 * c.ss, y1 * c.ss,
            _rgb(color), max(w, 0.0) * c.ss * 0.5)


def polyline(c, pts, color, w, dash=None):
    """折线。

    dash=None 画实线；dash=(on, off) 画虚线（单位逻辑像素，按**弧长**切分）。
    每个内部顶点补一个「直径 = 线宽」的实心圆，消除相邻段之间的白缝。
    虚线段跨顶点时，在顶点处同样补圆（保证虚线拐角连续）。

    矢量画布：整条折线一个 path 描边，内部顶点由 linejoin 连接（天然无白缝），
    dash 交给后端的 dash 数组（同样按弧长切分）。
    """
    if getattr(c, "vector", False):
        if w > 0.0 and pts is not None and len(pts) >= 2:
            c.polyline(pts, color, w, dash=dash)
        return
    if w <= 0.0 or pts is None or len(pts) < 2:
        return
    col = _rgb(color)
    ss = c.ss
    hw = w * ss * 0.5
    n = len(pts)
    if dash is None:
        for i in range(n - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            _seg_ss(c, x0 * ss, y0 * ss, x1 * ss, y1 * ss, col, hw)
        # 内部顶点补圆（两端保持平头，线条自然结束）
        for i in range(1, n - 1):
            x, y = pts[i]
            _disc_ss(c, x * ss, y * ss, hw, col)
        return

    # ---------------- 虚线：按弧长切分 ----------------
    try:
        on = float(dash[0])
        off = float(dash[1])
    except (TypeError, IndexError, ValueError):
        raise ValueError("dash 必须是 (on, off) 数值二元组，收到 %r" % (dash,))
    if on <= 0.0:
        return
    if off < 0.0:
        off = 0.0
    seglens = []
    total = 0.0
    for i in range(n - 1):
        L = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        seglens.append(L)
        total += L
    if total <= 0.0:
        return
    cum = [0.0]
    for L in seglens:
        cum.append(cum[-1] + L)
    period = on + off
    if period <= 0.0:
        return
    # 生成 on 区间（弧长参数）。上限防止病态参数（极短 dash + 超长线）爆内存。
    max_intervals = 20000
    intervals = []
    t = 0.0
    while t < total and len(intervals) < max_intervals:
        intervals.append((t, t + on if t + on < total else total))
        t += period
    nseg = n - 1
    for s, e in intervals:
        j = bisect.bisect_right(cum, s) - 1
        if j < 0:
            j = 0
        elif j > nseg - 1:
            j = nseg - 1
        first = True
        while j < nseg and cum[j] < e:
            L = seglens[j]
            if L > 0.0:
                a0 = s - cum[j]
                if a0 < 0.0:
                    a0 = 0.0
                a1 = e - cum[j]
                if a1 > L:
                    a1 = L
                if a1 > a0:
                    p0 = pts[j]
                    p1 = pts[j + 1]
                    t0 = a0 / L
                    t1 = a1 / L
                    x0 = p0[0] + (p1[0] - p0[0]) * t0
                    y0 = p0[1] + (p1[1] - p0[1]) * t0
                    x1 = p0[0] + (p1[0] - p0[0]) * t1
                    y1 = p0[1] + (p1[1] - p0[1]) * t1
                    _seg_ss(c, x0 * ss, y0 * ss, x1 * ss, y1 * ss, col, hw)
                    if not first:        # 跨顶点：补圆消缝
                        _disc_ss(c, x0 * ss, y0 * ss, hw, col)
                    first = False
            j += 1


def hline(c, x0, x1, y, color, w):
    """水平线段（相同抗锯齿与端帽处理）。"""
    if getattr(c, "vector", False):
        if x1 < x0:
            x0, x1 = x1, x0
        if w > 0.0:
            c.line(x0, y, x1, y, color, w)
        return
    if x1 < x0:
        x0, x1 = x1, x0
    _seg_ss(c, x0 * c.ss, y * c.ss, x1 * c.ss, y * c.ss, _rgb(color), max(w, 0.0) * c.ss * 0.5)


def vline(c, x, y0, y1, color, w):
    """竖直线段。"""
    if getattr(c, "vector", False):
        if y1 < y0:
            y0, y1 = y1, y0
        if w > 0.0:
            c.line(x, y0, x, y1, color, w)
        return
    if y1 < y0:
        y0, y1 = y1, y0
    _seg_ss(c, x * c.ss, y0 * c.ss, x * c.ss, y1 * c.ss, _rgb(color), max(w, 0.0) * c.ss * 0.5)


def rect(c, x0, y0, x1, y1, fill, edge=None, ew=0.9):
    """矩形。fill=None 表示不填充；edge 非 None 时画抗锯齿边框（ew 为边框线宽）。"""
    if getattr(c, "vector", False):
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        if fill is not None:
            c.rect(x0, y0, x1, y1, fill)
        if edge is not None and ew > 0.0:
            c.stroke_polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], edge, ew)
        return
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    ss = c.ss
    if fill is not None:
        _rect_fill_ss(c, x0 * ss, y0 * ss, x1 * ss, y1 * ss, _rgb(fill))
    if edge is not None and ew > 0.0:
        _rect_ring_ss(c, x0 * ss, y0 * ss, x1 * ss, y1 * ss, _rgb(edge), ew * ss * 0.5)


# ======================================================================
# 标记（markers）
# ======================================================================
#
# 约定（与 matplotlib 观感一致）：
#   r       —— 标记的「半径」：circle 的圆半径、square 的半边长、diamond 的半对角、
#              triangle 的外接圆半径、star 的外半径、cross/plus 的臂长。
#   fill    —— 填充色；None 表示不填充。
#   edge    —— 描边色；None 表示实心（只填充）。非 None 时为空心标记：
#              先填充 fill（通常是白色/浅色）再描边，内部是真正空的。

def _circle_pts(cx, cy, r):
    """圆形的矢量近似：按半径自适应段数（r=6px 时 37 边形，矢高 < 0.03 px）。"""
    n = int(min(72, max(16, math.ceil(r * 4.0) + 12)))
    step = 2.0 * math.pi / n
    return [(cx + r * math.cos(k * step), cy + r * math.sin(k * step)) for k in range(n)]


def circle(c, cx, cy, r, fill, edge=None, ew=0.9, sides=26):
    """圆形标记。

    `sides` 仅为接口兼容保留：内部用解析圆 SDF 光栅化（比 26 边形更圆、无棱角）。
    矢量画布：多边形近似填充 + 描边（段数按半径自适应，300dpi 下矢高 < 0.03 px）。
    """
    if getattr(c, "vector", False):
        if r <= 0.0:
            return
        pts = _circle_pts(cx, cy, r)
        if fill is not None:
            c.polygon(pts, fill)
        if edge is not None and ew > 0.0:
            c.stroke_polygon(pts, edge, ew)
        return
    if r <= 0.0:
        return
    ss = c.ss
    if fill is not None:
        _disc_ss(c, cx * ss, cy * ss, r * ss, _rgb(fill))
    if edge is not None and ew > 0.0:
        _ring_ss(c, cx * ss, cy * ss, r * ss, _rgb(edge), ew * ss * 0.5)


def square(c, cx, cy, r, fill, edge=None, ew=0.9):
    """方形标记（半边长 r）。"""
    if getattr(c, "vector", False):
        if r <= 0.0:
            return
        pts = [(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
        if fill is not None:
            c.polygon(pts, fill)
        if edge is not None and ew > 0.0:
            c.stroke_polygon(pts, edge, ew)
        return
    if r <= 0.0:
        return
    ss = c.ss
    if fill is not None:
        _rect_fill_ss(c, (cx - r) * ss, (cy - r) * ss, (cx + r) * ss, (cy + r) * ss, _rgb(fill))
    if edge is not None and ew > 0.0:
        _rect_ring_ss(c, (cx - r) * ss, (cy - r) * ss, (cx + r) * ss, (cy + r) * ss,
                      _rgb(edge), ew * ss * 0.5)


def triangle(c, cx, cy, r, fill, edge=None, ew=0.9, direction="up"):
    """等边三角形标记（外接圆半径 r，形心在 (cx, cy)）。direction: up/down/left/right。"""
    if r <= 0.0:
        return
    base = {"up": -90.0, "down": 90.0, "left": 180.0, "right": 0.0}.get(direction, -90.0)
    a0 = math.radians(base)
    pts = []
    for k in range(3):
        ang = a0 + k * (2.0 * math.pi / 3.0)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    if getattr(c, "vector", False):
        _marker_vec(c, pts, fill, edge, ew)
        return
    _marker_poly(c, pts, fill, edge, ew)


def diamond(c, cx, cy, r, fill, edge=None, ew=0.9):
    """菱形标记（半对角 r）。"""
    if r <= 0.0:
        return
    pts = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    if getattr(c, "vector", False):
        _marker_vec(c, pts, fill, edge, ew)
        return
    _marker_poly(c, pts, fill, edge, ew)


def star(c, cx, cy, r, fill, edge=None, ew=0.9, npoints=5):
    """星形标记（外半径 r，内半径比 0.382 —— 与 matplotlib '*' 一致）。"""
    if r <= 0.0 or npoints < 3:
        return
    inner = r * 0.382
    pts = []
    step = math.pi / npoints
    a0 = -math.pi / 2.0
    for k in range(npoints * 2):
        ang = a0 + k * step
        rr = r if (k & 1) == 0 else inner
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    if getattr(c, "vector", False):
        _marker_vec(c, pts, fill, edge, ew)
        return
    _marker_poly(c, pts, fill, edge, ew)


def cross(c, cx, cy, r, color, w=1.0):
    """× 号标记（两臂长 r，线宽 w）。"""
    if getattr(c, "vector", False):
        if r <= 0.0 or w <= 0.0:
            return
        d = r * 0.7071067811865476
        c.line(cx - d, cy - d, cx + d, cy + d, color, w)
        c.line(cx - d, cy + d, cx + d, cy - d, color, w)
        return
    if r <= 0.0 or w <= 0.0:
        return
    col = _rgb(color)
    ss = c.ss
    hw = w * ss * 0.5
    d = r * 0.7071067811865476
    _seg_ss(c, (cx - d) * ss, (cy - d) * ss, (cx + d) * ss, (cy + d) * ss, col, hw)
    _seg_ss(c, (cx - d) * ss, (cy + d) * ss, (cx + d) * ss, (cy - d) * ss, col, hw)


def plus(c, cx, cy, r, color, w=1.0):
    """+ 号标记（两臂长 r，线宽 w）。"""
    if getattr(c, "vector", False):
        if r <= 0.0 or w <= 0.0:
            return
        c.line(cx - r, cy, cx + r, cy, color, w)
        c.line(cx, cy - r, cx, cy + r, color, w)
        return
    if r <= 0.0 or w <= 0.0:
        return
    col = _rgb(color)
    ss = c.ss
    hw = w * ss * 0.5
    _seg_ss(c, (cx - r) * ss, cy * ss, (cx + r) * ss, cy * ss, col, hw)
    _seg_ss(c, cx * ss, (cy - r) * ss, cx * ss, (cy + r) * ss, col, hw)


_MARKER_ALIAS = {
    "o": "circle", "circle": "circle", "dot": "circle",
    "s": "square", "square": "square",
    "triangle": "triangle", "^": "triangle", "v": "triangle", "<": "triangle", ">": "triangle",
    "d": "diamond", "diamond": "diamond",
    "*": "star", "star": "star",
    "x": "cross", "cross": "cross", "×": "cross",
    "+": "plus", "plus": "plus",
    "none": "none", "": "none", "null": "none",
}


def marker(c, kind, cx, cy, r, fill, edge=None, ew=0.9, direction="up"):
    """标记分发：circle/square/triangle/diamond/star/cross/plus（另接受 matplotlib 单字符别名）。

    cross / plus 没有「面积」，其颜色取 edge（空心意图）或 fill，线宽取 ew。
    """
    key = (kind or "circle")
    key = key.lower() if isinstance(key, str) else str(key)
    key = _MARKER_ALIAS.get(key)
    if key is None:
        raise ValueError("未知 marker kind=%r（可用：circle/square/triangle/diamond/star/cross/plus）"
                         % (kind,))
    if key == "none":
        return
    if key == "cross":
        cross(c, cx, cy, r, edge if edge is not None else fill,
              w=ew if edge is not None else max(ew, 1.0))
    elif key == "plus":
        plus(c, cx, cy, r, edge if edge is not None else fill,
             w=ew if edge is not None else max(ew, 1.0))
    elif key == "triangle":
        d = direction
        if isinstance(kind, str):
            d = {"^": "up", "v": "down", "<": "left", ">": "right"}.get(kind.strip(), direction)
        triangle(c, cx, cy, r, fill, edge=edge, ew=ew, direction=d)
    elif key == "circle":
        circle(c, cx, cy, r, fill, edge=edge, ew=ew)
    elif key == "square":
        square(c, cx, cy, r, fill, edge=edge, ew=ew)
    elif key == "diamond":
        diamond(c, cx, cy, r, fill, edge=edge, ew=ew)
    elif key == "star":
        star(c, cx, cy, r, fill, edge=edge, ew=ew)


# ======================================================================
# 误差棒 / 箭头 / 区间（科研图必需）
# ======================================================================

def errorbar_v(c, x, y_lo, y_hi, color, w=0.9, cap=2.4):
    """竖直误差棒 + 上下横帽。y_lo/y_hi 是像素坐标（会自动排序）。cap 是帽的半宽。"""
    if getattr(c, "vector", False):
        if y_hi < y_lo:
            y_lo, y_hi = y_hi, y_lo
        if w <= 0.0:
            return
        c.line(x, y_lo, x, y_hi, color, w)
        if cap > 0.0:
            c.line(x - cap, y_lo, x + cap, y_lo, color, w)
            c.line(x - cap, y_hi, x + cap, y_hi, color, w)
        return
    if y_hi < y_lo:
        y_lo, y_hi = y_hi, y_lo
    col = _rgb(color)
    ss = c.ss
    hw = max(w, 0.0) * ss * 0.5
    _seg_ss(c, x * ss, y_lo * ss, x * ss, y_hi * ss, col, hw)
    if cap > 0.0:
        _seg_ss(c, (x - cap) * ss, y_lo * ss, (x + cap) * ss, y_lo * ss, col, hw)
        _seg_ss(c, (x - cap) * ss, y_hi * ss, (x + cap) * ss, y_hi * ss, col, hw)


def errorbar_h(c, y, x_lo, x_hi, color, w=0.9, cap=2.4):
    """水平误差棒 + 左右竖帽。cap 是帽的半高。"""
    if getattr(c, "vector", False):
        if x_hi < x_lo:
            x_lo, x_hi = x_hi, x_lo
        if w <= 0.0:
            return
        c.line(x_lo, y, x_hi, y, color, w)
        if cap > 0.0:
            c.line(x_lo, y - cap, x_lo, y + cap, color, w)
            c.line(x_hi, y - cap, x_hi, y + cap, color, w)
        return
    if x_hi < x_lo:
        x_lo, x_hi = x_hi, x_lo
    col = _rgb(color)
    ss = c.ss
    hw = max(w, 0.0) * ss * 0.5
    _seg_ss(c, x_lo * ss, y * ss, x_hi * ss, y * ss, col, hw)
    if cap > 0.0:
        _seg_ss(c, x_lo * ss, (y - cap) * ss, x_lo * ss, (y + cap) * ss, col, hw)
        _seg_ss(c, x_hi * ss, (y - cap) * ss, x_hi * ss, (y + cap) * ss, col, hw)


def _arrow(c, x, y, color, size, up):
    """实心三角箭头：(x, y) 是**尖端**，size 是箭头长度，底边宽 0.9*size。

    矢量画布：三角形直接填充（arrow_down / arrow_up 共用本函数）。
    """
    if size <= 0.0:
        return
    half = size * 0.45
    if up:
        pts = [(x, y), (x - half, y + size), (x + half, y + size)]
    else:
        pts = [(x, y), (x - half, y - size), (x + half, y - size)]
    if getattr(c, "vector", False):
        c.polygon(pts, color)
        return
    ss = c.ss
    _poly_fill_ss(c, [(px * ss, py * ss) for (px, py) in pts], _rgb(color))


def arrow_down(c, x, y, color, size=9):
    """向下的实心三角箭头（天文 3σ 上限标记）：尖端在 (x, y)。"""
    _arrow(c, x, y, color, size, up=False)


def arrow_up(c, x, y, color, size=9):
    """向上的实心三角箭头：尖端在 (x, y)。"""
    _arrow(c, x, y, color, size, up=True)


def band(c, xs, y_lo, y_hi, color, alpha=None):
    """置信带：上沿沿 y_lo（左→右），下沿沿 y_hi（右→左）拼成一个闭合多边形填充。

    大块填充走 Canvas.polygon（2× 超采样已足够平滑，且比 SDF 快一个量级）。
    半透明色请用 palettes.mix() 预先混好。
    """
    n = len(xs)
    if n < 2 or len(y_lo) != n or len(y_hi) != n:
        return
    pts = [(xs[i], y_lo[i]) for i in range(n)]
    pts.extend((xs[i], y_hi[i]) for i in range(n - 1, -1, -1))
    c.polygon(pts, _rgb(color))


def span_band(c, x0, x1, y_lo, y_hi, color):
    """矩形阴影区（标注观测窗口 / 入凌出凌等）。"""
    if getattr(c, "vector", False):
        if x1 < x0:
            x0, x1 = x1, x0
        if y_hi < y_lo:
            y_lo, y_hi = y_hi, y_lo
        c.rect(x0, y_lo, x1, y_hi, color)
        return
    if x1 < x0:
        x0, x1 = x1, x0
    if y_hi < y_lo:
        y_lo, y_hi = y_hi, y_lo
    ss = c.ss
    _rect_fill_ss(c, x0 * ss, y_lo * ss, x1 * ss, y_hi * ss, _rgb(color))


# ======================================================================
# 文本
# ======================================================================

def text_halo(c, s, x, y, size, color, align="left", halo=(255, 255, 255), r=1.6):
    """带描边的文字（数据点密集处 / 深色背景上的标注）。

    y 是**基线**（与 sci.fonts.draw_text 一致）。用 8 向偏移模拟描边：
    先画 8 个白色副本，再画正文，形成一圈浅色光晕。
    返回正文结束处的 x。
    """
    if not s:
        return x
    halo_col = _rgb(halo)
    body_col = _rgb(color)
    step = math.pi / 4.0
    for k in range(8):
        ang = k * step
        _fonts.draw_text(c, s, x + r * math.cos(ang), y + r * math.sin(ang),
                         size, halo_col, align=align)
    return _fonts.draw_text(c, s, x, y, size, body_col, align=align)


# ---- 半透明填充（依赖新引擎的 blend_polygon；旧画布自动退化） ----

def band_alpha(c, xs, y_lo, y_hi, color, alpha=0.25):
    """半透明置信带：在支持的画布上用真 alpha 混合，否则退回预混色。

    xs / y_lo / y_hi 都是等长的像素坐标列表。
    """
    if not xs or len(xs) < 2:
        return
    poly = [(x, y) for x, y in zip(xs, y_lo)]
    poly += [(x, y) for x, y in reversed(list(zip(xs, y_hi)))]
    blend = getattr(c, "blend_polygon", None)
    if blend is not None:
        blend(poly, color, alpha)
    else:
        from sci import palettes
        c.polygon(poly, palettes.mix(color, f=alpha))
