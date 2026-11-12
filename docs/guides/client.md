# Client guide

The client is the same Ostium package as the server. It runs a local Web UI at
<http://127.0.0.1:8787> and a privileged core service that owns the mixed proxy
and, when enabled, the TUN device.

## Windows 10 22H2+ / 11 x64

Run `Ostium-0.1.0-windows-x64-setup.exe`. The installer:

- copies the app to `%ProgramFiles%\Ostium`;
- installs the TUN core as the `OstiumCore` Windows service (LocalSystem);
- registers the console at logon for the current user;
- keeps data in `%ProgramData%\Ostium`.

Unsigned builds trigger SmartScreen. Verify the release SHA256 and use
“More info → Run anyway” only if you trust the source.

## macOS 14+

Open the DMG and run `install-macos.sh` with `sudo`. It installs a LaunchDaemon
for the core and a LaunchAgent for the UI. Unsigned/notarised builds trigger
Gatekeeper; verify checksums and allow manually.

## Linux x64/arm64

```bash
sudo ./install.sh --role client \
  --wheel ./ostium_ctl-0.1.0-py3-none-any.whl \
  --core ./ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz
```

Log out and back in so your user picks up the `ostium` group, then:

```bash
systemctl --user enable --now ostium
```

Open <http://127.0.0.1:8787>, complete the setup wizard and import a
subscription.

## First connection

1. **Profiles → Import** a subscription URL or share link.
2. Pick a profile and an endpoint on **Home**.
3. Start with **System proxy**; switch to **TUN** only when you need full
   TCP/UDP/DNS capture.
4. Use **Diagnostics** if a connection fails; it checks port, DNS, route, TUN,
   proxy and core health.

## Modes

| Mode | What it captures | Limits |
|---|---|---|
| Mixed proxy | Apps explicitly configured for `127.0.0.1:7890` | No DNS takeover |
| System proxy | Apps that honour the OS proxy | No DNS takeover; some apps bypass it |
| TUN | TCP/UDP/DNS on the whole machine | Requires admin/root; no standalone kill switch |

System proxy and TUN are mutually exclusive; switching cleans up the old mode.

## Updates

Ostium never silently updates. Use **Settings → Check for updates**, download
the signed release, verify the checksum and install it. The core keeps running
while the UI is upgraded; upgrading the core causes a brief tunnel interruption.

## Uninstall

- Windows: Apps → Ostium → Uninstall (data preserved unless removed).
- macOS: remove the LaunchDaemon/Agent and `/opt/ostium`; data in
  `/Library/Application Support/Ostium`.
- Linux: stop and disable `ostium-core` and the user `ostium` unit, then remove
  `/opt/ostium`. Remove `/var/lib/ostium-core` only if you want to delete data.

The uninstaller restores the system proxy and asks the core to clean routes and
the virtual interface.
