# 备份与恢复

## 内容

备份文件 `.ostb` 是加密 tar.gz，包含：

- `manifest.json`：版本、创建时间、字段密钥、数据库校验和；
- `database.json`：Django dumpdata（排除 sessions、admin log、django_q）；
- `certs/`：全部证书与私钥；
- `runtime/config.json`：当前生效配置。

格式：`OSTB1 | salt | nonce | AES-256-GCM(payload)`，密码经 scrypt 派生。

## 创建

```bash
ostium backup create --password 'a-long-backup-password'
```

或在控制台「系统」页创建。密码至少 12 位；丢失密码无法解密。

自动备份：设置 `auto_backup_enabled=true`，并配置自动备份密码。worker 每
5 分钟检查一次，距上次自动备份超过 23 小时才创建新备份，保留
`auto_backup_keep` 份。

密码来源按优先级：

1. 环境变量 `OSTIUM_BACKUP_PASSWORD`；
2. 控制台「设置 → 自动备份密码」保存的文件
   `/var/lib/ostium/secrets/backup-password`（0600）。

页面密码不会进入数据库，也不会进入 `.ostb` 备份文件。环境变量优先级更高；
如果两者同时存在，页面会提示当前由环境变量管理。密码至少 12 位，丢失后无法
解密备份。

## 恢复

**建议离线恢复**：

```bash
sudo systemctl stop ostium-web ostium-worker ostium-jobs
sudo -u ostium /opt/ostium/venv/bin/ostium backup restore \
  /var/lib/ostium/backups/ostium-backup-....ostb --password '...'
sudo systemctl start ostium-web ostium-worker ostium-jobs
```

恢复流程：

1. 解密并校验 manifest/数据库 SHA256；
2. flush 当前数据库并 loaddata；
3. migrate；
4. 如果备份的字段密钥与当前 `OSTIUM_FIELD_KEY` 不同，使用备份密钥解密、
   再用当前密钥重新加密所有凭据，避免恢复后无法读取；
5. 覆盖证书与配置；
6. 递增 desired revision，worker 重新应用。

恢复会替换当前数据库与证书，请先创建当前状态备份。

## 保留

- 自动备份按 `auto_backup_keep` 保留最近 N 份（默认 7），同时删除磁盘文件。
- 手动备份不会被自动清理；删除备份会同时删除 `.ostb` 文件。
- 建议把 `.ostb` 复制到另一台机器或对象存储；不要只留在同一块磁盘。
