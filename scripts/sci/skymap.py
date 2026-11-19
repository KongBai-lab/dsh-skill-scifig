# -*- coding: utf-8 -*-
"""sci/skymap.py — 天球投影天图（sinusoidal / mollweide / rect）。

把 (RA, Dec) 投影到平面并画散点：天文巡天、银河系/宇宙学天图的常用图种。
不依赖 numpy / matplotlib / pyproj，投影公式、网格、边界全部纯 Python 手算。

三种投影（都按"全天空 = 宽 2 : 高 1"归一化，x、y 用同一比例，等面积不变形）：
  sinusoidal  等面积正弦投影（Sanson–Flamsteed）
              x = Δλ·cosφ,  y = φ               （Δλ 为相对中心 RA 的经度差）
  mollweide   等面积椭圆投影
              x = (2√2/π)·Δλ·cosθ,  y = √2·sinθ，其中 2θ+sin2θ = π·sinφ
  rect        等距圆柱（plate carrée，矩形）
              x = Δλ,  y = φ
统一归一化到全天空 X∈[-1,1]、Y∈[-0.5,0.5]：
  sinusoidal / rect 除以 π；mollweide 除以 2√2 后再乘 √2，
  即 X = Δλ·cosθ/π、Y = sinθ/2。三者全天空边界分别为尖角透镜、椭圆、矩形。

天文惯例：RA 轴反向（RA 增大方向向左），由 Axes(invert_x=True) 完成。
网格：赤经/赤纬网格默认每 30° 一条（grid_step 可改），并叠画银道面 (b=0)
虚线参考线（J2000 赤道⇄银道坐标变换，参数 galactic_equator 可关）。

用法：
    from sci.skymap import skymap_figure
    skymap_figure(ra, dec, values=mag, projection="mollweide",
                  out="skymap.png", cmap="cividis")
"""
import math

from . import palettes, primitives, style as stylemod  # noqa: E402
from sciplot import Figure  # noqa: E402

_INK = (0, 0, 0)
_GRID = (170, 170, 170)        # 普通经纬网格
_GRID_EQ = (85, 85, 85)        # 赤道线加深一档
_D2R = math.pi / 180.0

# 赤道坐标（J2000）里的两个基准方向：银心 (l=0,b=0) 与北银极 (b=90)
_GC_RA, _GC_DEC = 266.40510, -28.936175
_NGP_RA, _NGP_DEC = 192.85948, 27.12825
_GAL_COL = (120, 120, 120)     # 银道面 (b=0) 参考线

# 画布边距（mm）：左侧放 Dec 刻度标签 + 轴标题，下方放 RA 刻度 + 轴标题
_MARGIN_L, _MARGIN_T, _MARGIN_B = 13.2, 2.5, 11.0
_MARGIN_R_CB = 24.0            # 有 colorbar 时右侧让出的空间（与 sciplot 约定一致）
_MARGIN_R = 3.0


# ---------------------------------------------------------------- 角度工具

def _wrap_pm180(a):
    """角度归一到 [-180, 180)。"""
    a = math.fmod(float(a) + 180.0, 360.0)
    if a < 0.0:
        a += 360.0
    return a - 180.0


def _ra_span(ra_range):
    """RA 区间 -> (起点, 起点+跨度)。支持跨 0° 的区间（如 (300, 60)）。"""
    lo = float(ra_range[0])
    span = (float(ra_range[1]) - lo) % 360.0
    if span < 1e-9:
        span = 360.0
    return lo, lo + span


def _grid_values(spec, lo, hi):
    """把 grid_step 的一项解析成网格线角度列表。

    spec 支持：
      None / 数字  -> 用该步长（默认 30°）铺满 [lo, hi]
      等差序列     -> 取公差作步长、首值作锚点，向两侧铺满 [lo, hi]
    因此默认参数 ((0, 30, 60), (-30, 0, 30)) 会展开成每 30° 一条的网格，
    而不是只画 3 条线。
    """
    if spec is None:
        step, base = 30.0, 0.0
    elif isinstance(spec, (int, float)):
        step, base = float(spec), 0.0
    else:
        vals = sorted(float(v) for v in spec)
        if not vals:
            step, base = 30.0, 0.0
        elif len(vals) == 1:
            step, base = 30.0, vals[0]
        else:
            diffs = [b - a for a, b in zip(vals, vals[1:]) if b - a > 1e-9]
            step = min(diffs) if diffs else 30.0
            base = vals[0]
    if step <= 1e-9:
        step = 30.0
    k = int(math.ceil((lo - base) / step - 1e-9))
    out = []
    v = base + k * step
    while v <= hi + 1e-9:
        out.append(v)
        k += 1
        v = base + k * step
    return out


def _fmt_angle(v):
    """角度标签：0° / 30° / −30°（负号用真正的减号 U+2212）。"""
    a = abs(v)
    s = ("%d" % round(a)) if abs(a - round(a)) < 1e-6 else ("%g" % round(a, 1))
    return ("\u2212" + s if v < -1e-9 else s) + "\u00b0"


# ---------------------------------------------------------------- 投影

def _mollweide_theta(phi):
    """解 Mollweide 辅助角：2θ + sin2θ = π·sinφ（牛顿迭代，±π/2 收敛）。"""
    target = math.pi * math.sin(phi)
    th = phi
    for _ in range(24):
        f = 2.0 * th + math.sin(2.0 * th) - target
        fp = 2.0 + 2.0 * math.cos(2.0 * th)
        if abs(fp) < 1e-12:
            break
        d = f / fp
        th -= d
        if abs(d) < 1e-13:
            break
    half_pi = math.pi * 0.5
    if th > half_pi:
        th = half_pi
    elif th < -half_pi:
        th = -half_pi
    return th


def _xy(dlam_deg, dec_deg, projection):
    """(经度差 Δλ, 赤纬) -> 归一化平面坐标。

    全天空时 X∈[-1,1]、Y∈[-0.5,0.5]；x、y 缩放比例相同（等面积不变形）。
    """
    lam = dlam_deg * _D2R
    phi = dec_deg * _D2R
    if projection == "sinusoidal":
        return lam * math.cos(phi) / math.pi, phi / math.pi
    if projection == "mollweide":
        th = _mollweide_theta(phi)
        # 由 x=(2√2/π)Δλcosθ、y=√2sinθ 同除 2√2 归一化
        return lam * math.cos(th) / math.pi, math.sin(th) * 0.5
    # rect：等距圆柱
    return lam / math.pi, phi / math.pi


def _meridian_xy(dlam_deg, dec_lo, dec_hi, projection, n=97):
    """一条经线：固定 Δλ，dec 从 dec_lo 扫到 dec_hi。"""
    if n < 2:
        n = 2
    return [_xy(dlam_deg, dec_lo + (dec_hi - dec_lo) * i / float(n - 1), projection)
            for i in range(n)]


def _parallel_xy(dec_deg, span, projection, n=181):
    """一条纬线：固定 dec，Δλ 从 -span/2 扫到 +span/2。"""
    if n < 2:
        n = 2
    return [_xy(-span * 0.5 + span * i / float(n - 1), dec_deg, projection)
            for i in range(n)]


def _boundary_xy(span, dec_lo, dec_hi, projection, n=121):
    """天区边界：上/下两条纬线 + 左右两条经线，闭合成环（用于画轮廓）。"""
    top = [_xy(-span * 0.5 + span * i / float(n - 1), dec_hi, projection) for i in range(n)]
    right = [_xy(span * 0.5, dec_hi - (dec_hi - dec_lo) * i / float(n - 1), projection)
             for i in range(n)]
    bottom = [_xy(span * 0.5 - span * i / float(n - 1), dec_lo, projection) for i in range(n)]
    left = [_xy(-span * 0.5, dec_lo + (dec_hi - dec_lo) * i / float(n - 1), projection)
            for i in range(n)]
    out = []
    for p in top + right + bottom + left:
        if out and abs(out[-1][0] - p[0]) < 1e-12 and abs(out[-1][1] - p[1]) < 1e-12:
            continue
        out.append(p)
    if out and (abs(out[0][0] - out[-1][0]) > 1e-12
                or abs(out[0][1] - out[-1][1]) > 1e-12):
        out.append(out[0])
    return out


# ---------------------------------------------------------------- 绘制

def _unit_vec(ra_deg, dec_deg):
    """赤道坐标 (RA, Dec) -> 单位向量。"""
    r = ra_deg * _D2R
    d = dec_deg * _D2R
    return (math.cos(d) * math.cos(r), math.cos(d) * math.sin(r), math.sin(d))


def _galactic_basis():
    """银道坐标系在赤道系里的三个基向量（J2000）。

    x = 银心方向 (l=0, b=0)，z = 北银极 (b=90)，y = z×x（即 l=90 方向）。
    用 z×x 而不是 x×z：这样 l=90° 落在赤经约 318°、赤纬约 +48°，
    与 IAU 银道坐标系一致（l=180° 的银心反方向在 RA 5h45m、Dec +29°）。
    """
    z = _unit_vec(_NGP_RA, _NGP_DEC)
    x = _unit_vec(_GC_RA, _GC_DEC)
    y = (z[1] * x[2] - z[2] * x[1],
         z[2] * x[0] - z[0] * x[2],
         z[0] * x[1] - z[1] * x[0])
    return x, y, z


_GAL_X, _GAL_Y, _GAL_Z = _galactic_basis()


def _galactic_to_eq(l_deg, b_deg):
    """银道坐标 (l, b) -> 赤道坐标 (RA, Dec)，单位度（J2000）。"""
    l = l_deg * _D2R
    b = b_deg * _D2R
    cb = math.cos(b)
    cl = cb * math.cos(l)
    sl = cb * math.sin(l)
    sb = math.sin(b)
    vx = cl * _GAL_X[0] + sl * _GAL_Y[0] + sb * _GAL_Z[0]
    vy = cl * _GAL_X[1] + sl * _GAL_Y[1] + sb * _GAL_Z[1]
    vz = cl * _GAL_X[2] + sl * _GAL_Y[2] + sb * _GAL_Z[2]
    ra = math.degrees(math.atan2(vy, vx)) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, vz))))
    return ra, dec


def _galactic_plane_segments(center, span, dec_lo, dec_hi, n=361):
    """银道面 (b=0) 的 (Δλ, Dec) 采样，按 RA 接缝/天区边界切成若干段。

    1° 采样足以让断口（贴到边界处）看不出来；段必须断开的地方：
      · 跨过 RA=0/360 接缝（Δλ 从 +180 跳到 −180）
      · 走出 RA 范围或 Dec 范围（否则会用一条弦横穿图内区域）
    """
    segs, cur = [], []
    for i in range(n):
        ra, dec = _galactic_to_eq(360.0 * i / float(n - 1), 0.0)
        dlam = _wrap_pm180(ra - center)
        inside = (abs(dlam) <= span * 0.5 + 1e-9
                  and dec_lo - 1e-9 <= dec <= dec_hi + 1e-9)
        if not inside:
            if len(cur) > 1:
                segs.append(cur)
            cur = []
            continue
        if cur and abs(dlam - cur[-1][0]) > 90.0:
            # 跨接缝：Δλ 从 +180 跳到 −180，必须断开，
            # 否则会在地图顶部/底部拉出一条横贯全图的假直线。
            if len(cur) > 1:
                segs.append(cur)
            cur = []
        cur.append((dlam, dec))
    if len(cur) > 1:
        segs.append(cur)
    return segs


def _draw_galactic_plane(ax, projection, center, span, dec_lo, dec_hi, dpi):
    """银道面 (b=0) 参考线：虚线，便于把天区与银河系结构对上。"""
    c = ax.canvas
    lw = max(0.8, stylemod.pt2px(0.4, dpi))
    for seg in _galactic_plane_segments(center, span, dec_lo, dec_hi):
        pts = [_xy(dlam, dec, projection) for (dlam, dec) in seg]
        primitives.polyline(c, [(ax.px(x), ax.py(y)) for (x, y) in pts],
                            _GAL_COL, lw, dash=(3.0, 2.2))


def _draw_grid(ax, projection, center, span, dec_lo, dec_hi,
               ra_grid, dec_grid, dpi):
    """赤经/赤纬网格：经线 + 纬线，赤道线加深。"""
    c = ax.canvas
    lw = max(1.0, stylemod.pt2px(0.35, dpi))

    for ra_v in ra_grid:
        dlam = _wrap_pm180(ra_v - center)
        if abs(abs(dlam) - span * 0.5) < 1e-6:
            continue                     # 与天区边界重合，由边界线负责
        pts = _meridian_xy(dlam, dec_lo, dec_hi, projection)
        primitives.polyline(c, [(ax.px(x), ax.py(y)) for (x, y) in pts], _GRID, lw)

    for dec_v in dec_grid:
        pts = _parallel_xy(dec_v, span, projection)
        is_eq = abs(dec_v) < 1e-9
        col = _GRID_EQ if is_eq else _GRID
        primitives.polyline(c, [(ax.px(x), ax.py(y)) for (x, y) in pts],
                            col, lw * (1.45 if is_eq else 1.0))


def _clip_outside(ax, bpts):
    """把天区边界外的散点/线头裁掉（光栅器没有 clip_path，用 even-odd 填白模拟）。

    做法：把「坐标框」与「边界」两个闭合轮廓合并做 even-odd 填充——两者之间
    的环带被涂白，边界内的数据完好。之后必须重画边界线。
    """
    c = ax.canvas
    x0, y0, x1, y1 = ax.box
    pad = 2.0
    frame = [(x0 - pad, y0 - pad), (x1 + pad, y0 - pad),
             (x1 + pad, y1 + pad), (x0 - pad, y1 + pad)]
    inner = [(ax.px(x), ax.py(y)) for (x, y) in bpts]
    c.polygons([frame, inner], (255, 255, 255))


def _draw_points(ax, ra, dec, values, projection, center, span,
                 dec_lo, dec_hi, cmap, vmin, vmax, dpi):
    """散点：values 给定时按 colormap 着色；返回实际色标范围 (vmin, vmax) 或 None。"""
    c = ax.canvas
    box = ax.box
    n = len(ra)
    if n <= 220:
        ms_pt = 2.6
    elif n <= 800:
        ms_pt = 2.0
    else:
        ms_pt = 1.4
    radius = stylemod.pt2px(ms_pt, dpi) / 2.0
    ew = max(0.6, stylemod.pt2px(0.25, dpi))

    lo = hi = None
    if values is not None:
        lo = min(values) if vmin is None else float(vmin)
        hi = max(values) if vmax is None else float(vmax)
        if not (hi > lo):
            hi = lo + 1e-12
    span_v = (hi - lo) if values is not None else 1.0

    for i in range(n):
        dlam = _wrap_pm180(ra[i] - center)
        if abs(dlam) > span * 0.5 + 1e-9:
            continue                      # 不在 RA 范围内
        if dec[i] < dec_lo - 1e-9 or dec[i] > dec_hi + 1e-9:
            continue                      # 不在 Dec 范围内
        x, y = _xy(dlam, dec[i], projection)
        px, py = ax.px(x), ax.py(y)
        if px < box[0] or px > box[2] or py < box[1] or py > box[3]:
            continue
        if values is not None:
            fill = palettes.colormap(cmap, (values[i] - lo) / span_v)
        else:
            fill = palettes.rgb("#0072B2")
        edge = palettes.mix(fill, bg=(0, 0, 0), f=0.55) if radius >= 2.0 else None
        primitives.marker(c, "circle", px, py, radius, fill, edge=edge, ew=ew)
    return (lo, hi) if values is not None else None


# ---------------------------------------------------------------- 对外接口

def skymap_figure(ra, dec, values=None, fig=None, profile="nature",
                  size="single", out="skymap.png", backend="raster",
                  projection="sinusoidal",
                  cmap="cividis", vmin=None, vmax=None,
                  ra_range=(0, 360), dec_range=(-90, 90),
                  grid_step=((0, 30, 60), (-30, 0, 30)),
                  cb_label="Value (a.u.)", galactic_equator=True):
    """天球投影天图：把 (RA, Dec) 画成散点，可选按第三维 values 着色并配色标。

    参数
      ra, dec     : 天球坐标（度）。RA 任意值都会归一到 0–360。
      values      : 可选第三维（如星等/流量/速度），给定后按 cmap 着色并画 colorbar。
      backend     : 输出后端 "raster"（PNG，默认）| "svg" | "pdf"——透传给 Figure；
                    fig 给定时该参数被忽略（用 fig 自己的后端）
      projection  : "sinusoidal"（等面积正弦）| "mollweide"（等面积椭圆）| "rect"（矩形）
      ra_range    : RA 范围（度），支持跨 0° 的区间；RA 轴反向（东在左）。
      dec_range   : Dec 范围（度），必须在 [-90, 90] 内。
      grid_step   : 经纬网格线，两项分别对应 RA / Dec：
                    传等差序列（公差即步长）或直接传步长数字；None 用 30°。
                    默认 ((0,30,60), (-30,0,30)) 会展开成每 30° 一条的网格。
      cb_label    : values 给定时的色标标题（应写「物理量 (单位)」）。
      galactic_equator : 是否叠画银道面 (b=0) 虚线参考线（J2000 坐标变换）。

    返回 Figure。全天空图的边界：sinusoidal 尖角透镜、mollweide 椭圆、rect 矩形。
    """
    projection = str(projection).lower()
    if projection not in ("sinusoidal", "mollweide", "rect"):
        raise ValueError("projection 只支持 sinusoidal / mollweide / rect，收到 %r"
                         % (projection,))

    ra = [float(v) % 360.0 for v in ra]
    dec = [float(v) for v in dec]
    if len(ra) != len(dec):
        raise ValueError("ra 与 dec 长度必须一致（%d vs %d）" % (len(ra), len(dec)))
    if not ra:
        raise ValueError("ra/dec 不能为空")
    for d in dec:
        if d < -90.0 or d > 90.0:
            raise ValueError("dec 必须在 [-90, 90] 度内，收到 %r" % (d,))
    if values is not None:
        values = [float(v) for v in values]
        if len(values) != len(ra):
            raise ValueError("values 长度必须与 ra 一致（%d vs %d）"
                             % (len(values), len(ra)))
    if not isinstance(grid_step, (tuple, list)):
        grid_step = (grid_step, grid_step)
    if len(grid_step) < 2:
        raise ValueError("grid_step 必须是 (RA 规格, Dec 规格) 二元组")

    ra_lo, ra_hi_x = _ra_span(ra_range)
    span = ra_hi_x - ra_lo
    center = (ra_lo + span * 0.5) % 360.0
    dec_lo, dec_hi = sorted((float(dec_range[0]), float(dec_range[1])))
    if dec_lo < -90.0 or dec_hi > 90.0:
        raise ValueError("dec_range 必须在 [-90, 90] 内")

    # ---- 网格角度（RA 先按范围取，再归一去重）----
    dec_grid = _grid_values(grid_step[1], dec_lo, dec_hi)
    ra_grid = []
    seen = set()
    for v in _grid_values(grid_step[0], ra_lo, ra_hi_x + 1e-9):
        key = round(v % 360.0, 6)
        if key in seen:
            continue
        seen.add(key)
        ra_grid.append(key)

    # ---- 边界与坐标范围（按投影后的真实极值，留 1.5% 余量）----
    bpts = _boundary_xy(span, dec_lo, dec_hi, projection)
    xs = [p[0] for p in bpts]
    ys = [p[1] for p in bpts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    pad = 0.015 * max(xmax - xmin, ymax - ymin) or 0.01
    xlim = (xmin - pad, xmax + pad)
    ylim = (ymin - pad, ymax + pad)
    xspan = xlim[1] - xlim[0]
    yspan = ylim[1] - ylim[0]

    # ---- 画布 ----
    has_cb = values is not None
    m_r = _MARGIN_R_CB if has_cb else _MARGIN_R
    if fig is None:
        st = stylemod.get(profile)
        base_mm = st["double_mm"] if size in ("double", "two") else st["single_mm"]
        map_w = base_mm - _MARGIN_L - m_r
        map_h = map_w * yspan / xspan
        fig = Figure(profile=profile, size=size,
                     height_mm=_MARGIN_T + _MARGIN_B + map_h,
                     backend=backend)
    dpi = fig.dpi

    aw = fig.width_mm - _MARGIN_L - m_r
    ah = fig.height_mm - _MARGIN_T - _MARGIN_B
    map_w = min(aw, ah * xspan / yspan)
    map_h = map_w * yspan / xspan
    x0 = _MARGIN_L + (aw - map_w) * 0.5
    y0 = _MARGIN_T + (ah - map_h) * 0.5
    ax = fig.axes_in_mm((x0, y0, x0 + map_w, y0 + map_h), xlim, ylim,
                        xlabel="RA (\u00b0)", ylabel="Dec (\u00b0)",
                        invert_x=True)

    # ---- 刻度（只标网格线位置；RA 标签取赤道处 x，Dec 标签取 y）----
    dec_ref = 0.0
    if dec_lo > 0.0:
        dec_ref = dec_lo
    elif dec_hi < 0.0:
        dec_ref = dec_hi
    xitems = []
    for ra_v in ra_grid:
        dlam = _wrap_pm180(ra_v - center)
        if abs(abs(dlam) - span * 0.5) < 1e-6:
            continue                      # 边界处的经线不标，避免标签压边
        xitems.append((_xy(dlam, dec_ref, projection)[0], _fmt_angle(ra_v)))
    xitems.sort(key=lambda t: t[0])
    if len(xitems) > 7:
        xitems = xitems[::2]
    ax.set_xticks(major=xitems)

    yitems = []
    for dec_v in dec_grid:
        yy = _xy(0.0, dec_v, projection)[1]
        if ylim[0] <= yy <= ylim[1]:
            yitems.append((yy, _fmt_angle(dec_v)))
    yitems.sort(key=lambda t: t[0])
    if len(yitems) > 7:
        yitems = yitems[::2]
    ax.set_yticks(major=yitems)

    # ---- 内容：网格 -> 银道面 -> 散点 -> 裁掉边界外 -> 边界 -> 坐标轴 -> 色标 ----
    _draw_grid(ax, projection, center, span, dec_lo, dec_hi,
               ra_grid, dec_grid, dpi)
    if galactic_equator:
        _draw_galactic_plane(ax, projection, center, span, dec_lo, dec_hi, dpi)
    vrange = _draw_points(ax, ra, dec, values, projection, center, span,
                          dec_lo, dec_hi, cmap, vmin, vmax, dpi)
    _clip_outside(ax, bpts)
    primitives.polyline(fig.canvas, [(ax.px(x), ax.py(y)) for (x, y) in bpts],
                        _INK, stylemod.pt2px(0.6, dpi))
    ax.draw()
    if vrange is not None:
        fig.colorbar(ax, cmap=cmap, vmin=vrange[0], vmax=vrange[1], label=cb_label)

    fig.set_cmap(cmap)
    if out:
        fig.save(out)
    return fig


__all__ = ["skymap_figure"]
