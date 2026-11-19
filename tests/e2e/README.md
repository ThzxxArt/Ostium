# E2E

真实客户端 E2E 使用高位端口，不需要 root：

```bash
OSTIUM_E2E=1 uv run pytest tests/e2e/test_client_matrix.py -q
```

测试会启动：

- 本地 sing-box 服务端（临时数据目录、高位端口）；
- 本地 TLS 目标，用于 VLESS Reality 握手；
- 真实 Mihomo / sing-box / Xray 客户端；
- 通过 `https://example.com` 验证实际出网。

二进制查找顺序：

```text
OSTIUM_SINGBOX_PATH / .cache/bin/sing-box
mihomo                  / .cache/bin/mihomo
OSTIUM_XRAY_PATH        / .cache/bin/xray
```

CI 的 `e2e` workflow 会下载 pinned 版本并运行同一测试。生产环境建议额外用真实
公网出口和真实客户端做一次验证。