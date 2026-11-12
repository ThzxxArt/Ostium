# Server guide (Ubuntu 24.04 / Debian 13)

## Baseline

- 1 vCPU / 1 GB works; 2 vCPU / 2 GB recommended.
- 20 GB SSD, IPv4/IPv6, UTC, NTP.
- Open 22 (restricted), 80/tcp (ACME), 443/tcp, 443/udp. Open 8443 only if you
  intentionally expose the admin UI.
- Use a non-root sudo user; do not run the UI as root.

## Install

1. Download the release wheel, the matching core tarball and `SHA256SUMS` from
   GitHub Releases.
2. Verify:

   ```bash
   sha256sum -c SHA256SUMS --ignore-missing
   ```

3. Run:

   ```bash
   sudo ./install.sh --role server \
     --wheel ./ostium_art-0.1.0-py3-none-any.whl \
     --core ./ostium-core-1.14.4-ostium.1-linux-amd64.tar.gz \
     --domain vpn.example.com
   ```

4. The installer creates the `ostium` user, installs both systemd services,
   initialises the database and prints a one-time admin password.
5. Open an SSH tunnel and finish setup in the UI:

   ```bash
   ssh -L 8443:127.0.0.1:8443 root@your-server
   ```

   Visit <http://127.0.0.1:8443>. Reality is enabled by default; create a user
   and import the generated subscription on a client.

## Firewall

```bash
ufw default deny incoming
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp
ufw enable
```

Configure the cloud security group too. Do not expose 8388 unless you
explicitly enable Shadowsocks 2022.

## sysctl

```ini
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
fs.file-max = 1000000
```

Run `sysctl --system`. The core unit sets `LimitNOFILE=65535`.

## Services

```bash
systemctl status ostium-core ostium
journalctl -u ostium -u ostium-core -f
```

The UI can restart/reload the core, but it cannot restart itself. Use
`sudo systemctl restart ostium` after changing listener/TLS settings.

## TLS and public UI

Issue a certificate in **Certificates** (ACME HTTP-01 or upload), assign it to
Hysteria2/Trojan, enable TOTP, then enable **Public admin UI** in Settings. The
UI will refuse to serve publicly over plain HTTP; restart `ostium.service` after
the change.

## Backups

Create an encrypted backup from Settings or:

```bash
sudo -u ostium ostium backup create --password 'a long passphrase'
```

The file lands in `/var/lib/ostium/backups`. Store it off-host. Restore requires
stopping both services or staging the restore from the UI and restarting.

## Operations

- `ostium doctor`
- `ostium logs --source core -f`
- `ostium diagnostics export`
- `ostium core version`
- `ostium update --check`

Never expose the control plane without TLS+TOTP. Never run the UI as root.
