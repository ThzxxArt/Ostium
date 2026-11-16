# 从 0.1.7 升级到 0.1.8

0.1.8 修复 Windows UI 登录任务的 PowerShell 包装器：uvicorn 的正常 stderr
不再被 `$ErrorActionPreference="Stop"` 当成终止错误，8787 不会被提前关闭。

## 1. Windows 客户端

直接运行 `Ostium-0.1.8-windows-x64-setup.exe` 覆盖安装 0.1.7，不需要先卸载。
安装最后一步显示实时服务日志。

安装后验证：

```powershell
ostium version
Get-Service OstiumCore
Get-ScheduledTask -TaskName Ostium | Format-List State
Get-ScheduledTaskInfo -TaskName Ostium | Format-List LastTaskResult
curl.exe -i http://127.0.0.1:8787/api/v1/auth/status
```

预期：

- `Ostium 0.1.8`；
- `OstiumCore` 为 `Running`；
- `Ostium` 任务为 `Ready` 或 `Running`；
- `auth/status` 返回 200，`initialized` 为 `false`（首次安装）或 `true`（已有管理员）。

如果浏览器仍显示旧的 “无法读取认证状态”，清除 `127.0.0.1:8787` 的站点数据/
Service Worker，或用无痕窗口打开。

## 2. 服务器

0.1.8 不包含服务端功能变更。服务器已经是 0.1.7 可以不动；仍停留在 0.1.5
或更早时，升级到 0.1.8 会同时包含 TOTP、Clash 和 Windows 修复代码。

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

## 3. 回滚

安装器保留 `venv.old` 和 `pre-upgrade-*` 快照。回滚时停止服务、恢复升级前
快照，再安装上一版 wheel/安装包。不要删除 `master.key`。
