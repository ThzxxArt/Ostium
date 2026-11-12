# 客户端指南

客户端和服务端是同一个 Ostium 包。它在本机运行 Web UI（<http://127.0.0.1:8787>）和一个有特权的核心服务；核心负责混合代理，启用 TUN 时也负责虚拟网卡。

## 一键安装（推荐）

### Windows 10 22H2+ / 11 x64

管理员 PowerShell：

```powershell
irm https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.ps1 | iex
```

脚本会下载并静默运行 Windows 安装包，校验 SHA256，然后打印初始管理员密码。

默认安装：

- 程序在 `%ProgramFiles%\Ostium`；
- `OstiumCore` 服务以 LocalSystem 运行 TUN 核心；
- Web UI 在当前用户登录时启动；
- 数据在 `%ProgramData%\Ostium`；
- 初始密码由在线安装器打印；离线 setup 保存在 `%ProgramData%\Ostium\initial-password.txt`，首次登录后请删除。

需要 UI 也以 SYSTEM 运行（不创建用户级隔离）：

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.ps1))) -RunAsSystem
```

未签名构建会触发 SmartScreen。请先校验 SHA256，确认来源可信后再选择“仍要运行”。

### macOS 14+

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.sh \
  | sudo bash -s -- install --role client
```

默认安装核心 LaunchDaemon 和当前用户 UI LaunchAgent。root 模式：

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role client --run-as-root
```

此时核心和 UI 都作为 LaunchDaemon 以 root 运行。未签名/未公证构建会触发 Gatekeeper。

### Linux x64/arm64

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role client
```

默认创建 `ostium-core` 核心用户和当前用户 UI。注销并重新登录（获得 `ostium` 组）后：

```bash
systemctl --user enable --now ostium
```

root 模式：

```bash
curl -fsSL .../install-online.sh | sudo bash -s -- install --role client --run-as-root
```

不创建用户，核心和 UI 都是系统级 `ostium.service` / `ostium-core.service`。

## 离线安装

Windows：运行 `Ostium-0.1.0-windows-x64-setup.exe`。

macOS：

```bash
sudo ./install-macos.sh client
```

Linux：

```bash
sudo ./install.sh --role client \
  --wheel ./ostium_ctl-0.1.0-py3-none-any.whl \
  --core ./ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz
```

## 第一次连接

1. 打开 <http://127.0.0.1:8787>，完成向导。
2. **Profiles → Import**：粘贴订阅 URL、分享链接、Clash/sing-box 配置或扫描二维码。
3. 在 **Home** 选择配置和线路。
4. 先用 **System proxy**；需要全机 TCP/UDP/DNS 接管时再切 **TUN**。
5. 连接失败时用 **Diagnostics** 检查端口、DNS、路由、TUN、代理和核心状态。

## 模式

| 模式 | 捕获范围 | 限制 |
|---|---|---|
| 混合代理 | 手动设置 `127.0.0.1:7890` 的应用 | 不接管 DNS |
| 系统代理 | 遵循系统代理的应用 | 部分应用会绕过；不接管 DNS |
| TUN | 全机 TCP/UDP/DNS | 需要管理员/root；v0.1.0 无独立 kill switch |

系统代理和 TUN 互斥；切换时会清理旧代理、路由和虚拟网卡。

## 更新

Ostium 不做静默自动更新。使用 **Settings → Check for updates**，下载签名版本，校验后安装。UI 升级时核心继续运行；核心升级会短暂中断隧道。

一键升级：

```bash
sudo bash install-online.sh upgrade
```

Windows 重新运行在线安装器或下载新版 setup.exe 覆盖安装。

## 卸载

### Windows

设置 → 应用 → Ostium → 卸载。卸载器会停止 `OstiumCore`、移除登录任务并尝试恢复系统代理。`%ProgramData%\Ostium` 默认保留。

### macOS

```bash
sudo launchctl unload -w /Library/LaunchDaemons/com.ostium.core.plist
sudo launchctl unload -w /Library/LaunchAgents/com.ostium.ui.plist
sudo rm -f /Library/LaunchDaemons/com.ostium.core.plist
sudo rm -f /Library/LaunchAgents/com.ostium.ui.plist
sudo rm -rf /opt/ostium
# 数据：/Library/Application Support/Ostium（确认后再删）
```

### Linux

```bash
systemctl --user disable --now ostium
sudo systemctl disable --now ostium-core
sudo rm -f /etc/systemd/system/ostium-core.service
rm -f ~/.config/systemd/user/ostium.service
sudo systemctl daemon-reload
systemctl --user daemon-reload

# 卸载前先清理代理/TUN（如果服务还在运行）
ostium proxy off
sudo ostium tun off

sudo rm -rf /opt/ostium
sudo rm -f /usr/local/bin/ostium
# 数据默认保留：/var/lib/ostium-core、/etc/ostium/client.toml
```

一键卸载：

```bash
sudo bash install-online.sh uninstall
# 彻底删除
sudo bash install-online.sh uninstall --purge
```

卸载器会恢复系统代理，并要求核心清理路由和虚拟网卡。
