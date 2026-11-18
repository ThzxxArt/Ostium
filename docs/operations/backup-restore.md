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

自动备份：设置 `auto_backup_enabled=true`，并在
`/etc/ostium/ostium.env` 设置 `OSTIUM_BACKUP_PASSWORD`。
worker 每天检查一次，保留 `auto_backup_keep` 份。

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
4. 覆盖证书与配置；
5. 递增 desired revision，worker 重新应用。

恢复会替换当前数据库与证书，请先创建当前状态备份。

## 保留

- 自动备份默认保留 7 份。
- 手动备份不会被自动清理。
- 建议把 `.ostb` 复制到另一台机器或对象存储；不要只留在同一块磁盘。
