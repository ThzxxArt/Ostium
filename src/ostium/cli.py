"""Console-script entry point.

The installed wrapper sources ``/etc/ostium/ostium.env`` so
``DJANGO_SETTINGS_MODULE`` points at production settings. During development
the dev settings are used by default.
"""

from __future__ import annotations

import os
import sys


def main(argv: list[str] | None = None) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ostium.config.settings.dev")
    from django.core.management import execute_from_command_line

    execute_from_command_line(["ostium", *(argv if argv is not None else sys.argv[1:])])


if __name__ == "__main__":
    main()
