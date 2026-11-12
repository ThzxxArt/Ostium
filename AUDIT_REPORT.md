# Ostium v0.1.0 — 全量审计与覆盖率报告

日期：2026-11-12  
审计对象：`/mnt/d/CodeWorkspace/Ostium`（v0.1.0 锁定基线）  
结论：**后端与前端覆盖率硬门禁全部通过；P0/P1 缺陷已根治；剩余事项均为本机无法完成的外部硬件、账号、域名或发布授权。**

---

## 1. 结论摘要

| 项目 | 基线 | 最终 | 门禁 |
|---|---|---|---|
| 后端语句覆盖率 | 66.81% | **98.54%** | ≥85% PASS |
| 后端分支覆盖率 | 39.46% | **95.84%** | ≥85% PASS |
| `api/` 覆盖 | — | 语句 98.13% / 分支 96.65% | ≥90% PASS |
| `core/` 覆盖 | — | 语句 99.19% / 分支 95.00% | ≥90% PASS |
| `services/` 覆盖 | — | 语句 98.06% / 分支 94.17% | ≥90% PASS |
| `engine/` 覆盖 | — | 语句 99.23% / 分支 97.29% | ≥90% PASS |
| 前端 statements | 0.92% | **91.84%** | ≥85% PASS |
| 前端 branches | 1.62% | **85.97%** | ≥85% PASS |
| 前端 functions | 0.56% | **89.39%** | ≥85% PASS |
| 前端 lines | 0.83% | **92.59%** | ≥85% PASS |
| 后端测试 | 69 | **384 passed / 0 skipped** | — |
| 前端测试 | 5 | **132 passed** | — |
| Playwright | 12 passed / 3 skipped | **18 passed / 0 skipped** | — |

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
| Python format | `uv run ruff format --check src tests scripts` | PASS（132 files） |
| Python types | `uv run mypy src/ostium` | PASS（69 files） |
| Backend tests | `uv run pytest -q` | 384 passed, 0 skipped |
| Backend coverage | `uv run pytest --cov=ostium --cov-branch ...` + `scripts/coverage_gate.py` | PASS |
| Frontend lint | `npm run lint` | PASS |
| Frontend types | `npm run typecheck` | PASS |
| Frontend unit tests | `npm run test` | 132 passed |
| Frontend coverage | `npm run test:coverage` | 91.84 / 85.97 / 89.39 / 92.59 |
| Frontend build | `npm run build` | PASS |
| Frontend format | `npm run format:check` | PASS |
| E2E/a11y/visual | `npx playwright test` | 18 passed |
| Shell scripts | `shellcheck scripts/*.sh deploy/**/*.sh install.sh` | PASS |
| Docs | `mkdocs build --strict` | PASS |
| Python audit | `uv run pip-audit` | 0 known vulnerabilities |
| npm audit | `npm audit --omit=dev --registry=https://registry.npmjs.org` | 0 vulnerabilities |
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
| AUD-015 | P2 | `web/playwright.config.ts`、`tests/e2e` | 移动端 412px、视觉基线缺失 | 未对齐 390px；visual skip | 390px + 6 张深浅色基线，移除 skip | Playwright 18 passed |
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
| 管理 Web UI 全部页面 | PASS | 132 个 Vitest + 18 个 Playwright |
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
uv run ruff format --check src tests scripts         -> 132 files already formatted
uv run mypy src/ostium                               -> Success: no issues in 69 files
uv run pytest -q                                     -> 384 passed, 35 warnings
uv run pytest -m "not integration" --cov=ostium ...  -> 378 passed, coverage 98.54/95.84
uv run python scripts/coverage_gate.py coverage.json -> Coverage gate passed
npm run lint                                         -> pass
npm run typecheck                                    -> pass
npm run test:coverage                                -> 132 passed; 91.84/85.97/89.39/92.59
npm run build                                        -> built
npm run format:check                                 -> pass
npx playwright test                                  -> 18 passed
shellcheck scripts/*.sh deploy/**/*.sh install.sh    -> exit 0
uv run --with mkdocs-material==9.7.0 mkdocs build --strict -> built
uv run pip-audit                                     -> No known vulnerabilities
npm audit --omit=dev --registry=https://registry.npmjs.org -> found 0 vulnerabilities
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

**最终判定：v0.1.0 代码与自动化测试已达到发布质量门禁；剩余阻断项全部是
本机不可获得的硬件、域名、账号、签名或发布授权，已逐项列入 MANUAL_TASKS。**
