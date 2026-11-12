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

- [ ] Install Go 1.25.5 and run `scripts/build-core.sh` for all five targets.
- [ ] Confirm `sing-box version` reports `1.14.4-ostium.1` and tags include
      `with_v2ray_api`, not `with_naive_outbound`.
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
- [ ] Generate Playwright visual baselines at 1440/1024/390 in dark and light;
      review diffs.
- [ ] Run axe on every page and keyboard-only walkthroughs; fix serious/critical
      findings and 200% zoom/long-text issues.
- [ ] Validate English/Chinese switching on every page, including long error
      messages and timezone formatting.

## Release / accounts

- [ ] Create the GitHub repository `ThzxxArt/Ostium` and push the implementation
      (requires explicit approval).
- [ ] Configure PyPI Trusted Publishing for `ostium-ctl`, GHCR permissions and
      GitHub release signing/attestation.
- [ ] Decide whether to buy a Windows code-signing certificate and Apple
      Developer ID/notarization (optional per PLAN).
- [ ] Run the release workflow on tag `v0.1.0`, verify `SHA256SUMS`, SBOM,
      wheel, core artifacts, Docker image and GitHub release.
- [ ] Complete the legal/AUP review for the chosen hosting provider and
      jurisdiction; this project provides no legal advice.
- [ ] Confirm the final 72h soak, ACME, backup/restore and upgrade/rollback
      gates before announcing v0.1.0.
