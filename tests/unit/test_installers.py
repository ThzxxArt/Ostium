from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_linux_upgrade_rewrites_console_script_shebangs() -> None:
    script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'OLD_VENV="$NEW_VENV"' in script
    assert 'sed -i "1s|^#!$OLD_VENV/|#!$PREFIX/venv/|" "$script"' in script
    assert 'mv "$NEW_VENV" "$PREFIX/venv"' in script
    assert 'install --no-cache-dir "$WHEEL"' in script


def test_installers_reject_conflicting_tls_and_unsafe_links() -> None:
    install = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    online = (ROOT / "scripts" / "install-online.sh").read_text(encoding="utf-8")
    assert "--behind-proxy 与 --public-ui 互斥" in install
    assert "--behind-proxy 与 --public-ui 互斥" in online
    assert 'validate_install_path "$BIN_LINK"' in install
    assert 'validate_install_path "$BIN_LINK"' in online
    assert 'validate_install_path "$SYSTEMD_DIR"' in install
    assert 'validate_install_path "$SYSTEMD_DIR"' in online
