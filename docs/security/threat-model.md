# 安全模型

## 信任边界

| 边界 | 可信 | 不可信 |
|---|---|---|
| 互联网 → 443 | 已认证代理用户 | 扫描器、探测、未认证流量 |
| 互联网 → 管理 UI | 已启用 TLS+TOTP 的管理员 | 公网攻击者 |
| UI 用户 → 核心 API | 持有 token 的 UI 用户 | 同机其他用户 |
| 核心 → sing-box | 固定二进制、已校验 JSON | 任意命令/路径 |
| 浏览器 → 本地 UI | 本地用户 + token | 恶意网页/DNS rebinding |
| 供应链 | 固定版本 + 校验和 | 镜像篡改 |

## 控制措施

- 单管理员、Argon2id、可选 TOTP（公网 UI 强制）、恢复码、会话空闲/绝对过期、登录限速；TOTP 未确认前不激活。
- CSRF double-submit Cookie、Origin 校验、TrustedHost/DNS rebinding 防护、CSP、HTTPS 时 HSTS、`frame-ancestors 'none'`。
- 管理 UI 默认只监听回环；非回环明文必须显式 `allow_insecure_bind`，否则拒绝启动；支持 CIDR allowlist。
- `/api/docs` 与 `/api/openapi.json` 仅管理员可访问；本地登录 token 一次性。
- 核心 API 只监听回环，常量时间比较 Bearer，2 MiB 请求体上限，严格 JSON，角色白名单，端口/路径校验和 `sing-box check`。
- AES-256-GCM 字段加密 + AAD；`master.key` 0600；备份使用 scrypt + AES-256-GCM；明文备份需显式确认。
- 日志脱敏 UUID、token、密码、私钥、代理 URI 和 Authorization 头。
- 订阅 token 哈希查找 + 加密恢复；公开响应设置 `no-referrer`、`no-store`。
- 服务端默认阻止云元数据、回环、link-local、CGNAT、私有网段和 SMTP 25；即使关闭私有网段阻断，25 仍拒绝。
- Webhook 禁止 loopback/link-local/metadata/私有地址；订阅刷新允许 LAN，但禁止 loopback/link-local/metadata。

## 运行身份与 root 模式

默认安装把控制面和 root 隔开：

- 控制面以无特权用户运行；
- 核心只拥有低端口/TUN 所需的最小 capability；
- Web/API 漏洞不能直接获得 root shell。

`--run-as-root` 会取消这层隔离：控制面和核心都以 root 运行。它适合单用户测试机、临时环境或已有容器/虚拟机隔离的场景，但不建议作为生产默认。若使用 root 模式，应额外限制管理 UI 暴露面、启用 TOTP、及时升级，并把它视为“整机信任边界”。

## 残余风险

- 服务器被入侵或扣押会暴露元数据和在线用户。
- Reality/uTLS/Hysteria2 可能被指纹识别或封锁；没有永久隐身保证。
- TUN 的 `strict_route` 不是独立 kill switch。
- 控制面停止时配额执行暂停。
- 核心应用配置会重启子进程，造成短暂断连和采样误差。
- 同用户的本地恶意软件可以控制 VPN，但默认模式不应获得 root shell。
- 开启 Allow LAN 后，混合代理对局域网可见且没有认证；必须用防火墙限制来源，只建议在可信网络使用。
- 未签名 Windows/macOS 构建降低 MITM 抵抗力；请校验 SHA256 或自行构建。
- 上游 sing-box/依赖 0-day 需要及时更新。
- 法律和云服务商 AUP 合规由运营者负责。

## 报告漏洞

不要开公开 issue。使用 GitHub 私密安全公告或 `SECURITY.md` 中的联系方式，附版本、平台、复现步骤，以及受影响的是核心还是控制面。
