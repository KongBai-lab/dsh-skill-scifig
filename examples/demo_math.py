# -*- coding: utf-8 -*-
"""演示：图上插入公式 / 特殊字符 / 颜色调控。"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, TOOLS)
for _m in list(sys.modules):
    if _m == "sciplot" or _m == "raster" or _m.startswith("sci"):
        sys.modules.pop(_m, None)

import raster
from sci import mathtext, palettes, style as stylemod
from sciplot import Figure, plot_series, plot_model

OUT = os.path.join(HERE, "out")


def showcase_formula():
    """公式 + 特殊字符排版总览。"""
    W, H, ss = 1040, 600, 3
    c = raster.Canvas(W, H, bg=(255, 255, 255), ss=ss)
    ink = (0, 0, 0)
    dpi = 300
    pt = lambda x: stylemod.pt2px(x, dpi)
    y = pt(11)
    items = [
        ("基本运算", r"$E = mc^2$     $a^2+b^2=c^2$     $F = ma$"),
        ("分式", r"$\frac{1}{2}mv^2$     $\frac{\partial f}{\partial x}$     $\frac{N_{\rm H}}{A}$"),
        ("根式", r"$\sqrt{2\pi\sigma^2}$     $v_{\rm esc}=\sqrt{\frac{2GM}{r}}$"),
        ("上下标与单位", r"$T_{\rm eff}=5800$ K   $\lambda=656.3$ nm   $M_\odot=1.989\times10^{30}$ kg"),
        ("天文符号", r"$M_\odot$   $R_\oplus$   $M_\oplus$   $\sigma$   $\Omega$   $\Delta m$   $\delta$"),
        ("特殊字符", "Å  ±  ×  ≤  ≥  ≈  ∞  ∂  ∇  ∫  √  ⟨ ⟩  →  °  ′  ″  ‰"),
        ("综合", r"$P(\chi^2)=\sqrt{\frac{2}{\pi}}\cdot\frac{1}{1+x^2}$"),
    ]
    for label, s in items:
        c.text if False else None
        size = pt(9)
        mathtext.draw(c, label, pt(4), y, size * 0.80, (130, 130, 130))
        mathtext.draw(c, s, pt(54), y, size, ink)
        y += pt(9) * 2.0
    p = OUT + "/showcase_math.png"
    c.png(p)
    return p


def color_and_math():
    """真实图：多色序列 + 公式标注 + 符号。"""
    fig = Figure(profile="nature", size="single")
    ax = fig.axes(xlim=(0, 10), ylim=(0, 1.15),
                  xlabel="Radius $r$ ($R_\\oplus$)",
                  ylabel="$v$ ($\\mathrm{km\\,s^{-1}}$)")

    xs = [i * 0.1 for i in range(101)]
    # Okabe-Ito 前三色
    series = [
        ("$v_{\\rm esc}=\\sqrt{2GM/r}$", "#0072B2", "-", [math.sqrt(2.0 / (r + 0.35)) for r in xs]),
        ("$v_{\\rm orb}=\\sqrt{GM/r}$", "#D55E00", "--", [math.sqrt(1.0 / (r + 0.35)) for r in xs]),
        ("$v_{\\rm rot}=r\\omega$", "#009E73", ":", [0.16 * r for r in xs]),
    ]
    for label, col, ls, ys in series:
        plot_series(ax, xs, ys, linestyle=ls, color=col, lw_pt=1.1)

    ax.draw()
    ax.legend([{"kind": "line", "color": col, "label": lab, "dash": None if ls == "-" else (4, 2)}
               for lab, col, ls, _ in series], loc="lower right")

    # —— 图上叠加公式与符号（这就是用户问的"插入公式"）——
    c = fig.canvas
    pt = lambda x: stylemod.pt2px(x, fig.dpi)
    mathtext.draw(c, "$M_\\oplus = 5.972\\times10^{24}$ kg", ax.px(5.6), ax.py(0.99),
                  pt(8), (0, 0, 0))
    mathtext.draw(c, "$\\sigma_v = \\pm\\,0.4$ km s$^{-1}$", ax.px(5.6), ax.py(0.90),
                  pt(8), (60, 60, 60))
    p = OUT + "/color_and_math.png"
    fig.save(p)
    print(fig.report())
    return p


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    print("A:", showcase_formula(), os.path.getsize(OUT + "/showcase_math.png"))
    print("B:", color_and_math())
