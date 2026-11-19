---
name: scifig
description: 科研出版级数据图（Nature/Science 规范）：轴标题带物理量与单位、误差棒、对数轴、多面板、残差子图、光变曲线、色盲友好色板，出图自动跑合规检查。要投论文、做实验数据图、画天文观测曲线时用；中文教学插图/讲义配图也可用（走「教学插图档」，150×92 mm @300 dpi）。做 PPT/报告/公众号里的装饰性图表请用 diagram。
whenToUse: 用户要画"投稿用的图""论文插图""实验数据图""带误差棒的图""光变曲线""拟合残差图""对数坐标图""带物理量单位的图"，或提到 Nature/Science/ApJ/A&A/MNRAS 投稿规格，或抱怨"图不够专业/不规范/不像论文里的图"。若只是要个柱状图/饼图/流程图放进 PPT，用 diagram。
---

# scifig：科研出版级图表

## 0. 边界

本 skill 做「能直接投稿的数据图」，不是"把数据画出来"就完事。

| 你要的 | 走哪里 |
|---|---|
| 论文插图、实验数据图、拟合+残差、光变曲线 | ✅ 本 skill |
| 带误差棒/对数轴/物理量单位/多面板的图 | ✅ 本 skill |
| 明确说"按 Nature/Science/ApJ 规范" | ✅ 本 skill |
| 中文教学插图、讲义配图（非投稿） | ✅ 本 skill（走 §0b「教学插图档」）；非投稿图也可用，但仍要过检查器 |
| PPT/报告里的柱状图/饼图/流程图 | ❌ 用 `diagram` |
| 海报、封面、插画、3D 立体图 | ❌ 都不是（`poster` / 不提供 3D） |

口诀：**图里要不要出现物理量和单位？** 要 → 本 skill；不要 → `diagram`。教学插图只要带数据坐标轴/物理量，即使不投稿也走本 skill。

## 0b. 教学插图档（中文教学 / 讲义配图的非投稿用法）

同一套 API 也出**中文教学插图**（讲义配图、复习资料插图、组会示意图里的数据图）。**不按投稿 profile 的地方按下面这套固定参数走**，别每次另调：

```python
from sciplot import Figure
fig = Figure(profile="nature", size="double",
             width_mm=150, height_mm=92)   # 150×92 mm @300 dpi ≈ 1772×1087 px
```

- **尺寸**：150 × 92 mm（≈16:10，放进 A4 讲义/课件不动缩放）；`size="double"` 只借双栏的字号档，宽高被显式 mm 覆盖。要方图/竖图只改 `width_mm` / `height_mm`。
- **300 dpi 线型补偿（必做）**：`sciplot` 默认虚线**按像素**给（`--` = (4.0, 2.2) px），300 dpi 下只有 0.3 mm 级，虚/点线会退化成实线或点。作图前显式改：

  ```python
  import sciplot
  sciplot._LINESTYLES = {"-": None, "--": (14.0, 7.0), ":": (3.0, 7.0), "-.": (12.0, 5.0)}
  ```

  （只改运行期模块级字典，不回写 `sciplot.py`；必须在调用 `plot_series` / `plot_model` **之前**设置。）
- **中文图注 / 中文标注**：字体链为 Noto Sans Math + Noto Sans CJK SC（§7）；中文正常，不要繁体/日文字形（CJK face 0 是日文，库已取 face 2 简体）。图注独立成段、写 **图 N 说明**，例：`图 3 不同参数下的谱线轮廓对比（示例数据，b = 0.2–1.0）`；讲义里"图 N"编号交给文档排版，图片内不放编号。
- **检查器照跑**：教学图虽不投稿，`fig.report()` 仍要 0 个 `[error]`；轴标题带物理量/单位、多曲线双编码、色盲可读照样适用（学生里也有色弱）。
- **`fig.report()` 前移到保存前必跑**：先 `print(fig.report())` 逐条看完、修完，再 `fig.save(...)`。`save()` 自带的检查只**打印**不阻断，跳过等于没查。**经验教训**：不在保存前跑检查器，300 dpi 下虚线退化成点这类问题只能靠肉眼看，返工一轮才补上——1 秒能报的别留到用户发现。

## 1. 六条铁律

1. **先定 profile**：`nature`（默认，89 mm）或 `science`（90 mm）。尺寸、字号、线宽全从 profile 取，不手写。
2. **轴标题必须写「物理量 (单位)」**：`"$T_{\\rm eff}$ (K)"`、`"$F_\\lambda$ (erg s$^{-1}$ cm$^{-2}$ $\\AA$$^{-1}$)"`。这是检查器会报的第一硬伤。
3. **有误差就必须画误差棒**：`yerr=` 传进去。
4. **同图多条曲线必须"颜色 + 线型/标记"双编码**（Nature/Science 要求色盲可读，AAS 明文禁止仅靠颜色区分）。
5. **出图必须过检查器 + `read_image` 目视**：`[error]` 必须修，`[warn]` 要判断。缺字、重叠、出界只有看图能发现。
6. **绘图脚本必须落盘到项目目录 `_figs/`**：脚本、数据、出图放**同一个项目目录**，脚本里写明确切输入/输出路径。不要只把脚本留在临时目录或缓存里——清理后图不可复现。**图不是交付物，脚本 + 数据才是**；交付时把脚本路径一并给用户。

## 2. 怎么跑

依赖：Python 3.10+、`fontTools`（`pip install fonttools`）和一个含数学/中文字形的字体。
字体目录可用环境变量 `SCI_FONT_DIR` 指定；不指定时自动探测
`/system/fonts`、`/usr/share/fonts`、`~/.local/share/fonts` 等常见目录。

把 `scripts/` 加进 `sys.path` 后即可导入（脚本放项目目录，见 §1 铁律 6）：

```python
import os, sys
SCRIPTS = "/path/to/scifig/scripts"
sys.path.insert(0, SCRIPTS)
for m in list(sys.modules):                      # 重跑必须清缓存，否则拿到旧结果
    if m == "sciplot" or m == "raster" or m.startswith("sci"):
        sys.modules.pop(m, None)

from sciplot import Figure, figure_fit, figure_lightcurve, plot_series, plot_model
```

冒烟测试（手造 20 个点画折线图 → PNG，断言文件存在且 >1KB）：

```bash
python tests/smoke.py
```

## 3. 两种写法

### 轨 A：一行出图（标准图种）

```python
from sciplot import figure_lightcurve
figure_lightcurve(
    time=mjd, mag=mag, err=err,           # 必填
    model=(mjdm, magm),                   # 可选：拟合曲线
    out="lightcurve.png")                 # 默认 invert_y=True（星等轴反向）
# MJD 自动偏移：跨度 <1 天而绝对值 >1000 时，自动写成 "Time (MJD - 60311.24 d)"
# 想关掉传 time_offset=None，想指定基准传 time_offset=60311.25
```

```python
from sciplot import figure_fit
figure_fit(x=x, y=y, yerr=err, model=(xm, ym),
           xlabel="$\\lambda$ (nm)", ylabel="Absorbance (a.u.)",
           out="fit.png")
```

### 轨 B：自己搭（要加标注/多序列/多面板时）

```python
from sciplot import Figure, plot_series, plot_model
fig = Figure(profile="nature", size="single")      # 89 mm 宽 → 1051 px
ax = fig.axes(xlim=(0, 10), ylim=(0, 1.2),
              xlabel="Orbital phase", ylabel="Normalized flux")
plot_series(ax, x, y, yerr=e, marker="circle", label="Observed", color="#0072B2")
plot_series(ax, x2, y2, marker="square", label="Model B", color="#D55E00", linestyle="--")
ax.legend([{"kind": "marker", "color": "#0072B2", "label": "Observed", "marker": "circle"},
           {"kind": "line",   "color": "#D55E00", "label": "Model B", "dash": (4, 2)}],
          loc="upper right")
ax.draw()
fig.save("custom.png")                              # 自动打印合规检查
```

## 4. 关键 API

| 调用 | 说明 |
|---|---|
| `Figure(profile="nature"\|"science", size="single"\|"double", height_mm=...)` | 画布，尺寸按 mm 自动换算像素 |
| `fig.axes(xlim, ylim, xlabel=, ylabel=, xscale="log", yscale="log", invert_y=True)` | 单个面板（占满画幅） |
| `fig.two_panel(xlim, ylim, ylim_res, ratio=3.0, main_kw=, res_kw=)` | 主图 + 残差图（上下叠放共享 x 轴），返回 `(ax, ax_res)`；两个面板参数分开传（残差轴不跟着反转/取对数） |
| `fig.grid(nrows, ncols, xlim, ylim)` | 多面板网格，返回二维列表 |
| `plot_series(ax, x, y, yerr=, xerr=, marker=, linestyle=, color=, label=, fill=(lo,hi))` | 画一组数据（折线+误差棒+标记） |
| `plot_model(ax, x, y, color=, linestyle="--")` | 画模型曲线 |
| `ax.set_xticks(major, minor)` / `ax.set_xfmt(fn)` | 手动刻度 / 自定义标签格式 |
| `ax.legend(entries, loc=)` | 图例，loc 支持 upper/lower + left/right/center |
| `ax.draw(xticklabels=False, xlabel=False)` | 画轴；残差面板共享 x 轴时上方主图要关掉 x 标签 |
| `fig.report()` / `fig.save(path)` | 合规检查报告 / 保存（save 会自动打印问题） |

**marker 可选**：`circle` `square` `triangle` `diamond` `star` `cross` `plus`
**linestyle 可选**：`"-"` `"--"` `":"` `"-."` `"none"`（none = 只画点）
**色板**：默认 Okabe-Ito（`#0072B2` 蓝、`#D55E00` 朱红、`#009E73` 绿…），禁止 jet/rainbow

## 4b. 图上的公式、字符与颜色

### 公式（`$...$`）

写在任何字符串里：轴标题、图例 label、`mathtext.draw()` 注释。

| 语法 | 例子 | 渲染 |
|---|---|---|
| 上下标 | `$a^2+b^2=c^2$`、`$T_{\rm eff}$`、`$10^{-10}$` | a²+b²=c² |
| 分式 | `$\frac{1}{2}mv^2$`、`$\frac{\partial f}{\partial x}$` | 水平分数线，可嵌套 |
| 根式 | `$\sqrt{2\pi\sigma^2}$`、`$v=\sqrt{\frac{2GM}{r}}$` | 根号 + 上划线 |
| 希腊字母 | `$\alpha\beta\gamma\sigma\Omega\Delta$` | αβγσΩΔ |
| 常用符号 | `$\pm\times\approx\leq\geq\propto\infty\partial\nabla\int\sum$` | ±×≈≤≥∝∞∂∇∫∑ |
| 天文符号 | `$M_\odot$`、`$R_\oplus$`、`$M_\oplus$` | M☉ R⊕ M⊕ |
| 单位 | `$\AA$`、`$\mu$m`、`erg s$^{-1}$ cm$^{-2}$` | Å μm |
| 正体文本 | `$\mathrm{km\,s^{-1}}$`、`$\text{rest}$` | 正体 + 细空格 |
| **分段函数** | `$f(x)=\begin{cases} x^2 & x\geq0 \\ -x & x<0 \end{cases}$` | 左侧大括号 + 两行 |
| **矩阵** | `$A=\begin{pmatrix} a & b \\ c & d \end{pmatrix}$` | ( 行×列 ) |
| | `$\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}$` | [ 行×列 ] |

**不支持**：多列对齐（align 环境）、积分号上下堆叠（按普通上下标排）、`\left/\right` 自动配尺寸。
复杂公式拆成几段分别画。

### 特殊字符

直接写在字符串里即可（字体链会挑到含该字的字体）：
`Å ± × ÷ ≤ ≥ ≈ ≡ ∞ ∂ ∇ ∫ ∑ ∏ √ ⟨ ⟩ → ← ↔ ° ′ ″ ‰ ☉ ⊕ · ⋅`

> 缺字保护：`sci.fonts.pick_font(ch)` 返回 `None` 就说明三个字体都没有该字。写代码时可先断言。

### 颜色

```python
plot_series(ax, x, y, color="#0072B2", marker="circle")     # 任意 hex
plot_series(ax, x, y, color=palettes.OKABE_ITO["vermillion"])

from sci import palettes
palettes.OKABE_ORDER          # 8 色色盲友好色板（默认）
palettes.colormap("viridis", t)      # 连续色板取色 t∈[0,1]，返回 (r,g,b)
palettes.colormap("cividis", t)      # 红绿色盲优化版
palettes.mix("#0072B2", f=0.15)      # 混成浅色（模拟半透明，画置信带用）
```

颜色规范（自动检查）：favicon 禁用 `jet`/`rainbow`；同面板多条线必须「颜色 + 线型/标记」双编码；禁止红绿并置——这些都会被 `fig.report()` 报出来。

## 4c. 二维数据：热图 / 等高线 / 色标

```python
from sciplot import (Figure, plot_heatmap, plot_contour, plot_scatter_c)

fig = Figure(profile="nature", size="single")
ax = fig.axes_with_colorbar(xlim=(0, 4), ylim=(0, 4),      # 右侧自动留色标空间
                            xlabel="Position $x$ (mm)", ylabel="Position $y$ (mm)")

# 热图：xs 长 nx、ys 长 ny、z 是 ny×nx
vmin, vmax = plot_heatmap(ax, xs, ys, z, cmap="viridis")
# 等高线：levels=None 自动取 nice 阈值；cmap 或统一 color
levels = plot_contour(ax, xs, ys, z, n=8, cmap="cividis", lw_pt=0.9,
                      labels=True)   # labels=True：在等值线上标数值（线自动断开）
# 第三维着色散点
vmin, vmax = plot_scatter_c(ax, x, y, t, cmap="cividis", ms_pt=3.4)

ax.draw()
fig.colorbar(ax, cmap="viridis", vmin=vmin, vmax=vmax, label="Intensity (a.u.)")
fig.save("heatmap.png")
```

要点：

- **必须用 `axes_with_colorbar()`**（等价于 `axes(..., right=24)`），否则色标会挤出画布
- `plot_heatmap` 返回 `(vmin, vmax)`，原样传给 `fig.colorbar` 保证色标与图一致
- **填色等高线** = `plot_heatmap(...)` 打底 + `plot_contour(...)` 叠线，两者用同一组 `vmin/vmax`
- 热图走批量写缓冲的快速路径，**500×500 实测 1.5s**（其中 1.2s 是 PNG 编码）；非均匀网格自动退回逐格填充（较慢）
- 等高线用 marching squares 实现，支持任意网格；`auto_levels(z, n)` 可拿到自动阈值

色标参数：`fig.colorbar(ax, cmap=, vmin=, vmax=, label=, width_mm=3.5, pad_mm=2.0, nticks=5)`

**半透明填充**（置信带、阴影区）：用 `primitives.band_alpha()`，是真 alpha 混合
（叠在数据线上线能透出来），不是预混浅色：

```python
from sci import primitives, palettes
primitives.band_alpha(ax.canvas,
                      [ax.px(v) for v in xs],
                      [ax.py(v) for v in y_hi],
                      [ax.py(v) for v in y_lo],
                      palettes.rgb("#0072B2"), alpha=0.22)
```
`plot_series(..., fill=(lo, hi))` 内部也走这条路径。

## 4d. 领域图种：corner plot 与天图

### corner plot（MCMC 后验，天文/统计标准图）

```python
from sci.corner import corner_figure
corner_figure(samples, ["$\\mu_0$", "$\\mu_1$", "$\\ln\\sigma$"], out="corner.png")
```

- `samples`：`[[v1, v2, ..., vn], ...]`，每行一个样本
- 自动布局：上三角留空 / 对角线 1D 直方图（含 16、50、84 分位竖线 + `+a/-b` 数值）/ 下三角 2D 等高线 + 散点
- 参数：`bins=28`、`range_pct=(0.5, 99.5)`、`quantiles=(0.16,0.50,0.84)`、`cmap="viridis"`

### 天图投影（RA/Dec）

```python
from sci.skymap import skymap_figure
skymap_figure(ra, dec, values=val, out="skymap.png")     # 单位都是度
```

- `projection` 可选 `sinusoidal`（正弦等面积，默认）/ `mollweide` / `rect`
- **RA 轴自动反向**（东在左，天文惯例）
- `values` 给定时按色板着色，自动配 colorbar
- 参数：`vmin`/`vmax`、`ra_range`、`dec_range`、`grid_step`

## 4e. 矢量输出（投稿用）

```python
fig = Figure(profile="nature", size="single", backend="svg")   # 或 backend="pdf"
ax = fig.axes(xlim=..., ylim=..., xlabel=..., ylabel=...)
plot_series(...)          # 绘图代码与位图完全一样
ax.draw()
fig.save("figure.svg")    # 按扩展名自动选出口
```

- **文字全部转成路径**，不依赖目标机器字体（审稿人打开不会缺字/跳字体）
- Nature 单栏实测：SVG 88.99 × 66.72 mm、PDF MediaBox 252.24 × 189.12 pt
- ⚠️ **必须创建时就指定 backend**——位图不能事后转矢量，会直接报错
- 矢量图适合投稿；PNG 300dpi 适合预览和 PPT

## 4f. 三维以上数据怎么画（不要用 3D）

期刊明确反对 3D 图（PLOS《Ten Simple Rules》：3D "induces an incorrect perception of quantities"）。
三维以上的数据用 **位置 + 颜色 + 大小** 编码，信息不丢且可精确读数：

```python
from sciplot import plot_scatter_c, size_legend

# 位置 = (l, b)，颜色 = 速度（第三维），大小 = 质量（第四维）
vmin, vmax = plot_scatter_c(ax, l, b, vel, s=mass, cmap="cividis",
                            ms_pt=3.2, smin_pt=1.8, smax_pt=7.5)
ax.draw()
size_legend(ax, mass, label="Mass ($M_\\odot$)",
            x_frac=0.46, y_frac=0.05)      # x/y_frac 是图例基线在图内的相对位置
fig.colorbar(ax, cmap="cividis", vmin=vmin, vmax=vmax, label="Velocity (km s$^{-1}$)")
```

| 维度 | 编码方式 | 用哪个 |
|---|---|---|
| 第 1、2 维 | 位置 (x, y) | `plot_series` / `plot_scatter_c` |
| 第 3 维 | 颜色 | `plot_scatter_c(c=...)` + `fig.colorbar` |
| 第 4 维 | 点面积 | `plot_scatter_c(s=...)` + `size_legend` |
| 第 3 维是连续场 | 等高线 / 热图 | `plot_contour` / `plot_heatmap` |

大小映射默认 `size_scale="area"`（面积正比于数值，气泡图惯例）；要直径正比改 `"diameter"`。

## 5. 规范速查（内置，不用记，但要知道边界）

| 项 | Nature | Science |
|---|---|---|
| 单栏宽 / 双栏宽 | 89 mm / 183 mm | 90 mm / 184 mm |
| 图内字号 | 5–7 pt（面板字母 8 pt） | ≥6 pt（轴标签 8 pt、面板 9 pt） |
| 最小线宽 | — | 0.28 pt |
| 光栅 | ≥300 dpi | ≥300 dpi；纯黑白线条 1200 dpi |
| 硬性禁止 | 背景网格、阴影、装饰元素、彩色文字 | 只收 RGB、避免红+绿 |

**领域惯例（已内置）**：
- 刻度朝内、四面框、只有左/下带标签
- 星等轴反向、RA 轴反向、H-R 图 Teff 反向（用 `invert_y=` / `invert_x=`）
- 对数轴刻度写 `10$^{n}$`
- 单位符号：`Å` `☉`(U+2609) `⊕`(U+2295) `±` `×`
- 天文 3σ 上限用向下三角箭头（`primitives.arrow_down`）

## 6. 自检（缺一不可）

1. **保存前**就跑 `fig.report()`（别等 `fig.save` 的自动打印——它只提示不阻断）：无 `[error]`；`[warn]` 逐条判断
2. `read_image` 目视：**缺字（□/空白）、标签重叠、数据点出界、图例压数据、y 轴标题是否从下往上**
3. 图内数字与传入数据一致（随机抽 2 个点核对）

## 7. 限制（如实告知；2026-11-03 实测更新）

- **位图 + 矢量均可**：PNG 默认 300 dpi；`Figure(..., backend="svg")` / `backend="pdf"` 矢量出口**已实现且实测可用**（2026-11-03 实跑 `fig.save("x.svg")` 成功，文字已 Path 化，见 §4e）。仍未提供 EPS 出口。
  > 旧口径“只能出 PNG、PDF 出口属 P2 计划”**已作废**（2026-11-03 实测修订）。
- **已实现图种**：`fit` / `lightcurve` / 2D（热图、等高线、第三维着色散点，§4c）/ corner plot（`sci.corner.corner_figure`）/ 天图投影（`sci.skymap.skymap_figure`，§4d）—— 2026-11-03 代码面与实跑核对均存在/可调用。旧口径“corner、等高线、天图尚未实现”**已作废**。
  > 仍未实现：动画、真正的 3D、`align` 多列对齐与 `\left/\right` 自动尺寸（§4b 已列）。
- **不做 3D**（期刊规范反对：3D 图会诱导对量值的错误感知）。三维以上的数据用下面 §4f 的方式表达；不提供动画。
- 字体固定 sans-serif（Noto Sans Math + Noto Sans CJK SC），中文显示正常，英文与中文混排时字重略有差异。字体目录可用环境变量 `SCI_FONT_DIR` 指定，未指定时自动探测 `/system/fonts`、`/usr/share/fonts`、`~/.local/share/fonts` 等常见目录；找不到字体时 `sci.fonts.pick_font()` 会给出明确错误。

## 8. 以前踩过的坑（改代码别退回去）

- 屏幕坐标 y 向下：**上标 dy 为负、下标为正**（写反了会造成上下标颠倒）
- `NotoSansCJK-Regular.ttc` 的 face 0 是**日文**，中文必须取 face 2（简体），否则中日字形混排
- `raster` 的 `polygon` 是 even-odd 填充，字形孔洞靠它；不要改成非零环绕（`o`、`口` 会填实）
- 上下标不要用 Unicode 字符（`⁰¹²₀₁₂` 在系统字体里几乎全缺），必须用字号缩放 + 基线偏移
- 重跑脚本前必须清 `sys.modules` 缓存，否则 `from sciplot import ...` 拿到的是上一版
- **复合字形必须展开**：Noto Sans Math 里 `i`/`j` 是 composite glyph，用 `RecordingPen` 只会记 addComponent 不展开 → 轮廓为空 → 字母整个不显示（表现为"T me""Magn tude"缺 i）。必须用 `DecomposingRecordingPen`（已在 `sci/fonts.py` 处理）
