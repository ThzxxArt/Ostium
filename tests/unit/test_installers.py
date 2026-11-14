from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_linux_upgrade_rewrites_console_script_shebangs() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'OLD_VENV="$NEW_VENV"' in script
    assert 'sed -i "1s|^#!$OLD_VENV/|#!$PREFIX/venv/|" "$script"' in script
    assert 'mv "$NEW_VENV" "$PREFIX/venv"' in script
    assert 'install --no-cache-dir "$WHEEL"' in script


def test_server_init_files_are_owned_by_service_user() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'chown -R ostium:ostium "$DATA" "$CONFIG"' in script
    assert 'if [[ "$RUN_AS_ROOT" != "true" ]]; then\n    chown -R ostium:ostium' in script


def test_public_ui_cannot_be_enabled_during_initial_install() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'if [[ "$PUBLIC_UI" == "true" && "$UPGRADE" != "true" ]]' in script
    assert "--public-ui 不能在首次安装时启用" in script


def test_offline_installer_can_use_release_assets() -> None:
    script = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert "extract_source()" in script
    assert "ostium_ctl-*.tar.gz" in script
    assert 'verify_asset "$SDIST" "$SUMS"' in script
    assert "archive/refs/tags" not in script
    assert 'verify_asset "$WHEEL" "$SUMS"' in script
    assert 'verify_asset "$CORE" "$SUMS"' in script


def test_release_bundles_include_license_and_sbom() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "install_license()" in install
    assert "for doc in LICENSE NOTICE; do" in install
    assert "for doc in LICENSE SBOM.txt; do" in install
    windows = (ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    assert 'Copy-Item "LICENSE", "NOTICE" $out -Force' in windows
    assert 'foreach ($doc in @("LICENSE", "SBOM.txt"))' in windows


def test_installers_default_to_loopback_and_require_insecure_opt_in() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    online = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert 'UI_HOST="${OSTIUM_UI_HOST:-127.0.0.1}"' in install
    assert "--allow-insecure-bind" in install
    assert "allow_insecure_bind = $ALLOW_INSECURE_BIND" in install
    assert "--allow-insecure-bind" in online
    assert "ALLOW_INSECURE_BIND" in online
    assert "0.0.0.0 已收敛为 127.0.0.1" in install
    assert "grep -Eq '^[[:space:]]*public_ui[[:space:]]*=[[:space:]]*true'" in install
    assert 'EXISTING_PORT="$(sed -n' in install


def test_linux_uninstall_restores_proxy_and_preserves_data_by_default() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "--uninstall" in install
    assert "--purge" in install
    assert "proxy off" in install
    assert 'rm -rf "$DATA" "$CONFIG" "$PREFIX" "$CLIENT_DATA" "$CLIENT_UI_DATA"' in install
    assert 'rm -rf "$user_home/.local/share/ostium"' in install
    assert "Ostium 程序与服务已移除；数据保留在" in install


def test_release_workflow_publishes_all_platform_assets_immutably() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "overwrite_files: false" in workflow
    assert "macos-dmg" in workflow
    assert "linux-packages" in workflow
    assert "build-linux-packages.sh" in workflow
    assert "build-sbom.py" in workflow
    assert "ostium-sbom.cdx.json" in workflow
    assert "npx playwright test" in workflow


def test_core_checksum_file_is_download_friendly() -> None:
    script = (ROOT / "scripts" / "build-core.sh").read_text(encoding="utf-8")
    assert '(cd "$OUT_DIR" && sha256sum "$name.tar.gz" >"$name.tar.gz.sha256")' in script
    assert 'sha256sum "$dir.tar.gz"' not in script


def test_linux_units_are_rendered_for_custom_paths() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "render_unit()" in script
    assert "s#/opt/ostium#$PREFIX#g" in script
    assert "s#/var/lib/ostium-core#$CLIENT_DATA#g" in script
    assert "s#/var/lib/ostium\\([ /]\\)#$data_dir\\1#g" in script
    assert "s#/var/lib/ostium\\$#$data_dir#g" in script
    assert "s#/etc/ostium/client.toml#__OSTIUM_CLIENT_CONFIG__#g" in script
    assert "s#__OSTIUM_CLIENT_CONFIG__#$CLIENT_CONFIG#g" in script
    assert 'install_unit "' not in script
    assert 'install -m 0644 "$(dirname "$0")/../deploy/systemd/user/ostium.service"' not in script


def test_installers_reject_conflicting_tls_and_unsafe_links() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    online = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert "--behind-proxy 与 --public-ui 互斥" in install
    assert "--behind-proxy 与 --public-ui 互斥" in online
    assert 'validate_install_path "$BIN_LINK"' in install
    assert 'validate_install_path "$BIN_LINK"' in online
    assert 'validate_install_path "$SYSTEMD_DIR"' in install
    assert 'validate_install_path "$SYSTEMD_DIR"' in online
    assert 'chmod 0640 "$CLIENT_CONFIG"' in install
    assert 'chmod 0660 "$CLIENT_CONFIG"' not in install
    assert "export OSTIUM_NO_START=true" in online
    assert "export OSTIUM_NO_START=1" not in online
