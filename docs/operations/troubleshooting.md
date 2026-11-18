# 排障

先运行：

```bash
ostium doctor
ostium status
curl -s http://127.0.0.1:8000/readyz | python -m json.tool
```

## 控制台打不开

- 确认 `ostium-web` 正在运行：`systemctl status ostium-web`。
- 管理面只监听 `127.0.0.1:8000`；公网请用 Caddy 或 SSH 隧道。
- 检查 `ALLOWED_HOSTS` 是否包含访问域名。
- 502：Caddy 无法连接 web；检查 web 健康与端口。

## 登录被锁定

5 次失败后锁定 15 分钟。等待或：

```bash
ostium axes_reset
```

## 安装时报 `venv/bin/python: Permission denied`

安装器必须使用 `/opt/ostium/python` 下由 uv 管理的解释器，不能用 `/root`
下的 Python。若 root 的 `PATH` 先命中 `/root/.local/bin/python3.14`，venv 可能
链接到 `ostium` 用户不可读的路径。

先检查：

```bash
readlink -f /opt/ostium/venv/bin/python
namei -l /opt/ostium/venv/bin/python
```

修复并重新安装：

```bash
export UV_PYTHON_INSTALL_DIR=/opt/ostium/python
export UV_PYTHON_BIN_DIR=/opt/ostium/bin
export UV_PYTHON_PREFERENCE=only-managed
uv python install 3.14
uv venv --python 3.14 --clear /opt/ostium/venv
chmod -R a+rX /opt/ostium/python /opt/ostium/venv
runuser -u ostium -- /opt/ostium/venv/bin/python -V
```

然后重新执行一键安装命令。新版安装器会自动强制 managed Python，并自动
重建指向错误路径的旧 venv。

## 配置一直“待应用”

1. `ostium status` 查看 `last_error`。
2. 常见原因：证书缺失/过期、端口冲突、Reality 密钥缺失、DoH fail-closed。
3. 修复后 `ostium apply` 或重启 worker。
4. 查看 `/var/lib/ostium/logs/sing-box.log`。

## sing-box 未运行

```bash
systemctl status ostium-worker
journalctl -u ostium-worker -n 100 --no-pager
```

- worker 需要 `CAP_NET_BIND_SERVICE` 才能绑定 443。
- 二进制缺少 `with_v2ray_api` 时，stats 不可用；服务器配置本身仍可运行。
- 若 `OSTIUM_SINGBOX_BINARY_SHA256` 设置错误，worker 会拒绝启动。

## 订阅 403

- 用户被禁用、到期或超配额。
- 没有启用线路，或 Hysteria2/Trojan 证书未就绪。
- 检查 `ostium user show <name>` 与「线路」页。

## 订阅 404

- token 错误或已轮换。
- 重新在用户详情页显示/复制链接。

## 订阅 429

- IP 60 次/分钟或 token 120 次/分钟。
- 等待 `Retry-After` 秒，或减少客户端刷新频率。

## 统计为 0

- sing-box 必须用 `with_v2ray_api` 构建。
- 确认 `127.0.0.1:19091` 在监听。
- 第一次采样只建立基线；产生流量后 5–60 秒写入数据库。

## 客户端连不上

- 检查 443/tcp、443/udp 防火墙与云安全组。
- Reality：SNI、公钥、short_id 必须与订阅一致。
- Hysteria2/Trojan：证书必须被客户端信任；自签证书需要 pin。
- Shadowsocks：确认使用 2022 方法与 `server_key:user_key`。

## 恢复数据库后异常

```bash
ostium migrate
ostium collectstatic --noinput
systemctl restart ostium-web ostium-worker ostium-jobs
```

## 收集诊断

```bash
ostium diagnostics export --output /tmp/ostium-diag.tar.gz
```

诊断包包含版本、doctor、运行状态、脱敏配置与日志尾部，不包含 token、密码、私钥。
