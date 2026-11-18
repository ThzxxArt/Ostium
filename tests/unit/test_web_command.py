"""Web command executable resolution."""

from __future__ import annotations

import os
import sys

from ostium.operations.management.commands.web import gunicorn_binary


def test_gunicorn_binary_prefers_the_venv_sibling(monkeypatch, tmp_path):
    python = tmp_path / "python"
    gunicorn = tmp_path / "gunicorn"
    python.write_text("")
    gunicorn.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    gunicorn.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(python))
    assert gunicorn_binary() == str(gunicorn)
    assert os.access(gunicorn, os.X_OK)
