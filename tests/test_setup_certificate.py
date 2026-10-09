# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Setup meeting a server whose https certificate isn't trusted: at a terminal it asks what to do, tries again with
the answer and writes it into config.yml as server.verify; anywhere else it stops and says why."""
import builtins
import getpass

import pytest
import requests

from cinesets import cli, config, servers
from test_catalog_config import _Info, serve_libraries
from test_server_errors import UNTRUSTED

URL = "https://media.example.com:8920"


class Terminal:
    """sys.stdin as a person at a terminal."""

    def isatty(self):
        return True


@pytest.fixture
def self_signed(monkeypatch):
    """A Jellyfin whose certificate isn't trusted: any request that checks it fails, one that doesn't gets an answer."""
    seen = []

    def get(url, **kw):
        seen.append(kw.get("verify", True))
        if kw.get("verify", True) is True:
            raise UNTRUSTED
        if url.endswith("/System/Info/Public"):
            return _Info(200, {"ProductName": "Jellyfin Server", "Version": "10.11.0"})
        raise requests.ConnectionError("nothing there")
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    serve_libraries(monkeypatch, lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    return seen


def answer(monkeypatch, *lines):
    replies = iter(lines)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(replies))


def test_setup_can_use_the_ca_file_that_signed_the_certificate(tmp_path, monkeypatch, self_signed):
    ca = tmp_path / "my-ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setattr(cli.sys, "stdin", Terminal())
    answer(monkeypatch, URL, "1", str(ca), "")
    cli.setup(str(tmp_path / "config.yml"))
    cfg = config.load(str(tmp_path / "config.yml"))
    assert cfg["server"]["type"] == "jellyfin" and cfg["server"]["verify"] == str(ca)
    assert self_signed[0] is True and str(ca) in self_signed     # it tried first, then again with the file


def test_setup_can_skip_the_certificate_check(tmp_path, monkeypatch, self_signed, capsys):
    monkeypatch.setattr(cli.sys, "stdin", Terminal())
    answer(monkeypatch, URL, "2", "")
    cli.setup(str(tmp_path / "config.yml"))
    assert config.load(str(tmp_path / "config.yml"))["server"]["verify"] is False
    assert "can't tell your server from something pretending to be it" in capsys.readouterr().out


def test_setup_can_stop(tmp_path, monkeypatch, self_signed):
    monkeypatch.setattr(cli.sys, "stdin", Terminal())
    answer(monkeypatch, URL, "3")
    with pytest.raises(SystemExit, match="Stopped"):
        cli.setup(str(tmp_path / "config.yml"))
    assert not (tmp_path / "config.yml").exists()


def test_a_missing_ca_file_stops_setup(tmp_path, monkeypatch, self_signed):
    monkeypatch.setattr(cli.sys, "stdin", Terminal())
    answer(monkeypatch, URL, "1", str(tmp_path / "nowhere.pem"))
    with pytest.raises(SystemExit, match="no file at"):
        cli.setup(str(tmp_path / "config.yml"))


def test_without_a_terminal_setup_stops_and_says_why(tmp_path, monkeypatch, self_signed):
    answer(monkeypatch, URL)
    with pytest.raises(servers.UntrustedCertificate) as e:
        cli.setup(str(tmp_path / "config.yml"))
    assert isinstance(e.value, SystemExit) and "server.verify" in str(e.value) and "terminal" in str(e.value)


def test_a_trusted_server_is_never_asked_about(tmp_path, monkeypatch):
    def get(url, **kw):
        assert kw.get("verify", True) is True
        if url.endswith("/System/Info/Public"):
            return _Info(200, {"ProductName": "Jellyfin Server", "Version": "10.11.0"})
        raise requests.ConnectionError("nothing there")
    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    serve_libraries(monkeypatch, lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    monkeypatch.setattr(cli.sys, "stdin", Terminal())
    answer(monkeypatch, URL, "")
    cli.setup(str(tmp_path / "config.yml"))
    assert config.load(str(tmp_path / "config.yml"))["server"]["verify"] is True
