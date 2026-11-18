# E2E

真实代理 E2E 需要 root 或 `CAP_NET_BIND_SERVICE` 才能绑定 443。开发主机上的验证步骤
与结果记录在 [`docs/operations/e2e-evidence.md`](../../docs/operations/e2e-evidence.md)。

生产环境请在 systemd 或 Docker Compose 中运行，并使用真实公网出口。
