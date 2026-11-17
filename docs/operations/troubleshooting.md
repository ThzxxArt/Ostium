# 故障排查

## UI 打不开

- `ostium status` / `systemctl status ostium`
- 检查 `http://127.0.0.1:8443/healthz`
- 如果启用了 `public_ui`，纯 HTTP 失败是预期行为；请用 HTTPS + TOTP
- 修改监听地址后重启 `ostium.service`

## 核心未运行

- `ostium core status`
- `journalctl -u ostium-core -n 100`
- `ostium core version`
- 核心二进制必须在 `<data>/core/sing-box` 或 `OSTIUM_ENGINE_PATH`
- `sing-box check` 失败会保留 last-good 配置；错误会返回 UI 并写日志

## 用户连不上

1. 确认用户已启用、未到期、未超配额。
2. 重新下载订阅（轮换后旧 URL 失效）。
3. 在客户端配置页测试线路。
4. 确认服务器防火墙放行 443/tcp、443/udp。
5. 确认客户端时间在 NTP 容差内（Reality 不用 TOTP，但 TLS 对时间敏感）。

## Hysteria2 启不来

- 需要有效证书；申请或上传后分配给入口。
- 443/udp 必须放行。
- 自签证书需要客户端允许 insecure/pin；公网 UI 不建议自签。

## TUN 失败或泄漏

- TUN 需要核心以 root/SYSTEM 运行，或具备 `CAP_NET_ADMIN`。
- 另一个 VPN 可能占用了网卡或路由表。
- 关闭再开启 TUN；核心崩溃后重启核心清理路由。
- 当前版本没有独立 kill switch。

## ACME 失败

- 确认 A/AAAA 指向本机，公网能访问 80。
- 先用 staging 测试。
- 查看任务错误和 `journalctl -u ostium`。
- 回退到手动上传证书。

## 重载后统计不对

sing-box 计数器在核心子进程重启后重置。Ostium 会检测下降并开启新 epoch 继续累计；最多丢失一个 5 秒采样。配额不是计费级精度。

## 恢复

UI 不可用时，CLI 和数据库仍在：

```bash
ostium doctor --json
ostium backup create --password '...'
sudo systemctl restart ostium-core
```

两个服务都挂了：恢复最近备份，再用本地 SSH 隧道打开 UI。

## 收集诊断

```bash
sudo ostium diagnostics export --output /tmp/ostium-diagnostics.tar.gz
```

诊断包会脱敏 token、密码、UUID、私钥和分享链接。仍然不要发到公开 issue，优先走私密安全渠道。

## 页面版本和 CLI 不一致（0.1.11）

先确认监听端口的进程，而不是只看 HTTP 200：

```bash
ostium version --json
curl -fsS http://127.0.0.1:8443/healthz
curl -fsS -H "Authorization: Bearer $(sudo cat /var/lib/ostium/runtime/cli.token)" \
  http://127.0.0.1:8443/api/v1/system/provenance
```

`/system/provenance` 会返回 `listener.pid`、`listener.exe`、`started_at` 和
`consistency.mismatches`。如果 `listener.pid` 不是当前控制面，说明旧进程仍占着端口；
停止它后重新启动服务。0.1.11 安装器会在版本不匹配时直接失败，不再误报成功。

## DNS 仍然解析错误（0.1.11）

```bash
sudo cat /var/lib/ostium/runtime/last-good.meta.json
```

- `dns_mode=doh`：加密 DNS 已生效。
- `dns_mode=udp` 且配置为 `auto`：DoH 探测失败后回退，查看告警和
  `journalctl -u ostium`；必要时把 `server_dns_mode` 改为 `doh` 让失败显式化。
- 配置为 `doh` 却启动失败：说明 DoH 被网络阻断，先修复网络或显式改为 `udp`。

`local2` 已删除：sing-box 的 `dns.final` 只使用一个服务器，旧配置里的第二个服务器
从未生效。

## “在线”是什么意思（0.1.11）

在线表示“最近 N 秒内观察到流量”（默认 60 秒），不是 TCP 连接数，也不是设备数。
同一用户的多个设备会合并；精确到设备需要定制核心，当前版本不提供。
速率在连续两个采样无流量或统计采集中断后归零。

## 核心崩溃后整机断网（0.1.11）

客户端默认 `system_proxy_fail_open = true`，核心不可达 45 秒后会关闭系统代理并恢复
直连，同时产生 critical 告警。核心恢复后代理自动恢复；显式 Disconnect 不会被覆盖。

这不是 kill switch。若关闭 fail-open，核心故障时系统代理会继续指向已停止的本地端口，
整机流量可能黑洞。可在 Settings 中调整阈值。

## 安装器拒绝未知端口占用

0.1.11 安装器只停止可证明属于 Ostium 的监听进程。遇到未知进程时会输出 PID、路径和
启动时间并退出。先确认该进程用途，再手动停止或修改 UI 端口；安装器不会盲杀。
