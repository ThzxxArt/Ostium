# 从 0.1.1 升级到 0.1.2

0.1.2 是状态收敛与发布真实性版本，不新增协议，不改变角色模型。升级前请先备份数据库、配置、证书、规则集和 `master.key`。

## 1. 升级前检查

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium status
sudo ostium update --check
```

确认：

- 当前版本是 `0.1.1`；
- 备份文件已复制到另一台机器或加密介质；
- 磁盘剩余空间足够容纳数据库和备份；
- 如果使用 Public UI，域名、证书和 TOTP 都可用。

## 2. 使用在线安装器升级

Linux：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

Windows（管理员 PowerShell）：

```powershell
irm https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.ps1 | iex
```

安装器现在默认跟随 `latest`，不会再固定安装 0.1.1。需要固定版本时显式传入 `--version 0.1.2`（PowerShell 使用 `-Version 0.1.2`）。

## 3. 升级后验证

```bash
sudo -u ostium ostium version
sudo -u ostium ostium status
sudo -u ostium ostium doctor
```

预期：

- 版本显示 `0.1.2`；
- 管理员仍可登录，TOTP 和恢复码仍然有效；
- 用户、订阅 token、证书、规则集和备份列表仍在；
- Public UI 在 8443 时，订阅 URL 包含 `:8443`；
- 旧证书续期后浏览器使用新证书；
- `ostium-core` 没有继续运行旧的安全策略配置。

安装器在停止服务后会生成 `pre-upgrade-<时间>` 快照，包含 `ostium.db`、WAL/SHM 与 `master.key`（Linux 安装器还会保存配置文件副本）：Linux 服务端位于 `/var/lib/ostium`，Linux 客户端位于 UI 数据目录（默认 `~/.local/share/ostium`），macOS 位于 `/Library/Application Support/Ostium UI`，Windows 位于 `%ProgramData%\Ostium`。Linux 与 macOS 会在健康检查失败时自动恢复该快照；Windows 安装器只保留快照，需要手工恢复后再回到 0.1.1。

如果启动失败：

1. 停止 `ostium` 和 `ostium-core`；
2. 恢复升级前的数据库快照；
3. 重新安装 0.1.1 wheel 或使用安装器回滚文件；
4. 保留 `/var/lib/ostium/logs` 和备份用于诊断。

## 4. 备份格式变化

0.1.2 备份格式为 v2：

- 新增 `rulesets/` 和 `acme/`；
- manifest 包含每个成员的 SHA-256；
- 证书和规则集路径改为相对 `data_dir`；
- 缺少 `master.key` 且数据库有加密字段时拒绝恢复；
- 恢复后清理旧 `last-good`，由当前数据库重新生成配置。

0.1.1 的 v1 备份仍可导入。

## 5. 回滚

0.1.2 不修改已发布的 0.1.1 tag、Release 资产、PyPI 或 GHCR 版本。回滚时：

- 恢复 0.1.1 的虚拟环境和数据库快照；
- 如果已经用 0.1.2 恢复过备份，优先使用升级前快照，而不是反向覆盖；
- 不要删除 `master.key`；它必须与数据库配套。
