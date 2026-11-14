from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_linux_upgrade_rewrites_console_script_shebangs() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'OLD_VENV="$NEW_VENV"' in script
    assert 'sed -i "1s|^#!$OLD_VENV/|#!$PREFIX/venv/|" "$script"' in script
    assert 'mv "$NEW_VENV" "$PREFIX/venv"' in script
    assert 'install --no-cache-dir "$WHEEL"' in script


def test_supplying_python_still_installs_curl_tar_and_ca_certificates() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "ca-certificates curl tar" in install
    # The dependency install is outside the "if [[ -z $PYTHON_BIN ]]" block.
    before_python = install.split('if [[ -z "$PYTHON_BIN" ]]; then', 1)[0]
    assert "ca-certificates curl tar" in before_python


def test_reinstall_over_an_existing_database_does_not_print_a_new_password() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'DB_PREEXISTING="false"' in install
    assert 'elif [[ "$DB_PREEXISTING" == "true" ]]; then' in install
    assert 'ADMIN_PASSWORD_DISPLAY="未更改（已有数据库）"' in install


def test_service_accounts_create_or_reuse_a_real_group() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    deb = (ROOT / "scripts" / "build-linux-packages.sh").read_text(encoding="utf-8")
    assert "getent group ostium >/dev/null || groupadd --system ostium" in install
    assert "useradd --system --gid ostium" in install
    assert "getent group ostium >/dev/null 2>&1 || groupadd --system ostium" in deb
    assert "adduser --system --ingroup ostium" in deb
    assert "install -d -m 0750 -o ostium -g ostium" in deb


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


def test_upgrade_snapshots_state_and_restores_services_on_failure() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "snapshot_upgrade_state()" in install
    assert "restore_upgrade_snapshot()" in install
    assert "restore_upgrade_services()" in install
    assert "trap cleanup_install EXIT" in install
    assert 'UPGRADE_SERVICES_STOPPED="true"' in install
    # Services are stopped only after the new virtualenv is fully staged.
    assert install.index("stop_services\n  UPGRADE_SERVICES_STOPPED") > install.index(
        'pip" install --no-cache-dir "$WHEEL"'
    )


def test_upgrade_core_health_accepts_an_idle_but_ready_core() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "wait_for_core()" in install
    assert "grep -q '\"running\"'" not in install
    assert "if ! systemctl is-active --quiet ostium-core || ! wait_for_core; then" in install


def test_online_installer_requires_the_uv_checksum() -> None:
    script = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert "拒绝安装未校验的 uv" in script
    assert "继续安装" not in script.split("uv-${uv_target}.tar.gz.sha256", 1)[1].split("fi", 1)[0]


def test_online_purge_does_not_delete_pre_existing_service_accounts() -> None:
    script = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert "userdel ostium" not in script
    assert "userdel ostium-core" not in script


def test_online_uninstall_stops_the_user_ui_before_deleting_it() -> None:
    script = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert "systemctl --user disable --now ostium" in script
    assert "default.target.wants/ostium.service" in script


def test_online_upgrade_detects_the_installed_role() -> None:
    script = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert "detect_existing_role()" in script
    assert 'ROLE_EXPLICIT="false"' in script
    assert '"$CONFIG/client.toml"' in script
    assert "need_root\ndetect_existing_role\ndetect_platform" in script


def test_macos_upgrade_checks_and_rolls_back_the_core_and_user_agent() -> None:
    script = (ROOT / "deploy" / "launchd" / "install-macos.sh").read_text(encoding="utf-8")
    assert "wait_for_core()" in script
    assert "rollback_core_binary()" in script
    assert 'if [[ -n "$OLD_VENV" ]] && ! wait_for_core; then' in script
    assert 'launchctl asuser "$(id -u "$SUDO_USER")" launchctl unload -w' in script
    assert 'cp -p "$target" "$target.old"' in script


def test_mode_switch_removes_stale_root_and_opposite_units() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert '"$SYSTEMD_DIR/ostium.service.d/root.conf"' in install
    assert '"$SYSTEMD_DIR/ostium-core.service.d/root.conf"' in install
    assert (
        'rm -f "$SYSTEMD_DIR/ostium.service" "$SYSTEMD_DIR/ostium.service.d/root.conf"' in install
    )
    assert 'rm -f "$USER_HOME/.config/systemd/user/ostium.service"' in install


def test_client_upgrade_restarts_the_user_ui() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "systemctl --user restart ostium.service" in install
    assert 'if [[ "$UPGRADE" == "true" && "$START" == "true" ]]; then' in install


def test_fresh_install_waits_for_the_health_endpoint() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "首次安装健康检查失败" in install
    assert 'wait_for_url "http://127.0.0.1:$UI_PORT/healthz"' in install


def test_release_bundles_include_license_and_sbom() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "install_license()" in install
    assert "for doc in LICENSE NOTICE; do" in install
    assert "for doc in LICENSE SBOM.txt; do" in install
    windows = (ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    assert 'Copy-Item "LICENSE", "NOTICE" $out -Force' in windows
    assert 'foreach ($doc in @("LICENSE", "SBOM.txt"))' in windows


def test_installers_reject_a_bare_user_home_as_prefix() -> None:
    for name in ("install.sh", "install-online.sh"):
        script = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "home_rest" in script
        assert "拒绝把用户主目录本身作为" in script
        assert "/usr/local|/usr/local/bin" in script
    macos = (ROOT / "deploy" / "launchd" / "install-macos.sh").read_text(encoding="utf-8")
    assert "home_rest" in macos
    assert "refusing to use a user home" in macos


def test_upgrade_preserves_an_existing_insecure_bind_opt_in() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "EXISTING_INSECURE_BIND" in install
    assert 'if [[ "$EXISTING_INSECURE_BIND" == "true" ]]; then' in install


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


def test_linux_uninstall_does_not_require_install_artifacts() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'if [[ "$UNINSTALL" != "true" ]]; then' in install
    assert '"$UNINSTALL" != "true"' in install
    assert "DB_PREEXISTING" in install


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
