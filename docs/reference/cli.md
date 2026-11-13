# CLI 参考

所有命令在适用时支持 `--json`。退出码：`0` 成功，`1` 一般错误，`2` 用法错误，`3` 配置保存但未应用（可用全局 `--allow-degraded` 降级为 0），`4` 服务不可用，`5` 权限不足，`6` 核心/绑定错误。

全局选项 `--allow-degraded`：配置应用失败时仍返回 0；默认失败返回 3。也可用环境变量 `OSTIUM_ALLOW_DEGRADED=1`。

| 命令 | 说明 |
|---|---|
| `ostium init --role server\|client` | 初始化数据/配置、管理员和默认入口；服务端默认 `127.0.0.1`，非回环明文需 `--allow-insecure-bind` |
| `ostium serve [--host HOST] [--allow-insecure-bind]` | 运行控制面 / SPA；非回环明文未 opt-in 时退出码 6 |
| `ostium core-run` | 运行特权核心服务（内部命令） |
| `ostium version` | 打印版本和构建信息 |
| `ostium status [--json]` | 本地角色、路径、数据库、核心状态 |
| `ostium open` | 打开本地 Web UI |
| `ostium doctor [--json] [--fix]` | 本地诊断；`--fix` 修复目录/权限/缺失配置 |
| `ostium logs [-f] [--source ostium\|core]` | 查看日志 |
| `ostium connect` / `disconnect` | 客户端通过本地 API 连接/断开 |
| `ostium proxy on\|off\|status` | 操作系统代理；`on` 会先 apply 客户端配置 |
| `ostium tun on\|off\|status` | 通过本地 API 开关 TUN |
| `ostium update [--check]` | `--check` 查询 GitHub 最新 Release 并比较 SemVer；安装始终显式 |
| `ostium diagnostics export` | 导出脱敏诊断包（doctor/配置摘要/日志尾部） |
| `ostium user list\|add\|show\|disable\|enable\|rotate\|remove` | 服务端用户 |
| `ostium user quota <name> --quota 50G --cycle monthly` | 配额 |
| `ostium user subscription <name> [--rotate]` | 打印订阅 URL；使用 `public_base_url` 或 `--domain` 派生的公网地址 |
| `ostium user export <name> --output profile.json` | Ostium Profile v1 |
| `ostium profile list\|import\|refresh\|remove` | 客户端配置 |
| `ostium core install --binary PATH \| --url URL --sha256 HASH` | 安装核心 |
| `ostium core status\|version` | 核心健康/版本 |
| `ostium backup create\|list\|restore` | 备份 |
| `ostium cert list\|issue --self-signed` | 证书 |
| `ostium service install\|uninstall` | systemd 单元（Linux root） |

示例：

```bash
ostium user add alice --quota 100G --cycle monthly --expires 2027-01-01T00:00:00+00:00
ostium user subscription alice
ostium profile import https://vpn.example.com/sub/TOKEN?format=ostium --name HK
ostium backup create --password 'long passphrase'
```

本地 CLI 请求使用 `<data>/runtime/cli.token` 的回环 token。远程自动化请在 **Settings → API tokens** 创建带 scope 的 API token。

> `ostium service install` 只安装默认 systemd 单元。需要 `--run-as-root` 或自定义用户时，请使用一键安装器，或按[服务管理](../guides/service-manager.md)编辑 drop-in。
