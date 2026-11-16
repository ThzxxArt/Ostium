# 从 0.1.5 升级到 0.1.6

0.1.6 是 Windows 客户端修复补丁：补齐 `aiosqlite`，把服务重导入移到 SCM
报到之后，避免安装器在核心服务失败时阻断 UI，并补上安装包图标和诊断日志。

## 1. 升级前

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium status
```

`v0.1.5` 的 tag、Release 资产、PyPI 和 GHCR 版本是已发布资产，不会被修改。

## 2. 在线升级

Linux 服务端：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

固定版本：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/download/v0.1.6/install-online.sh \
  | sudo bash -s -- upgrade --version 0.1.6
```

安装器会保留数据、配置、证书、用户、订阅 token 和 `master.key`。如果服务端仍
停留在 0.1.4，本次升级同时包含 0.1.5 的 TOTP 和 Clash 修复。

## 3. Windows 客户端必须重装

运行 `Ostium-0.1.6-windows-x64-setup.exe`。不要只替换 exe，必须重新运行安装包，
因为 0.1.5 的 PyInstaller 包缺少 `aiosqlite`，且服务入口的导入顺序也不同。

安装后验证：

```powershell
Get-Service OstiumCore
Start-Service OstiumCore
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/healthz
```

预期：

- `OstiumCore` 状态为 `Running`；
- `http://127.0.0.1:8787` 可以打开；
- 新开终端运行 `ostium version` 显示 `0.1.6`；
- 安装包和 exe 显示 Ostium 图标。

如果服务仍未启动，查看：

```text
%ProgramData%\Ostium\logs\install.log
%ProgramData%\OstiumCore\logs\service.log
%ProgramData%\OstiumCore\logs\service-bootstrap.log
```

并运行：

```powershell
& "$env:ProgramFiles\Ostium\service\ostium-service.exe" debug
sc.exe qc OstiumCore
```

## 4. 回滚

安装器保留 `venv.old` 和 `pre-upgrade-*` 快照。需要回滚时：

1. 停止 `ostium` 和 `ostium-core`；
2. 恢复升级前快照；
3. 重新安装 0.1.5 wheel/安装包；
4. 保留日志和备份用于诊断。

不要删除 `master.key`；它必须与数据库配套。
