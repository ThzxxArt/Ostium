"""Static-file packaging checks.

These catch source-map and manifest-storage failures that only appear with the
production ``CompressedManifestStaticFilesStorage`` backend.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_collectstatic_with_manifest_storage(settings, tmp_path):
    settings.STATIC_ROOT = str(tmp_path)
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
    }
    call_command("collectstatic", interactive=False, verbosity=0, clear=True)
    assert (tmp_path / "staticfiles.json").is_file()
