# 从 0.1.6 升级到 0.1.7

0.1.7 是 Windows 服务入口和安装器日志补丁：修复 SCM 启动时无参数导致的
1053，并让交互安装在最后一步显示实时服务日志。

## 1. 升级前

服务器升级前仍然建议备份：

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium status
```

`v0.1.6` 的 tag、Release 资产、PyPI 和 GHCR 版本是已发布资产，不会被修改。

## 2. Windows 客户端

直接运行 `Ostium-0.1.7-windows-x64-setup.exe` 覆盖安装 0.1.6，不必先卸载。
安装器最后一步会显示 PowerShell 控制台，实时输出：

- 服务注册；
- `Start-Service` 结果；
- 8787 健康检查；
- 失败时的服务状态和日志路径。

静默安装（`/VERYSILENT`）保持隐藏，但同样写入
`%ProgramData%\Ostium\logs\install.log`。

安装后验证：

```powershell
ostium version
Get-Service OstiumCore
Start-Service OstiumCore
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/healthz
```

预期：

- `Ostium 0.1.7`；
- `OstiumCore` 为 `Running`；
- 8787 能打开；
- 安装包和 exe 显示 Ostium 图标。

如果服务仍未启动：

```powershell
Get-Content "$env:ProgramData\OstiumCore\logs\service.log" -Tail 100
Get-Content "$env:ProgramData\OstiumCore\logs\service-bootstrap.log" -Tail 100
Get-Content "$env:ProgramData\Ostium\logs\install.log" -Tail 100
```

## 3. 服务器

0.1.7 不包含服务端功能变更。若服务器已经是 0.1.6，可以不动；如果仍停在
0.1.5 或更早，升级到 0.1.7 会同时包含 TOTP、Clash 和 Windows 修复代码。

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

## 4. 回滚

安装器保留 `venv.old` 和 `pre-upgrade-*` 快照。需要回滚时停止服务、恢复
升级前快照，再安装上一版 wheel/安装包。不要删除 `master.key`。
