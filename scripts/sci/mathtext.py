# -*- coding: utf-8 -*-
"""sci/mathtext.py — 极简 LaTeX 数学排版（$...$）。

支持：
  上下标       $T_{eff}$  $10^{-10}$  $^{-1}$
  希腊字母     $\\alpha$ $\\Omega$ $\\lambda$
  常用符号     $\\pm$ $\\times$ $\\approx$ $\\mu$ $\\AA$ $\\sigma$ $\\odot$
  分式         $\\frac{1}{2}mv^2$  $\\frac{N}{A}$（水平分数线，支持嵌套）
  根式         $\\sqrt{2\\pi\\sigma^2}$  $\\sqrt{x}$
  正体文本     $\\text{rest}$  $\\mathrm{He}$
  转义         \\$ 表示字面 $

不做：矩阵、多行对齐、积分上下限的上下堆叠（\\int 直接用字符，上下限按普通上下标处理）。

单位书写惯例（Science/Nature）：轴标题 `Quantity (unit)`，
  例如 "$F_\\lambda$ (erg s$^{-1}$ cm$^{-2}$ $\\AA$$^{-1}$)"。
"""
from . import fonts  # noqa: E402

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ",
    "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ",
    "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "varepsilon": "ε", "varphi": "φ", "vartheta": "θ", "varrho": "ρ",
}

SYMBOL = {
    "times": "×", "pm": "±", "mp": "∓", "approx": "≈", "sim": "∼", "simeq": "≃",
    "propto": "∝", "infty": "∞", "leq": "≤", "geq": "≥", "neq": "≠", "ll": "≪", "gg": "≫",
    "odot": "⊙", "oplus": "⊕", "ominus": "⊖", "otimes": "⊗", "deg": "°", "prime": "′",
    "langle": "⟨", "rangle": "⟩", "star": "⋆", "ell": "ℓ", "partial": "∂", "nabla": "∇",
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮",
    "sun": "☉", "earth": "⊕", "leftarrow": "←", "rightarrow": "→", "leftrightarrow": "↔",
    "AA": "Å", "micro": "μ", "percent": "%", "dot": "·", "cdots": "⋯", "ldots": "…",
    ",": "\u2009", ";": "\u2005", "!": "", ":": "\u2005",
    "quad": "\u2003", "qquad": "\u2003\u2003",
    "cdot": "·", "bullet": "•", "div": "÷", "pmb": "±", "equiv": "≡", "cong": "≅",
    "subset": "⊂", "supset": "⊃", "in": "∈", "notin": "∉", "forall": "∀", "exists": "∃",
    "uparrow": "↑", "downarrow": "↓", "Rightarrow": "⇒", "Leftarrow": "⇐",
    "ln": "ln", "log": "log", "exp": "exp", "max": "max", "min": "min", "sin": "sin",
    "cos": "cos", "tan": "tan", "lim": "lim",
}

STRUCT = ("frac", "sqrt")
ENVS = ("cases", "pmatrix", "bmatrix", "matrix")

# 屏幕坐标 y 向下为正：下标 = 下移(正)，上标 = 上移(负)
SUBSCRIPT_DY = 0.22
SUPERSCRIPT_DY = -0.36
SUB_SCALE = 0.68

FRAC_SCALE = 0.92          # 分式内字号系数
FRAC_GAP = 0.14            # 分式左右留白（×字号）
SQRT_SCALE = 0.96


# ---------------------------------------------------------------- 结构判断

def _is_frac(tok):
    """("frac", scale, dy, num, den) —— 5 元组。"""
    return isinstance(tok, tuple) and len(tok) == 5 and tok[0] == "frac"


def _is_sqrt(tok):
    """("sqrt", scale, dy, inner) —— 4 元组。"""
    return isinstance(tok, tuple) and len(tok) == 4 and tok[0] == "sqrt"


def _is_env(tok):
    """("env", scale, dy, rows, kind) —— 5 元组，kind 在 ENVS 里。"""
    return isinstance(tok, tuple) and len(tok) == 5 and tok[0] == "env" and tok[4] in ENVS


def _is_struct(tok):
    return _is_frac(tok) or _is_sqrt(tok) or _is_env(tok)


# ---------------------------------------------------------------- 解析

def parse(s):
    """混合字符串 -> token 列表。

    token 两种形态：
      线性  (text, scale, dy)
      结构  ("frac", scale, dy, num_tokens, den_tokens)
             ("sqrt", scale, dy, inner_tokens)
    """
    toks = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "$":
            j = s.find("$", i + 1)
            if j < 0:
                toks.extend(_parse_body(s[i + 1:]))
                break
            toks.extend(_parse_body(s[i + 1:j]))
            i = j + 1
        else:
            j = s.find("$", i)
            if j < 0:
                j = n
            toks.append((s[i:j], 1.0, 0.0))
            i = j
    return toks


def _read_cmd(body, i, n):
    """从 body[i] == '\\\\' 读命令名，返回 (name, new_i)。"""
    j = i + 1
    while j < n and body[j].isalpha():
        j += 1
    if j == i + 1:      # 单字符命令，如 \$
        j = i + 2
    return body[i + 1:j], j


def _read_group(body, i, n):
    """读一个参数：{...}（支持嵌套）、\\cmd、或单个字符。返回 (内容, new_i)。"""
    while i < n and body[i] == " ":
        i += 1
    if i >= n:
        return "", i
    if body[i] == "{":
        depth, j = 0, i
        while j < n:
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
                if depth == 0:
                    return body[i + 1:j], j + 1
            j += 1
        return body[i + 1:], n
    if body[i] == "\\":
        # 返回带反斜杠的原文，交给 _parse_body 当命令解析；
        # 若只返回命令名（如 "odot"），会被当成普通字母排成字面 "odot"。
        name, j = _read_cmd(body, i, n)
        return body[i:j], j
    return body[i], i + 1


def _split_top(s, sep):
    """按 sep 切分，但跳过花括号内部的 sep（用于 \\ 分行、& 分列）。"""
    out, depth, cur, i = [], 0, "", 0
    while i < len(s):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
        if depth == 0 and s.startswith(sep, i):
            out.append(cur)
            cur = ""
            i += len(sep)
            continue
        cur += s[i]
        i += 1
    out.append(cur)
    return out


def _poly_bezier(p0, p1, p2, n=14):
    pts = []
    for k in range(n + 1):
        t = k / n
        mt = 1 - t
        pts.append((mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                    mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]))
    return pts


def _draw_delim(c, x, y0, y1, kind, color, lw, side="left"):
    """手绘定界符（大括号/圆括号/方括号）。

    不用字体的 { } ( ) 字形：它们是固定高度的，拉不高；这里按内容高度画曲线，
    任意高矮都正常。
    """
    h = y1 - y0
    w = h * 0.16 if kind != "brace" else h * 0.22
    sag = w * 0.55
    sgn = 1.0 if side == "left" else -1.0

    def X(d):
        return x + sgn * d

    if kind == "paren":
        pts = _poly_bezier((X(0.0), y0), (X(-sag), (y0 + y1) / 2.0), (X(0.0), y1))
        for a, b in zip(pts, pts[1:]):
            c.line(a[0], a[1], b[0], b[1], color, lw)
    elif kind == "bracket":
        c.line(X(0.0), y0, X(w * 0.6), y0, color, lw)
        c.line(X(0.0), y0, X(0.0), y1, color, lw)
        c.line(X(0.0), y1, X(w * 0.6), y1, color, lw)
    else:  # brace
        ym = (y0 + y1) / 2.0
        k = h * 0.13
        pts = [(X(w), y0), (X(w * 0.25), y0 + k * 0.55), (X(0.0), y0 + k * 1.5),
               (X(0.0), ym - k * 0.9), (X(-sag * 0.55), ym), (X(0.0), ym + k * 0.9),
               (X(0.0), y1 - k * 1.5), (X(w * 0.25), y1 - k * 0.55), (X(w), y1)]
        for a, b in zip(pts, pts[1:]):
            c.line(a[0], a[1], b[0], b[1], color, lw)


def _scale_tokens(toks, k):
    """整体缩放（塞进上下标时保持内部比例）。"""
    out = []
    for t in toks:
        if _is_frac(t):
            out.append(("frac", t[1] * k, t[2], _scale_tokens(t[3], k), _scale_tokens(t[4], k)))
        elif _is_sqrt(t):
            out.append(("sqrt", t[1] * k, t[2], _scale_tokens(t[3], k)))
        elif _is_env(t):
            rows = [[_scale_tokens(cell, k) for cell in row] for row in t[3]]
            out.append(("env", t[1] * k, t[2], rows, t[4]))
        else:
            out.append((t[0], t[1] * k, t[2]))
    return out


def _parse_body(body):
    out = []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch == "\\":
            name, i = _read_cmd(body, i, n)
            if name in ("rm", "mathit", "mathnormal", "left", "right", "displaystyle"):
                continue
            if name in ("text", "mathrm", "operatorname"):
                grp, i = _read_group(body, i, n)
                out.extend(_parse_body(grp))       # 递归：允许嵌套 \, \alpha ^{-1}
                continue
            if name == "begin":
                envname, i = _read_group(body, i, n)
                endtag = "\\end{%s}" % envname
                j = body.find(endtag, i)
                content = body[i:j] if j >= 0 else body[i:]
                i = j + len(endtag) if j >= 0 else n
                kind = "cases" if "cases" in envname else (
                    "pmatrix" if "pmatrix" in envname else (
                        "bmatrix" if "bmatrix" in envname else "matrix"))
                rows = []
                for line in _split_top(content, "\\\\"):
                    if not line.strip():
                        continue
                    rows.append([_parse_body(cell) for cell in _split_top(line, "&")])
                out.append(("env", 1.0, 0.0, rows, kind))
                continue
            if name == "end":
                _tag, i = _read_group(body, i, n)   # 孤立的 \end，跳过
                continue
            if name == "frac":
                num, i = _read_group(body, i, n)
                den, i = _read_group(body, i, n)
                out.append(("frac", 1.0, 0.0, _parse_body(num), _parse_body(den)))
                continue
            if name == "sqrt":
                inner, i = _read_group(body, i, n)
                out.append(("sqrt", 1.0, 0.0, _parse_body(inner)))
                continue
            sym = GREEK.get(name) or SYMBOL.get(name)
            if sym is not None:
                out.append((sym, 1.0, 0.0))
            continue
        if ch in "_^":
            i += 1
            if i >= n:
                break
            grp, i = _read_group(body, i, n)
            dy = SUBSCRIPT_DY if ch == "_" else SUPERSCRIPT_DY
            for t in _scale_tokens(_parse_body(grp), SUB_SCALE):
                if _is_frac(t):
                    out.append(("frac", t[1], dy + t[2], t[3], t[4]))
                elif _is_sqrt(t):
                    out.append(("sqrt", t[1], dy + t[2], t[3]))
                else:
                    out.append((t[0], t[1], dy + t[2]))
            continue
        if ch == "{":
            grp, i = _read_group(body, i, n)
            out.extend(_parse_body(grp))
            continue
        if ch == "}":
            i += 1
            continue
        if ch == " ":
            out.append((" ", 1.0, 0.0))
            i += 1
            continue
        out.append((ch, 1.0, 0.0))
        i += 1
    return out


# ---------------------------------------------------------------- 度量

def _tok_width(tok, size, bold):
    if _is_frac(tok):
        wn = _tokens_width(tok[3], size * FRAC_SCALE, bold)
        wd = _tokens_width(tok[4], size * FRAC_SCALE, bold)
        return max(wn, wd) + size * FRAC_GAP
    if _is_sqrt(tok):
        inner = _tokens_width(tok[3], size * SQRT_SCALE, bold)
        return fonts.text_width("√", size, bold) * 0.90 + inner + size * 0.06
    if _is_env(tok):
        sz = size * tok[1]
        rows, kind = tok[3], tok[4]
        ncols = max(len(r) for r in rows) if rows else 1
        colw = [0.0] * ncols
        for r in rows:
            for i, cell in enumerate(r):
                colw[i] = max(colw[i], _tokens_width(cell, sz, bold))
        w = sum(colw) + sz * 0.55 * max(ncols - 1, 0)
        if kind in ("cases", "pmatrix", "bmatrix"):
            w += sz * 0.80
        return w
    return fonts.text_width(tok[0], size * tok[1], bold)


def _tokens_width(toks, size, bold=False):
    return sum(_tok_width(t, size, bold) for t in toks)


def width(s, size, bold=False):
    return _tokens_width(parse(s), size, bold)


# ---------------------------------------------------------------- 绘制

def _draw_env(c, tok, x, baseline_y, size, color, bold=False):
    """分段/矩阵环境：cases、pmatrix、bmatrix、matrix。"""
    _, sc, dy, rows, kind = tok
    sz = size * sc
    nrows = max(len(rows), 1)
    ncols = max((len(r) for r in rows), default=1) or 1
    colw = [0.0] * ncols
    for r in rows:
        for i, cell in enumerate(r):
            colw[i] = max(colw[i], _tokens_width(cell, sz, bold))
    gap = sz * 0.55
    content_w = sum(colw) + gap * max(ncols - 1, 0)
    rowh = sz * 1.60
    total_h = rowh * nrows
    top = baseline_y + dy * size - total_h * 0.62
    lw = max(1.0, sz * 0.07)

    if kind == "cases":
        _draw_delim(c, x + sz * 0.34, top, top + total_h, "brace", color, lw, "left")
        cx0 = x + sz * 0.66
    elif kind == "pmatrix":
        _draw_delim(c, x + sz * 0.22, top, top + total_h, "paren", color, lw, "left")
        _draw_delim(c, x + sz * 0.30 + content_w + sz * 0.06, top, top + total_h,
                    "paren", color, lw, "right")
        cx0 = x + sz * 0.38
    elif kind == "bmatrix":
        _draw_delim(c, x + sz * 0.20, top, top + total_h, "bracket", color, lw, "left")
        _draw_delim(c, x + sz * 0.28 + content_w + sz * 0.06, top, top + total_h,
                    "bracket", color, lw, "right")
        cx0 = x + sz * 0.34
    else:
        cx0 = x

    for ri, row in enumerate(rows):
        y = top + rowh * (ri + 0.5) + sz * 0.34
        cx = cx0
        for ci in range(ncols):
            cell = row[ci] if ci < len(row) else []
            cw = _tokens_width(cell, sz, bold)
            off = 0.0 if kind == "cases" else (colw[ci] - cw) / 2.0
            if cell:
                _draw_tokens(c, cell, cx + off, y, sz, color, bold)
            cx += colw[ci] + gap
    return x + _tok_width(tok, size, bold)


def _draw_tokens(c, toks, x, baseline_y, size, color, bold=False):
    cx = x
    for tok in toks:
        if _is_env(tok):
            cx = _draw_env(c, tok, cx, baseline_y, size, color, bold)
            continue
        if _is_frac(tok):
            wn = _tokens_width(tok[3], size * FRAC_SCALE, bold)
            wd = _tokens_width(tok[4], size * FRAC_SCALE, bold)
            w = max(wn, wd)
            # 分子（基线上方）
            _draw_tokens(c, tok[3], cx + (w - wn) / 2.0, baseline_y - size * 0.70,
                         size * FRAC_SCALE, color, bold)
            # 分数线：落在分子与分母之间的轴线上（不能压到分母字顶）
            ly = baseline_y - size * 0.18
            c.rect(cx - size * 0.02, ly, cx + w + size * 0.02,
                   ly + max(1.0, size * 0.05), color)
            # 分母（基线下方）
            _draw_tokens(c, tok[4], cx + (w - wd) / 2.0, baseline_y + size * 0.72,
                         size * FRAC_SCALE, color, bold)
            cx += w + size * FRAC_GAP
        elif _is_sqrt(tok):
            rw = fonts.text_width("√", size, bold)
            inner_w = _tokens_width(tok[3], size * SQRT_SCALE, bold)
            # 根号字形略微放大以罩住内部高度
            fonts.draw_text(c, "√", cx, baseline_y, size * 1.14, color, bold=bold)
            # 内部
            _draw_tokens(c, tok[3], cx + rw * 0.80, baseline_y, size * SQRT_SCALE, color, bold)
            # 上划线：内部含分式时要抬得更高，否则会压住分子
            has_frac = any(_is_frac(x) for x in tok[3])
            top = baseline_y - size * (1.58 if has_frac else 1.18)
            c.rect(cx + rw * 0.60, top, cx + rw * 0.80 + inner_w + size * 0.04,
                   top + max(1.0, size * 0.055), color)
            cx += rw * 0.80 + inner_w + size * 0.06
        else:
            txt, sc, dy = tok
            if txt.strip():
                fonts.draw_text(c, txt, cx, baseline_y + dy * size, size * sc, color, bold=bold)
            cx += fonts.text_width(txt, size * sc, bold)
    return cx


def draw(c, s, x, baseline_y, size, color, align="left", bold=False):
    toks = parse(s)
    total = _tokens_width(toks, size, bold)
    if align == "center":
        x -= total / 2.0
    elif align == "right":
        x -= total
    return _draw_tokens(c, toks, x, baseline_y, size, color, bold)


def draw_rotated(c, s, cx, cy, size, color, bold=False):
    """旋转 90° 的数学文本（y 轴标题）。结构单元退化成线性排布。"""
    toks = parse(s)
    total = _tokens_width(toks, size, bold)
    y = cy + total / 2.0
    for tok in toks:
        if _is_struct(tok):
            for sub in tok[3]:
                if not _is_struct(sub) and sub[0].strip():
                    w = fonts.char_width(sub[0], size * sub[1], bold)
                    fonts.draw_rotated_char(c, sub[0], cx - sub[2] * size,
                                            y - w / 2.0, size * sub[1], color, bold)
                    y -= w * 1.08
            continue
        txt, sc, dy = tok
        for ch in txt:
            w = fonts.char_width(ch, size * sc, bold)
            fonts.draw_rotated_char(c, ch, cx - dy * size, y - w / 2.0,
                                    size * sc, color, bold)
            y -= w * 1.08
