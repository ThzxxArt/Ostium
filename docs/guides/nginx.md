# Nginx 共存与反向代理

Ostium 和 Nginx 装在同一台服务器时，先分清三类流量：

| 流量 | 协议 | 能否用 Nginx HTTP 反代 |
|---|---|---|
| 管理 UI / API / WebSocket | HTTP/HTTPS | ✅ 可以 |
| Reality / Trojan | 自定义 TLS（TCP） | ❌ 不能当普通 HTTP 反代 |
| Hysteria2 | QUIC（UDP） | ❌ HTTP 反代不适用 |
| Shadowsocks 2022 | TCP/UDP | ❌ 不能 HTTP 反代 |

所以推荐架构是：

- **Nginx 占 80/443/tcp**，用域名 + Let's Encrypt 证书终止 TLS，反代到 Ostium UI `127.0.0.1:8443`。
- **Ostium 的 Reality/Trojan 改到 9443/tcp（或 9444/tcp）**，继续直连，不走 Nginx。
- **Hysteria2 保留 443/udp**，因为 Nginx 默认只占 TCP 443。如果 Nginx 开了 HTTP/3（`listen 443 quic`），把 Hysteria2 改到 8443/udp。
- 客户端订阅会使用新端口；重新复制订阅即可。

> 不建议为了“保留 443 给 Reality”做 Nginx SNI 分流。Ostium 当前订阅会按入口监听端口生成客户端端口；Nginx 占 443 时 Reality 只能监听别的端口，订阅就会写那个端口。SNI 分流会引入额外维护成本，收益有限。

## 端口规划示例

| 用途 | 地址 | 说明 |
|---|---|---|
| Nginx HTTP | `0.0.0.0:80` | ACME webroot + 跳转 HTTPS |
| Nginx HTTPS | `0.0.0.0:443/tcp` | 管理 UI 域名 |
| Ostium UI | `127.0.0.1:8443` | 只监听回环，由 Nginx 反代 |
| Reality / Trojan | `0.0.0.0:9443/tcp` | 客户端直连 |
| Hysteria2 | `0.0.0.0:443/udp` | Nginx 未开 HTTP/3 时可用 |
| SS2022（可选） | `0.0.0.0:8388` | 默认关闭 |

防火墙放行：`22/tcp`、`80/tcp`、`443/tcp`、`443/udp`、`9443/tcp`（以及你选择的其它代理端口）。

## 第一步：让 Ostium UI 只监听回环

### 新安装

使用一键安装器的反向代理模式：

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.sh \
  | sudo bash -s -- install --role server \
      --domain admin.example.com \
      --behind-proxy
```

`--behind-proxy` 会：

- 把管理 UI 绑定到 `127.0.0.1:8443`；
- 启用 Secure Cookie；
- 把 `admin.example.com` 加入 `trusted_hosts`；
- 不改变代理入口端口（下一步在 UI 里改）。

### 已有安装

编辑 `/etc/ostium/config.toml`：

```toml
role = "server"
host = "127.0.0.1"
port = 8443
public_ui = false
secure_cookies = true
trusted_hosts = ["localhost", "127.0.0.1", "::1", "admin.example.com"]
```

然后：

```bash
sudo systemctl restart ostium
ss -lntp | grep 8443
```

应看到 `127.0.0.1:8443`，而不是 `0.0.0.0:8443`。

> `public_ui = true` 不是 Nginx 反代的必要条件。它主要用于 Ostium 自己要求 TLS+TOTP 的场景；Nginx 终止 TLS 时，保持 `false` 也可以，但 `secure_cookies` 必须为 `true`，且 `trusted_hosts` 必须包含域名。

## 第二步：把 Reality/Trojan 改到 9443

打开 Ostium UI → **Inbounds**：

- Reality：端口改为 `9443`；
- Trojan：如果同时启用，使用另一个 TCP 端口（例如 `9444`），不能和 Reality 共用同一个 TCP 端口；
- Hysteria2：保持 `443/udp`；如果 Nginx 开了 HTTP/3，改为 `8443/udp`；
- 保存并应用。

已启用的用户需要重新复制订阅，客户端才会拿到新端口。

如果只想用 Reality，建议保持 Hysteria2 关闭或使用独立 UDP 端口，避免和 Nginx 的 QUIC 冲突。

## 第三步：安装 Nginx 和证书

Debian/Ubuntu：

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
sudo mkdir -p /var/www/certbot
```

把仓库里的示例配置复制过去（没有源码 checkout 时直接下载）：

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/deploy/nginx/ostium-ui.conf \
  -o /tmp/ostium-ui.conf
sudo cp /tmp/ostium-ui.conf /etc/nginx/conf.d/ostium-ui.conf
sudo editor /etc/nginx/conf.d/ostium-ui.conf
```

至少替换：

- `admin.example.com` → 你的管理域名；
- `ssl_certificate` / `ssl_certificate_key` 路径；
- `proxy_pass http://127.0.0.1:8443;` 如果你改了 UI 端口。

先申请证书（webroot 模式，不需要停 Nginx）：

```bash
sudo certbot certonly --webroot -w /var/www/certbot \
  -d admin.example.com \
  --email you@example.com --agree-tos --no-eff-email
```

检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

自动续期：

```bash
sudo certbot renew --dry-run
sudo certbot renew --deploy-hook "systemctl reload nginx"
```

## 第四步：给 Hysteria2/Trojan 上传证书

Ostium 内置 ACME 会直接绑定 80 端口；Nginx 占用 80 时，点击 **Certificates → Issue → ACME** 会失败（`port_80_unavailable`）。这不是 bug，是端口冲突。

正确做法：

1. 用上面的 certbot 申请证书；
2. 打开 Ostium **Certificates → Upload**；
3. 上传：
   - `/etc/letsencrypt/live/admin.example.com/fullchain.pem`
   - `/etc/letsencrypt/live/admin.example.com/privkey.pem`
4. 域名填 `admin.example.com`（或你给代理单独申请的域名）；
5. 把证书分配给 Hysteria2/Trojan。

Reality 不需要证书，它使用自己的密钥对。

## 第五步：TOTP 与公网 UI 策略

即使 Nginx 已经终止 TLS，也建议：

1. 登录 Ostium；
2. **Settings → Security** 启用 TOTP，保存恢复码；
3. 如需让 Ostium 自己记录“公网 UI”策略，可在 **Settings → Public admin UI** 填域名并开启（需要先有该域名的证书记录）；
4. 重启 `ostium.service`。

如果开启 Public admin UI 后通过 SSH 隧道访问 `http://127.0.0.1:8443`，Secure Cookie 不会发送，登录可能无法保持。请用 `https://admin.example.com` 访问，或临时关闭 `secure_cookies` 调试。

## Nginx 配置要点

示例文件：[`deploy/nginx/ostium-ui.conf`](https://github.com/ThzxxArt/Ostium/blob/main/deploy/nginx/ostium-ui.conf)

关键点：

```nginx
proxy_pass http://127.0.0.1:8443;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection $ostium_connection_upgrade;
proxy_read_timeout 3600s;
proxy_buffering off;
client_max_body_size 100m;
```

- `Host` 必须保留域名，否则 Ostium 返回 `400 invalid Host header`，或 CSRF Origin 校验失败。
- `X-Forwarded-For` 让审计日志拿到真实 IP；Ostium 只在直连方是回环时信任它。
- WebSocket `/api/v1/events` 需要 `Upgrade`/`Connection`。
- 备份/恢复/诊断上传可能较大，`client_max_body_size` 建议 100m。
- `proxy_buffering off` 对实时事件更友好。

## 验证

```bash
curl -I https://admin.example.com
curl -fsS https://admin.example.com/healthz
sudo nginx -t
sudo systemctl status nginx
sudo journalctl -u ostium -n 50
```

浏览器打开 `https://admin.example.com`，登录后检查：

- 页面静态资源正常；
- 实时日志/连接能更新（WebSocket）；
- 用户、订阅、证书页面能正常读写；
- 审计日志里的 IP 是客户端公网 IP，而不是 127.0.0.1。

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| `400 invalid Host header` | `trusted_hosts` 没有域名 | 加入 `admin.example.com` 并重启 Ostium |
| `403 cross-origin request rejected` | Nginx 改了 Host，或 Origin 与 Host 不一致 | 设置 `proxy_set_header Host $host;` |
| 登录成功但立刻掉线 | Secure Cookie 在 HTTP 下不发送 | 用 HTTPS 访问；或临时 `secure_cookies=false` |
| WebSocket 断开/实时不更新 | 缺少 Upgrade 头 | 加 `proxy_http_version 1.1` 和 Upgrade/Connection |
| `502 Bad Gateway` | Ostium 没监听 127.0.0.1:8443 | `ss -lntp \| grep 8443`；`systemctl status ostium` |
| ACME 报 `port_80_unavailable` | Nginx 占用 80 | 用 certbot，或临时停 Nginx |
| Hysteria2 起不来 | Nginx 开了 HTTP/3 占用 443/udp | 关闭 `listen 443 quic`，或把 Hysteria2 改到 8443/udp |
| 代理客户端连不上 | 订阅还是旧端口 | 在 Inbounds 改端口后重新复制订阅 |
| `413 Request Entity Too Large` | Nginx 默认 1m | 提高 `client_max_body_size` |

## 进阶：保留 443 给 Reality/Trojan？

技术上可以用 Nginx `stream` + `ssl_preread` 按 SNI 分流：管理域名进 Nginx HTTPS，Reality 的伪装 SNI 进 Ostium。但它有两个代价：

1. Ostium 的订阅按入口监听端口生成客户端端口；Nginx 占 443 后 Reality 只能监听 9443，订阅会写 9443，除非你手动改客户端配置或给 Ostium 增加“对外端口”字段。
2. Reality/Trojan/Hysteria2 的 TLS/QUIC 行为需要仔细测试，升级 Nginx 或改 SNI 都可能破坏连接。

因此 v0.1.0 的推荐答案是：**Nginx 用 443 做管理 UI，代理协议用 9443/tcp 和 443/udp 直连**。这比 SNI 分流简单、稳定，也更容易排查。
