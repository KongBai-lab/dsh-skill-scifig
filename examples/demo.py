# -*- coding: utf-8 -*-
"""scifig 验收样例：fit（阻尼振荡拟合+残差）与 lightcurve（凌星光变）。

用法：python examples/demo.py，出两张图到 examples/out/。
"""
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, TOOLS)
for _m in list(sys.modules):
    if _m == "sciplot" or _m == "raster" or _m.startswith("sci"):
        sys.modules.pop(_m, None)

OUT = os.path.join(HERE, "out")


# ---------------------------------------------------------------- 数据
def damped_model(t):
    return 2.40 * math.exp(-0.18 * t) * math.cos(2.10 * t) + 0.06


def make_fit_data(n=64, seed=2026):
    rnd = random.Random(seed)
    xs, ys, es = [], [], []
    for i in range(n):
        t = i * 0.12
        e = 0.16 + 0.07 * rnd.random()
        xs.append(t)
        ys.append(damped_model(t) + rnd.gauss(0.0, e))
        es.append(e)
    return xs, ys, es


def make_model_curve(n=400, tmax=None):
    tmax = tmax or (63 * 0.12)
    return ([tmax * i / n for i in range(n + 1)],
            [damped_model(tmax * i / n) for i in range(n + 1)])


def transit_model(ph):
    depth, t1, t2, t3, t4 = 0.0104, -0.034, -0.027, 0.027, 0.034
    if ph < t1 or ph > t4:
        m = 1.0
    elif ph < t2:
        m = 1.0 - depth * (ph - t1) / (t2 - t1)
    elif ph < t3:
        m = 1.0 - depth
    else:
        m = 1.0 - depth * (t4 - ph) / (t4 - t3)
    return m + 0.00055 * math.sin(2 * math.pi * ph / 0.021)


def make_lightcurve(n=110, seed=7):
    """MJD 起点随便取一个真实感的值，星等 = -2.5log10(flux)+零点。"""
    rnd = random.Random(seed)
    t0 = 60311.25  # MJD
    times, mags, errs = [], [], []
    for i in range(n):
        ph = -0.06 + 0.12 * i / (n - 1)
        f = transit_model(ph) + rnd.gauss(0, 0.00045)
        mag = 12.40 - 2.5 * math.log10(f)
        e = 0.0009 + 0.0004 * rnd.random()
        times.append(t0 + ph * 0.18)      # 相位 → 天
        mags.append(mag)
        errs.append(e)
    return times, mags, errs


def make_lc_model(n=400, t0=60311.25):
    ts, ms = [], []
    for i in range(n + 1):
        ph = -0.06 + 0.12 * i / n
        ts.append(t0 + ph * 0.18)
        ms.append(12.40 - 2.5 * math.log10(transit_model(ph)))
    return ts, ms


# ---------------------------------------------------------------- 跑图
def main():
    from sciplot import figure_fit, figure_lightcurve

    os.makedirs(OUT, exist_ok=True)
    x, y, e = make_fit_data()
    mx, my = make_model_curve()
    fig = figure_fit(
        x, y, yerr=e, model=(mx, my),
        xlabel="Time (s)", ylabel="Displacement (mm)",
        legend_loc="upper right", out=OUT + "/demo_fit.png")
    print(fig.report())

    t, mag, err = make_lightcurve()
    ltx, lty = make_lc_model()
    fig2 = figure_lightcurve(
        t, mag, err=err, model=(ltx, lty),
        out=OUT + "/demo_lightcurve.png")
    print(fig2.report())
    print("done")


if __name__ == "__main__":
    main()
