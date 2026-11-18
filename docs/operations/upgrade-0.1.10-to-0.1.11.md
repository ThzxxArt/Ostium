# 从 0.1.10 升级到 0.1.11

> 状态：0.1.11 已于 2026-11-17 发布；tag `v0.1.11`、Release、PyPI 和 GHCR 均已发布。
> 本文保留升级步骤，安装公开的 0.1.11 资产前仍以 [发布状态](../release-status.md) 为准。

## 范围

0.1.11 是“可验证性与故障闭环”版本：

- 版本契约：CLI、`/healthz`、`/auth/status`、`/system/info`、`/system/provenance`
  和核心 API 报告可比较的版本、提交和进程信息。
- 安装器只在端口归属、期望版本和核心状态匹配时报告成功。
- 服务端 DNS 默认 `auto`：启动时探测 DoH，成功使用加密 DNS，失败才回退 UDP；
  删除不会生效的第二个 UDP 服务器；配置策略版本提升到 3。
- 诊断覆盖版本、端口、配置漂移、DNS 对照、TLS/代理出口、系统代理、TUN 和磁盘。
- “在线”明确为最近流量窗口；速率在无流量或采集中断后归零。
- 系统代理在核心不可达超过阈值后默认 fail-open（恢复直连），核心恢复后自动恢复。
- 不引入数据库迁移。

## 升级前

1. 记录当前版本和端口归属：

   ```bash
   ostium version --json
   curl -fsS http://127.0.0.1:8443/healthz
   ss -lntp 'sport = :8443' || true
   ss -lntp 'sport = :8788' || true
   ```

2. 备份：

   ```bash
   sudo -u ostium ostium backup create --password '...'
   ```

3. 确认 `v0.1.10` 已发布的 wheel/核心仍在本机或可重新下载，便于回滚。

## 升级服务端

```bash
sudo bash install-online.sh upgrade --version 0.1.11
```

安装器现在会：

- 从 wheel 文件名解析期望版本，并断言 `/healthz` 的 `version` 精确匹配；
- 在启动前检查 8443/8788 的监听进程；只停止可证明属于 Ostium 的旧进程，
  未知进程会报错并保留；
- 首次安装额外要求核心 `/v1/health` 的 `running=true` 且版本匹配。

不要用旧安装器安装 0.1.11：旧安装器只检查 HTTP 200，无法发现旧进程。

## 验证 DNS

```bash
sudo cat /var/lib/ostium/runtime/last-good.meta.json
sudo python3 - <<'PY'
import json
d = json.load(open('/var/lib/ostium/runtime/last-good.json'))
print(json.dumps(d['dns'], indent=2))
PY
```

预期：

- `policy_version` 为 `3`；
- `dns_mode` 为 `doh`（或在 `auto` 下探测失败时为 `udp`，并伴随告警）；
- `dns.servers` 只有一个实际使用的服务器，没有 `local2`；
- 不包含 `223.5.5.5`。

配置项：

```toml
server_dns_mode = "auto"          # auto | doh | udp
server_dns_doh_url = "https://1.1.1.1/dns-query"
```

- `auto`：探测成功使用 DoH，失败回退 UDP 并记录告警。
- `doh`：探测失败时拒绝启动，避免静默降级到不可信 DNS。
- `udp`：显式接受 UDP/53，仅用于已知可信网络。

## 验证客户端

```powershell
ostium version --json
curl.exe -s http://127.0.0.1:8787/healthz
curl.exe -I -x http://127.0.0.1:7897 --max-time 20 https://www.google.com
ostium doctor --json
```

预期：

- CLI、`/healthz`、核心 API 都报告 `0.1.11`；
- `doctor` 的 `version_consistency` 为 `pass`，`port_owner` 的 PID 是当前进程；
- 通过代理访问 Google/Hugging Face 返回 200/302 且 TLS 握手成功。

如果页面仍显示旧版本，先检查 `Get-Process ostium | Select Id,Path,StartTime`；
0.1.11 安装器会在版本不匹配时失败，而不是继续报告成功。

## 系统代理 fail-open

客户端默认：

```toml
system_proxy_fail_open = true
system_proxy_fail_open_seconds = 45
```

核心不可达超过 45 秒后，系统代理会关闭、恢复直连并产生 critical 告警。
核心恢复且未显式 Disconnect 时，代理自动恢复。显式 Disconnect 不会被覆盖。

这不是 kill switch：关闭 fail-open 会让整机流量继续指向已停止的本地端口。

## 回滚到 0.1.10

1. 停控制面。
2. 恢复 0.1.10 wheel/venv 和核心二进制。
3. 如数据库不兼容，恢复升级前备份。
4. 启动并检查 `/healthz`、`/readyz` 和登录。

注意：0.1.10 核心看到 `policy_version: 3` 的 `last-good` 会拒绝启动；0.1.10
控制面启动后会重新生成 policy 2 配置。这段短暂的核心未运行是预期行为，不是升级失败。
