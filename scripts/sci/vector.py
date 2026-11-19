# -*- coding: utf-8 -*-
"""sci/vector.py — 矢量画布：SVG 1.1 + PDF 1.4（纯标准库 + fontTools）。

背景
----
raster.Canvas 是纯 Python 光栅器（bytearray 像素缓冲 + 2× 超采样 + zlib PNG），
sci/primitives.py 更是在它的超采样缓冲上直接写 SDF 覆盖率做抗锯齿。
本模块提供「接口兼容」的矢量画布 VectorCanvas：sci.axes / sci.mathtext /
sci.fonts / sciplot 一行不改，就能把同一张图输出成真正的矢量图。

接口兼容范围
------------
  raster.Canvas                 VectorCanvas
  ----------------------------  -------------------------------------------
  w / h / ss / cw / ch          w / h / ss(=1) / cw / ch（同名属性，ss 无意义）
  rect / polygon / polygons     rect / polygon / polygons（填充，even-odd）
  line                          line（描边线段）
  text / text_width             text / text_width（字形轮廓转路径）
  png(path)                     save_svg(path) / save_pdf(path)

附加方法（矢量后端专用，primitives 的矢量分支使用）：
  polyline(pts, color, width, dash=None)        折线描边（dash 交给后端 dash 数组）
  stroke_polygon(pts, color, width, dash=None)  闭合多边形描边（空心标记的边框）

坐标与物理尺寸（二选一，本模块采用「画布尺寸 = 逻辑像素 @ dpi」）
----------------------------------------------------------------
* 与 raster.Canvas 完全一致：逻辑像素、y 轴向下、原点在左上角；布图代码零改动。
* 物理尺寸由 dpi 换算（默认 300，与 sci/style.py 的 profile 一致）：
    width_pt = w_px / dpi * 72
    width_mm = w_px / dpi * 25.4
  Figure 的 W/H 是逻辑像素，直接复用即可，调用方不需要自己换算。
* SVG：width/height 用 mm，viewBox="0 0 w h"——用户单位就是逻辑像素，
  路径坐标不缩放，只量化到 3 位小数（省体积且没有 300dpi 的换算舍入误差）。
* PDF：MediaBox 用 pt；内容流开头用 `cm` 把逻辑像素映射到 pt 并翻转 y 轴：
  [s 0 0 -s 0 H_pt]，s = 72/dpi。此后所有路径坐标仍按逻辑像素书写。

文字
----
全部转路径：字形轮廓来自 sci.fonts._contours（DecomposingRecordingPen，已展开
复合字形，支持拉丁/希腊/中文/数学符号），因此 SVG 在没装 Noto 的机器上字形也
不会变，PDF 不需要任何字体对象。

体积控制
--------
1. 坐标统一量化到 3 位小数并去掉无意义尾零；
2. 字形轮廓做 Douglas-Peucker 简化（容差 0.02 逻辑像素 ≈ 0.0017 mm @300dpi，
   肉眼不可见）：_contours 每段二次贝塞尔离散成 16 段，冗余点可砍掉 70%+；
3. PDF 内容流用 zlib 压缩（FlateDecode）；
4. 纯填充矩形（背景/热图格子/色标条）走 SVG `<rect>`、PDF `re`，不写成 path。

注意：VectorCanvas 没有像素缓冲（无 buf），sci/primitives 检测到
`canvas.vector is True` 后走矢量分支，绝不触碰光栅字段。
"""

import math
import os
import zlib

from . import fonts as _fonts  # noqa: E402
from .palettes import rgb as _palette_rgb  # noqa: E402


__all__ = ["VectorCanvas"]

_DEFAULT_DPI = 300
_TEXT_EPS = 0.02        # 字形轮廓简化容差（逻辑像素），见模块 docstring「体积控制」


# ======================================================================
# 数值 / 颜色工具
# ======================================================================

def _f(v):
    """坐标/尺寸格式化：保留 3 位小数，去掉无意义尾零（控制文件体积）。"""
    s = "%.3f" % v
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("", "-0"):
        return "0"
    return s


def _rgb(color):
    """颜色归一化成 (r, g, b) int 三元组（接受 '#RRGGBB' / 'RRGGBB' / (r,g,b)）。"""
    if isinstance(color, (tuple, list)):
        vals = [int(round(float(v))) for v in color[:3]]
        if len(vals) < 3:
            raise TypeError("颜色三元组不足 3 个分量：%r" % (color,))
    elif isinstance(color, str):
        return _palette_rgb(color)
    else:
        raise TypeError("颜色必须是 '#RRGGBB' 或 (r,g,b)，收到 %r" % (color,))
    return tuple(0 if v < 0 else (255 if v > 255 else v) for v in vals)


def _hex(color):
    """颜色 -> '#RRGGBB'（大写，与科学图表色板写法一致）。"""
    r, g, b = _rgb(color)
    return "#%02X%02X%02X" % (r, g, b)


def _simplify(pts, eps=_TEXT_EPS):
    """折线 Douglas-Peucker 简化（端点保留，偏差 <= eps 逻辑像素）。

    只用于字形轮廓：TrueType 二次贝塞尔在 fonts._contours 里被离散成 16 段，
    点的密度远超 300dpi 所需；按 0.02 px 容差简化后轮廓偏差 < 0.0017 mm，
    肉眼与打印都不可见，但点数通常只剩 20%~30%。
    """
    n = len(pts)
    if n < 3 or eps <= 0.0:
        return list(pts)
    if n > 4000:        # 字形轮廓远小于该阈值；超大折线不做 O(n^2) 简化
        return list(pts)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if l2 <= 0.0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / l2
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, bi = d, i
        if best > eps:
            keep[bi] = True
            stack.append((a, bi))
            stack.append((bi, b))
    return [pts[i] for i in range(n) if keep[i]]


# ======================================================================
# VectorCanvas
# ======================================================================

class VectorCanvas:
    """与 raster.Canvas 接口兼容的矢量画布，供现有绘图代码直接使用。

    参数
      w, h : 逻辑像素尺寸（与 raster.Canvas 相同语义；由 dpi 换算成物理尺寸）
      bg   : 背景色（默认白）——构造时记录一个铺满画布的矩形
      dpi  : 输出分辨率，仅用于 px ↔ pt/mm 换算（默认 300）

    输出格式由 save_svg / save_pdf 决定：同一个画布对象可以两种格式各存一份。
    """

    # 关键标志：sci/primitives 检测到它就走矢量分支（不碰 buf/cw/ch 的光栅算法）
    vector = True

    def __init__(self, w, h, bg=(255, 255, 255), dpi=_DEFAULT_DPI):
        self.w = int(round(w))
        self.h = int(round(h))
        if self.w <= 0 or self.h <= 0:
            raise ValueError("VectorCanvas 尺寸必须为正：(%r, %r)" % (w, h))
        self.dpi = float(dpi)
        if self.dpi <= 0:
            raise ValueError("dpi 必须为正：%r" % (dpi,))
        # 与 raster.Canvas 同名属性：矢量没有超采样概念，ss 恒为 1；
        # cw/ch 保留是为了「属性兼容」（primitives 的矢量分支不会用到它们）。
        self.ss = 1
        self.cw = self.w
        self.ch = self.h
        self.bg = bg
        self._ops = []          # 绘制操作列表，save_svg/save_pdf 时才序列化
        if bg is not None:
            self.rect(0, 0, self.w, self.h, bg)

    # ------------------------------------------------------------ 基础图元

    def rect(self, x0, y0, x1, y1, color):
        """填充矩形（逻辑坐标，自动排序；SVG 用 <rect>，PDF 用 re 算子）。"""
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        if x1 <= x0 or y1 <= y0:
            return
        self._ops.append(("R", float(x0), float(y0), float(x1), float(y1), _hex(color)))

    def polygon(self, pts, color):
        """填充简单多边形（even-odd 规则，与 raster.Canvas.polygon 的扫描线一致）。"""
        if pts is None or len(pts) < 3:
            return
        self._ops.append(("P", [list(pts)], _hex(color), None, 0.0,
                          True, None, True))

    def polygons(self, contours, color):
        """多轮廓 even-odd 填充——字形孔洞靠这个挖出来（与 raster.Canvas 语义一致）。"""
        if not contours:
            return
        cons = []
        for con in contours:
            if con is None or len(con) < 3:
                continue
            cons.append(_simplify(con, _TEXT_EPS))
        if not cons:
            return
        self._ops.append(("P", cons, _hex(color), None, 0.0,
                          True, None, True))

    def line(self, x0, y0, x1, y1, color, width=1.0):
        """线段描边（平头端帽，与 raster.Canvas.line 的四边形一致）。"""
        if width is None or width <= 0.0:
            return
        if x0 == x1 and y0 == y1:       # 退化点：与 raster.Canvas.line 一样画成小方块
            hw = width * 0.5
            self.rect(x0 - hw, y0 - hw, x0 + hw, y0 + hw, color)
            return
        self._ops.append(("P", [[(float(x0), float(y0)), (float(x1), float(y1))]],
                          None, _hex(color), float(width), False, None, False))

    # ------------------------------------------------------------ 矢量专用

    def polyline(self, pts, color, width, dash=None):
        """折线描边（单个 path，内部顶点由 linejoin 连接，天然无白缝）。

        dash=(on, off)：交给 SVG stroke-dasharray / PDF d 算子按**弧长**切分，
        与光栅版 primitives.polyline 的弧长切分语义一致。
        """
        if width is None or width <= 0.0 or pts is None or len(pts) < 2:
            return
        self._ops.append(("P", [list(pts)], None, _hex(color), float(width),
                          False, _norm_dash(dash), False))

    def stroke_polygon(self, pts, color, width, dash=None):
        """闭合多边形描边（空心标记边框 / 矩形边框；与光栅版环宽居中一致）。"""
        if width is None or width <= 0.0 or pts is None or len(pts) < 2:
            return
        self._ops.append(("P", [list(pts)], None, _hex(color), float(width),
                          True, _norm_dash(dash), False))

    # ------------------------------------------------------------ 文本

    def text(self, s, x, baseline_y, size, color, font=None, align="left"):
        """文字转路径绘制。y 是**基线**（与 sci.fonts.draw_text / raster.Canvas 一致）。

        font=None：走 sci.fonts 的字体回退链（拉丁/希腊/中文/数学符号分段选字体，
        与全库其它文字完全一致）；font=TTF 路径：走 raster 的单字体路径（兼容
        raster.Canvas.text 的调用习惯）。返回结束处 x。
        """
        if not s:
            return x
        if font is None:
            # 字体回退链（拉丁/希腊/中文/数学符号分段选字体）→ fonts.draw_text，
            # 内部逐字形调 fonts._contours 取轮廓，再走本画布的 polygons
            return _fonts.draw_text(self, s, x, baseline_y, size, color, align=align)
        # —— 单字体兼容路径（font = TTF/TTC 路径或 (路径, face号)）——
        f, glyphs, cmap, upm = (_fonts._font(*font) if isinstance(font, tuple)
                                else _fonts._font(font))
        if align == "center":
            x -= self.text_width(s, size, font) / 2.0
        elif align == "right":
            x -= self.text_width(s, size, font)
        cursor = x
        for ch in s:
            name = cmap.get(ord(ch))
            if name is None:
                cursor += size * 0.5
                continue
            cons = _fonts._contours(f, glyphs, name, size, cursor, baseline_y)
            if cons:
                self.polygons(cons, color)
            cursor += glyphs[name].width * size / upm
        return cursor

    def text_width(self, s, size, font=None):
        """文本宽度（供排版用）。font=None 时与 sci.fonts.text_width 同源。"""
        if not s:
            return 0.0
        if font is None:
            return _fonts.text_width(s, size)
        f, glyphs, cmap, upm = (_fonts._font(*font) if isinstance(font, tuple)
                                else _fonts._font(font))
        total = 0.0
        for ch in s:
            name = cmap.get(ord(ch))
            total += (size * 0.5) if name is None else glyphs[name].width * size / upm
        return total

    # ------------------------------------------------------------ 体积 / 统计

    def op_count(self):
        """已记录的绘制操作数（调试用）。"""
        return len(self._ops)

    # ------------------------------------------------------------ SVG 输出

    def save_svg(self, path):
        """写合法 SVG 1.1 文件（viewBox 用逻辑像素，width/height 用 mm）。"""
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        w_mm = self.w / self.dpi * 25.4
        h_mm = self.h / self.dpi * 25.4
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<svg xmlns="http://www.w3.org/2000/svg" version="1.1"'
            ' width="%smm" height="%smm" viewBox="0 0 %d %d">'
            % (_f(w_mm), _f(h_mm), self.w, self.h),
        ]
        for op in self._ops:
            el = self._svg_element(op)
            if el:
                out.append(el)
        out.append("</svg>")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(out))
            fh.write("\n")
        return path

    def _svg_element(self, op):
        """一条绘制操作 -> SVG 元素字符串（矩形 <rect>，其它 <path>）。"""
        if op[0] == "R":
            _, x0, y0, x1, y1, col = op
            return ('<rect x="%s" y="%s" width="%s" height="%s" fill="%s"/>'
                    % (_f(x0), _f(y0), _f(x1 - x0), _f(y1 - y0), col))
        _, cons, fill, stroke, width, closed, dash, evenodd = op
        d = _svg_path_d(cons, closed)
        if not d:
            return None
        attrs = ['d="%s"' % d]
        if fill is not None:
            attrs.append('fill="%s"' % fill)
            if evenodd:
                attrs.append('fill-rule="evenodd"')
        else:
            attrs.append('fill="none"')
        if stroke is not None:
            attrs.append('stroke="%s"' % stroke)
            attrs.append('stroke-width="%s"' % _f(width))
            # 圆角连接：raster 用「距离场描边 + 顶点补圆」，round join 观感最接近
            # （两端仍是 butt cap，与光栅版一致）
            attrs.append('stroke-linejoin="round"')
            if dash:
                attrs.append('stroke-dasharray="%s %s"' % (_f(dash[0]), _f(dash[1])))
        return "<path %s/>" % " ".join(attrs)

    # ------------------------------------------------------------ PDF 输出

    def save_pdf(self, path):
        """手写 PDF 1.4 文件：对象 + 交叉引用表 + startxref + %%EOF。"""
        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        content = zlib.compress(self._pdf_content(), 9)
        w_pt = self.w / self.dpi * 72.0
        h_pt = self.h / self.dpi * 72.0
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %s %s]"
             " /Resources << /ProcSet [/PDF] >> /Contents 4 0 R >>"
             % (_f(w_pt), _f(h_pt))).encode("ascii"),
            (b"<< /Length " + str(len(content)).encode("ascii")
             + b" /Filter /FlateDecode >>\nstream\n" + content + b"\nendstream"),
        ]
        buf = bytearray(b"%PDF-1.4\n")
        buf += b"%\xe2\xe3\xcf\xd3\n"          # 二进制标记：告诉工具这是二进制 PDF
        offsets = []
        for i, body in enumerate(objs, 1):
            offsets.append(len(buf))
            buf += ("%d 0 obj\n" % i).encode("ascii") + body + b"\nendobj\n"
        xref_pos = len(buf)
        buf += ("xref\n0 %d\n" % (len(objs) + 1)).encode("ascii")
        buf += b"0000000000 65535 f \n"
        for off in offsets:
            buf += ("%010d 00000 n \n" % off).encode("ascii")
        buf += ("trailer\n<< /Size %d /Root 1 0 R >>\n"
                % (len(objs) + 1)).encode("ascii")
        buf += ("startxref\n%d\n" % xref_pos).encode("ascii")
        buf += b"%%EOF\n"
        with open(path, "wb") as fh:
            fh.write(bytes(buf))
        return path

    def _pdf_content(self):
        """内容流（未压缩）：q ... Q 包裹；开头 cm 完成 px -> pt 与 y 轴翻转。"""
        s = 72.0 / self.dpi
        h_pt = self.h * s
        out = ["q", "%s 0 0 %s 0 %s cm" % (_f(s), _f(-s), _f(h_pt)), "0 J 0 j"]
        for op in self._ops:
            if op[0] == "R":
                _, x0, y0, x1, y1, col = op
                out.append("%s %s %s %s re" % (_f(x0), _f(y0),
                                               _f(x1 - x0), _f(y1 - y0)))
                out.append("%s rg" % _pdf_color(col))
                out.append("f")
                continue
            _, cons, fill, stroke, width, closed, dash, evenodd = op
            ops = _pdf_path_ops(cons, closed)
            if not ops:
                continue
            if fill is not None:
                out.append("%s rg" % _pdf_color(fill))
            if stroke is not None:
                out.append("%s RG" % _pdf_color(stroke))
                out.append("%s w" % _f(width))
                out.append("1 j")          # round join：与 raster SDF 描边观感一致
                out.append(_pdf_dash(dash))
            out.extend(ops)
            if fill is not None and stroke is not None:
                out.append("B*" if evenodd else "B")
            elif fill is not None:
                out.append("f*" if evenodd else "f")
            else:
                out.append("S")
        out.append("Q")
        return ("\n".join(out) + "\n").encode("ascii")


# ======================================================================
# 后端无关的小工具
# ======================================================================

def _norm_dash(dash):
    """dash 归一化成 (on, off) 浮点二元组；非法返回 None（实线）。"""
    if not dash:
        return None
    try:
        on = float(dash[0])
        off = float(dash[1])
    except (TypeError, IndexError, ValueError):
        return None
    if on <= 0.0:
        return None
    if off < 0.0:
        off = 0.0
    return (on, off)


def _svg_path_d(contours, closed):
    """轮廓列表 -> SVG path 的 d 属性（每段轮廓一个 M...L...，闭合时补 Z）。"""
    out = []
    for con in contours:
        n = len(con)
        if n < 2:
            continue
        x, y = con[0]
        out.append("M %s %s" % (_f(x), _f(y)))
        for k in range(1, n):
            x, y = con[k]
            out.append("L %s %s" % (_f(x), _f(y)))
        if closed:
            out.append("Z")
    return " ".join(out)


def _pdf_path_ops(contours, closed):
    """轮廓列表 -> PDF 路径构造算子（m/l/h），坐标仍是逻辑像素（由 CTM 缩放）。"""
    out = []
    for con in contours:
        n = len(con)
        if n < 2:
            continue
        x, y = con[0]
        out.append("%s %s m" % (_f(x), _f(y)))
        for k in range(1, n):
            x, y = con[k]
            out.append("%s %s l" % (_f(x), _f(y)))
        if closed:
            out.append("h")
    return out


def _pdf_color(hexstr):
    """'#RRGGBB' -> PDF 的 'r g b'（0..1，3 位小数）。"""
    h = hexstr[1:]
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return "%s %s %s" % (_f(r), _f(g), _f(b))


def _pdf_dash(dash):
    """dash 元组 -> PDF 虚线算子（[] 0 d 表示实线）。"""
    if not dash:
        return "[] 0 d"
    return "[%s %s] 0 d" % (_f(dash[0]), _f(dash[1]))
