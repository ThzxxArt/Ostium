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
- v0.1.0 没有独立 kill switch。

## ACME 失败

- 确认 A/AAAA 指向本机，公网能访问 80。
- 先用 staging 测试。
- 查看任务错误和 `journalctl -u ostium`。
- 回退到手动上传证书。

## 重载后统计不对

sing-box 计数器在 SIGHUP 后重置。Ostium 会检测下降并开启新 epoch 继续累计；最多丢失一个 5 秒采样。配额不是计费级精度。

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
