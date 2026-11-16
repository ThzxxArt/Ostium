# 从 0.1.4 升级到 0.1.5

0.1.5 是登录、Windows 客户端和 Clash 订阅的三点修复补丁，不新增协议、
不改变角色模型、不重做 UI。

## 1. 升级前

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
sudo -u ostium ostium status
```

确认备份文件已复制到另一台机器或加密介质。`v0.1.4` 的 tag、Release 资产、
PyPI 和 GHCR 版本是已发布资产，不会被本次升级修改。

## 2. 在线升级

Linux：

```bash
curl -fsSL https://github.com/ThzxxArt/Ostium/releases/latest/download/install-online.sh \
  | sudo bash -s -- upgrade
```

需要固定版本时显式传入 `--version 0.1.5`。安装器会保留数据、配置、证书、
用户、订阅 token 和 `master.key`。

## 3. 升级后验证

```bash
sudo -u ostium ostium version
sudo -u ostium ostium status
sudo -u ostium ostium doctor
```

预期：

- 版本显示 `0.1.5`；
- 管理员、TOTP、恢复码仍然有效；
- 打开登录页时，如果账号已启用 TOTP，验证码输入框**第一次就显示**；
  只输入账号密码点登录不会增加失败次数；
- 错误验证码仍然会增加失败次数并触发锁定；
- 用户、订阅 token、证书、规则集和备份列表仍在；
- 订阅页刷新后，Clash 订阅包含 `dns.enhanced-mode: fake-ip` 和
  `GEOIP,CN,DIRECT,no-resolve`；
- Public UI 的证书和监听端口保持不变。

浏览器强制刷新一次以清除旧的页面资源。第三方 Clash 客户端需要重新拉取
订阅，旧缓存不会自动更新规则。

## 4. Windows 客户端

Windows 必须重新运行 `Ostium-0.1.5-windows-x64-setup.exe`：

- 安装器会等待 `http://127.0.0.1:8787/healthz` 成功后才报告完成；
- 安装目录加入机器级 `PATH`，新开的终端可以直接运行 `ostium`；
- 启动日志在 `%ProgramData%\Ostium\logs\ui.log`。

如果 8787 仍打不开，先把该日志和 `Get-ScheduledTask Ostium`、
`Get-ScheduledTaskInfo Ostium` 的输出附到 issue。

## 5. 回滚

安装器在升级前保留 `venv.old` 与 `pre-upgrade-*` 快照（数据库、WAL/SHM、
`master.key`，Linux 还包含配置副本）。健康检查失败时会自动恢复。需要手工
回滚时：

1. 停止 `ostium` 和 `ostium-core`；
2. 恢复升级前快照；
3. 重新安装 0.1.4 wheel；
4. 保留日志和备份用于诊断。

不要删除 `master.key`；它必须与数据库配套。
