"""Windows-only cleanup for TUN state left behind by a crashed core.

``TerminateProcess`` does not unwind sing-box's Wintun/routing cleanup.  A
stale default route through a dead ``ostium0`` adapter blackholes outbound
traffic until the machine reboots, which looks like "the server is down" even
though raw TCP from another host works.  The privileged core calls this on
startup and after stopping sing-box.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any


def cleanup_script(interface_name: str) -> str:
    safe = interface_name.replace("'", "''")
    return f"""
$ErrorActionPreference = 'SilentlyContinue'
$names = @('{safe}', 'Ostium', 'sing-box')
$adapters = @(Get-NetAdapter -IncludeHidden | Where-Object {{
    $names -contains $_.Name -or $_.InterfaceDescription -match 'Ostium|sing-box'
}})
$removedRoutes = 0
foreach ($adapter in $adapters) {{
    $routes = @(Get-NetRoute -InterfaceIndex $adapter.ifIndex)
    foreach ($route in $routes) {{
        Remove-NetRoute -DestinationPrefix $route.DestinationPrefix `
            -InterfaceIndex $adapter.ifIndex -NextHop $route.NextHop `
            -Confirm:$false
        $removedRoutes += 1
    }}
    Disable-NetAdapter -Name $adapter.Name -Confirm:$false
}}
$staleRoutes = @(Get-NetRoute | Where-Object {{
    $_.InterfaceAlias -match '^({safe}|Ostium|sing-box)'
}})
foreach ($route in $staleRoutes) {{
    Remove-NetRoute -DestinationPrefix $route.DestinationPrefix `
        -InterfaceIndex $route.ifIndex -NextHop $route.NextHop -Confirm:$false
    $removedRoutes += 1
}}
"adapters=$($adapters.Count) routes=$removedRoutes"
"""


def cleanup_stale_tun(interface_name: str = "ostium0", *, timeout: float = 20.0) -> dict[str, Any]:
    """Remove only Ostium's stale adapters/routes.  Never touches other VPNs."""

    if os.name != "nt":
        return {"ok": True, "skipped": "not windows"}
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        cleanup_script(interface_name),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc) or exc.__class__.__name__}
    output = (result.stdout or "").strip()
    return {
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "output": output[-500:],
        "error": (result.stderr or "").strip()[-500:] or None,
    }
