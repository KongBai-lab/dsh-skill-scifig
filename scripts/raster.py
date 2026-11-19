# -*- coding: utf-8 -*-
"""raster.py — 纯 Python 光栅化 + PNG 编码。

原理（已在纯 Python 环境验证）:
  1. fontTools 取字形轮廓（RecordingPen） -> 贝塞尔离散成多边形
  2. 扫描线填充多边形（奇偶规则）+ 2x 超采样抗锯齿
  3. zlib 编码 PNG（IHDR/IDAT/IEND + CRC32）

不依赖 Pillow / cairo / 浏览器 / ImageMagick。
坐标约定：所有 API 收“逻辑像素”，内部乘 supersample 倍数。
"""
import glob
import math
import os
import struct
import zlib

from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.pens.recordingPen import RecordingPen  # noqa: E402

# 字体发现：SCI_FONT_DIR 优先，其次常见系统字体目录。
# 候选名覆盖 Linux（Noto / 文泉驿 / DejaVu）、macOS（PingFang / Helvetica）、
# Windows（微软雅黑）与 HarmonyOS（FZHeiT）。
_FONT_DIR = os.environ.get("SCI_FONT_DIR") or ""

_FONT_CANDIDATES = {
    "reg": ["NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf",
            "NotoSansSC-Regular.otf", "SourceHanSansSC-Regular.otf",
            "wqy-zenhei.ttc", "DejaVuSans.ttf", "msyh.ttc", "msyh.ttf",
            "PingFang.ttc", "FZHeiT-SC-Regular.ttf"],
    "bold": ["NotoSansCJK-Bold.ttc", "NotoSansCJKsc-Bold.otf",
             "NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf", "msyhbd.ttc",
             "PingFang.ttc", "FZHeiT-SC-Bold.ttf"],
    "math": ["NotoSansMath-Regular.ttf", "DejaVuMathTeXGyre.ttf"],
}


def _font_dirs():
    dirs = []
    if _FONT_DIR:
        dirs.append(_FONT_DIR)
    dirs += ["/system/fonts", "/usr/share/fonts", "/usr/local/share/fonts",
             os.path.expanduser("~/.local/share/fonts"),
             os.path.expanduser("~/.fonts"),
             "/Library/Fonts", "/System/Library/Fonts",
             os.path.expanduser("~/Library/Fonts"),
             "C:\\Windows\\Fonts"]
    out = []
    for d in dirs:
        if d and os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def _find_font(names):
    dirs = _font_dirs()
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p):
                return p
    for d in dirs:
        for n in names:
            for p in glob.glob(os.path.join(d, "**", n), recursive=True):
                if os.path.isfile(p):
                    return p
    return None


FONT_REG = _find_font(_FONT_CANDIDATES["reg"])
FONT_BOLD = _find_font(_FONT_CANDIDATES["bold"]) or FONT_REG
FONT_MATH = _find_font(_FONT_CANDIDATES["math"]) or FONT_REG

_FONTS = {}


def _font(path):
    if not path:
        raise RuntimeError(
            "找不到可用字体：请安装 Noto Sans CJK / DejaVu Sans（或任意中文 TTF），"
            "并用环境变量 SCI_FONT_DIR 指向字体目录。")
    if path not in _FONTS:
        f = TTFont(path, fontNumber=0)
        _FONTS[path] = (f, f.getGlyphSet(), f.getBestCmap())
    return _FONTS[path]


def _quadratic(p0, c, p1, steps=16):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        out.append((mt * mt * p0[0] + 2 * mt * t * c[0] + t * t * p1[0],
                    mt * mt * p0[1] + 2 * mt * t * c[1] + t * t * p1[1]))
    return out


def _glyph_polys(font, glyphs, glyph_name, size, ox, baseline):
    pen = RecordingPen()
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
                cur.extend(_quadratic(prev, ctrl, nxt))
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


class Canvas:
    def __init__(self, w, h, bg=(255, 255, 255), ss=2):
        self.w, self.h, self.ss = int(w), int(h), ss
        self.cw, self.ch = self.w * ss, self.h * ss
        self.buf = bytearray(self.cw * self.ch * 3)
        self.rect(0, 0, self.w, self.h, bg)

    # -------- 图元（逻辑坐标） --------
    def rect(self, x0, y0, x1, y1, color):
        s = self.ss
        X0, X1 = max(0, int(x0 * s)), min(self.cw, int(x1 * s))
        Y0, Y1 = max(0, int(y0 * s)), min(self.ch, int(y1 * s))
        if X1 <= X0 or Y1 <= Y0:
            return
        row = bytes(color) * (X1 - X0)
        for y in range(Y0, Y1):
            off = (y * self.cw + X0) * 3
            self.buf[off:off + len(row)] = row

    def polygon(self, pts, color):
        s = self.ss
        poly = [(x * s, y * s) for (x, y) in pts]
        n = len(poly)
        if n < 3:
            return
        edges = []
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if y0 == y1:
                continue
            edges.append((x0, y0, x1, y1))
        if not edges:
            return
        ymin = max(0, int(math.floor(min(min(e[1], e[3]) for e in edges))))
        ymax = min(self.ch - 1, int(math.ceil(max(max(e[1], e[3]) for e in edges))))
        col = bytes(color)
        for y in range(ymin, ymax + 1):
            yc = y + 0.5
            xs = []
            for (x0, y0, x1, y1) in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
            if len(xs) < 2:
                continue
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                xa = max(0, int(math.ceil(xs[i])))
                xb = min(self.cw - 1, int(math.floor(xs[i + 1])))
                for x in range(xa, xb + 1):
                    off = (y * self.cw + x) * 3
                    self.buf[off:off + 3] = col

    def polygons(self, contours, color):
        """多轮廓合并做 even-odd 填充——字形的孔洞靠这个挖出来。"""
        s = self.ss
        edges = []
        for poly in contours:
            p = [(x * s, y * s) for (x, y) in poly]
            n = len(p)
            for i in range(n):
                x0, y0 = p[i]
                x1, y1 = p[(i + 1) % n]
                if y0 == y1:
                    continue
                edges.append((x0, y0, x1, y1))
        if not edges:
            return
        ymin = max(0, int(math.floor(min(min(e[1], e[3]) for e in edges))))
        ymax = min(self.ch - 1, int(math.ceil(max(max(e[1], e[3]) for e in edges))))
        col = bytes(color)
        for y in range(ymin, ymax + 1):
            yc = y + 0.5
            xs = []
            for (x0, y0, x1, y1) in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
            if len(xs) < 2:
                continue
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                xa = max(0, int(math.ceil(xs[i])))
                xb = min(self.cw - 1, int(math.floor(xs[i + 1])))
                for x in range(xa, xb + 1):
                    off = (y * self.cw + x) * 3
                    self.buf[off:off + 3] = col

    def line(self, x0, y0, x1, y1, color, width=1.0):
        dx, dy = x1 - x0, y1 - y0
        L = math.hypot(dx, dy)
        if L < 1e-9:
            self.rect(x0 - width / 2, y0 - width / 2, x0 + width / 2, y0 + width / 2, color)
            return
        nx, ny = -dy / L * width / 2, dx / L * width / 2
        self.polygon([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                      (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], color)

    # -------- 批量填充 / 半透明（科研图用，不影响上面任何既有方法） --------
    def blend_polygon(self, pts, color, alpha):
        """半透明多边形：（读原像素 → alpha 混合 → 写回），等价 source-over。

        光栅器本身没有 alpha 通道，这里直接对 RGB 缓冲做合成，
        因此透明色能正确叠在已有内容上（而不是预先混成浅色）。
        alpha=1 时退化为普通 polygon 填充。
        """
        a = min(max(float(alpha), 0.0), 1.0)
        if a <= 0.0:
            return
        if a >= 1.0:
            self.polygon(pts, color)
            return
        s = self.ss
        poly = [(x * s, y * s) for (x, y) in pts]
        n = len(poly)
        if n < 3:
            return
        edges = []
        for i in range(n):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % n]
            if y0 == y1:
                continue
            edges.append((x0, y0, x1, y1))
        if not edges:
            return
        ymin = max(0, int(math.floor(min(min(e[1], e[3]) for e in edges))))
        ymax = min(self.ch - 1, int(math.ceil(max(max(e[1], e[3]) for e in edges))))
        ia = 1.0 - a
        r, g, b = color[0], color[1], color[2]
        ar, ag, ab = r * a, g * a, b * a
        cw = self.cw
        buf = self.buf
        for y in range(ymin, ymax + 1):
            yc = y + 0.5
            xs = []
            for (x0, y0, x1, y1) in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
            if len(xs) < 2:
                continue
            xs.sort()
            base = y * cw
            for k in range(0, len(xs) - 1, 2):
                xa = max(0, int(math.ceil(xs[k])))
                xb = min(cw - 1, int(math.floor(xs[k + 1])))
                for x in range(xa, xb + 1):
                    off = (base + x) * 3
                    buf[off] = int(buf[off] * ia + ar)
                    buf[off + 1] = int(buf[off + 1] * ia + ag)
                    buf[off + 2] = int(buf[off + 2] * ia + ab)

    def image_rgb(self, x0, y0, w, h, rows):
        """整块写入 RGB 图像（用于热图等大面积填充）。

        rows: 长度 h 的序列，每项是 w*3 字节的 1x 像素行（bytes/bytearray）。
        内部用步长切片把 1x 行放大到 ss×ss 子像素，全程 C 速度拷贝，
        比逐格调用 rect 快一到两个数量级。
        """
        if w <= 0 or h <= 0:
            return
        s = self.ss
        cw = self.cw
        X0 = int(round(x0 * s))
        Y0 = int(round(y0 * s))
        stride = s * 3
        for ry in range(h):
            src = rows[ry]
            if len(src) < w * 3:
                continue
            big = bytearray(w * s * 3)
            for c in range(3):
                chan = src[c::3]
                for k in range(s):
                    big[(c + k * 3)::stride] = chan
            for k in range(s):
                row_y = Y0 + ry * s + k
                if row_y < 0 or row_y >= self.ch:
                    continue
                off = (row_y * cw + X0) * 3
                end = min(off + len(big), len(self.buf))
                if end > off:
                    self.buf[off:end] = big[:end - off]

    # -------- 文本 --------
    def text_width(self, s, size, font=FONT_REG):
        f, glyphs, cmap = _font(font)
        upm = f["head"].unitsPerEm
        total = 0.0
        for ch in s:
            name = cmap.get(ord(ch))
            total += (size * 0.5) if name is None else glyphs[name].width * size / upm
        return total

    def text(self, s, x, baseline_y, size, color, font=FONT_REG, align="left"):
        f, glyphs, cmap = _font(font)
        upm = f["head"].unitsPerEm
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
            self.polygons(_glyph_polys(f, glyphs, name, size, cursor, baseline_y), color)
            cursor += glyphs[name].width * size / upm
        return cursor

    # -------- 输出 --------
    def _downsample(self):
        ss = self.ss
        if ss == 1:
            return self.buf
        out = bytearray(self.w * self.h * 3)
        n = ss * ss
        for y in range(self.h):
            for x in range(self.w):
                r = g = b = 0
                base = (y * ss * self.cw + x * ss) * 3
                for dy in range(ss):
                    off = base + dy * self.cw * 3
                    for dx in range(ss):
                        p = off + dx * 3
                        r += self.buf[p]; g += self.buf[p + 1]; b += self.buf[p + 2]
                q = (y * self.w + x) * 3
                out[q] = r // n; out[q + 1] = g // n; out[q + 2] = b // n
        return out

    def png(self, path):
        rgb = self._downsample()
        raw = b"".join(b"\x00" + bytes(rgb[y * self.w * 3:(y + 1) * self.w * 3])
                       for y in range(self.h))

        def chunk(tag, data):
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xffffffff)

        blob = b"\x89PNG\r\n\x1a\n"
        blob += chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
        blob += chunk(b"IDAT", zlib.compress(raw, 9))
        blob += chunk(b"IEND", b"")
        with open(path, "wb") as fh:
            fh.write(blob)
        return path


if __name__ == "__main__":
    c = Canvas(640, 360, bg=(247, 244, 238))
    c.rect(40, 40, 600, 100, (31, 78, 121))
    c.text("纯 Python 光栅化测试", 320, 80, 28, (255, 255, 255), font=FONT_BOLD, align="center")
    c.text("中文 / ABC / 123 / ∑∫∂", 320, 180, 24, (30, 30, 30), font=FONT_REG, align="center")
    c.line(40, 260, 600, 260, (192, 0, 0), width=4)
    c.polygon([(40, 320), (140, 280), (240, 330)], (31, 78, 121))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "_raster_test.png")
    out = os.path.abspath(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    c.png(out)
    print("saved", out, os.path.getsize(out), "bytes")
