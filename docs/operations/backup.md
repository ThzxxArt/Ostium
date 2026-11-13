# 备份与恢复

## 备份包含什么

- SQLite 数据库（在线备份 API，WAL 安全）
- `master.key`（解密用户密码和 token 所必需）
- `config.toml`
- 证书和私钥
- JSON manifest

不包含核心二进制和日志。带密码的备份使用 scrypt（N=2^15, r=8, p=1）+ AES-256-GCM 加密；没有密码无法恢复。

## 创建备份

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
```

或在 **Settings → Maintenance → Backups** 创建。加密文件扩展名为 `.ostb`；明文归档为 `.tar.gz`。API/UI 创建明文备份需要显式确认，因为归档包含 `master.key`。请把备份存到异地。

root 模式下：

```bash
sudo ostium backup create --password 'a long passphrase'
```

## 恢复

推荐：**Settings → Backups → Apply**。它先把归档 staging，提示你重启两个服务；重启前当前数据库不变。

命令行恢复（先停服务）：

```bash
sudo systemctl stop ostium ostium-core
sudo -u ostium ostium backup restore ./ostium-backup-....ostb --password '...'
sudo systemctl start ostium-core ostium
```

恢复会校验归档/角色、SQLite `integrity_check`，替换数据库与主密钥，然后执行 Alembic 迁移；
迁移失败会恢复旧数据库并保留 pending 文件。**请定期演练恢复**，不要只在出事时才第一次测试。

## 保留策略

- 审计日志默认 90 天
- 任务记录默认 7 天
- 流量聚合默认 365 天
- 每日自动本地备份可选，默认关闭；最多保留 7 份

## 安全提醒

备份包含 `master.key`，等同于最高敏感文件。不要上传公开网盘、issue 或聊天群；丢失密码或主密钥后，用户密码、订阅 token 和证书私钥都无法恢复。
