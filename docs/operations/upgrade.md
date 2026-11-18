# 升级

Ostium 不提供 0.1.x 迁移路径。0.2.0 是全新安装版本。

## 升级前

1. 创建加密备份。
2. 记录当前版本与 `ostium status --json`。
3. 确认新版本 changelog 与 sing-box tag。
4. 在维护窗口执行（worker 重启会中断隧道 1–3 秒）。

## systemd

在线升级（不需要本地 checkout）：

```bash
curl -fsSL https://raw.githubusercontent.com/ThzxxArt/Ostium/main/install.sh \
  | sudo bash -s -- upgrade --ref main
```

或从本地 checkout 升级：

```bash
sudo bash install.sh upgrade --from-source
```

安装器在 `OSTIUM_BACKUP_PASSWORD` 已配置时会自动创建 pre-upgrade 备份；
否则会明确警告并继续。也可以先手动备份：

```bash
sudo systemctl stop ostium-web ostium-worker ostium-jobs
sudo -u ostium /opt/ostium/venv/bin/ostium backup create --password '...'
# 替换 /opt/ostium/venv 与 sing-box
sudo -u ostium /opt/ostium/venv/bin/ostium migrate
sudo -u ostium /opt/ostium/venv/bin/ostium collectstatic --noinput
sudo systemctl start ostium-web ostium-worker ostium-jobs
```

## Docker

```bash
cd deploy/docker
docker compose pull   # 若使用镜像
docker compose up -d --build
```

## 回滚

- 代码/镜像回滚到上一版本。
- 数据库：用升级前备份离线恢复。
- 若新版本已写入不兼容 schema，只能恢复备份；本项目不提供降级迁移。

## 版本策略

- `0.2.x`：补丁与安全修复。
- `0.3.x`：新功能，可能带数据库迁移。
- 不静默自动更新；升级必须由管理员执行。
