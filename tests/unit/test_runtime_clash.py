"""Miscellaneous runtime, Clash API and formatting tests."""

from __future__ import annotations

import json

import pytest

from ostium.engine.clash import ClashClient, ClashError
from ostium.engine.runtime import read_clash_secret, read_config_text, read_usage, tail_file, write_usage
from ostium.formatting import format_bytes, format_datetime, format_duration, relative_time, short_hash


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.content = json.dumps(payload).encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("httpx").HTTPStatusError("bad", request=None, response=None)

    def json(self):
        return self._payload


class FakeClient:
    payload = {}

    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, path):
        return FakeResponse(self.payload)


def test_clash_client(monkeypatch):
    import ostium.engine.clash as clash

    monkeypatch.setattr(clash.httpx, "Client", FakeClient)
    client = ClashClient(secret="s")
    FakeClient.payload = {
        "connections": [
            {
                "id": "1",
                "metadata": {
                    "user": "alice",
                    "inboundName": "vless-in",
                    "network": "tcp",
                    "host": "example.com",
                    "destinationIP": "1.1.1.1",
                    "destinationPort": "443",
                },
                "rule": "match",
                "chains": ["direct"],
                "upload": 10,
                "download": 20,
                "start": "now",
            }
        ]
    }
    assert client.connections()[0]["user"] == "alice"
    FakeClient.payload = {"uploadTotal": 1, "downloadTotal": 2, "connections": []}
    assert client.traffic()["upload_total"] == 1
    FakeClient.payload = {"version": "1"}
    assert client.version() == {"version": "1"}
    client.close_all()
    client.close_connection("1")


def test_clash_client_error(monkeypatch):
    import ostium.engine.clash as clash

    class Broken:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def request(self, *args):
            raise clash.httpx.ConnectError("down")

    monkeypatch.setattr(clash.httpx, "Client", Broken)
    with pytest.raises(ClashError):
        ClashClient().connections()


def test_usage_roundtrip_and_errors(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    write_usage({"stats_ok": True, "users": {"a": {"online": True}}})
    data = read_usage()
    assert data["stats_ok"] is True
    (tmp_path / "runtime" / "usage.json").write_text("not json")
    assert read_usage()["stats_ok"] is False
    assert read_usage()["users"] == {}
    (tmp_path / "runtime" / "usage.json").write_text("[1]")
    assert read_usage()["users"] == {}


def test_runtime_files(tmp_path, settings):
    settings.OSTIUM_DATA_DIR = str(tmp_path)
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "clash.secret").write_text("secret")
    assert read_clash_secret() == "secret"
    (tmp_path / "runtime" / "config.json").write_text('{"a":1}')
    assert read_config_text().startswith("{")
    log = tmp_path / "log"
    log.write_text("a" * 100)
    assert tail_file(log, max_bytes=10) == "a" * 10
    assert tail_file(tmp_path / "missing") == ""
    assert read_clash_secret() == "secret"


def test_formatting_edges():
    assert format_bytes(-1) == "0 B"
    assert format_bytes(None) == "—"
    assert format_bytes(1024**4) == "1.0 TiB"
    assert format_duration(30) == "30s"
    assert format_duration(90000) == "1d 1h"
    assert format_datetime(None) == "—"
    assert relative_time(None) == "never"
    assert short_hash(None) == "—"
