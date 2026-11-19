# -*- coding: utf-8 -*-
"""sci/fonts.py — 字体回退链、文本度量与绘制。

为什么不用 raster.Canvas.text：
  1. 它只支持单字体，科研图必须跨字体回退（数学符号/中文/希腊字母不在同一字体）
  2. 它内部 TTFont(path, fontNumber=0)，对 .ttc 会拿到日文 face（NotoSansCJK face 0 = JP）
  3. 它的 text_width 需要 Canvas 实例，排版阶段只要度量、还没画布

字体链（全部 sans-serif，符合 Nature/Science 对无衬线字体的偏好）：
  Noto Sans Math（拉丁/希腊/数学/花体，19/19 运算符号）
  → Noto Sans CJK SC face 2（中文 + 兜底）
  → DejaVu Math TeX Gyre（♃ 等罕见天文符号）
"""
import glob
import os
import sys

import raster  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.pens.recordingPen import DecomposingRecordingPen  # noqa: E402


# --------------------------------------------------------------------------
# 字体发现：环境变量 SCI_FONT_DIR + 常见系统字体目录
# --------------------------------------------------------------------------
def _font_dirs():
    dirs = []
    env = os.environ.get("SCI_FONT_DIR") or ""
    for p in env.split(os.pathsep):
        if p:
            dirs.append(p)
    dirs += [
        "/system/fonts",
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.expanduser("~/.local/share/fonts"),
        os.path.expanduser("~/.fonts"),
        "/Library/Fonts",
        "/System/Library/Fonts",
        os.path.expanduser("~/Library/Fonts"),
        "C:\\Windows\\Fonts",
    ]
    out = []
    for d in dirs:
        if d and os.path.isdir(d) and d not in out:
            out.append(d)
    return out


_FOUND = {}


def find_font(*names):
    """按候选文件名在字体目录里查找，返回第一个存在的路径或 None。"""
    key = names
    if key in _FOUND:
        return _FOUND[key]
    dirs = _font_dirs()
    for name in names:
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                _FOUND[key] = p
                return p
    # 字体通常放在发行版/子目录里（如 /usr/share/fonts/truetype/noto/）
    for name in names:
        for d in dirs:
            for p in glob.glob(os.path.join(d, "**", name), recursive=True):
                if os.path.isfile(p):
                    _FOUND[key] = p
                    return p
    _FOUND[key] = None
    return None


def _cjk_face(path):
    """NotoSansCJK-*.ttc 的 face 2 才是简体中文；OTF 单字重文件用 face 0。"""
    if not path:
        return 0
    base = os.path.basename(path).lower()
    return 2 if base.endswith(".ttc") and "notosanscjk" in base else 0


FONT_MATH = find_font("NotoSansMath-Regular.ttf", "DejaVuMathTeXGyre.ttf")
FONT_CJK = find_font("NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf",
                     "NotoSansCJK-Regular.otf", "NotoSansSC-Regular.otf",
                     "SourceHanSansSC-Regular.otf", "wqy-zenhei.ttc")
FONT_FALLBACK = find_font("DejaVuMathTeXGyre.ttf", "DejaVuSans.ttf")
FONT_BOLD = find_font("NotoSansCJKsc-Bold.otf", "NotoSansCJK-Bold.ttc",
                      "NotoSans-Bold.ttf", "FZHeiT-SC-Bold.ttf",
                      "DejaVuSans-Bold.ttf")

CJK_FACE = _cjk_face(FONT_CJK)
CHAIN = tuple((p, n) for p, n in ((FONT_MATH, 0),
                                  (FONT_CJK, CJK_FACE),
                                  (FONT_FALLBACK, 0)) if p)

_FONTS = {}


def _font(path, num=0):
    if not path:
        raise RuntimeError(
            "找不到可用字体：请安装 Noto Sans Math / Noto Sans CJK，"
            "或用环境变量 SCI_FONT_DIR 指向字体目录。")
    key = (path, num)
    if key not in _FONTS:
        f = TTFont(path, fontNumber=num, lazy=True)
        _FONTS[key] = (f, f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm)
    return _FONTS[key]


def pick_font(ch, bold=False):
    """返回 (path, fontNumber)：按回退链找第一个含该字符的字体。"""
    if bold and FONT_BOLD:
        f = _font(FONT_BOLD)
        if ord(ch) in f[2]:
            return (FONT_BOLD, 0)
    for cand in CHAIN:
        if ord(ch) in _font(*cand)[2]:
            return cand
    if not CHAIN:
        _font(None)          # 抛出带指引的 RuntimeError
    return CHAIN[0]


def _contours(font, glyphs, glyph_name, size, ox, baseline):
    """提取字形轮廓，返回 [[(x,y)...]]（像素坐标，y 已向下翻转）。

    用 DecomposingRecordingPen 而不是 RecordingPen：Noto Sans Math 里 `i`/`j`
    是复合字形（composite glyph，由若干组件拼成），RecordingPen 只会记录
    addComponent 而不展开，导致轮廓为空、字母整个不显示。DecomposingRecordingPen
    会自动递归展开组件。这是「T me」「Magn tude」缺 i 的根因。
    """
    pen = DecomposingRecordingPen(glyphs)
    glyphs[glyph_name].draw(pen)
    scale = size / font["head"].unitsPerEm
    contours, cur = [], []
    for op, args in pen.value:
        if op == "moveTo":
            if len(cur) > 2:
                contours.append(cur)
            cur = [args[0]]
        elif op == "lineTo":
            cur.append(args[0])
        elif op == "qCurveTo":
            pts = list(args)
            closed = bool(pts) and pts[-1] is None
            if closed:
                pts = pts[:-1]
            prev = cur[-1] if cur else (0, 0)
            for i, ctrl in enumerate(pts[:-1]):
                if i + 1 < len(pts) - 1:
                    nxt = ((ctrl[0] + pts[i + 1][0]) / 2.0, (ctrl[1] + pts[i + 1][1]) / 2.0)
                else:
                    nxt = pts[-1] if not closed else cur[0]
                cur.extend(raster._quadratic(prev, ctrl, nxt))
                prev = nxt
        elif op == "curveTo":
            prev = cur[-1] if cur else (0, 0)
            c1, c2, p1 = args[-3], args[-2], args[-1]
            for i in range(1, 17):
                t = i / 16
                mt = 1 - t
                cur.append((
                    mt ** 3 * prev[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p1[0],
                    mt ** 3 * prev[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p1[1],
                ))
            prev = p1
        elif op == "closePath":
            if len(cur) > 2:
                contours.append(cur)
            cur = []
    if len(cur) > 2:
        contours.append(cur)
    return [[(ox + x * scale, baseline - y * scale) for (x, y) in con] for con in contours]


def _glyph(c, ch, x, baseline_y, size, color, path, num):
    f, glyphs, cmap, upm = _font(path, num)
    name = cmap.get(ord(ch))
    if name is None:
        return
    contours = _contours(f, glyphs, name, size, x, baseline_y)
    if contours:
        c.polygons(contours, color)


def char_width(ch, size, bold=False):
    path, num = pick_font(ch, bold)
    f, glyphs, cmap, upm = _font(path, num)
    name = cmap.get(ord(ch))
    if name is None:
        return size * 0.5
    return glyphs[name].width * size / upm


def text_width(s, size, bold=False):
    return sum(char_width(ch, size, bold) for ch in s)


def draw_text(c, s, x, baseline_y, size, color, align="left", bold=False):
    """按字体回退链分段绘制，返回结束 x。"""
    if align == "center":
        x -= text_width(s, size, bold) / 2.0
    elif align == "right":
        x -= text_width(s, size, bold)
    cx = x
    for ch in s:
        path, num = pick_font(ch, bold)
        if bold and path != FONT_BOLD:
            # 无粗体字面的字符：微偏移叠加模拟加粗
            for dx in (-size * 0.022, 0.0, size * 0.022):
                _glyph(c, ch, cx + dx, baseline_y, size, color, path, num)
        else:
            _glyph(c, ch, cx, baseline_y, size, color, path, num)
        cx += char_width(ch, size, bold)
    return cx


def rotated_text(c, s, cx, cy, size, color, bold=False):
    """以 (cx,cy) 为中心逆时针旋转 90° 的文本（用于 y 轴标题）。

    逐个字形旋转：把字形轮廓以包围盒中心为原点旋转 (x,y)->(y,-x) 后平移到目标位置。
    """
    total = text_width(s, size, bold)
    y = cy + total / 2.0
    for ch in s:
        path, num = pick_font(ch, bold)
        w = char_width(ch, size, bold)
        polys = _rot_glyph(ch, size, path, num)
        if polys:
            xs = [p[0] for poly in polys for p in poly]
            ys = [p[1] for poly in polys for p in poly]
            xc, yc = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
            out = []
            for poly in polys:
                out.append([(cx + (gy - yc), (y - w / 2.0) - (gx - xc)) for (gx, gy) in poly])
            c.polygons(out, color)
        y -= w * 1.08


def draw_rotated_char(c, ch, cx, cy, size, color, bold=False):
    """单个字形逆时针 90° 绘制，中心落在 (cx, cy)。mathtext 旋转文本用。"""
    path, num = pick_font(ch, bold)
    polys = _rot_glyph(ch, size, path, num)
    if not polys:
        return
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    xc, yc = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    out = []
    for poly in polys:
        out.append([(cx + (gy - yc), cy - (gx - xc)) for (gx, gy) in poly])
    c.polygons(out, color)


_ROTCACHE = {}


def _rot_glyph(ch, size, path, num):
    key = (ch, round(size, 3), path, num)
    if key in _ROTCACHE:
        return _ROTCACHE[key]
    f, glyphs, cmap, upm = _font(path, num)
    name = cmap.get(ord(ch))
    polys = []
    if name is not None:
        # _glyph_polys 返回像素坐标（y 已向下翻转）
        for con in _contours(f, glyphs, name, size, 0.0, 0.0):
            polys.append([(gx, gy) for (gx, gy) in con])
    _ROTCACHE[key] = polys
    return polys


def glyph_exists(ch):
    return pick_font(ch) is not None
