# 0.1.11 → 0.1.12 升级

0.1.12 是客户端可靠性补丁，不包含数据库迁移。升级保留用户、凭据、订阅 token、证书、
备份和 `master.key`。

## 一键升级

```bash
sudo bash install-online.sh upgrade --version 0.1.12
```

安装器会：

1. 停止控制面，核心尽量保持运行；
2. 替换 `/opt/ostium/venv` 和核心二进制；
3. 启动并断言 `/healthz` 的版本是 `0.1.12`，且监听端口属于新进程；
4. 失败时回滚旧 venv/核心和数据库快照。

## Windows 客户端

直接运行 `Ostium-0.1.12-windows-x64-setup.exe`。安装器保留
`%ProgramData%\Ostium\config.toml` 和数据库，不会重置模式、端口或订阅。

### 如果 0.1.11 已经留下“断开后 443 仍不通”

0.1.12 的 `OstiumCore` 在启动和 TUN 停止时会清理 `Ostium`/`ostium0`/`sing-box`
的残留路由和虚拟网卡。安装 0.1.12 后重启一次 `OstiumCore` 服务即可触发清理：

```powershell
Restart-Service OstiumCore
```

如果服务重启后仍不通，以管理员 PowerShell 执行
[`docs/guides/tun.md`](../guides/tun.md) 中的一次性修复脚本，或重启一次电脑。该脚本
只删除 Ostium 自己的虚拟网卡路由，不影响 Clash、WireGuard 等其他 VPN。

### 端口与系统代理

- 修改混合端口后，已启用的系统代理会在同一个请求里迁移到新端口；
- 如果 Clash 等程序改写了 WinINET 代理，Ostium 会显示 `stale`，重新连接时重新接管；
- 不要让 Ostium 和 Clash 共用同一个监听端口。系统代理只记录 `IP:port`，无法区分
  两个程序；共用端口会导致“测试连接成功但浏览器走了另一个核心”的假象。

## 回滚

```bash
sudo bash install-online.sh upgrade --version 0.1.11
```

0.1.12 没有数据库结构变更，回滚不需要恢复数据库。回滚后 Windows 客户端也会回到
0.1.11 的旧清理逻辑；如果再次出现残留，使用上面的 TUN 修复脚本。

## 验证

```bash
ostium version --json
curl -fsS http://127.0.0.1:8443/healthz
```

两者都应报告 `0.1.12`。Windows 客户端还应在 **诊断** 页确认：

- 核心 PID 与 7807/配置端口的监听 PID 一致；
- 系统代理显示 `enabled`，且 `ProxyServer` 指向当前 `mixed_port`；
- 断开连接后 `Test-NetConnection <server> -Port 443` 不再被本地残留路由影响。
