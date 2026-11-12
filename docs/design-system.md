# Aurora Console 设计系统

## 原则

- **沉稳的自信**：深空背景、克制的极光强调色、清晰层级。强调色最多占可见面积 5%。
- **每页一个主角**：最重要的状态获得最大视觉权重，其余是支撑证据。
- **渐进披露**：常用操作优先；MTU、栈、原始 JSON 和 diff 放在“高级”里。
- **默认可访问**：键盘、焦点、对比度、减少动画和读屏标签是组件契约的一部分。
- **性能即设计**：模糊只用于框架和主视觉；图表懒加载；表格不做布局动画。

## Token

CSS 变量在 `web/src/styles/tokens.css`，Naive UI 覆盖在 `web/src/design/theme.ts`。页面中不要硬编码颜色。

| Token | 深色 | 浅色 |
|---|---|---|
| `--bg` | `#060911` | `#F4F7FC` |
| `--surface` | `rgba(13,21,36,.78)` | `#FFFFFF` |
| `--surface-2` | `#101A2B` | `#EDF2FA` |
| `--text` | `#EDF3FF` | `#0F172A` |
| `--text-2` | `#A7B6CE` | `#475569` |
| `--accent` | `#5EEAD4` | `#0F766E` |
| `--accent-2` | `#60A5FA` | `#2563EB` |
| `--success` | `#34D399` | `#047857` |
| `--warning` | `#FBBF24` | `#B45309` |
| `--danger` | `#FB7185` | `#BE123C` |

间距以 4px 为基准（8/12/16/20/24/32/40/48）。圆角 8/12/16/24。阴影只表达层级；结构主要靠边框。

## 字体

Inter Variable 自托管。中文回退到 PingFang SC、Microsoft YaHei 或 Noto Sans CJK SC。展示 30/38，H1 24/32，H2 18/26，正文 14/22，小字 12/18，micro 11/16。数字使用 `font-variant-numeric: tabular-nums`。日志使用等宽字体栈。

## 组件

`OPageHeader`、`OSectionCard`、`OStatCard`、`OStatusPill`、`OCopyButton`、`OQrModal`、`OEmptyState`、`OErrorState`、`OSkeletonPage`、`OConnectOrb`、`OTrafficChart`、`OLazyChart`、`OCommandPalette`、`OJobDrawer`、`OShortcutModal`、`OBrandMark`。

规则：

- 每页一个 `h1`（页面标题）。
- 卡片不嵌套卡片；用分隔线和子区块。
- 状态是图标 + 文本，不能只靠颜色。
- 每页都要有空、加载、错误、无权限状态。
- 破坏性操作必须用对话框解释后果。

## 图表

ECharts 自定义调色板。2px 线、12% 面积填充、水平虚线网格、无垂直网格、玻璃浮层 tooltip、300ms 动画。时间序列用线/面积；环图只用于配额/健康。

## 动效

150–220ms，`cubic-bezier(.2,.8,.2,1)`。页面进入为淡入 + 8px 上移。不要持续旋转或闪烁。`prefers-reduced-motion` 下全部关闭。连接状态用缓慢呼吸光，而不是警报。

## 布局

侧边栏 248px（可折叠 76px），顶栏 64px，内容最大 1600px。断点：≥1440、1024–1439、768–1023、<768、<480。手机上侧边栏变抽屉，底部导航保留四个主要入口。

## 验证

Playwright 视觉基线覆盖 1440/1024/390 的深色和浅色；axe 检查 serious/critical；首屏 JS < 300 KB gzip；LCP < 2.5s；INP < 200ms；CLS < 0.05。可用性脚本见 `docs/ux.md`。
