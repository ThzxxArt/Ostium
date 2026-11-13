# Manual tasks / external validation

These items cannot be completed inside this Linux workspace. They are required
for the v0.1.0 release gates and must be performed by a human with the relevant
hardware or accounts.

## Server / network

- [ ] Provision the Hong Kong VPS (Ubuntu 24.04), configure SSH keys, firewall,
      BBR/sysctl and a domain A/AAAA record.
- [ ] Run `scripts/install.sh --role server` on a clean VM and record any
      missing package/command. Verify both systemd units start on boot.
- [ ] Run ACME staging against Pebble/Let's Encrypt staging, then one production
      issuance; verify renewal and UI HTTPS restart.
- [ ] Verify 443/tcp Reality, 443/udp Hysteria2, optional Trojan/SS2022 from a
      real client network; test UDP, IPv6 and DNS behavior.
- [ ] Verify server egress blocks cloud metadata/private ranges and that
      legitimate targets still work.
- [ ] Run a 72h soak with config reloads, subscription refreshes, quota changes
      and a core kill/restart; capture memory/FD/goroutine trends.
- [ ] Run performance tests (iperf3 via SOCKS/TUN, 1/10/100 streams) and record
      the release report.

## Custom core

- [x] Linux amd64 core built locally with Go 1.25.5; `sing-box version` reports
      `1.14.4-ostium.1`, tags include `with_v2ray_api`, and the live collector
      test passes.
- [ ] Build and sign the remaining four release targets
      (`linux/arm64`, `darwin/amd64`, `darwin/arm64`, `windows/amd64`) with
      `scripts/build-core.sh --all`.
- [ ] Start the server core and query `127.0.0.1:19091` gRPC stats for two users;
      verify counters increase and reset correctly after SIGHUP.
- [ ] Publish the core tarballs, checksums, SBOM and manifest to the GitHub
      release.

## Windows

- [ ] Build the PyInstaller one-dir distribution and run the Inno Setup script.
- [ ] Install on a clean Windows 11 x64 VM (non-admin user), confirm the
      `OstiumCore` service exists and starts, and the UI starts at logon.
- [ ] Test TUN with Wintun, system proxy, reconnect after sleep/network change,
      and uninstall cleanup (routes, proxy, service, startup task).
- [ ] Run `scripts/build-windows.ps1` and verify the signed/unsigned artifacts,
      service wrapper and Inno Setup output.
- [ ] Verify SmartScreen behavior and document the checksum/bypass steps.

## macOS

- [ ] Build PyInstaller app/DMG for arm64 and x64.
- [ ] Install on macOS 14/15, verify LaunchDaemon/Agent, utun TUN, system proxy,
      DNS, sleep/wake and uninstall cleanup.
- [ ] Verify Gatekeeper behavior and document the manual allow steps.

## Linux client

- [ ] Install on a clean Ubuntu/Fedora desktop; verify the `ostium` group,
      user systemd unit, TUN capability, GNOME/KDE proxy restore and uninstall.
- [ ] Test a non-GNOME/KDE desktop and document the env-variable fallback.

## UX / accessibility

- [ ] Run the 5-user usability test described in `docs/ux.md`; record times and
      failure points.
- [x] Playwright visual baselines generated and committed for 1440/1024/390 in
      dark and light; reviewed locally.
- [ ] Review the committed baselines on real Windows/macOS/Linux browsers and
      confirm font rendering differences are acceptable.
- [ ] Run axe on every page and keyboard-only walkthroughs; fix serious/critical
      findings and 200% zoom/long-text issues.
- [ ] Validate browser notification permission on Chrome/Edge/Safari and PWA
      install/update on a real device.
- [ ] Validate English/Chinese switching on every page, including long error
      messages and timezone formatting.

## Release / accounts

- [x] Create the GitHub repository `ThzxxArt/Ostium` and push the implementation.
- [x] Isolated Linux install/upgrade/uninstall tests with local release assets,
      including failed-wheel rollback and `--run-as-root --no-service`.
- [x] Real GitHub Release online install (`install-online.sh --version 0.1.0`)
      with uv-managed Python 3.13, SHA256 verification and `ostium 0.1.0`.
- [x] PyPI Trusted Publishing for `ostium-ctl`, GHCR permissions and release
      attestations; Release workflow `43381306485` published `v0.1.0`.
- [x] Downloaded all 17 Release assets and verified `sha256sum -c SHA256SUMS`;
      PyPI wheel install and GHCR tags (`0.1.0`, `v0.1.0`, `latest`) verified.
- [ ] Decide whether to buy a Windows code-signing certificate and Apple
      Developer ID/notarization (optional per PLAN).
- [ ] If immutable provenance is required for the post-release
      `install-online.sh`/`SHA256SUMS` hotfix, publish `v0.1.1` (PyPI 0.1.0
      sdist and tag source still contain the pre-hotfix copy).
- [ ] Complete the legal/AUP review for the chosen hosting provider and
      jurisdiction; this project provides no legal advice.
- [ ] Confirm the final 72h soak, ACME, backup/restore and upgrade/rollback
      gates before announcing v0.1.0.
