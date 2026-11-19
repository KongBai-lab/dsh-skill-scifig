# -*- coding: utf-8 -*-
"""tests/smoke.py — scifig 冒烟测试。

不依赖任何外部数据：手造 20 个点画一条折线，保存 PNG，
断言文件存在且大于 1 KB。用法：

    python tests/smoke.py

成功时打印 SMOKE OK 和图片路径；失败时抛 AssertionError（非 0 退出）。
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)


def main():
    import sciplot
    from sciplot import Figure, plot_series

    x = [0.5 * i for i in range(20)]
    y = [0.55 + 0.28 * math.sin(0.65 * v) + 0.04 * math.cos(2.1 * v) for v in x]
    yerr = [0.03 + 0.01 * (i % 3) for i in range(20)]

    fig = Figure(profile="nature", size="single")
    ax = fig.axes(xlim=(0.0, 10.0), ylim=(0.0, 1.2),
                  xlabel="Example $x$ (a.u.)", ylabel="Example $y$ (V)")
    plot_series(ax, x, y, yerr=yerr, marker="circle", color="#0072B2",
                label="Example data")
    ax.legend([{"kind": "marker", "color": "#0072B2",
                "label": "Example data", "marker": "circle"}],
              loc="upper right")
    ax.draw()

    out = os.path.join(tempfile.mkdtemp(prefix="scifig-smoke-"), "smoke.png")
    fig.save(out)

    assert os.path.isfile(out), "PNG 没有生成：%s" % out
    size = os.path.getsize(out)
    assert size > 1024, "PNG 只有 %d 字节（应 >1KB）" % size
    print("SMOKE OK — %s（%d 字节，%d 个数据点）"
          % (out, size, len(x)))
    print("sciplot:", os.path.abspath(sciplot.__file__))
    return 0


if __name__ == "__main__":
    sys.exit(main())
