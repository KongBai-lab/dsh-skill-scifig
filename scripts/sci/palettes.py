# -*- coding: utf-8 -*-
"""sci/palettes.py — 色盲友好与感知均匀色板。

规范依据（见 SKILL.md）：
  - 分类色板默认 Okabe-Ito（Nature 官方图表指南给出的 8 色）
  - 连续量默认 viridis；色盲关键场景 cividis
  - 禁用 jet / rainbow（亮度非单调，转灰度丢信息）
"""

OKABE_ITO = {
    "black": "#000000",
    "orange": "#E69F00",
    "skyblue": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
}

OKABE_ORDER = ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
               "#E69F00", "#56B4E9", "#000000", "#F0E442"]

# viridis 控制点（感知均匀，matplotlib 同源）
_VIRIDIS = [
    (0.00, (0.267, 0.005, 0.329)), (0.14, (0.283, 0.141, 0.458)),
    (0.29, (0.254, 0.265, 0.530)), (0.43, (0.207, 0.372, 0.553)),
    (0.57, (0.164, 0.471, 0.558)), (0.71, (0.128, 0.567, 0.551)),
    (0.86, (0.135, 0.659, 0.518)), (1.00, (0.993, 0.906, 0.144)),
]

# cividis 控制点（红绿色盲优化、亮度线性）
_CIVIDIS = [
    (0.00, (0.000, 0.135, 0.305)), (0.17, (0.055, 0.243, 0.427)),
    (0.33, (0.180, 0.349, 0.494)), (0.50, (0.357, 0.443, 0.510)),
    (0.67, (0.545, 0.537, 0.510)), (0.83, (0.749, 0.639, 0.467)),
    (1.00, (0.996, 0.847, 0.267)),
]

CMAPS = {"viridis": _VIRIDIS, "cividis": _CIVIDIS}

BAD_CMAPS = {"jet", "rainbow", "hsv", "gist_rainbow"}


def rgb(h):
    """'#RRGGBB' / 'RRGGBB' / (r,g,b) -> (r,g,b)。"""
    if isinstance(h, (tuple, list)):
        return tuple(int(v) for v in h[:3])
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def hexstr(c):
    if isinstance(c, str):
        return c if c.startswith("#") else "#" + c
    return "#%02X%02X%02X" % tuple(c[:3])


def _interp(ctrl, t):
    t = min(max(t, 0.0), 1.0)
    for k in range(len(ctrl) - 1):
        a, ca = ctrl[k]
        b, cb = ctrl[k + 1]
        if a <= t <= b:
            f = (t - a) / (b - a) if b > a else 0.0
            return tuple(int(round(255 * (ca[i] + (cb[i] - ca[i]) * f))) for i in range(3))
    return tuple(int(round(255 * v)) for v in ctrl[-1][1])


_LUT_CACHE = {}


def lut(name, n=256):
    """色板查找表：返回 n 个 (r,g,b)。热图逐格取色时比 colormap() 快数倍。"""
    key = (name, n)
    if key not in _LUT_CACHE:
        _LUT_CACHE[key] = [colormap(name, i / (n - 1.0)) for i in range(n)]
    return _LUT_CACHE[key]


def colormap(name, t):
    """连续色板取色：t∈[0,1] -> (r,g,b)。"""
    if name in BAD_CMAPS:
        raise ValueError("色板 %r 不推荐（亮度非单调，色盲不友好）；改用 viridis/cividis" % name)
    ctrl = CMAPS.get(name)
    if ctrl is None:
        raise ValueError("未知色板 %r（可用：%s）" % (name, ", ".join(CMAPS)))
    return _interp(ctrl, t)


def palette(name="okabe"):
    """分类色板：返回 hex 列表。"""
    if name in ("okabe", "okabe-ito", "okabe_ito"):
        return list(OKABE_ORDER)
    if name.startswith("#"):
        return [name]
    raise ValueError("未知分类色板 %r" % name)


def series_color(idx, name="okabe"):
    p = palette(name)
    return p[idx % len(p)]


def mix(color, bg=(255, 255, 255), f=0.25):
    """把颜色按比例混到背景色——光栅器无 alpha 通道时模拟半透明。"""
    c = rgb(color)
    return tuple(int(round(c[i] * f + bg[i] * (1 - f))) for i in range(3))


def is_red_green_pair(pal):
    """判断色板里是否出现「纯红 + 纯绿」并置（Science/Nature 明确避免）。

    阈值要点：绿判定必须同时要求蓝通道低，否则 Okabe-Ito 的蓝 #0072B2
    (0,114,178) 会因为 g=114 被误判成绿色，产生假警报。
    蓝绿 #009E73 (0,158,115) 同理不计入——它是有意设计的色盲友好色。
    """
    reds, greens = 0, 0
    for h in pal:
        r, g, b = rgb(h)
        if r > 140 and g < 100 and b < 100:
            reds += 1
        if g > 130 and r < 100 and b < 100:
            greens += 1
    return reds > 0 and greens > 0
