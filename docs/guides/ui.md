# Web UI 指南

服务端打开 `http://127.0.0.1:8443`（建议 SSH 隧道），客户端打开 `http://127.0.0.1:8787`。

## 服务端页面

- **Overview** — 服务脉搏、实时速率、今日流量、在线用户、告警、证书健康和快捷操作。
- **Inbounds** — 启用/禁用 Reality、Hysteria2、Trojan、SS2022；轮换 Reality 密钥；为每个 TLS 线路选择证书；显示端口冲突和 skipped 原因。
- **Users** — 新建/编辑用户、配额、到期、备注、批量操作、流量图、分页/筛选 URL 持久化和订阅入口；在线标签表示最近流量窗口，不是 TCP 连接数。
- **Subscriptions** — 只有在显式“显示令牌”后才展示完整 URL/二维码，显示操作写审计；支持标准分享链接。
- **Subscriptions** — 四种格式、复制、二维码、token 轮换。
- **Connections** — 实时连接表，支持搜索和关闭。
- **Routing** — 规则优先级、动作、测试面板和远程规则集。
- **Certificates** — ACME/自签/上传、到期环、续期和分配；临期证书不再显示为 ready。
- **Logs / Jobs / Audit** — 观察控制面和长任务。
- **System** — 主机指标、服务、doctor 和脱敏诊断；warn/fail 分开计数。
- **Settings** — 主题/语言、安全、TOTP、API token、IP allowlist、通知、备份、DNS、fail-open 和公网 UI 策略；“关于”显示版本、commit、PID、核心/Web 构建和版本一致性。

## 客户端页面

- **Home** — 大号连接球、配置/线路选择、实时速率、模式标签和“测试连接”；核心运行但未测试时显示 Core running，出口测试失败时显示 Egress test failed。
- **Profiles** — 导入 URL/分享链接/二维码，刷新，选择线路。
- **Routing** — 智能/全局/直连/自定义预设和规则。
- **Network** — 混合/系统代理/TUN、端口、监听进程、TUN 可用性、Allow LAN 和系统代理 fail-open 状态。
- **Statistics** — 流量趋势和活跃目标。
- **Diagnostics** — 按版本/端口/核心/DNS/出口分组，支持测试连接、复制报告和下载脱敏诊断包。
- **Logs / Settings** — 与服务端共用。

## 命令面板

按 `Cmd/Ctrl+K`，输入页面、操作或用户名。`↑/↓` 选择，`Enter` 打开，`Esc` 关闭。最近使用会记在本地。按 `?` 查看完整快捷键。

## 主题与语言

- 深色/浅色主题即时切换，不需要刷新。
- 中文/英文界面即时切换。
- 手机端侧边栏变为抽屉，底部保留四个主要入口。
- PWA 支持离线壳和更新提示。
