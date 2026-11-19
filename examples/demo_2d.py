# -*- coding: utf-8 -*-
"""测试：热图 + 色标、等高线、第三维着色散点。"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, TOOLS)
for _m in list(sys.modules):
    if _m == "sciplot" or _m == "raster" or _m.startswith("sci"):
        sys.modules.pop(_m, None)

from sciplot import (Figure, plot_heatmap, plot_contour, plot_series,
                     add_colorbar)

OUT = os.path.join(HERE, "out")


def field(x, y):
    return (math.exp(-(((x - 2.0) ** 2 + (y - 2.0) ** 2) / 0.9))
            + 0.55 * math.exp(-(((x - 1.1) ** 2 + (y - 3.0) ** 2) / 0.22))
            + 0.25 * math.exp(-(((x - 3.0) ** 2 + (y - 1.2) ** 2) / 0.35)))


def grid(n=44):
    xs = [0.0 + 4.0 * i / (n - 1) for i in range(n)]
    ys = [0.0 + 4.0 * j / (n - 1) for j in range(n)]
    z = [[field(x, y) for x in xs] for y in ys]
    return xs, ys, z


def main():
    os.makedirs(OUT, exist_ok=True)
    xs, ys, z = grid()

    # ---------- A. 热图 + 色标 ----------
    fig = Figure(profile="nature", size="single")
    ax = fig.axes_with_colorbar(xlim=(0, 4), ylim=(0, 4),
                                xlabel="Position $x$ (mm)", ylabel="Position $y$ (mm)")
    vmin, vmax = plot_heatmap(ax, xs, ys, z, cmap="viridis")
    ax.draw()
    fig.colorbar(ax, cmap="viridis", vmin=vmin, vmax=vmax,
                 label="Intensity (a.u.)")
    fig.save(OUT + "/demo_heatmap.png")
    print("A heatmap:", fig.report().replace("\n", " | "))

    # ---------- B. 等高线 ----------
    fig2 = Figure(profile="nature", size="single")
    ax2 = fig2.axes(xlim=(0, 4), ylim=(0, 4),
                    xlabel="Position $x$ (mm)", ylabel="Position $y$ (mm)")
    levels = plot_contour(ax2, xs, ys, z, n=9, cmap="cividis", lw_pt=0.9)
    ax2.draw()
    fig2.save(OUT + "/demo_contour.png")
    print("B contour: levels=", ["%.2f" % v for v in levels],
          fig2.report().replace("\n", " | "))

    # ---------- C. 填色等高线（plot_heatmap 打底 + 等高线叠加）----------
    fig3 = Figure(profile="nature", size="single")
    ax3 = fig3.axes_with_colorbar(xlim=(0, 4), ylim=(0, 4),
                                  xlabel="Position $x$ (mm)",
                                  ylabel="Position $y$ (mm)")
    from sci import contour as ct
    lv = ct.auto_levels(z, 10)
    vmin, vmax = min(lv), max(lv)
    plot_heatmap(ax3, xs, ys, z, cmap="viridis", vmin=vmin, vmax=vmax)
    plot_contour(ax3, xs, ys, z, levels=lv, color="#222222", lw_pt=0.6)
    ax3.draw()
    fig3.colorbar(ax3, cmap="viridis", vmin=vmin, vmax=vmax,
                  label="Intensity (a.u.)")
    fig3.save(OUT + "/demo_contourf.png")
    print("C contourf:", fig3.report().replace("\n", " | "))


def scatter_c():
    import random
    from sciplot import plot_scatter_c
    rnd = random.Random(11)
    x = [rnd.gauss(0, 1) for _ in range(160)]
    y = [0.8 * xx + rnd.gauss(0, 0.6) for xx in x]
    t = [0.5 * xx - 0.4 * yy + rnd.gauss(0, 0.3) for xx, yy in zip(x, y)]

    fig = Figure(profile="nature", size="single")
    ax = fig.axes_with_colorbar(xlim=(-3.2, 3.2), ylim=(-3.2, 3.2),
                                xlabel="Galactic $l$ (deg)",
                                ylabel="Galactic $b$ (deg)")
    vmin, vmax = plot_scatter_c(ax, x, y, t, cmap="cividis", ms_pt=3.4)
    ax.draw()
    fig.colorbar(ax, cmap="cividis", vmin=vmin, vmax=vmax,
                 label="Velocity (km s$^{-1}$)")
    fig.save(OUT + "/demo_scatter_c.png")
    print("D scatter_c:", fig.report().replace("\n", " | "))


if __name__ == "__main__":
    main()
    scatter_c()
