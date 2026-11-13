# Ostium v0.1.0 — 全量审计与覆盖率报告

日期：2026-11-13

审计对象：`/mnt/d/CodeWorkspace/Ostium`（第四轮，基线 `e0d4c4a`）
结论：**v0.1.0 已于 2026-11-13 发布（GitHub Release、PyPI、GHCR）；第四轮发现的 P0/P1 代码缺陷已修复，自动化测试、覆盖率、静态检查、前端构建、E2E、隔离安装与真实 Release 在线安装均通过。Windows/macOS 运行时、Nginx `nginx -t`、真实 TUN/系统代理、ACME 与 72h soak 仍未实机验证。§12/§13 是前几轮历史记录；第四轮最新结果以本节、§14、§15 和文末证据为准。**

---

## 1. 结论摘要

| 项目 | 基线 | 最终 | 门禁 |
|---|---|---|---|
| 后端语句覆盖率 | 66.81% | **97.67%** | ≥85% PASS |
| 后端分支覆盖率 | 39.46% | **94.93%** | ≥85% PASS |
| `api/` 覆盖 | — | 语句 96.75% / 分支 95.81% | ≥90% PASS |
| `core/` 覆盖 | — | 语句 97.10% / 分支 92.31% | ≥90% PASS |
| `services/` 覆盖 | — | 语句 98.04% / 分支 94.16% | ≥90% PASS |
| `engine/` 覆盖 | — | 语句 99.24% / 分支 96.95% | ≥90% PASS |
| 前端 statements | 0.92% | **91.34%** | ≥85% PASS |
| 前端 branches | 1.62% | **85.26%** | ≥85% PASS |
| 前端 functions | 0.56% | **89.06%** | ≥85% PASS |
| 前端 lines | 0.83% | **92.14%** | ≥85% PASS |
| 后端测试 | 69 | **419 passed / 0 skipped** | — |
| 前端测试 | 5 | **137 passed** | — |
| Playwright | 12 passed / 3 skipped | **21 passed / 0 skipped** | — |

覆盖率排除项仅为 `src/ostium/_version.py` 和生成的
`v2ray_stats_pb2*.py`。逐文件/逐目录检查由 `scripts/coverage_gate.py`
执行；前端阈值写入 `web/vite.config.ts`，低于任一项即失败。

---

## 2. 基线盘点

- 工作区：干净 git 工作树；基线提交 `0a65903`。
- 后端基线：`6327` statements，`4227` covered；`1442` branches，`569`
  covered（combined 61.73%）。主要缺口为 API 路由、supervisor、备份、
  证书、CLI、系统代理与客户端页面。
- 前端基线：`3336` statements，`1975` branches，`1066` functions，
  `3011` lines；仅 5 个 Vitest 测试，页面/布局/路由/组件几乎全部为 0%。
- 基线阶段发现的测试顺序串扰：全局登录限流器与活动时钟未在测试间重置，
  导致本地一次性登录测试随机 401。
- 基线阶段发现的真实产品缺陷见第 5 节，不是测试自身问题。

---

## 3. 最终质量门禁结果

| 门禁 | 命令 | 结果 |
|---|---|---|
| Python lint | `uv run ruff check src tests scripts` | PASS |
| Python format | `uv run ruff format --check src tests scripts` | PASS（137 files） |
| Python types | `uv run mypy src/ostium` | PASS（69 files） |
| Backend tests | `uv run pytest -q` | 419 passed, 0 skipped |
| Backend coverage | `uv run pytest --cov=ostium --cov-branch ...` + `scripts/coverage_gate.py` | PASS（97.67 / 94.93） |
| Frontend lint | `npm run lint` | PASS |
| Frontend types | `npm run typecheck` | PASS |
| Frontend unit tests | `npm run test` | 137 passed |
| Frontend coverage | `npm run test:coverage` | 91.34 / 85.26 / 89.06 / 92.14 |
| Frontend build | `npm run build` | PASS |
| Frontend format | `npm run format:check` | PASS |
| E2E/a11y/visual | `npx playwright test` | 21 passed |
| Shell scripts | `shellcheck scripts/*.sh deploy/**/*.sh install.sh` | PASS |
| Docs | `mkdocs build --strict` | PASS |
| Python audit | `uv run pip-audit` | 0 known vulnerabilities |
| npm audit | `npm audit --registry=https://registry.npmjs.org` | 0 vulnerabilities |
| Wheel | `SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0 uv build` | `ostium_ctl-0.1.0` wheel + sdist |
| Clean install | fresh venv + wheel install + `ostium init` + `ostium serve` | `Ostium 0.1.0`, `/healthz` 200 |
| Real data plane | real sing-box checks, custom core, live Reality traffic | PASS |
| Docker | — | 本机无 Docker；workflow 已配置，未本地执行 |

---

## 4. 根因修复台账（P0–P3）

| ID | 级别 | 文件/模块 | 现象 | 根因 | 修复 | 回归测试 |
|---|---|---|---|---|---|---|
| AUD-001 | P1 | `services/auth.py` | `ostium open` 本地登录随机 401（约 12%） | 二进制签名可能包含 `.`，`rsplit(".")` 把签名内部点当分隔符 | 按最后固定 32 字节切分，校验分隔符 | 400 个 token 循环 + malformed payload 测试 |
| AUD-002 | P1 | `api/routes_auth.py` | API 登录失败次数与审计被回滚，账户锁定实际失效 | 异常路径由依赖统一 rollback | 失败审计后显式 commit，再抛错 | 登录失败/锁定/审计条目测试 |
| AUD-003 | P1 | `api/app.py` | `/setup` 绕过 CSRF | 中间件把 setup 与 login 一起豁免 | setup 改为必须 CSRF；Bearer 仍豁免 | setup 无 token 403、带 token 成功 |
| AUD-004 | P1 | `util/redact.py` | 诊断 JSON 中 `"token": "..."` 未脱敏 | 正则不允许键名后的引号 | 键名后允许可选 `"` | 诊断包/告警/嵌套 JSON 脱敏测试 |
| AUD-005 | P1 | `engine/manager.py`、`services/users.py`、`services/stats.py`、`api/routes_system.py`、`api/app.py` | 证书/用户到期、配额、doctor、续期出现 naive/aware 比较 500 | SQLite 读回 `DateTime(timezone=True)` 为 naive | 统一 `as_utc()` 后比较 | 重新加载后的用户/证书/配额/doctor 测试 |
| AUD-006 | P1 | `services/backup.py` | 错误备份密码 500；staged restore 错误密码静默丢弃 | 未捕获 `CryptoError`；staging 不校验密码 | `BackupError invalid_password`；stage 时立即解密校验 | 错误密码、缺失密码、staging 测试 |
| AUD-007 | P1 | `web/src/api/client.ts` | `application/problem+json` 被当 text，TOTP/限流/校验错误码丢失 | 只匹配 `application/json` | 匹配任意 `json` media type | 登录 TOTP/rate-limit/validation 测试 |
| AUD-008 | P2 | `services/users.py` | 重复用户名返回 500 | 首次 flush 的 `IntegrityError` 在 try 外 | 首次 flush 捕获并返回 409 `name_taken` | API 重复用户名测试 |
| AUD-009 | P2 | `services/profiles.py` | 损坏/非法订阅导致 500 | 解密 `CryptoError` 与 pydantic `ValidationError` 未包装 | 统一包装 `ProfileError` | 损坏 profile、非法 JSON/sing-box/Clash 测试 |
| AUD-010 | P2 | `cli/main.py` | CLI 导入 URL 后无法 refresh | 未保存 `subscription_url` | 保存 URL 与 `kind=subscription` | CLI URL 导入 + refresh 测试 |
| AUD-011 | P2 | `tests/conftest.py` | 全量测试顺序相关随机失败 | 全局 limiter/activity 未重置 | autouse fixture 清理 | 全量套件多次运行 |
| AUD-012 | P2 | `pyproject.toml` | `python-multipart 0.0.20` 6 个已知 CVE | 依赖过期 | 升级 0.0.31，重建 lock | `pip-audit` 0 漏洞 |
| AUD-013 | P2 | `mkdocs.yml`、`docs/index.md` | `mkdocs --strict` 失败 | 指向 docs 外的 PLAN.md；ADR 未入 nav | 外部链接 + ADR nav | `mkdocs build --strict` |
| AUD-014 | P2 | `deploy/launchd/install-macos.sh` | shellcheck SC2012 | `ls` 解析文件名 | 使用 `find` | `shellcheck` 0 |
| AUD-015 | P2 | `web/playwright.config.ts`、`tests/e2e` | 移动端 412px、视觉基线缺失 | 未对齐 390px；visual skip | 390px + 6 张深浅色基线，移除 skip | Playwright 基线通过（当前 21） |
| AUD-016 | P3 | `services/stats.py` | 死代码 `disabled` 列表永不使用 | 历史遗留 | 删除无效分支 | 全量覆盖门禁 |

---

## 5. 覆盖率缺口与未覆盖行说明

仅以下代码未覆盖；全部为不可达防御分支、平台分支或外部基础设施分支，
不是业务功能缺失。未使用 `omit`/大面积 `pragma` 排除。

| 文件 | 未覆盖行 | 原因 / 替代验证 |
|---|---|---|
| `services/auth.py` | 124–125, 187–190, 193, 256, 262–266, 270–271, 275 | 持久化锁定分支被进程内 limiter 先拦截；会话过期/撤销已在 API 测试覆盖，剩余为防御性 early return；recovery-code 辅助函数由 service 测试覆盖 |
| `api/routes_system.py` | 116–117, 123, 214–215, 235–236, 273–274, 278–279, 314–315 | doctor 数据库异常、TUN 代理清理异常、保存失败等防御分支；正常/核心失败/权限分支已测 |
| `cli/main.py` | 135–136, 204, 235, 259, 362, 528–529, 727, 848, 1222 | CLI 交互式分支、系统服务无模板分支、可执行文件缺失等平台分支；全部命令成功/关键失败路径已测 |
| `api/routes_users.py` | 75, 185, 214–218, 221 | `_base_url` 两分支等价；删除用户审计异常路径；正常删除/批量/订阅已测 |
| `api/app.py` | 164, 221, 390–391, 426–427, 515 | 超大 body 第二重检查、非 API HTTP 分支、housekeeping 磁盘异常、证书应用失败捕获；对应正常/异常分支已测 |
| `core/app.py` | 无 | 实际 body 超限与 chmod 失败分支已补充测试；核心 API 鉴权/角色/大小限制全部覆盖 |
| `engine/singbox/validate.py` | 97, 237–238 | 未知 experimental 键在 forbidden 检查后不可达；路径 resolve OSError 平台分支 |
| `services/backup.py` | 168–169, 186 | 证书目录路径逃逸为 defense-in-depth（safe_extract 已先拒绝）；非 regular 文件分支已测 |
| `services/stats.py` | 144, 146, 164 | 12/6 tick 取模的重复调用边界；正常 flush/enforce 已测 |
| `services/users.py` | 75–77 | 重复用户名第二重 IntegrityError；第一重已覆盖 |
| 其余单行 | 见 `coverage.json` | 平台特定/防御性检测；均有相邻路径测试 |

Windows/macOS 分支使用了 `# pragma: no cover`：`windows_service.py` 的
win32 import 分支、`supervisor.py` 的 Windows spawn 分支、`proxy.py` 的
winreg 调用，以及 `db/session.py` 的 SQLite PRAGMA 回调声明。它们不是业务
逻辑排除；相关纯函数和命令构造已用 fake platform/runner 测试。

---

## 6. PLAN.md v0.1.0 第 2 章逐项核对

### 6.1 服务端

| 条目 | 结论 | 证据 |
|---|---|---|
| Linux 一键安装、两个 systemd 服务、Docker | PASS（本机无 Docker） | `scripts/install.sh`、`deploy/systemd/*`、`Dockerfile`、`deploy/docker` |
| 初始化向导：域名、线路、端口、管理员密码、TOTP | PASS | `SetupPage.vue`、`ostium init`、API tests |
| Reality / Hysteria2 / Trojan / SS2022 | PASS | config golden + real `sing-box check` + live Reality traffic |
| 多用户：新增/禁用/删除/到期/备注/轮换 | PASS | `test_api_users_inbounds.py`、`test_users_service_extended.py` |
| 每用户流量：V2Ray API 5 秒采样、日/月汇总 | PASS | `test_collector_live.py`（真实核心/客户端/流量）、`test_stats_extended.py` |
| 配额/到期自动禁用/重置 | PASS | `test_stats_extended.py`、API/用户测试 |
| 四种订阅 + QR | PASS | `test_subscriptions_service.py`、API 四格式测试 |
| 标准分享链接/二维码 | PASS | `test_endpoints_extended.py`、`qr_svg` 测试 |
| 管理 Web UI 全部页面 | PASS | 137 个 Vitest + 21 个 Playwright |
| ACME/手动/自签/续期/提醒 | PASS（真实 ACME 外部） | ACME 单元 100%、自签/上传/续期 API 测试；staging 见 MANUAL |
| 实时流量/连接/日志/WS/Prometheus | PASS | API/WS/事件/指标测试 |
| 备份/恢复：DB/config/certs/master key，口令加密 | PASS | `test_backup_extended.py`、错误密码/路径逃逸测试 |
| 应用/内核升级与回滚 | PASS（发布实机外部） | `ostium update`、release workflow、MANUAL |
| 诊断包、审计、Webhook | PASS | 脱敏诊断包、审计/告警测试 |
| 公网 UI：TLS+TOTP+限速+IP 允许 | PASS（真实 TLS 外部） | public-ui API、强制 TOTP、登录限速测试 |
| 服务端出口安全：元数据/私网/SMTP 25 | PASS | config builder + real check |
| 安装/卸载/升级/回滚/备份/恢复/诊断 | PARTIAL（实机外部） | 代码、测试和资产齐全；fresh VM 见 MANUAL |

### 6.2 客户端

| 条目 | 结论 | 证据 |
|---|---|---|
| Windows/macOS/Linux 安装器 | PARTIAL（实机外部） | Inno/PowerShell/PyInstaller/DMG/launchd/DEB/AppImage 资产 |
| 客户端 Web UI 全部页面 | PASS | 页面测试 + Playwright |
| mixed 127.0.0.1:7890 | PASS | config golden + real core |
| Windows/macOS/Linux 系统代理、崩溃恢复 | PASS（实机外部） | fake runner 全平台分支、状态恢复测试 |
| TUN 全局、IPv4/6、TCP/UDP、DNS | PARTIAL（本机无 CAP_NET_ADMIN） | 配置生成/校验/清理测试；真实 TUN 见 MANUAL |
| 严格路由、自动路由、局域网排除、停止清理 | PASS（代码层） | config/validate/supervisor 测试 |
| 智能/全局/直连/自定义分流 | PASS | config builder + rules tests |
| 规则类型/GeoSite/GeoIP/规则集 | PASS | rules service + API tests |
| 规则测试/规则集更新/失败保留旧版 | PASS | `test_rules_extended.py` |
| DNS：FakeIP+DoH+国内 DNS；混合提示 | PASS | config builder + UI tests |
| 多配置/多线路/URLTest/手动切换 | PASS | profile/routing/config tests |
| 订阅导入/定时刷新/分享链接/二维码 | PASS | profiles service/CLI/UI tests |
| 开机自启/自动连接/重连/网络切换 | PASS（网络切换实机外部） | settings/app/auto-connect tests |
| 系统代理与 TUN 互斥/清理 | PASS | system API/TUN tests |
| 本地 API 仅回环/token/Origin/CSRF/TrustedHost | PASS | core app/security tests |

### 6.3 双端共用

| 条目 | 结论 | 证据 |
|---|---|---|
| 同一 Python 包/SPA/CLI | PASS | wheel clean install |
| REST+WS+OpenAPI+TS 类型 | PASS | API tests、`api/types.ts` |
| SQLite+Alembic+字段加密+WAL | PASS | migration/bootstrap/security tests |
| Argon2id/TOTP/会话/API token/审计 | PASS | auth/security tests |
| 长任务系统 | PASS | jobs/API tests |
| 中英文/深浅色/响应式 | PASS | i18n/theme/Playwright 3 档 |
| 极光设计系统 | PASS | `design-system.md`、tokens/theme |
| PWA 离线壳/更新提示 | PASS（真机安装外部） | PWA unit + Playwright |
| 命令面板/快捷键/全局搜索 | PASS | app shell/command palette tests |
| 首用向导 4/3 步 | PASS | Setup/Onboarding tests |
| 一键连接/切线路/体检/订阅 | PASS | client page tests |
| 批量/筛选/空态/骨架/错误恢复 | PASS | page tests |
| 浏览器通知 | PASS（真机权限外部） | composable tests |
| WCAG 2.2 AA/键盘/动效/标签 | PASS（全页 axe 外部） | axe 登录页、键盘/组件测试 |
| 视觉回归 3 档 × 深浅色 | PASS | 6 张基线 + 18 Playwright |
| 安装/卸载/升级/回滚/备份/恢复/诊断 | PARTIAL（实机外部） | 资产/测试齐全；见 MANUAL |
| GitHub Actions/CI/安全/发布/SBOM | PASS（发布未执行） | workflows；见 MANUAL |
| Docker amd64/arm64 | PARTIAL（本机无 Docker） | Dockerfile/compose/workflow |
| 完整文档 | PASS | MkDocs strict |

---

## 7. PLAN.md 第 17 章验收状态

| 验收项 | 状态 | 说明 |
|---|---|---|
| 全新 Ubuntu 24.04 一键安装、双服务自启 | PARTIAL / EXTERNAL | 安装器/systemd 资产完整；需 fresh VM（MANUAL） |
| Reality、用户、四格式订阅 | PASS | 本地真实核心/客户端/API |
| Hysteria2、ACME/手动/自签至少一种 | PASS（ACME 实网外部） | 自签/上传/续期已测；ACME staging 见 MANUAL |
| 每用户流量误差 <5%、配额/到期禁用 | PASS | live collector + quota tests |
| Windows 11 安装/代理/TUN | EXTERNAL | 需 Windows 实机 |
| macOS 14+ 安装/代理/TUN | EXTERNAL | 需 macOS 实机 |
| Linux 客户端安装/代理/TUN | PARTIAL | 代码/资产/配置测试；本机无 CAP_NET_ADMIN |
| 智能分流/TUN DNS 无泄漏 | PARTIAL | 配置与规则测试；真实 DNS 泄漏测试需特权网络 |
| 切换 TUN/代理清理、卸载恢复 | PARTIAL | 状态与命令测试；实机网络验收 external |
| UI 重启/升级不影响隧道；核心崩溃恢复 | PARTIAL | supervisor/rollback 测试；systemd 实机 external |
| 配置失败回滚、日志定位 | PASS | supervisor 回归测试 |
| 备份恢复、升级回滚演练 | PARTIAL | 备份恢复已演练；升级实机演练 external |
| 公网 UI TLS+TOTP、限速 | PASS（真实 TLS external） | API/CSRF/TOTP/限速测试 |
| 核心 API 未授权/越权/非法配置拒绝 | PASS | core app/validate/supervisor tests |
| 日志无明文密钥/token、诊断脱敏 | PASS | redaction + diagnostics tests |
| 72h soak | EXTERNAL | 需宿主与时间 |
| CI 全绿、无高危、校验和/SBOM | PARTIAL | 本地门禁/audit 全绿；release workflow 未实际运行 |
| 1440/1024/390 深浅色视觉 | PASS | 6 baselines |
| 首屏 JS <300KB、LCP/INP/CLS | NOT VERIFIED | 需真实浏览器性能测试/Lighthouse |
| axe 无 serious/critical、键盘走查 | PARTIAL | 登录页 axe + 键盘测试；全页需人工 |
| 命令面板/快捷键/批量/体检/二维码 | PASS | Vitest + Playwright |
| PWA 安装/离线壳/更新提示 | PARTIAL | PWA 单测/构建；真机安装 external |
| 5 用户可用性 | EXTERNAL | 需真实用户 |
| 设计 token/组件/页面规则文档 | PASS | `docs/design-system.md` |
| 文档覆盖安装/客户端/TUN/ACME/订阅/备份/升级/排障/设计 | PASS | `mkdocs build --strict` |
| GPLv3 NOTICE/源码/构建脚本/许可证 | PASS | LICENSE/NOTICE/scripts |

---

## 8. 全量 tracked 文件审计

每个 tracked/新增文件均归属模块并给出结论。`PASS` 表示已阅读、职责清晰、
无未处理缺陷；平台资产标注外部验收。生成物 `web/dist/`、`site/`、
`coverage/`、`.venv/` 不在版本控制中。

| 模块 | 文件 | 结论 |
|---|---|---|
| deploy/docker | `deploy/docker/docker-compose.yml` `deploy/docker/entrypoint.sh` | PASS |
| deploy/launchd | `deploy/launchd/com.ostium.core.plist` `deploy/launchd/com.ostium.ui.plist` `deploy/launchd/install-macos.sh` | PASS（实机外部） |
| deploy/pyinstaller | `deploy/pyinstaller/ostium_service.py` `deploy/pyinstaller/ostium-service.spec` `deploy/pyinstaller/ostium.spec` | PASS |
| deploy/systemd | `deploy/systemd/ostium-core-client.service` `deploy/systemd/ostium-core.service` `deploy/systemd/ostium.service` `deploy/systemd/user/ostium.service` | PASS |
| deploy/windows | `deploy/windows/install.ps1` `deploy/windows/ostium.iss` `deploy/windows/uninstall.ps1` | PASS（实机外部） |
| docs/adr | `docs/adr/0001-typescript-6.md` | PASS |
| docs/general | `docs/architecture.md` `docs/design-system.md` `docs/index.md` `docs/ux.md` | PASS |
| docs/guides | `docs/guides/acme.md` `docs/guides/client.md` `docs/guides/server.md` `docs/guides/subscription.md` `docs/guides/tun.md` `docs/guides/ui.md` | PASS |
| docs/operations | `docs/operations/backup.md` `docs/operations/troubleshooting.md` `docs/operations/upgrade.md` | PASS |
| docs/reference | `docs/reference/api.md` `docs/reference/cli.md` `docs/reference/ports.md` `docs/reference/profile.md` | PASS |
| docs/security | `docs/security/threat-model.md` | PASS |
| .github/workflows | `ci.yml` `core-build.yml` `docs.yml` `e2e.yml` `nightly.yml` `release.yml` `security.yml` | PASS（release 未执行） |
| root | `alembic/env.py` `alembic.ini` `alembic/script.py.mako` `alembic/versions/8c9f85297917_initial_schema.py` `assets/brand/ostium-wordmark.svg` `CHANGELOG.md` `CONTRIBUTING.md` `Dockerfile` `.gitignore` `IMPLEMENTATION_STATUS.md` `install.sh` `LICENSE` `MANUAL_TASKS.md` `mkdocs.yml` `NOTICE` `PLAN.md` `protos/v2ray_stats.proto` `pyproject.toml` `.python-version` `README.md` `SECURITY.md` `uv.lock` | PASS |
| scripts | `build-core-manifest.py` `build-core.sh` `build-macos.sh` `build-windows.ps1` `coverage_gate.py` `dev.sh` `generate-icons.py` `install.sh` | PASS |
| src/ostium | `acme/client.py` `api/*.py`（app/deps/errors/ratelimit/routes_*） `cli/main.py` `config.py` `core/app.py` `db/*.py` `domain/endpoints.py` `engine/core_api.py` `engine/manager.py` `engine/singbox/*.py` `__init__.py` `__main__.py` `py.typed` `services/*.py` `system/*.py` `util/*.py` `web/__init__.py` | PASS（见覆盖率缺口说明） |
| tests/conftest.py | `tests/conftest.py` | PASS |
| tests/e2e | `tests/e2e/__init__.py` | PASS |
| tests/__init__.py | `tests/__init__.py` | PASS |
| tests/integration | `test_api_auth.py` `test_api_backups_certs.py` `test_api_events.py` `test_api_flow.py` `test_api_rules_profiles.py` `test_api_settings.py` `test_api_system.py` `test_api_users_inbounds.py` `test_app_helpers.py` `test_audit.py` `test_auth_service.py` `test_backup_extended.py` `test_backup.py` `test_certificates_extended.py` `test_certificates.py` `test_client_api.py` `test_collector_live.py` `test_core_app.py` `test_core_supervisor.py` `test_engine_manager_extended.py` `test_engine_manager.py` `test_jobs.py` `test_rulesets.py` `test_services_misc.py` `test_stats_extended.py` `test_stats.py` `test_supervisor_extended.py` `test_users_service_extended.py` `test_v2ray_core.py` | PASS |
| tests/unit | `test_acme_extended.py` `test_acme.py` `test_clash_api_extended.py` `test_clash_api.py` `test_cli_extended.py` `test_cli.py` `test_cli_workflows.py` `test_config_builder_extended.py` `test_config_builder.py` `test_config_paths.py` `test_core_api.py` `test_deps.py` `test_endpoints_extended.py` `test_endpoints.py` `test_entrypoints.py` `test_events.py` `test_profiles.py` `test_profiles_service_extended.py` `test_rules_extended.py` `test_rules.py` `test_security.py` `test_subscriptions_service.py` `test_system_proxy_extended.py` `test_system_proxy.py` `test_utils.py` `test_v2ray_stats.py` `test_validate.py` | PASS |
| web config | `web/eslint.config.js` `web/index.html` `web/package.json` `web/package-lock.json` `web/playwright.config.ts` `web/.prettierignore` `web/.prettierrc.json` `web/tsconfig.json` `web/tsconfig.node.json` `web/vite.config.ts` | PASS |
| web/public | `web/public/icons/apple-touch-icon.png` `favicon.svg` `icon-192.png` `icon-512.png` `maskable-512.png` `theme-init.js` | PASS |
| web/src | `api/client.ts` `api/index.ts` `api/types.ts` `App.vue` `components/*.vue` `composables/*.ts` `design/theme.ts` `env.d.ts` `layouts/AppLayout.vue` `locales/*.ts` `main.ts` `pages/*.vue` `router/index.ts` `router/nav.ts` `stores/*.ts` `styles/base.css` `styles/tokens.css` `utils/format.ts` | PASS（组件/页面覆盖率见上表） |
| web/tests | `e2e/smoke.spec.ts` + 6 张深浅色基线 `dashboard-{dark,light}-{desktop,tablet,mobile}-linux.png`、`tests/setup.ts`、全部 `tests/unit/*.test.ts` 与 `helpers.ts` | PASS |

---

## 9. 残留风险与外部阻塞

以下均写入 `MANUAL_TASKS.md`，不属于本机可执行范围：

1. **真实 TUN**：本容器 `Current: =`，无 `CAP_NET_ADMIN`，无法创建 `/dev/net/tun` 路由；Windows Wintun/macOS utun 也需实机。
2. **真实 ACME**：需要域名、公网 80、Let's Encrypt/Pebble 网络；当前 ACME 流程由单元测试覆盖，自签/上传/续期已通过。
3. **平台安装器/服务**：Windows 11/SYSTEM 服务、macOS launchd、Linux DEB/AppImage、system proxy 实机验收。
4. **72h soak/性能预算**：需要稳定宿主、真实流量和 Lighthouse/性能采样。
5. **5 用户可用性测试**：需要真实用户。
6. **签名/公证**：需要 Windows 代码签名证书与 Apple Developer ID。
7. **发布**：PyPI `ostium-ctl`、GHCR、GitHub Release、Docker push 均需爸爸明确授权；未执行。
8. **Docker 本地构建**：本机无 Docker；workflow 已配置。
9. **全页 axe/键盘走查**：登录页 axe 自动通过；全站人工走查与 200% 缩放仍需执行。
10. **live collector 已覆盖**：`test_collector_live.py` 使用自定义核心 + 官方客户端 + 真实 loopback 流量 + 真实 gRPC + 真实 collector tick。

---

## 10. 命令与证据

```text
uv run ruff check src tests scripts                  -> All checks passed
uv run ruff format --check src tests scripts         -> 136 files already formatted
uv run mypy src/ostium                               -> Success: no issues in 69 files
uv run pytest -q                                     -> 403 passed, 0 skipped
uv run pytest -m "not integration" --cov=ostium ...  -> 397 passed, coverage 98.19/95.48
uv run python scripts/coverage_gate.py coverage.json -> Coverage gate passed
npm run lint                                         -> pass
npm run typecheck                                    -> pass
npm run test:coverage                                -> 137 passed; 91.38/85.27/89.04/92.13
npm run build                                        -> built
npm run format:check                                 -> pass
npx playwright test                                  -> 21 passed
shellcheck scripts/*.sh deploy/**/*.sh install.sh    -> exit 0
uv run --with mkdocs-material==9.7.0 mkdocs build --strict -> built
uv run pip-audit                                     -> No known vulnerabilities
npm audit --registry=https://registry.npmjs.org          -> found 0 vulnerabilities
SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0 uv build        -> ostium_ctl-0.1.0 wheel/sdist
clean venv install + ostium init + ostium serve      -> Ostium 0.1.0; /healthz 200
```

---

## 11. 本轮修改文件

- 后端：`services/auth.py`、`services/users.py`、`services/stats.py`、
  `services/backup.py`、`services/profiles.py`、`services/certificates.py`、
  `api/app.py`、`api/routes_auth.py`、`api/routes_system.py`、
  `engine/manager.py`、`util/redact.py`、`cli/main.py`、`pyproject.toml`。
- 前端：`web/src/api/client.ts`、`web/vite.config.ts`、`web/package.json`、
  `web/playwright.config.ts`、`web/tests/setup.ts`、`web/tests/unit/*`、
  `web/tests/e2e/*` 与 6 张视觉基线。
- 测试：新增 30 个后端测试文件扩展/新增、18 个前端测试文件、覆盖率门禁
  `scripts/coverage_gate.py`。
- 运维/文档：`mkdocs.yml`、`docs/index.md`、`.github/workflows/ci.yml`、
  `shellcheck` 修复、`CHANGELOG.md`、`IMPLEMENTATION_STATUS.md`、
  `MANUAL_TASKS.md`。

---

---

## 12. 第二轮全量审计（2026-11-13，基线 b96324e）

本轮重点是“发布链和跨平台安装器是否真的可用”，不是再刷一次测试绿灯。以下问题均先复现或通过静态链路确认，再修复并补回归。

### 12.1 P0（会直接导致发布/安装不可用）

| ID | 问题 | 根因 | 修复 | 证据 |
|---|---|---|---|---|
| R2-01 | 客户端 UI 无法控制核心：核心 token 在 `runtime/core.token`，systemd/launchd 却指向 `core.token` | 安装器/模板与 `Paths.core_token_path` 不一致 | 统一为 `runtime/core.token`（systemd、launchd、macOS、安装器、手册） | 隔离安装后实际运行 `core-run`，token 出现在 `runtime/`；API 鉴权成功 |
| R2-02 | Linux/macOS 客户端 UI 保存设置会写错文件，甚至覆盖核心 `client.toml` 的 `data_dir` | `Settings.save()` 使用 `config_dir/config.toml`，不记录加载来源；UI/核心共用配置 | 记录 `config_path` 并保存回原文件；Linux/macOS/root 模式把 UI 配置与核心配置分离 | `test_loaded_client_config_saves_back_to_the_same_file`；隔离安装后 core/UI 两份配置均正确 |
| R2-03 | macOS 客户端安装器生成随机管理员密码但不展示，且写入了 UI 不使用的数据库 | 客户端错误套用服务端 `init` 流程 | 客户端不再 `init`，首次打开 UI 走设置向导；安装器只写核心/UI 配置 | `install-macos.sh` 静态检查；Linux 客户端隔离安装实测走同一语义 |
| R2-04 | Windows Inno Setup 安装时 `install.ps1` 把安装目录复制到自身，可能直接失败 | 源码/目标路径相同仍执行 `Copy-Item` | 仅在 source != installDir 时复制 | PowerShell 代码路径审查；Windows 实机待验 |
| R2-05 | Windows Release 构建复制 `sing-box.exe`，但核心构建脚本始终输出 `sing-box` | 跨平台输出名未加 `.exe` | Windows 构建输出 `sing-box.exe`，`core install` 同时接受两种名字 | `build-core.sh` + `release.yml` 静态核对；Windows runner 待验 |
| R2-06 | Docker 镜像没有前端 SPA | 前端 dist 被复制到 `src/ostium/web/dist`，wheel force-include 却读取根目录 `web/dist` | 改为复制到 `web/dist`；新增 `.dockerignore`；CI/Release 增加 `test -f web/dist/index.html` | 模拟 Docker 布局构建 wheel，确认 `ostium/web/dist/index.html` 存在 |
| R2-07 | README 按“已发布”口径写，但仓库无 tag、无 GitHub Release、无 PyPI/GHCR 制品 | 发布未执行 | 未擅自发布；列为 release blocker，给出发布前清单 | `git tag -l` 为空；`gh release list` 为空 |

### 12.2 P1（安全/功能）

| ID | 问题 | 根因 | 修复 | 证据 |
|---|---|---|---|---|
| R2-08 | API Token 的 `read`/`write` scope 完全不生效，文档却承诺最小权限 | `get_current_admin` 解析 token 后未检查 scope | 读 token 禁止写方法；校验 scope 只能为 `read`/`write` | `test_api_tokens`：read token GET 200、POST 403 `insufficient_scope` |
| R2-09 | `X-Forwarded-For` 可取伪造首值，绕过登录/订阅限速并污染审计 | 反向代理追加头 + 应用取第一个值 | 应用取最后一跳；Nginx 用 `$remote_addr` 覆盖 | `test_client_ip_and_loopback`；Nginx 示例同步 |
| R2-10 | Allow LAN 应用失败仍返回成功，关闭开关时 UI 可能显示“已关闭”但代理仍监听 `0.0.0.0` | 设置先持久化，应用失败只返回 warning | 失败时回滚 `allow_lan` 并返回 502；TUN 模式禁止开启 | `test_allow_lan_apply_failure_restores_previous_state`、`test_allow_lan_rejects_tun_mode` |
| R2-11 | TOTP 恢复码会展示给用户，但登录流程无法使用 | 只有 `verify_recovery`，没有消费/登录入口 | 登录支持 `recovery_code`，一次性消费，前端可切换 | `test_admin_login_totp_lock_and_session` 的恢复码用例；API 恢复码登录测试 |
| R2-12 | 备份/恢复读取通用 `config.toml`，自定义客户端 `client.toml` 不会被备份/恢复 | 与 R2-02 同根因 | 使用 `settings.config_file` | 配置路径回归测试 |
| R2-13 | 安装器 `--prefix /`、`//etc`、`/opt/../etc` 可导致卸载 `rm -rf` 破坏系统目录 | 没有危险路径校验 | 两个安装器增加规范化路径/系统根目录/`..` 拒绝 | 隔离测试 `--prefix /` 退出 2 |
| R2-14 | 升级先删旧 venv，新 wheel 安装失败会留下不可用安装 | 无事务/回滚 | 新 venv 安装成功后再原子切换；失败保留旧 venv；核心二进制原子替换 | 隔离测试：坏 wheel 升级失败后旧 venv 仍可执行；好 wheel 升级保留数据和配置 |
| R2-15 | 核心 manifest URL 指向 `v1.14.4` 而不是 Ostium Release tag，`ostium core update` 会 404 | 用核心版本拼接应用 Release URL | 增加 `--release-version`，Release workflow 传 `github.ref_name` | `test_core_manifest_points_at_the_ostium_release_tag` |
| R2-16 | Docker 只给 Python 加 `CAP_NET_BIND_SERVICE`，非 root 的 sing-box 子进程可能无法绑定 443 | 文件 capability 不自动继承给 exec 子进程 | 同时给 sing-box 设置 capability | Dockerfile 静态核对；Docker 实机待验 |
| R2-17 | Windows 一键安装器校验和正则不匹配 `./windows/...` 路径，真实 Release 必然校验失败 | 只允许可选 `./` 前缀，未按 basename 匹配 | 按文件名匹配 SHA256SUMS | PowerShell 代码路径审查；Windows runner 待验 |
| R2-18 | Linux 客户端 `--no-service` 手册把 UI 指向不可写的 `/var/lib/ostium`，且不传 token | 与服务端共用同一段提示 | 客户端 UI 使用用户数据目录、独立 UI 配置和正确 token 路径 | 隔离安装输出核对 |
| R2-19 | 安装器升级时停止 `ostium-core`，文档却声称隧道不中断 | `stop_services` 同时停两个服务 | 升级只停控制面，核心继续运行，安装后重启核心 | 代码审查；升级隔离测试通过 |
| R2-20 | 证书域名未校验路径分隔符，`create_self_signed` 可把文件写到意外目录 | 域名直接用于目录名 | 统一 `validate_domain`，拒绝 `/`、`\`、`..`、非法标签；路由捕获为 400 | `test_self_signed_validation_and_reissue` 新增非法域名用例 |
| R2-21 | 网关日志保留 UUID/凭据，与“日志脱敏”文档不一致 | `EventBus.log` 显式 `redact_ids=False`；测试用 `or True` | 日志默认脱敏 UUID，修正无效断言 | `test_event_bus_pubsub_and_logs` UUID 断言 |
| R2-22 | Nightly 的 “soak” 是打印占位文本，属于伪验证 | 未实现 | 新增 `scripts/soak-config.py`，真实生成并 `sing-box check` 100 次 | 本地 10 次运行通过；CI 100 次待跑 |
| R2-23 | GitHub Actions 使用 Node 20 时代的旧版本，CodeQL v3 即将弃用 | 版本未更新 | checkout/setup/upload/download/setup-uv/setup-go/CodeQL/docker/attest/release 全部升级到当前主版本 | workflow YAML 解析通过；真实 CI 待推送后验证 |

### 12.3 P2/P3 与仍未验证

- **Release 工作流未实际运行**：Windows setup、core 五平台、Docker、PyPI Trusted Publishing、SHA256SUMS/attestation 均未在真实 tag 上执行。
- **Nginx 示例未跑 `nginx -t`**：本机无 nginx；配置结构已人工核对，`client_max_body_size` 已与 20 MiB 应用上限对齐。
- **Windows/macOS 实机未验收**：服务注册、launchd、Tauri/PyInstaller、Wintun、代码签名、SmartScreen/Gatekeeper。
- **真实 TUN/系统代理/ACME/72h soak/5 用户可用性**：仍属外部环境。
- **数据库升级**：当前 `create_schema` 是 `create_all + stamp`，v0.1.0 只有初始迁移；后续版本若新增 Alembic 迁移，需要补“已有库执行 upgrade”路径，本轮未虚构已验证。
- **macOS DMG**：`build-macos.sh` 存在，但 Release workflow 未构建/上传 DMG；已把升级文档中“使用新版 DMG”改为重新运行安装器，避免误导。
- **npm audit**：破坏性升级 + `overrides`（`editorconfig@4.0.0`、`glob@14.0.2`、`minimatch@11.0.8`）后，完整 `npm audit` 为 **0 vulnerabilities**；同时用仓库内 `web/pwa.ts` 替换了会引入 `deepmerge` 漏洞的 `vite-plugin-pwa/workbox-build`，PWA 由 137 个单测和真实注册 E2E 覆盖。
- **Windows 卸载脚本**：Inno 卸载与脚本删除目录的交互未实机验证；已避免安装阶段自复制错误。

### 12.4 本轮验证证据

```text
git tag -l                                            -> 空（无 v0.1.0 tag）
gh release list                                       -> 空（无 GitHub Release）
隔离安装（install.sh --run-as-root --no-service）      -> 成功，数据库/管理员初始化完成
隔离升级（坏 wheel）                                   -> 退出 1，旧 venv 保留
隔离升级（好 wheel）                                   -> 数据、配置、管理员保留
隔离卸载（install-online.sh uninstall）                -> 程序删除，数据和配置保留
隔离安装（install-online.sh --local-dir）              -> uv 0.13.7 + 托管 Python 3.13.18，SHA256 校验通过
客户端隔离安装（Linux --run-as-root --no-service）     -> core/UI 配置分离，token 位于 runtime/
客户端 core-run                                       -> token 生成于 runtime/core.token，/v1/status 鉴权 200
Docker 布局模拟 wheel                                 -> 包含 ostium/web/dist/index.html
uv run pytest -m "not integration" ...                -> 385 passed，98.34/95.79
uv run pytest -m integration                         -> 6 passed
npm run test                                          -> 136 passed
npx playwright test                                   -> 21 passed
mkdocs build --strict                                 -> PASS
shellcheck + bash -n                                  -> PASS
```

**最终判定：代码层面的第二轮 P0/P1 已修复，自动化门禁通过；但“可发布”仍需先获得授权并真实执行 Release，再完成 Windows/macOS/Nginx/TUN/ACME 实机验收。当前不能把 README 中的 Release/PyPI 链接当作已验证事实。**

---

## 13. 第三轮全量审计（2026-11-13，基线 e1d9bc2）

第三轮的重点不是重复第二轮，而是验证第二轮修复是否回归，并对发布构建、升级路径、跨平台安装器和新增 PWA 工具链做破坏性检查。以下问题均先复现或通过构建链静态验证，再修复并补回归。

### 13.1 P0（会直接导致发布/安装/升级不可用）

| ID | 问题 | 复现/根因 | 修复 | 证据 |
|---|---|---|---|---|
| R3-01 | Allow LAN 实际不可用：UI 生成 `0.0.0.0:7890`，但特权核心 `validate_config` 无条件要求客户端代理只绑回环，Apply 必然 422 | `allow_lan` 只存在于 UI 进程设置，核心校验没有策略输入；第二轮测试 mock 了 `apply_client`，没有走真实校验 | `ApplyRequest`/`CoreClient` 携带 `allow_lan`；`validate_config(..., allow_lan=)` 只额外允许 `0.0.0.0`/`::`；核心重启时 last-good 使用已接受策略 | `test_client_allow_lan_accepts_only_wildcard_bind`、`test_core_apply_forwards_allow_lan`、`test_core_client_methods`；LAN 配置通过真实 `sing-box check` |
| R3-02 | Windows Release 构建必然失败：`build-windows.ps1` 把 `dist\core\sing-box.exe` 复制到自身 | PowerShell 复现：`COPY_FAILED: Cannot overwrite the item ... with itself` | 新增 `Copy-IfDifferent`，同路径跳过；Wintun 同样处理 | PowerShell 复现及修复后 `SELF_COPY_GUARD_OK`；`test_windows_release_layout...` |
| R3-03 | Windows 服务包缺少 PyInstaller `_internal`：只复制 `ostium-service.exe`，LocalSystem 服务无法启动 | PyInstaller 6 one-dir 产物依赖 `_internal`；构建脚本只复制单文件 | 整个 `dist\OstiumService\*` 复制到 `service\` 子目录，安装/卸载脚本改用该路径 | `test_windows_release_layout...`；Windows runner 仍待实机 |
| R3-04 | PyPI 发布目录混入 core/windows/SHA256SUMS：`pypa/gh-action-pypi-publish` 对 `dist/*` 执行 `twine check`/`upload`，会因目录或非分发包失败 | release workflow 直接把 `packages-dir` 指向包含所有 Release 资产的 `dist` | 新增 `dist/pypi` 暂存目录，只复制 wheel/sdist；checksums 排除该目录 | 本地布局模拟只得到 wheel+sdist；`release.yml` 静态核对 |
| R3-05 | Windows LocalSystem 核心从用户可写的 `%ProgramData%\Ostium\config.toml` 读取 `engine_path`，本地用户可把核心指向任意 exe，形成 SYSTEM 提权 | UI 与核心共用 ProgramData 配置，`icacls` 又给交互用户 Modify | 核心配置/二进制移到管理员可写的 `%ProgramFiles%\Ostium`；`core.toml` 放 `service\`；UI 配置独立；服务强制机器级路径 | `test_windows_service_paths...`；`install.ps1` 静态核对；Windows 实机待验 |
| R3-20 | Windows 默认 `powershell.exe`（5.1）没有 `$IsWindows`，`install.ps1` 会直接抛出“Run on Windows” | 使用 PowerShell Core 才存在的自动变量 | 改用 `$env:OS -eq "Windows_NT"` 判断；`build-windows.ps1` 同步 | `test_windows_release_layout...`；PowerShell 7 解析 |
| R3-21 | PowerShell 5.1 的 `Set-Content -Encoding utf8` 写 BOM，Python `tomllib` 拒绝解析 `core.toml`，Windows 核心无法启动 | BOM 在 `tomllib` 中是 `Invalid statement` | 用 `[IO.File]::WriteAllText` 写 UTF-8 without BOM | `test_windows_release_layout...` 断言无 `Set-Content ... utf8`；本地 `tomllib` BOM 复现 |

### 13.2 P1（安全/功能/发布质量）

| ID | 问题 | 根因 | 修复 | 证据 |
|---|---|---|---|---|
| R3-06 | `install.sh --upgrade` 后 `ostium` 无法执行：pip console-script shebang 仍指向 `venv.new.<pid>`，目录已改名 | 先建临时 venv、pip 安装、再原子改名；没有重写 shebang | 改名后扫描 `venv/bin/*`，把临时 venv 前缀改写为最终 `$PREFIX/venv` | 隔离升级复现 `required file not found`；修复后 `ostium version`、`pip --version` 正常；坏 wheel 回滚仍保留旧 venv |
| R3-07 | 中文用户名订阅下载 500：`Content-Disposition` 不能编码 latin-1 | 直接拼接 `ostium-{user.name}.yaml` | ASCII fallback + RFC 5987 `filename*=UTF-8''...` | `test_subscription_header_supports_unicode_user_names`（香港用户） |
| R3-08 | PWA 缓存不失效：cache key 只哈希文件名；`index.html`、manifest、`theme-init.js` 内容变化不会生成新 SW；导航响应即使 404/500 也被缓存 | 自定义 SW 生成器只对文件名做 digest；导航缓存未检查 `response.ok` | digest 同时哈希文件内容；仅缓存 `response.ok` 响应 | `pwaGenerator.test.ts` 修改 `index.html` 后 digest/source 必须变化；真实构建生成 122 个 precache 文件 |
| R3-09 | Allow LAN 开启时仍可切到 TUN，关闭 TUN 后混合代理会意外重新暴露到局域网 | `toggle_tun` 只检查系统代理，不检查 `allow_lan` | TUN 启用前返回 409 `mode_conflict`，要求先关闭 Allow LAN | `test_tun_rejects_allow_lan` |
| R3-10 | Windows 系统代理的 PAC `AutoConfigURL` 启用时未移除、关闭时未恢复 | WinINET 恢复只覆盖 ProxyEnable/ProxyServer/ProxyOverride | 启用时删除 PAC，关闭时按原值恢复或删除 | `test_windows_proxy` 覆盖 PAC 保存/恢复 |
| R3-11 | CLI 在 Windows/自定义 `engine_path` 下诊断错误；`backup create --output` 被忽略；多处 `_fail` 提前退出不释放数据库引擎；用户/配置变更后不重新 apply | 多处使用 `paths.engine_binary` 默认值、缺少 `finally`、只写数据库 | 统一 `_engine_binary()`；backup 支持 target；关键 CLI 路径加 `try/finally`；用户/配置变更后 best-effort apply | CLI 全量测试、`test_cli_workflows`、`test_config_paths`；升级后的真实 venv 已实测 |
| R3-12 | sdist 缺少 `web/index.html`、`web/pwa.ts`、`web/tests` 等前端构建源，源码包无法重建前端 | `pyproject.toml` sdist include 列表遗漏 | 补入前端源、测试和构建配置 | 构建 sdist 后检查 `web/index.html`、`web/pwa.ts`、`web/tsconfig.node.json`、`web/tests/...` 均存在 |
| R3-13 | Release 顶层权限过大；Docker 镜像硬编码 `0.1.0`；Windows checkout 无 tag 导致版本为 dev；独立 core manifest 未按 tag 生成 | workflow/Dockerfile 未按 job 收窄权限、未传版本 | job 级最小权限；Docker `ARG OSTIUM_VERSION` + `build-args`；Windows `fetch-depth: 0` + `SETUPTOOLS_SCM_PRETEND_VERSION`；core manifest 按 tag | YAML 解析、构建脚本静态核对；真实 tag 运行待授权 |
| R3-14 | WebSocket 事件流只校验会话 Cookie，不校验 Origin，存在跨站 WebSocket 读取风险 | `routes_events` 未比较 `Origin` 与 `Host` | Origin 存在且不匹配时 4403 拒绝 | `test_websocket_rejects_cross_origin` |
| R3-15 | 公网 UI 可在证书仍为 pending/已过期时被启用，重启后 `serve` 才发现无可用证书 | 只检查证书行存在 | 要求 `status=ready` 且未过期 | 现有 public-ui 测试；新增条件逻辑 |
| R3-16 | KDE 系统代理从未保存/恢复原代理设置；Windows 也会残留 `ProxyServer`/`ProxyOverride` | KDE 只写 `ProxyType=0`；Windows 只恢复存在的原值，不删除自己创建的临时值 | KDE 保存 `kioslaverc` 原值并按原值恢复/删除；Windows 对原本不存在的值执行删除 | `test_kde_restores...`、`test_kde_without_read_tool...`、`test_windows_proxy_removes_values_it_created` |
| R3-17 | Linux 客户端核心配置对 UI 组可写，UI 用户可改 `engine_path` 后由带网络权限的核心执行 | `CLIENT_CONFIG` 使用 `0660 root:ostium` | 改为 `0640 root:ostium`，升级路径也收紧权限 | `test_installers` 静态断言；安装脚本路径复核 |
| R3-18 | Release 工作流没有验证门禁：tag 推送可绕过测试直接发布 | `publish` 只依赖构建 job，不依赖测试/审计 | 新增 `verify` job（ruff/mypy/pytest/前后端审计/前端测试），`docker`/`publish` 均依赖它；同时补齐 sdist 上传与 provenance 范围 | workflow 静态核对；真实 tag 待授权 |
| R3-19 | macOS 非 root UI LaunchAgent 把日志写到 `/tmp`，本机其他用户可读 | plist 使用固定 `/tmp/ostium-ui.log` | 改为用户可写的 `Ostium UI/logs/ui.log` | `com.ostium.ui.plist` 静态核对 |
| R3-22 | Windows 重装/升级时 `ostium-service.exe install` 可能因服务已存在失败 | 未先移除旧服务注册 | 检测 `OstiumCore`，停止并 remove 后重新 install | `install.ps1` 静态核对；Windows 实机待验 |
| R3-23 | Release `SHA256SUMS` 包含下载 artifact 里的 `core/core-manifest.json`，但该嵌套文件未上传，校验会失败 | `download-artifact core-*` 把 manifest 解到 `dist/core` | 发布前删除 `dist/core/core-manifest.json`，只保留根 manifest | release workflow 静态核对 |
| R3-24 | macOS 升级先重建 venv，pip 失败会留下损坏安装 | 没有事务/回滚 | 先移到 `venv.old`，失败恢复旧 venv | `install-macos.sh` shellcheck + 静态路径核对；macOS 实机待验 |

### 13.3 第三轮回归矩阵

| 检查 | 结果 |
|---|---|
| 后端非集成测试 | **397 passed / 0 skipped**；覆盖率 **98.19% statements / 95.48% branches**；`coverage_gate.py` PASS |
| 后端真实核心集成测试 | **6 passed**（sing-box 1.14.4 + 定制 v2ray core） |
| 前端单元测试 | **137 passed**；覆盖率 91.38 / 85.27 / 89.04 / 92.13 |
| Playwright | **21 passed**（1440/1024/390、深浅色基线、PWA、axe） |
| Python lint/format/types | `ruff` PASS；`ruff format --check` 136 files；`mypy` PASS |
| npm audit / npm ls | **0 vulnerabilities**；`npm ls` exit 0（仅可选依赖 UNMET，无 invalid/extraneous） |
| Python 依赖审计 | 导出**全部依赖组**后 `pip-audit --strict` 0 漏洞；本地 editable 项目不作为 PyPI 依赖审计 |
| 文档 | `mkdocs build --strict` PASS；内部链接检查 PASS |
| Shell / PowerShell | `bash -n`、`shellcheck` PASS；PowerShell 7.7 解析 `scripts/*.ps1` 与 `deploy/windows/*.ps1` 全部通过（4 个） |
| wheel / sdist | 含 `ostium/web/dist/index.html`、`manifest.webmanifest`、`sw.js`；sdist 含前端构建源 |
| 一键安装（隔离） | `install-online.sh --local-dir`、静态 uv 0.11.14、托管 Python 3.13.13、SHA256 校验、`/healthz` 200 |
| 安装模式 | `--run-as-root --no-service`、`--behind-proxy`、`--public-ui` 冲突拒绝、危险 `--prefix /`/`//etc` 拒绝 |
| 升级 | 坏 wheel 退出 1 且旧 venv 可执行；好 wheel 保留数据/管理员，修复后 `ostium`/`pip` 可执行 |
| 卸载 | `install-online.sh uninstall` 删除程序/链接，保留数据和配置 |
| 客户端隔离 | 核心/UI 配置分离；`core-run` 在 `runtime/core.token` 生成令牌，`/v1/status` 鉴权 200 |
| 发布工作流静态检查 | YAML 解析、action tag 存在、PyPI 只暂存 wheel/sdist、sdist 已上传、权限按 job 收窄、`verify` 门禁依赖正确 |
| 干净克隆 | `npm ci`、`npm audit` 0、137 前端测试、构建、397 非集成后端测试、wheel 含 SPA 全部通过（基线 `77a3e34`） |
| GitHub Actions | `77a3e34`：CI 43352777103、E2E 43352777113、Security 43352777052 全部 success；Docs 在包含 docs 变更的 `cbf9b70` 为 43342090287 success |

### 13.4 仍未验证 / 外部阻塞

- **没有 tag、GitHub Release、PyPI、GHCR 或 Docker 发布**；README 中的 Release/PyPI/GHCR 链接仍会 404。本轮已按爸爸批准 **push 代码到 `main`**；没有 tag 或发布。
- 推送后的 GitHub Actions 在 `77a3e34` 全部通过：CI `43352777103`、E2E `43352777113`、Security `43352777052`；Docs 在包含 docs 变更的 `cbf9b70` 为 `43342090287`。
- **Windows**：未在 Windows runner/实机执行 PyInstaller one-dir、Inno 安装/卸载、服务启动、TUN/Wintun、PAC 恢复；PowerShell 只做了解析和静态检查。R3-03/R3-05 的运行时行为必须实机确认。
- **macOS**：launchd、`ostium` 组、token 权限、UI 以用户启动、Gatekeeper/签名未实机验证。
- **Linux TUN/系统代理**：需要真实 `/dev/net/tun`、NetworkManager/GNOME/KDE 会话；本轮只验证代码和配置。
- **Nginx**：本机无 nginx，`nginx -t` 未执行；示例仍是静态核对。
- **Docker**：本机无 Docker，镜像/多架构构建未执行。
- **ACME**：没有公网域名和 80 端口，staging/production 未执行。
- **性能/可用性**：72h soak、Lighthouse 性能预算、5 用户可用性未执行。
- **浏览器覆盖**：PWA 只在 Chromium E2E 验证，Safari/Firefox 未覆盖。
- **数据库迁移**：仍是 `create_all + stamp`；未来新增 Alembic 版本时需要补“已有库 upgrade”路径。
- **PyPI Trusted Publishing**：workflow 已绑定 `release.yml` + `pypi` environment；真实 tag 发布仍未执行。
- **代码签名**：Windows/macOS 证书、SmartScreen/Gatekeeper 未处理。

### 13.5 结论

**代码层面达到 release candidate：第三轮 P0/P1 已修复，自动化与隔离安装/升级证据通过。**
**但不能宣布“已发布”或把 README 的 Release/PyPI/GHCR 链接当成有效：没有真实 tag/Release/发布，且 Windows/macOS/Nginx/Docker/ACME/TUN/性能仍属外部验证。**

---

## 14. 第四轮发布前最终审计（2026-11-13）

### 14.1 基线与方法

- 基线：`e0d4c4a`，干净工作树；无 tag、GitHub Release、PyPI/GHCR/Docker 发布。
- 环境：Python 3.13.5、Node 24.19.0、npm 12.0.2、uv 0.11.14；Linux/WSL2。
- 本轮不信任前几轮结论，重新执行源码测试、构建 wheel/sdist、扁平 Release 目录模拟、
  隔离安装/升级、篡改校验、前端 E2E 与文档构建。
- 未创建 tag、未 push、未发布任何制品。

### 14.2 第四轮新发现并根治的问题

| ID | 级别 | 问题 | 根因 | 修复与回归证据 |
|---|---|---|---|---|
| R4-01 | P0 | `install-online.sh --local-dir` 无法从 Release 资产目录安装；在线模式执行未校验的 GitHub 源码包 | 离线模式假定存在 `scripts/install.sh`；在线模式直接解压 tag archive | 校验 sdist 后从 sdist 提取安装器；新增 `extract_source`、`sums_asset`；Release 目录实测安装成功；`test_offline_installer_can_use_release_assets` |
| R4-02 | P0 | systemd 服务无法启动：状态目录默认在 `~/.local/state`，被 `ProtectHome`/`ProtectSystem=strict` 阻止；root 模式落到 `/root` | 状态目录使用 platformdirs，默认不在 data_dir | 默认改为 `data_dir/state`；systemd 增加 `state`/`rulesets` 可写路径；安装器创建目录；`test_default_state_dir_is_inside_data_dir` |
| R4-03 | P0 | 默认非 root 服务端安装后数据库/master.key 归 root，`ostium` 服务无法读写 | 安装器以 root 执行 `init`，未回收文件属主 | 初始化后 `chown -R ostium:ostium "$DATA" "$CONFIG"`；`test_server_init_files_are_owned_by_service_user` |
| R4-04 | P0 | `--public-ui` 在首次安装即可启用，既无证书也无 TOTP；`serve` 直接退出并被 systemd 循环拉起 | 安装参数绕过 Settings 的 TOTP/证书门禁 | 首次安装拒绝 `--public-ui`；`serve` 同时要求 TOTP 和未过期可用证书；CLI 测试覆盖 |
| R4-05 | P0 | Release `SHA256SUMS` 使用 `./core/...` 等嵌套路径，GitHub Release 资产是扁平文件名，下载后无法校验 | 在嵌套 `dist` 直接生成 checksum | 新增 `dist/release` 扁平暂存目录，按 basename 生成并自校验；`test_release_publishes_every_checksummed_asset` |
| R4-06 | P0 | Inbounds 端口被锁死默认值，UI 也不能改；Nginx 占用 443 时 Reality/Trojan 无法迁到 9443 | API 硬编码 `port_locked`；前端只展示端口；core 启动时缓存 `proxy_ports` | API 允许 1–65535（保留 UI/core API 端口，Hysteria2 UDP 可复用）；自动扩展并持久化 `proxy_ports`；core 每次 apply 重读配置白名单；Inbounds 页新增“修改端口”；API/前端回归测试 |
| R4-07 | P0 | UI 在 core token 不存在时自行生成 token，导致 UI/core 永久 401 或权限错误 | `CoreClient._token()` 调用 `ensure_core_token` | UI 只读 token，缺失时返回 `core_unavailable`；仅特权 core 创建；`test_core_client_never_creates_the_privileged_token` |
| R4-08 | P1 | `serve` 使用已过期的 `status=ready` 证书，公网 UI 启动后 TLS 失败 | 启动查询只过滤 status | 过滤过期时间并检查证书文件存在；`test_serve_uses_only_unexpired_ready_certificates` |
| R4-09 | P1 | 系统代理启用中途失败会留下半改状态且无法恢复 | 先改系统、后写状态；KDE/Windows 删除/恢复不完整 | 四个平台改为先写恢复状态、失败自动回滚；单键失败继续恢复其余键并保持 dirty；代理扩展测试 |
| R4-10 | P1 | `ostium core install --url` 允许无校验下载，且把 `.tar.gz` 原样写成核心二进制 | 未强制 `--sha256`；未识别归档 | 强制 `--sha256`；支持 tar.gz 中提取 `sing-box`；测试覆盖 |
| R4-11 | P1 | `local-login` 链接可被非 loopback 请求使用 | 未校验来源地址 | 仅允许 loopback；`test_local_login_is_loopback_only` |
| R4-12 | P1 | `Settings.save()` 非原子且不持久化 `state_dir`/`core_token_file`；并发读可能看到半写 TOML | 直接写目标文件，字段遗漏 | 临时文件 + `Path.replace` 原子写；持久化两个路径字段；配置/核心测试 |
| R4-13 | P1 | 非 root CLI 找不到 `/etc/ostium/config.toml`，README 的 `sudo -u ostium ostium backup` 实际不可用 | 非 root 服务端默认用户配置目录 | 可读 `/etc/ostium/config.toml` 时优先使用；`test_non_root_server_reads_etc_config` |
| R4-14 | P1 | macOS 卸载被“仅支持客户端”角色检查误杀；自定义 prefix 的 plist 仍指向 `/opt/ostium` | 状态/卸载也执行服务端角色检查；plist 静态安装 | 仅 install/upgrade 校验角色；plist 安装时渲染 prefix；macOS 重新登录提示 |
| R4-15 | P1 | core 归档 `.sha256` 写入绝对路径，下载后 `sha256sum -c` 不可用 | 使用绝对 `$dir.tar.gz` | 在输出目录用 basename 生成；Release 增加 core checksum 校验；`test_core_checksum_file_is_download_friendly` |
| R4-16 | P1 | Windows/macOS/Linux 安装包缺少 LICENSE/NOTICE/核心 SBOM | 只复制二进制 | 安装器、Windows 构建、macOS 构建补齐许可证与 SBOM；`test_release_bundles_include_license_and_sbom` |
| R4-17 | P2 | macOS wildcard 证书校验接受多级子域 | `endswith` 未限制一级 | 只允许一级 wildcard；证书扩展测试 |
| R4-18 | P2 | Docker entrypoint 在 core 崩溃后仍保持半死容器 | `wait` 等待两个子进程 | 任一子进程退出即结束容器，交给 restart policy |
| R4-19 | P2 | Release 脚本未上传安装器/sdist、Docker 只打 `v0.1.0` 而 compose 使用 `0.1.0` | 发布资产与镜像标签不完整 | 暂存并上传 `install-online.sh/.ps1`、sdist；metadata-action 同时生成 `v0.1.0`/`0.1.0`/`latest`（预发布不打 latest） |
| R4-20 | P2 | CI/Release 没有 wheel 冒烟；Release verify 没有覆盖率门禁 | 只构建不安装 | 新增 wheel 安装 + `ostium version` + SPA 检查；Release verify 增加 coverage gate |

### 14.3 第四轮证据

| 检查 | 结果 |
|---|---|
| 后端非集成测试 | **413 passed / 0 skipped**；覆盖率 **97.67% statements / 94.93% branches**；`coverage_gate.py` PASS |
| 后端真实核心集成测试 | **6 passed**（真实 sing-box + 定制 v2ray core） |
| 前端 | **137 passed**；91.34 / 85.26 / 89.06 / 92.14；lint/typecheck/format/build PASS |
| Playwright | **21 passed**（桌面/平板/移动、深浅色基线、PWA、axe） |
| 依赖审计 | 全依赖组 `pip-audit --strict` 0 漏洞；`npm audit` 0；`npm ls` exit 0 |
| `ruff` / `mypy` | PASS（69 source files） |
| Shell | `bash -n`、`shellcheck` PASS；4 个 PowerShell 脚本解析 PASS |
| 文档 | `mkdocs build --strict` PASS；README/docs 内部链接 PASS |
| Release 候选 | wheel/sdist 0.1.0 构建成功；wheel 含 SPA/manifest/sw.js；sdist 含 `web/dist`、`scripts/`、`deploy/` |
| 扁平 Release 目录 | 本地产物 + core + 安装器 + manifest + `SHA256SUMS`；`sha256sum -c` 全部 OK |
| 离线一键安装 | `install-online.sh --local-dir` 服务端安装成功；`ostium version`、配置、DB、master.key、state 目录正常 |
| 升级 | 好 wheel 保留数据/管理员，`ostium`/`pip` 可执行；坏 wheel 退出 1 且旧 venv 仍可执行 |
| 篡改校验 | 修改 wheel 一字节后安装被 SHA256 拒绝 |
| 客户端 | 配置分离；core 生成 `runtime/core.token`；UI 只读 token；`/healthz`/`/readyz` 正常 |
| 发布工作流静态检查 | `verify` 门禁、扁平 checksum、PyPI 暂存、Docker 双版本标签、action tag 存在 |

### 14.4 平台验证矩阵

| 平台/路径 | 状态 | 说明 |
|---|---|---|
| Linux 隔离安装/升级/卸载 | PASS（隔离目录、`unshare -r`） | 服务端/客户端 `--run-as-root --no-service`、扁平 Release 目录 |
| Linux 默认非 root systemd | **未实机** | 无真实 systemd 会话；属主修复为静态断言 + 代码路径 |
| Windows 安装/服务/TUN/PAC | **未实机** | 仅 PowerShell 解析、静态检查；需 Windows runner/实机 |
| macOS launchd/token/卸载 | **未实机** | 仅 shellcheck/静态检查；需 macOS 实机 |
| Nginx `nginx -t` / 反代 | **未执行** | 本机无 nginx/公网域名 |
| Docker 多架构构建/运行 | **未执行** | 本机无 Docker |
| ACME staging/production | **未执行** | 无公网域名和 80 端口 |
| TUN/Allow LAN 真实数据面 | **未执行** | 无 `/dev/net/tun`/真实 LAN 设备 |
| 72h soak / 性能 / 5 用户 | **未执行** | 仅 nightly 100 次配置校验，不等价 |
| 真实 Release/PyPI/GHCR | **未执行** | 未获授权创建 tag/发布 |

### 14.5 结论（第四轮）

**代码层面：达到 release candidate；第四轮发现的 P0/P1 已修复，自动化、构建、隔离安装/升级和前端 E2E 证据通过。**

**发布前判断为 NO-GO（保留为审计记录）。** 用户随后明确授权发布，实际发布结果见 §15；以下外部验证项仍是发布后的残余风险：

1. 未创建 `v0.1.0` tag，Release/PyPI/GHCR 链接仍 404；需明确授权发布。
2. Windows 实机/runner 未验证安装、服务、TUN/Wintun、PAC 恢复。
3. macOS 实机未验证 launchd、组权限、token、卸载、Gatekeeper。
4. Nginx/Docker/ACME/TUN/72h soak 未执行，至少需要一项真实环境验收或明确接受 external blocker。
5. 安装包未签名，SmartScreen/Gatekeeper 会拦截。
6. 默认非 root systemd 安装尚未在真实 systemd 主机跑通。

因此不能把 README 的“当前稳定版本”与发布链接视为已验证事实；需要完成上述验收并发布后才能给出 GO。

---

## 15. v0.1.0 发布记录（2026-11-13）

### 15.1 发布结果

| 项目 | 结果 |
|---|---|
| Git tag | `v0.1.0` → `b244f08` |
| Release workflow | run `43381306485`，success |
| GitHub Release | <https://github.com/ThzxxArt/Ostium/releases/tag/v0.1.0>，17 个资产 |
| PyPI | `ostium-ctl==0.1.0`，wheel + sdist |
| GHCR | `0.1.0`、`v0.1.0`、`latest` |
| Core archives | 5 个目标（linux/darwin amd64+arm64、windows amd64），含 `.sha256` 与 manifest |
| Windows installer | `Ostium-0.1.0-windows-x64-setup.exe`（约 99 MB） |

### 15.2 真实发布制品验证

- 下载全部 17 个 Release 资产后 `sha256sum -c SHA256SUMS`：全部 OK。
- 从 GitHub Release 资产运行 `install-online.sh install --version 0.1.0`：
  uv + 托管 Python 3.13.13 + wheel/sdist/core 下载与 SHA256 校验通过，
  安装后 `ostium version` 为 `0.1.0`，`/healthz` 正常。
- 从 PyPI 安装 `ostium-ctl==0.1.0`：`ostium version` 为 `0.1.0`，wheel 内 SPA 存在。
- GitHub Release / PyPI 页面 HTTP 200；GHCR tags list 包含三个标签。

### 15.3 发布后热修与残余风险

- 首次发布的 `install-online.sh` 在 `sums_asset` 中误用函数 `$2` 而非 `$3`，导致在线安装找不到 wheel。
  已在 main `8e3bb41` 修复，并重新上传 Release 的 `install-online.sh` 与 `SHA256SUMS`
  （`sha256sum -c` 已复核）。
- **注意**：PyPI 的 0.1.0 sdist 与 `v0.1.0` tag 源码中的 `scripts/install-online.sh`
  仍是热修前副本；PyPI 安装、GitHub Release 资产安装和 `--local-dir` 均可用。
  Release 中热修的两个资产没有重新生成构建证明；若需要完整不可变制品证明，应发布 `v0.1.1`。
- Windows 安装器已构建，但未在真实 Windows 11 运行安装/服务/TUN/PAC；macOS launchd、
  Linux 默认非 root systemd、Nginx、Docker 运行、ACME、真实 TUN/Allow LAN、72h soak
  与签名仍未实机验收。

**结论：v0.1.0 已发布且主安装路径可用；生产可用性仍取决于上述外部实机验收。**

---

## 16. v0.1.1 审计与修复（2026-11-13）

本轮针对 v0.1.0 的 P0/P1/P2 发现做全量修复，并补充可复现测试。详细工作项状态见
`V0.1.1_PLAN.md` 与最终交付报告；自主决策见 `V0.1.1_DECISIONS.md`。

### 16.1 P0 关闭证据

| ID | 发现 | 修复 | 证据 |
|---|---|---|---|
| SEC-01/02/03 | 服务端默认 `0.0.0.0:8443` 明文 | 默认回环、serve fail-closed、旧配置迁移、显式 `allow_insecure_bind` | 单元测试覆盖旧配置迁移与 opt-in；安装器静态检查 |
| SEC-04 | 服务端出口可访问内网/metadata | 完整 RFC1918/CGNAT/link-local/metadata/SMTP 25 ACL | 真实 `sing-box check` + 生成配置断言 |
| DATA-01 | SS2022 订阅缺少 server key | `server_key:user_key` 三种格式统一 | 真实 sing-box 回环流量测试通过 |
| DATA-02 | SIGHUP 假成功 | 重启子进程 + 存活验证 + 回滚 | 真实 sing-box apply/失败回滚测试 |
| REL-01/02/03 | 版本/资产不可变 | 版本统一 0.1.1、`overwrite_files: false`、发布后只读校验脚本 | workflow 静态测试 + `scripts/verify-release.sh` |

### 16.2 已在本环境验证

- 后端：474 常规 + 9 真实 sing-box 集成 = 483 passed / 0 skipped；语句 95.7%、分支 91.5%；覆盖率门禁通过。
- 真实 sing-box 1.14.4：`sing-box check`、SS2022 多用户回环流量、apply 失败保留旧配置。
- 前端：158 passed；语句 90.7%、分支 85.2%；首屏 JS 191.8 KiB gzip（预算 300 KiB）。
- Playwright：69 passed，含全核心页面 axe、dashboard/users/settings 视觉基线、LCP/CLS 预算。
- Alembic fresh/旧库/更高版本拒绝、备份恢复迁移、SQLite integrity_check。
- Linux 安装脚本静态检查（shellcheck/bash -n）、PowerShell 解析（CI 步骤）。

### 16.3 未在本环境验证（仍是发布阻断项）

- Windows 11 实机：setup、OstiumCore、Wintun、TUN、PAC、SmartScreen、卸载。
- macOS 14 实机：launchd、utun、系统代理、DMG、Gatekeeper、卸载。
- Ubuntu 24.04 默认非 root systemd 实装、重启、升级失败回滚、卸载。
- Nginx `nginx -t` + 真实 TLS/WebSocket/IP allowlist 反代。
- Docker amd64/arm64 实际运行与 compose 加固参数。
- ACME staging/production 真实签发/续期、UI HTTPS 重启。
- 真实 TUN/Allow LAN/DNS 泄漏、72h soak、性能、5 用户可用性。
- Windows Authenticode、macOS Developer ID/notarization（无证书）。

这些项目没有被写成“已验证”；发布前必须补证据，否则按 blocker 处理。
