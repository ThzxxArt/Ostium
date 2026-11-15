# 从 0.1.2 升级到 0.1.3

0.1.3 是部署可靠性补丁，不新增协议、不改变角色模型、不重做 UI。它修复了部分
VPS/容器网络栈下仪表盘 `/api/v1/system/info` 返回 500 的问题，以及首次安装时
核心健康检查误报“未运行”的问题。

## 1. 升级前

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium status
```

确认备份文件已复制到另一台机器或加密介质。`v0.1.2` 的 tag、Release 资产、
PyPI 和 GHCR 版本是已发布资产，不会被本次升级修改。

## 2. 在线升级

Linux：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

需要固定版本时显式传入 `--version 0.1.3`。安装器会保留数据、配置、证书、
用户、订阅 token 和 `master.key`。

## 3. 升级后验证

```bash
sudo -u ostium ostium version
sudo -u ostium ostium status
sudo -u ostium ostium doctor
```

预期：

- 版本显示 `0.1.3`；
- 管理员、TOTP、恢复码仍然有效；
- 用户、订阅 token、证书、规则集和备份列表仍在；
- 仪表盘可以加载，`/api/v1/system/info` 不再返回 500；
- Public UI 的证书和监听端口保持不变。

如果使用 Public UI，浏览器强制刷新一次以清除旧的失败页面缓存。

## 4. 回滚

安装器在升级前保留 `venv.old` 与 `pre-upgrade-*` 快照（数据库、WAL/SHM、
`master.key`，Linux 还包含配置副本）。健康检查失败时会自动恢复。需要手工
回滚时：

1. 停止 `ostium` 和 `ostium-core`；
2. 恢复升级前快照；
3. 重新安装 0.1.2 wheel；
4. 保留日志和备份用于诊断。

不要删除 `master.key`；它必须与数据库配套。
