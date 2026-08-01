---
version: 2
supersedes: v1 (见文末「v1 → v2 废弃对照表」)
implementation: templates/index.html — 三个 <style> 块：pd-tokens / pd-base / pd-ui
---

# Port Dashboard 设计规范 v2

## Overview

Port Dashboard 是给同机跑多个服务的开发者用的本地控制台。视觉基调仍是
**复古 CRT 终端**：等宽字体、hairline 边框、扫描线与环境弧光。但 v2 把
"单一琥珀强调色 + 固定深绿色板"扩展成了**七套主题 + 八个语义 tone**，
因为四个安全等级加五个进程分类无法用一种色相表达。

气质仍是"冷静但警觉的机舱控制台"，不是营销落地页。

## 1. 主题模型（8 变量契约）

`THEME_VARIABLES`（index.html）为每套主题提供**且仅提供** 8 个变量：

| 变量 | 含义 |
|---|---|
| `--background` | 页面底色 |
| `--midground` | 主前景（文字、边框推导源） |
| `--card-bg` | 卡片/面板底 |
| `--card-border` | 兼容保留，新代码用 `--st-line` 系列 |
| `--glow-color` | 环境弧光（半透明） |
| `--accent` | 不透明强调色 |
| `--dimmed` | 次级文字色 |
| `--label` | 仅供设置面板展示，不写入 DOM |

`applyTheme()` 把它们写到 `<html>` 的 inline style，并设 `body.dataset.theme`。

**铁律：token 块之外不写十六进制色值。**要新颜色就用 `color-mix()` 从这 8 个变量推导，
或在 `body[data-theme=...]` 里加逐主题覆写。

七套主题：`dark-emerald`（默认）/ `blueprint` / `midnight` / `arctic`（唯一亮底）/
`terra` / `neon` / `velvet`。

## 2. 颜色角色

从 8 个源变量派生出的 `--st-*` 层：

- **三级表面**：`--st-surface`（内容区）< `--st-surface-2`（侧栏/header/footer）<
  `--st-surface-3`（输入、分段、hover）
  **两个混色操作数都必须不透明。**半透明表面会让环境弧光透上来并破坏对比度 ——
  这是设置面板改造中最重要的一条教训。
- **三级线**：`--st-line`(14%) / `--st-line-soft`(8%) / `--st-line-strong`(26%)，
  全部由 `--midground` 推导。绝不依赖任何框架的默认边框色。
- **三级文字**：`--st-fg` / `--st-fg-2`(=`--dimmed`) / `--st-fg-3`
- **强调阶梯**：`--st-accent` / `-weak`(12%) / `-soft`(22%) / `--st-ring`(45%)，
  以及 `--st-accent-fg`（叠在强调填充上的文字色，逐主题校准）

## 3. tone 契约

**组件永远不指定颜色，只声明 tone。** 这是 v2 最核心的约束。

```html
<span class="pd-badge" data-tone="danger">极危</span>
<button class="pd-btn pd-btn--solid" data-tone="ok">启动</button>
```

组件 CSS 只消费 `--tone` 与 `--tone-fg`；`[data-tone="x"]` 负责解析成具体色值。

八个 tone 及其语义：

| tone | 用于 |
|---|---|
| `ok` | 进程健康、HTTP 服务、我的应用、启动键 |
| `info` | 外部占用、说明性对话框 |
| `warn` | 需要确认、警告级端口 |
| `danger` | 禁止操作、失败、强杀/删除键 |
| `self` | 面板自身端口（与 warn 同级但需独立配色） |
| `creative` | 创意软件分类 |
| `network` | 网络工具分类 |
| `muted` | 已停止、系统服务 |
| `accent` | 主行动，等同主题强调色 |

未声明 tone 时退化为强调色。该回退规则**必须包在 `:where()` 里**把特异度归零 ——
否则它与 `[data-tone]` 同为 (0,1,0) 且写在后面，会反过来盖掉所有 tone。
（这个 bug 真实发生过：所有按钮一度都变成琥珀色。）

**arctic 与 neon 需要逐主题校准**：arctic 是亮底，tone 既要当浅底上的文字色就必须压暗；
neon 全站单色绿，tone 收进绿/黄谱系以免彩色徽章破坏主题识别度。

## 4. 字体

两个家族，角色严格：

- `--font-mono`：**JetBrains Mono**，本地托管 latin 子集（`static/fonts/*.woff2`，
  各约 21KB，`font-display: swap`）。用于所有数据、端口号、命令、日志、按钮、徽章。
- `--font-sans`：系统 UI 栈。仅用于长段落说明文字。

> v1 规范同样要求 JetBrains Mono，但项目里从来没有 `@font-face` 也没有字体文件，
> 全站一直静默回退到系统等宽。v2 真正把它装上了。

字号层级：品牌标题 22 / 分区标题 19 / 弹窗标题 15 / 卡片标题 15 / 行标题 13 /
正文 11.5 / 说明 11 / 徽章与 eyebrow 10。

## 5. 间距与圆角

- **间距**：8px 基准，`--st-1`…`--st-7` = 4/8/12/16/20/24/28
- **圆角阶梯**：modal 16 → icon/卡片 12 → 卡片·分段·主题行 10 → nav·按钮·输入 8 →
  swatch 6 → pill 999
- **容纳规则**：容器圆角 ≥ 子元素圆角 + 内边距

> **明确废止 v1 的「4px 是圆角上限」。** 设置面板验证了更柔和的阶梯观感更好，
> 而"工程控制台"的识别度由等宽字体与 hairline 边框承担，不依赖尖角。

## 6. 深度

**明确废止 v1 的「禁用阴影」。** 表面改为不透明后，原先靠半透明暗示的层次消失了，
需要用阴影补回来：

- `--st-shadow-sm`：静置卡片、面板、指标格
- `--st-shadow`：浮层（弹窗、对话框、toast）
- `--st-glow`：focus 环、品牌标记、激活态

## 7. 交互三态

| 组件 | hover | 激活/选中 | focus-visible |
|---|---|---|---|
| tab | `surface-3` 底 | `accent` 填充 + `accent-fg` 字 + glow | 3px ring |
| pill | `tone` 16% 淡底 | `tone` 填充 + `tone-fg` 字 | 3px ring |
| 卡片 | `tone` 45% 描边 | 左侧 3px `tone` 色轨 | — |
| btn | `surface-2` | — | 3px ring |
| btn--tone | 反相为 `tone` 实填充 | — | 3px ring |
| btn--solid | `brightness(1.08)` | 按下回落 | 3px ring |

## 8. 布局原语

- `.pd-app` → `.pd-main`（≥1280px 为 12 栅格，`.pd-col-main` 8 / `.pd-col-side` 4）
- **三段式高度收敛链**：`.pd-pane`(min-height:0) → `.pd-scroll`(flex:1 + min-height:0)。
  `min-height: 0` 生效时完全不可见、缺失时整条链崩塌，是最容易回归的地方。
- 行与栈：`.pd-row` / `.pd-stack` / `.pd-grow`（含 `min-width:0`，truncate 才会生效）

**硬规则：不提供数值型间距 utility。**间距归属于组件，否则就是在重建一套 Tailwind。

## 9. 效果层

CRT 扫描线、磨砂噪点、环境弧光全部保留，但颜色与强度由 token 驱动：
`--crt-opacity` / `--crt-stripe` / `--crt-blend` / `--noise-opacity` / `--noise-blend`。

arctic 亮底需要特殊处理：深色扫描线叠白底会发灰脏，因此降低强度并改用 `multiply` 混合。

> **CRT 开关的特异度契约**：`body.crt-disabled.crt-overlay::after` 靠 (0,2,1) 压制
> (0,1,1) 的 `.crt-overlay::after`。**不要"简化"成单类选择器** —— 那会让开关静默失效
> （已经坏过一次）。

## 10. 无障碍

- 每一对 `tone` / `tone-fg` 组合都必须 ≥ 4.5:1。`tests/verify_ui.py` 会逐主题断言。
- 逐主题覆写只允许改 `--st-*` / `--tone-*`，**绝不触碰那 8 个源变量**。
- 对话框：`role="alertdialog"`，焦点落确认键，Esc 取消（resolve false）、Enter 确认。
- 所有可聚焦元素都有 3px 强调色焦点环。

## 11. Do / Don't

**Do**
- 从 8 个源变量派生所有颜色
- 任何有多种配色变体的组件都用 `data-tone`
- 新 CSS 一律放 `<head>` 的三个 `<style>` 块里

**Don't**
- token 块与 `body[data-theme]` 之外写十六进制色值
- 用 `color-mix(..., transparent)` 生成**表面**（只能用于线与叠在已知表面上的淡色）
- 新增数值型间距 utility
- 引用 `hermes-*`、`retro-border`、`glow-active`、`terminal-output` 或任何 Tailwind 类
  —— 这些已全部移除

> **为什么模板里的 `<style>` 必须放 `<head>`**：Vue 会把模板内的 `<style>` 当作副作用标签忽略，
> CSS 会静默失效。这个坑踩过一次，`tests/verify_ui.py` 里有固化断言。

## v1 → v2 废弃对照表

保留而非删除，以便追溯。

| v1 规则 | 状态 | 原因 |
|---|---|---|
| 圆角上限 `md`(4px) | **废止**，改为 6–16px 阶梯 | 设置面板验证柔和阶梯观感更好；工程识别度由等宽字体 + hairline 承担 |
| "There are no shadows" | **废止**，改为两级阴影 + glow | 表面改不透明后失去了半透明带来的层次暗示 |
| "琥珀是唯一强调色" | **废止**，改为 8 tone 体系 | 4 个安全等级 + 5 个分类无法用一种色相编码；琥珀仍是唯一**交互**强调色 |
| 固定色板 `#041c1c`/`#FFE6CB`/`#FFBD38` | **废止**，改为 7 主题 | 色板现在是一套主题，不是规范本身 |
| success/info/warning/danger "绝不用于按钮" | **废止** | 启动/关闭/强杀按钮按设计就该由 tone 驱动 |
| 要求 JetBrains Mono | **保留并真正实现** | v1 只写了规范，既无 `@font-face` 也无字体文件 |
| `tracking-widest` | **移除** | 属于 Tailwind 词汇，已不再依赖该框架 |
