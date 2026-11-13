# 升级与回滚

## 一键升级（推荐）

```bash
sudo bash install-online.sh upgrade
```

行为：

1. 读取现有安装和运行模式（默认用户或 `--run-as-root`）。
2. 停止控制面；核心尽量保持运行。
3. 替换 `/opt/ostium/venv` 和核心二进制。
4. 保留数据库、`master.key`、配置、证书、用户和订阅。
5. 重启服务。

指定版本：

```bash
sudo bash install-online.sh upgrade --version 0.1.1
```

## 手动升级应用

1. 阅读 release notes，先备份。
2. `ostium update --check`；手动下载签名版本。
3. 服务端只停 `ostium.service`，核心继续跑，隧道不断。
4. 把新 wheel 安装到 `/opt/ostium/venv`。
5. 启动时自动执行迁移。
6. 检查 `/readyz`。
7. 健康检查失败时回滚 wheel 和数据库备份。

```bash
sudo -u ostium ostium backup create --password '...'
sudo systemctl stop ostium
sudo /opt/ostium/venv/bin/pip install --upgrade ./ostium_ctl-0.1.0-py3-none-any.whl
sudo systemctl start ostium
curl -fsS http://127.0.0.1:8443/readyz
```

Ostium 不做静默自动更新。UI 只提供下载链接，不自动执行。

## 核心升级

核心版本固定在 manifest 中。`ostium core install` 会校验 SHA256 并替换二进制；下一次
apply/重启时 supervisor 才对当前配置执行 `sing-box check`，失败时回滚配置。升级前请备份
旧二进制，并用 `ostium core version` 确认新二进制可执行。

```bash
sudo ostium core install --binary ./sing-box
# 或
sudo ostium core install --url https://.../ostium-core-....tar.gz --sha256 <hash>
sudo ostium core update
```

## 数据库

v0.1.0 的 SQLite 迁移是前向的。release notes 会标记不可回滚的迁移；升级前必须备份。Alembic 用 `alembic_version` 记录版本。

回滚步骤：

1. 停 `ostium.service`。
2. 安装上一版 wheel。
3. 如果迁移不兼容，从备份恢复数据库。
4. 启动并检查 `/readyz`、登录、订阅和核心状态。

## 客户端升级

- Windows：重新运行新版 `setup.exe` 覆盖安装，数据和订阅保留。
- macOS：重新运行 `install-macos.sh` 覆盖安装，数据与订阅保留。
- Linux：重新执行一键脚本 `upgrade` 或 `install.sh --role client`。

核心升级会短暂中断隧道；UI 升级不会。升级前建议先导出配置或备份数据。
