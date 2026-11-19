# -*- coding: utf-8 -*-
"""sci/contour.py — 纯 Python 等高线（marching squares）。

为什么不用 matplotlib / scipy：不依赖 numpy，也没有 C 扩展，只能自己算。
marching squares 是标准的等值线提取算法：把网格每个格子按「四个角与阈值的
大小关系」编码成 0-15，再查表得到穿过该格的线段，最后把线段连成折线。

对外接口：
    segments(xs, ys, z, level)  -> [((x0,y0),(x1,y1)), ...]  数据坐标
    lines(xs, ys, z, levels)    -> [(level, [ [ (x,y), ... ], ... ]), ...]
                                  把线段串成折线，便于一次 polyline 画完
"""

# 四种角：0=左下 1=右下 2=右上 3=左上；边：0=下 1=右 2=上 3=左
# 查表：case -> [(edge_a, edge_b), ...]
_TABLE = {
    1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 5: [(3, 2), (0, 1)],
    6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)], 9: [(2, 0)], 10: [(0, 3), (1, 2)],
    11: [(2, 1)], 12: [(1, 3)], 13: [(1, 0)], 14: [(0, 3)], 15: [],
}


def _interp(p0, p1, v0, v1, level):
    """在 p0-p1 边上线性插值出 level 等值点的位置。"""
    d = v1 - v0
    if abs(d) < 1e-30:
        t = 0.5
    else:
        t = (level - v0) / d
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)


def segments(xs, ys, z, level):
    """返回一组线段 [( (x0,y0), (x1,y1) ), ...]，坐标为数据坐标。"""
    ny, nx = len(ys), len(xs)
    segs = []
    for j in range(ny - 1):
        z0row, z1row = z[j], z[j + 1]
        y0, y1 = ys[j], ys[j + 1]
        for i in range(nx - 1):
            x0, x1 = xs[i], xs[i + 1]
            v = (z0row[i], z0row[i + 1], z1row[i + 1], z1row[i])
            case = 0
            if v[0] > level:
                case |= 1
            if v[1] > level:
                case |= 2
            if v[2] > level:
                case |= 4
            if v[3] > level:
                case |= 8
            edges = _TABLE.get(case)
            if not edges:
                continue
            # 边交点（惰性计算）
            pts = {}
            for a, b in edges:
                for e in (a, b):
                    if e in pts:
                        continue
                    if e == 0:
                        pts[e] = _interp((x0, y0), (x1, y0), v[0], v[1], level)
                    elif e == 1:
                        pts[e] = _interp((x1, y0), (x1, y1), v[1], v[2], level)
                    elif e == 2:
                        pts[e] = _interp((x1, y1), (x0, y1), v[2], v[3], level)
                    else:
                        pts[e] = _interp((x0, y1), (x0, y0), v[3], v[0], level)
                segs.append((pts[a], pts[b]))
    return segs


def _chain(segs, tol=1e-9):
    """把无序线段串成折线。用端点哈希（四舍五入到 tol）连通。"""
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    adj = {}
    for idx, (a, b) in enumerate(segs):
        adj.setdefault(key(a), []).append(idx)
        adj.setdefault(key(b), []).append(idx)
    used = [False] * len(segs)
    out = []
    for seed in range(len(segs)):
        if used[seed]:
            continue
        used[seed] = True
        a, b = segs[seed]
        poly = [a, b]
        # 向两端延伸
        for end in (1, 0):
            while True:
                cur = poly[-1] if end == 1 else poly[0]
                k = key(cur)
                nxt = None
                for idx in adj.get(k, ()):
                    if used[idx]:
                        continue
                    p0, p1 = segs[idx]
                    if key(p0) == k:
                        nxt = (idx, p1)
                        break
                    if key(p1) == k:
                        nxt = (idx, p0)
                        break
                if nxt is None:
                    break
                used[nxt[0]] = True
                if end == 1:
                    poly.append(nxt[1])
                else:
                    poly.insert(0, nxt[1])
        if len(poly) >= 2:
            out.append(poly)
    return out


def lines(xs, ys, z, levels):
    """返回 [(level, [折线 [[(x,y)...], ...]]), ...]。"""
    res = []
    for lv in levels:
        segs = segments(xs, ys, z, lv)
        res.append((lv, _chain(segs)))
    return res


# ---------------------------------------------------------------- 自动等值

def auto_levels(z, n=6, lo=None, hi=None):
    """给一组自动的等值线阈值（nice numbers）。"""
    flat = [v for row in z for v in row if v is not None]
    if not flat:
        return []
    lo = min(flat) if lo is None else lo
    hi = max(flat) if hi is None else hi
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(n, 1)
    mag = 10.0 ** _floor_log10(raw)
    step = mag * 10.0
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag * 1.0001:
            step = m * mag
            break
    import math
    start = math.ceil(lo / step - 1e-9) * step
    out, v = [], start
    while v <= hi + step * 1e-6:
        out.append(round(v, 12))
        v += step
    return out


def _floor_log10(v):
    import math
    if v <= 0:
        return 0.0
    return math.floor(math.log10(v))
