# -*- coding: utf-8 -*-
"""sci/axes.py — 科研图表坐标轴系统（四面闭合框 / 内向刻度 / log / 反转 / 轴标题 / 图例）。

本模块解决的问题（旧原型 tmp/sci_plot_proto.py 里 Axes 的缺陷）：
  * 旧版 box 的 y0=顶边、y1=底边，但方法里时而当顶时而当底，语义靠注释猜；
    本版统一约定 box = (x_left, y_top, x_right, y_bottom)，且强制 x_left<x_right、
    y_top<y_bottom，画之前先校验。
  * 旧版把字号/线宽写死在调用处，违反期刊规范；本版全部从 style profile
    的 pt 值经 style.pt2px 换算（dpi 由调用方给）。
  * 旧版刻度标签位置硬编码偏移，长标签会压到画布外；本版先排版后绘制，
    按画布边界自动缩字号/间距（要求 8）。

绘制层次（draw 一次画完）：
  1. 四面闭合框（黑，lw.axis）
  2. 主/次刻度，四条边全部朝内（底向上、顶向下、左向右、右向左）
  3. 刻度标签：只画底边（居中，基线在下）和左边（右对齐，垂直居中）
  4. x 轴标题：底边下方居中；y 轴标题：左侧外，逆时针 90°，从下往上读
  5. 图例：legend() 单独调用，白底 + 0.5pt 细框，loc 七种位置

坐标约定：
  * 数据坐标 -> 像素由 px()/py() 完成；box 与画布都是逻辑像素（raster.Canvas 约定）。
  * invert_x / invert_y 只翻转轴的映射方向，不改变刻度"朝内"的几何方向。
  * xlim/ylim 允许降序传入（如 (1.2, 0.5) 表示反向轴），与 invert 标志叠加生效。

依赖：sci.fonts / sci.mathtext / sci.palettes / sci.primitives / sci.style。
不依赖 numpy / matplotlib / PIL。
"""
import math

from . import mathtext, palettes, primitives, style as stylemod  # noqa: E402

INK = (0, 0, 0)
WHITE = (255, 255, 255)

_MARGIN = 2.0      # 画布边缘安全余量（px）——要求 8
_ASCENT = 0.85     # 数学标签基线以上高度 / 字号（含上标，Noto Sans Math 经验值）
_DESCENT = 0.25    # 基线以下高度 / 字号
_LEGEND_FRAME_PT = 0.5   # 图例边框 0.5pt（要求 7）


# ---------------------------------------------------------------- 数值工具

def _decimals(v, step):
    """求能无歧义表示 v、分辨率不粗于 step 的小数位数。"""
    tol = abs(step) * 1e-6 if step else abs(v) * 1e-9
    if abs(v) < tol:
        return 0
    for d in range(0, 13):
        if abs(round(v, d) - v) <= tol:
            return d
    return 6


def _parse_loc(loc):
    """图例位置字符串 -> (vertical, horizontal)，容忍连字符/下划线/别名。"""
    s = str(loc or "upper left").lower().replace("_", " ").replace("-", " ")
    if "upper" in s or "top" in s:
        vertical = "upper"
    elif "lower" in s or "bottom" in s:
        vertical = "lower"
    else:
        vertical = "center"
    if "left" in s:
        horizontal = "left"
    elif "right" in s:
        horizontal = "right"
    else:
        horizontal = "center"
    return vertical, horizontal


def _fmt_sci(v, step):
    """科学计数法标签：$1.5\\times10^{-3}$。"""
    av = abs(v)
    e = int(math.floor(math.log10(av)))
    m = v / (10.0 ** e)
    sm = (abs(step) / (10.0 ** e)) if step else None
    d = _decimals(m, sm if sm else abs(m) * 1e-6)
    ms = ("%d" % int(round(m))) if d == 0 else ("%.*f" % (d, m))
    return "$%s\\times10^{%d}$" % (ms, e)


class Axes:
    """一块带四面框的坐标区。

    参数
      canvas : raster.Canvas（或兼容 API 的对象），绘图目标
      box    : (x_left, y_top, x_right, y_bottom) 逻辑像素，必须左上-右下有序
      xlim   : (lo, hi) 数据范围；降序表示该轴反向（与 invert_x 叠加）
      ylim   : (lo, hi) 同上
      xscale : "linear" | "log"
      yscale : "linear" | "log"
      style  : profile dict（style.get() 的返回值）或 profile 名（"nature"/"science"）
      dpi    : 输出分辨率，pt -> px 用
      invert_x / invert_y : 轴方向翻转（天文：星等轴、RA 轴、H-R 图 Teff 轴）
    """

    def __init__(self, canvas, box, xlim, ylim, xscale="linear", yscale="linear",
                 style=None, dpi=300, invert_x=False, invert_y=False):
        box = tuple(float(v) for v in box)
        if len(box) != 4:
            raise ValueError("box 必须是 (x_left, y_top, x_right, y_bottom) 四元组")
        x0, y0, x1, y1 = box
        if x1 <= x0 or y1 <= y0:
            raise ValueError("box 需满足 x_left < x_right 且 y_top < y_bottom：%r" % (box,))
        self.box = box
        self.xlim = (float(xlim[0]), float(xlim[1]))
        self.ylim = (float(ylim[0]), float(ylim[1]))
        if self.xlim[0] == self.xlim[1]:
            raise ValueError("xlim 上下限不能相等：%r" % (self.xlim,))
        if self.ylim[0] == self.ylim[1]:
            raise ValueError("ylim 上下限不能相等：%r" % (self.ylim,))
        self.xscale = self._check_scale(xscale, self.xlim, "xlim")
        self.yscale = self._check_scale(yscale, self.ylim, "ylim")
        self.invert_x = bool(invert_x)
        self.invert_y = bool(invert_y)

        self.canvas = canvas
        if style is None:
            self.style = stylemod.get()
        elif isinstance(style, str):
            self.style = stylemod.get(style)
        else:
            self.style = style
        self.dpi = dpi

        # 轴标题与刻度（None = 自动）
        self._xlabel = ""
        self._ylabel = ""
        self._xmajor = None
        self._xminor = None
        self._ymajor = None
        self._yminor = None
        self._xfmt = None
        self._yfmt = None

    # ------------------------------------------------------------ 构造期校验

    @staticmethod
    def _check_scale(scale, lim, name):
        scale = (scale or "linear").lower()
        if scale not in ("linear", "log"):
            raise ValueError("scale 只支持 'linear' / 'log'，收到 %r" % (scale,))
        if scale == "log" and (lim[0] <= 0 or lim[1] <= 0):
            raise ValueError("%s 用 log 轴时必须全为正：%r" % (name, lim))
        return scale

    # ------------------------------------------------------------ 数据 -> 像素

    def px(self, v):
        """数据 x -> 像素 x。超出 xlim 的值正常线性外推，不抛异常。"""
        a, b, x = self._map_input(v, self.xscale, self.xlim, "x")
        t = (x - a) / (b - a)
        if self.invert_x:
            t = 1.0 - t
        return self.box[0] + t * (self.box[2] - self.box[0])

    def py(self, v):
        """数据 y -> 像素 y（y 越大越靠上）。超出 ylim 的值正常外推，不抛异常。"""
        a, b, x = self._map_input(v, self.yscale, self.ylim, "y")
        t = (x - a) / (b - a)
        if self.invert_y:
            t = 1.0 - t
        return self.box[3] - t * (self.box[3] - self.box[1])

    @staticmethod
    def _map_input(v, scale, lim, which):
        """返回 (a, b, x) 三个映射后的量；log 轴对非正值做有限钳制避免抛异常。"""
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ValueError("%s 轴数据必须是数值：%r" % (which, v))
        if scale == "log":
            # 数据点 <=0 在 log 轴上无定义；钳到极小正数外推到画布外，
            # 由调用方自行裁剪，避免上游因个别越界点崩溃。
            vv = v if v > 0 else 1e-300
            return math.log10(lim[0]), math.log10(lim[1]), math.log10(vv)
        return lim[0], lim[1], v

    # ------------------------------------------------------------ 轴标题 / 刻度设置

    def set_xlabel(self, s):
        self._xlabel = "" if s is None else str(s)
        return self

    def set_ylabel(self, s):
        self._ylabel = "" if s is None else str(s)
        return self

    @staticmethod
    def _norm_ticks(seq):
        """刻度列表规范化：元素可以是数值，也可以是 (value, label) 二元组。"""
        if seq is None:
            return None
        out = []
        for item in seq:
            if isinstance(item, (tuple, list)):
                if len(item) != 2:
                    raise ValueError("刻度二元组必须是 (value, label)：%r" % (item,))
                out.append((float(item[0]), str(item[1])))
            else:
                out.append((float(item), None))
        return out

    def set_xticks(self, major=None, minor=None):
        """major=None 表示自动 nice ticks；元素可为数值或 (value, label)。"""
        self._xmajor = self._norm_ticks(major)
        self._xminor = self._norm_ticks(minor)
        return self

    def set_yticks(self, major=None, minor=None):
        self._ymajor = self._norm_ticks(major)
        self._yminor = self._norm_ticks(minor)
        return self

    def set_xfmt(self, fn):
        """自定义刻度标签：fn(value) -> str。"""
        self._xfmt = fn
        return self

    def set_yfmt(self, fn):
        self._yfmt = fn
        return self

    # ------------------------------------------------------------ 自动刻度

    @staticmethod
    def nice_ticks(lo, hi, n=5):
        """线性轴 nice ticks：返回 (values, step)，step 用于决定标签小数位。"""
        lo, hi = float(lo), float(hi)
        if lo > hi:
            lo, hi = hi, lo
        if hi - lo <= 0:
            return [lo], 1.0
        n = max(2, int(n))
        raw = (hi - lo) / n
        mag = 10.0 ** math.floor(math.log10(raw))
        step = mag * 10.0
        for m in (1.0, 2.0, 2.5, 5.0, 10.0):
            if raw <= m * mag * (1.0 + 1e-12):
                step = m * mag
                break
        start = math.ceil(lo / step - 1e-10) * step
        vals = []
        v = start
        for _ in range(1000):
            if v > hi + step * 1e-6:
                break
            vals.append(v)
            v += step
        # 浮点清理：把 -0.0 / 1e-17 这类噪声归零，便于标签格式化
        vals = [0.0 if abs(t) < abs(step) * 1e-9 else t for t in vals]
        return vals, step

    @staticmethod
    def log_ticks(lo, hi):
        """log 轴刻度：返回 ([(value, "10$^{n}$"), ...], [次刻度值])。

        主刻度 = 10 的整数次幂，标签写成 10$^{-10}$ 形式（mathtext 上标）；
        次刻度 = 2..9 × 10^k，只画短线不标字。
        """
        lo, hi = float(lo), float(hi)
        if lo > hi:
            lo, hi = hi, lo
        if lo <= 0:
            raise ValueError("log_ticks 要求范围全为正：(%r, %r)" % (lo, hi))
        majors, minors = [], []
        e0 = int(math.floor(math.log10(lo) + 1e-12)) - 1
        e1 = int(math.floor(math.log10(hi) + 1e-12)) + 1
        eps = 1e-12
        for e in range(e0, e1 + 1):
            if e > 308 or e < -323:
                continue
            p = 10.0 ** e
            if p <= 0 or math.isinf(p):
                continue
            if lo * (1 - eps) <= p <= hi * (1 + eps):
                majors.append((p, "10$^{%d}$" % e))
            for m in range(2, 10):
                v = m * p
                if lo * (1 - eps) <= v <= hi * (1 + eps):
                    minors.append(v)
        return majors, minors

    # ------------------------------------------------------------ 刻度解析

    def _resolve_ticks(self, which):
        """按"手动设置 / 自动"解析出 ([(value, label)], minor_values, step)。"""
        if which == "x":
            scale, lim = self.xscale, self.xlim
            user_major, user_minor, fmt = self._xmajor, self._xminor, self._xfmt
        else:
            scale, lim = self.yscale, self.ylim
            user_major, user_minor, fmt = self._ymajor, self._yminor, self._yfmt
        lo, hi = (lim if lim[0] <= lim[1] else (lim[1], lim[0]))

        if user_major is not None:
            step = self._step_of([v for v, _ in user_major])
            pairs = []
            for v, lab in user_major:
                if lab is None:
                    lab = fmt(v) if fmt else self._fmt_value(v, step, scale)
                pairs.append((v, str(lab)))
            minors = [v for v, _ in user_minor] if user_minor else []
            if scale == "log":
                minors = [v for v in minors if v > 0]
            return pairs, minors, step

        if scale == "log":
            pairs, minors = self.log_ticks(lo, hi)
            if fmt is not None:
                pairs = [(v, str(fmt(v))) for v, _ in pairs]
            if len(pairs) < 2:
                # 亚十倍程范围（如 2..5）：没有整数幂主刻度，退化为线性 nice ticks，
                # 映射仍走 log，标签按普通数字格式，避免出现"零主刻度"的轴。
                vals, step = self.nice_ticks(lo, hi, 5)
                pairs = [(v, str(fmt(v)) if fmt else self._fmt_value(v, step, scale))
                         for v in vals]
                minors = [v for v in minors if lo <= v <= hi]
            return pairs, minors, None

        vals, step = self.nice_ticks(lo, hi, 5)
        pairs = [(v, str(fmt(v)) if fmt else self._fmt_value(v, step, scale)) for v in vals]
        minors = [v for v, _ in user_minor] if user_minor else []
        return pairs, minors, step

    @staticmethod
    def _step_of(values):
        """手动刻度：用相邻差值中位数估计步长（只影响标签小数位）。"""
        if len(values) < 2:
            return None
        vals = sorted(values)
        diffs = sorted(abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1))
        return diffs[len(diffs) // 2]

    @staticmethod
    def _fmt_value(v, step, scale):
        """默认刻度标签格式：log 轴整幂用 10^n；普通数值按步长定小数位，过大/过小转科学计数法。"""
        if scale == "log" and v > 0:
            try:
                e = math.log10(v)
            except ValueError:
                e = None
            if e is not None:
                k = int(round(e))
                if abs(e - k) < 1e-9:
                    return "10$^{%d}$" % k
        if v == 0:
            return "0"
        av = abs(v)
        if av >= 1e5 or av < 1e-3:
            return _fmt_sci(v, step)
        d = _decimals(v, step if step else av * 1e-6)
        return ("%d" % int(round(v))) if d == 0 else ("%.*f" % (d, v))

    # ------------------------------------------------------------ 排版（不越界）

    def _layout(self, xpairs, ypairs, xtl, ytl, xlab, ylab):
        """先算出四边所需空间；放不下就缩字号/间距（要求 8）。

        返回 dict：tick_size / axis_size / pad / gap / max_yw。
        """
        st, dpi = self.style, self.dpi
        cw, ch = self.canvas.w, self.canvas.h
        x0, y0, x1, y1 = self.box

        tick_size = stylemod.pt2px(st["pt"]["tick_label"], dpi)
        axis_size = stylemod.pt2px(st["pt"]["axis_label"], dpi)
        floor = max(4.0, stylemod.pt2px(st.get("min_font_pt", 5.0), dpi) * 0.8)
        base_pad = max(2.0, stylemod.pt2px(2.5, dpi))
        gap = max(2.0, stylemod.pt2px(3.0, dpi))

        xl_txt = self._xlabel if xlab else ""
        yl_txt = self._ylabel if ylab else ""
        xpos = [self.px(v) for v, _ in xpairs] if xtl else []
        ypos = [self.py(v) for v, _ in ypairs] if ytl else []
        xlabels = [lab for _, lab in xpairs] if xtl else []
        ylabels = [lab for _, lab in ypairs] if ytl else []

        def measure():
            # 左下角：y 最底标签的下降与 x 首标签的上升会打架，够大间距才安全
            pad = base_pad
            if xlabels and ylabels:
                pad = max(base_pad, 0.62 * tick_size + 1.0)
            xw = [mathtext.width(t, tick_size) for t in xlabels]
            yw = [mathtext.width(t, tick_size) for t in ylabels]
            max_yw = max(yw) if yw else 0.0
            xl_w = mathtext.width(xl_txt, axis_size) if xl_txt else 0.0
            yl_h = mathtext.width(yl_txt, axis_size) if yl_txt else 0.0
            if xlabels:
                tick_base = y1 + pad + _ASCENT * tick_size
                bottom = tick_base + _DESCENT * tick_size
                if xl_txt:
                    bottom = tick_base + _DESCENT * tick_size + gap + 1.02 * axis_size
            elif xl_txt:
                bottom = y1 + pad + 1.02 * axis_size
            else:
                bottom = y1
            left = x0 - pad - max_yw
            if yl_txt:
                left -= gap + 0.90 * axis_size
            return pad, xw, yw, max_yw, xl_w, yl_h, bottom, left

        pad = base_pad
        max_yw = 0.0
        for _ in range(120):
            pad, xw, yw, max_yw, xl_w, yl_h, bottom, left = measure()
            # 空间约束：左侧/下方留白 + 端点标签不碰画布边
            space_ok = (left >= _MARGIN) and (bottom <= ch - _MARGIN)
            if xlabels and xw:
                if min(p - w / 2.0 for p, w in zip(xpos, xw)) < _MARGIN:
                    space_ok = False
                if max(p + w / 2.0 for p, w in zip(xpos, xw)) > cw - _MARGIN:
                    space_ok = False
            if ylabels and yw:
                if min(ypos) - 0.5 * tick_size < _MARGIN:
                    space_ok = False
                if max(ypos) + 0.6 * tick_size > ch - _MARGIN:
                    space_ok = False
            # 标题约束：标题长度不能超过轴框，也不能横向/纵向伸出画布
            title_ok = True
            if xl_txt:
                if xl_w > (x1 - x0) - 2 * _MARGIN:
                    title_ok = False
                cx = (x0 + x1) / 2.0
                if cx - xl_w / 2.0 < _MARGIN or cx + xl_w / 2.0 > cw - _MARGIN:
                    title_ok = False
            if yl_txt:
                if yl_h > (y1 - y0) - 2 * _MARGIN:
                    title_ok = False
                cy = (y0 + y1) / 2.0
                if cy - yl_h / 2.0 < _MARGIN or cy + yl_h / 2.0 > ch - _MARGIN:
                    title_ok = False
            if space_ok and title_ok:
                break
            # 只缩真正造成溢出的那一项：标题超长先缩标题字号；空间不够先缩刻度字号
            if not title_ok and axis_size > floor + 1e-9:
                axis_size = max(floor, axis_size * 0.94)
            elif not space_ok and tick_size > floor + 1e-9:
                tick_size = max(floor, tick_size * 0.94)
            elif axis_size > floor + 1e-9:
                axis_size = max(floor, axis_size * 0.94)
            elif gap > 1.0:
                gap = max(1.0, gap * 0.85)
            else:
                break

        # 兜底：极端情况下标题长度超过轴框，按比例压进框内。
        # 宁可低于 min_font_pt，也不让文字越出画布（要求 8 优先于字号下限）。
        if xl_txt:
            limit = (x1 - x0) - 2 * _MARGIN
            xl_w = mathtext.width(xl_txt, axis_size)
            if 0 < limit < xl_w:
                axis_size = max(4.0, axis_size * limit / xl_w)
        if yl_txt:
            limit = (y1 - y0) - 2 * _MARGIN
            yl_h = mathtext.width(yl_txt, axis_size)
            if 0 < limit < yl_h:
                axis_size = max(4.0, axis_size * limit / yl_h)
        pad, xw, yw, max_yw, xl_w, yl_h, bottom, left = measure()
        return {"tick_size": tick_size, "axis_size": axis_size,
                "pad": pad, "gap": gap, "max_yw": max_yw}

    # ------------------------------------------------------------ 绘制

    def draw(self, xticklabels=True, yticklabels=True, xlabel=True, ylabel=True):
        """一次画完坐标轴。

        四面框与内向刻度**始终画**；四个开关只控制刻度标签与轴标题：
          xticklabels=False / xlabel=False —— 主图+残差子图共享 x 轴时，
          上方主图关掉 x 标签与标题，只留下方残差面板的（避免重复/重叠）。
        """
        xpairs, xminors, _ = self._resolve_ticks("x")
        ypairs, yminors, _ = self._resolve_ticks("y")
        xtl = bool(xticklabels and xpairs)
        ytl = bool(yticklabels and ypairs)
        xlab = bool(xlabel and self._xlabel)
        ylab = bool(ylabel and self._ylabel)

        lay = self._layout(xpairs, ypairs, xtl, ytl, xlab, ylab)
        tick_size = lay["tick_size"]
        axis_size = lay["axis_size"]

        self._draw_frame()
        self._draw_ticks(xpairs, xminors, ypairs, yminors)
        if xtl:
            self._draw_x_ticklabels(xpairs, tick_size, lay)
        if ytl:
            self._draw_y_ticklabels(ypairs, tick_size, lay)
        if xlab:
            self._draw_x_title(axis_size, lay, xtl)
        if ylab:
            self._draw_y_title(axis_size, lay)

    def _draw_frame(self):
        """四面闭合框：黑，lw.axis（pt -> px）。

        线段两端各外延半个线宽，让四个外角成为实心方角；
        否则 raster 的平头端帽会在外角留下半个线宽的缺口。
        """
        c = self.canvas
        x0, y0, x1, y1 = self.box
        w = stylemod.pt2px(self.style["lw"]["axis"], self.dpi)
        hw = w / 2.0
        c.line(x0 - hw, y0, x1 + hw, y0, INK, w)   # 上
        c.line(x0 - hw, y1, x1 + hw, y1, INK, w)   # 下
        c.line(x0, y0 - hw, x0, y1 + hw, INK, w)   # 左
        c.line(x1, y0 - hw, x1, y1 + hw, INK, w)   # 右

    def _draw_ticks(self, xpairs, xminors, ypairs, yminors):
        """主/次刻度，四条边全部朝内：底向上、顶向下、左向右、右向左。"""
        c = self.canvas
        st, dpi = self.style, self.dpi
        x0, y0, x1, y1 = self.box
        w_major = max(0.3, stylemod.pt2px(st["lw"]["tick"], dpi))
        w_minor = max(0.3, w_major * 0.8)
        l_major = stylemod.pt2px(st["tick_len_pt"]["major"], dpi)
        l_minor = stylemod.pt2px(st["tick_len_pt"]["minor"], dpi)

        for v, _ in xpairs:
            x = self.px(v)
            if x0 - 0.5 <= x <= x1 + 0.5:
                c.line(x, y1, x, y1 - l_major, INK, w_major)   # 底边：向上
                c.line(x, y0, x, y0 + l_major, INK, w_major)   # 顶边：向下
        for v in xminors:
            x = self.px(v)
            if x0 - 0.5 <= x <= x1 + 0.5:
                c.line(x, y1, x, y1 - l_minor, INK, w_minor)
                c.line(x, y0, x, y0 + l_minor, INK, w_minor)
        for v, _ in ypairs:
            y = self.py(v)
            if y0 - 0.5 <= y <= y1 + 0.5:
                c.line(x0, y, x0 + l_major, y, INK, w_major)   # 左边：向右
                c.line(x1, y, x1 - l_major, y, INK, w_major)   # 右边：向左
        for v in yminors:
            y = self.py(v)
            if y0 - 0.5 <= y <= y1 + 0.5:
                c.line(x0, y, x0 + l_minor, y, INK, w_minor)
                c.line(x1, y, x1 - l_minor, y, INK, w_minor)

    def _draw_x_ticklabels(self, pairs, size, lay):
        """x 刻度标签：只标底边，居中；放不下时按是否重叠跳过（不画到画布外）。"""
        c = self.canvas
        x0, y0, x1, y1 = self.box
        cw, ch = c.w, c.h
        pad = lay["pad"]
        base = y1 + pad + _ASCENT * size
        base = min(max(base, _MARGIN + _ASCENT * size), ch - _MARGIN - _DESCENT * size)

        items = []
        for v, lab in pairs:
            x = self.px(v)
            if not (x0 - 0.5 <= x <= x1 + 0.5):
                continue
            w = mathtext.width(lab, size)
            cx = min(max(x, _MARGIN + w / 2.0), cw - _MARGIN - w / 2.0)
            items.append((cx, lab, w))
        items.sort()
        last_right = -1e9
        for cx, lab, w in items:
            if cx - w / 2.0 < last_right + 0.8:
                continue
            mathtext.draw(c, lab, cx, base, size, INK, align="center")
            last_right = cx + w / 2.0

    def _draw_y_ticklabels(self, pairs, size, lay):
        """y 刻度标签：只标左边，右对齐、垂直居中；竖直放不下时跳过重叠项。"""
        c = self.canvas
        x0, y0, x1, y1 = self.box
        cw, ch = c.w, c.h
        right = x0 - lay["pad"]

        items = []
        for v, lab in pairs:
            y = self.py(v)
            if not (y0 - 0.5 <= y <= y1 + 0.5):
                continue
            w = mathtext.width(lab, size)
            r = min(right, cw - _MARGIN)
            if r - w < _MARGIN:
                r = _MARGIN + w
            base = y + 0.35 * size
            base = min(max(base, _MARGIN + _ASCENT * size), ch - _MARGIN - _DESCENT * size)
            items.append((y, r, lab, base))
        items.sort(key=lambda t: t[0])
        last_bottom = -1e9
        for y, r, lab, base in items:
            top = base - _ASCENT * size
            if top < last_bottom + 0.8:
                continue
            mathtext.draw(c, lab, r, base, size, INK, align="right")
            last_bottom = base + _DESCENT * size

    def _draw_x_title(self, size, lay, has_ticklabels):
        """x 轴标题：底边下方居中。有刻度标签时排在其下，没有时贴近轴。"""
        c = self.canvas
        x0, y0, x1, y1 = self.box
        cw, ch = c.w, c.h
        pad, gap = lay["pad"], lay["gap"]
        tick_size = lay["tick_size"]
        w = mathtext.width(self._xlabel, size)
        cx = (x0 + x1) / 2.0
        cx = min(max(cx, _MARGIN + w / 2.0), cw - _MARGIN - w / 2.0)
        if has_ticklabels:
            base = (y1 + pad + _ASCENT * tick_size + _DESCENT * tick_size
                    + gap + 0.80 * size)
        else:
            base = y1 + pad + 0.80 * size
        base = min(max(base, _MARGIN + 0.80 * size), ch - _MARGIN - 0.22 * size)
        mathtext.draw(c, self._xlabel, cx, base, size, INK, align="center")

    def _draw_y_title(self, size, lay):
        """y 轴标题：左边外侧，逆时针 90°（从下往上读，mathtext 支持上下标）。"""
        c = self.canvas
        x0, y0, x1, y1 = self.box
        ch = c.h
        pad, gap = lay["pad"], lay["gap"]
        # 标签列最大宽度：横向让出整列刻度标签（_layout 按最终字号量过）
        max_yw = lay["max_yw"]
        cx = x0 - pad - max_yw - gap - 0.45 * size
        cx = max(cx, _MARGIN + 0.45 * size)
        cy = (y0 + y1) / 2.0
        half = mathtext.width(self._ylabel, size) / 2.0
        cy = min(max(cy, _MARGIN + half), ch - _MARGIN - half)
        mathtext.draw_rotated(c, self._ylabel, cx, cy, size, INK)

    # ------------------------------------------------------------ 图例

    def legend(self, entries, loc="upper left", frame=True):
        """画图例。

        entries = [{"kind": "line"|"marker"|"line+marker", "color": "#RRGGBB",
                    "label": "...", "dash": (on, off) 或 None,
                    "marker": "circle"/"square"/"triangle"/"diamond"/"star"}]
        返回图例框 (x, y, w, h)；entries 为空时返回 None。
        """
        entries = [e for e in (entries or []) if e]
        if not entries:
            return None
        c = self.canvas
        st, dpi = self.style, self.dpi
        x0, y0, x1, y1 = self.box
        cw, ch = c.w, c.h

        size = stylemod.pt2px(st["pt"]["legend"], dpi)
        row_h = size * 1.42
        pad = max(2.0, size * 0.42)
        handle = size * 1.9
        tgap = size * 0.5
        n = len(entries)
        labels = [str(e.get("label", "")) for e in entries]
        tw = max(mathtext.width(t, size) for t in labels)
        w = pad * 2.0 + handle + tgap + tw
        h = pad * 2.0 + row_h * n

        # 图例与框的间距：至少让开主刻度长度，避免图例压住内向刻度
        inset = max(3.0, stylemod.pt2px(3.0, dpi),
                    stylemod.pt2px(st["tick_len_pt"]["major"] + 0.5, dpi))
        vertical, horizontal = _parse_loc(loc)
        if horizontal == "left":
            x = x0 + inset
        elif horizontal == "right":
            x = x1 - inset - w
        else:
            x = (x0 + x1) / 2.0 - w / 2.0
        if vertical == "upper":
            y = y0 + inset
        elif vertical == "lower":
            y = y1 - inset - h
        else:
            y = (y0 + y1) / 2.0 - h / 2.0
        # 图例不得越出画布
        x = min(max(x, _MARGIN), cw - _MARGIN - w)
        y = min(max(y, _MARGIN), ch - _MARGIN - h)

        if frame:
            c.rect(x, y, x + w, y + h, WHITE)   # 白色不透明底
            fw = stylemod.pt2px(_LEGEND_FRAME_PT, dpi)
            c.line(x, y, x + w, y, INK, fw)
            c.line(x, y + h, x + w, y + h, INK, fw)
            c.line(x, y, x, y + h, INK, fw)
            c.line(x + w, y, x + w, y + h, INK, fw)

        lw_data = stylemod.pt2px(st["lw"]["data"], dpi)
        for i, e in enumerate(entries):
            cy = y + pad + row_h * (i + 0.5)
            hx0 = x + pad
            hx1 = hx0 + handle
            kind = str(e.get("kind") or "line").lower()
            color = palettes.rgb(e.get("color", "#000000"))
            dash = e.get("dash")
            if "line" in kind:
                primitives.polyline(c, [(hx0, cy), (hx1, cy)], color, lw_data, dash=dash)
            if "marker" in kind:
                mk = e.get("marker") or "circle"
                r = size * 0.30
                if e.get("hollow"):
                    # 与数据点一致：白底 + 有色描边（上游 plot_series 默认空心）
                    primitives.marker(c, mk, (hx0 + hx1) / 2.0, cy, r, WHITE, color,
                                      ew=stylemod.pt2px(0.8, dpi))
                else:
                    primitives.marker(c, mk, (hx0 + hx1) / 2.0, cy, r, color)
            lab = labels[i]
            mathtext.draw(c, lab, hx1 + tgap, cy + size * 0.35, size, INK)
        return (x, y, w, h)


__all__ = ["Axes"]
