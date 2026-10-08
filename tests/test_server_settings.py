# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The server settings each module reads for itself: server.verify, which goes with every request (setup's included),
and server.url, tidied by the server's own module wherever it comes from, only ever in its path."""
import os
import subprocess
import sys

import pytest
import requests

from cinesets import config, servers
from cinesets.servers import emby, jellyfin, silo
from test_server_retries import ALL, Answer, client, waits  # noqa: F401 (waits is a fixture)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- server.verify
@pytest.mark.parametrize("kind", ALL)
def test_a_ca_file_goes_with_every_request(make_cfg, monkeypatch, tmp_path, kind):
    (tmp_path / "home-ca.pem").write_text("a CA certificate")
    cfg = make_cfg(kind)
    cfg["server"]["verify"] = "home-ca.pem"                        # relative to config.yml's folder
    srv = {"emby": emby.EmbyServer, "jellyfin": jellyfin.JellyfinServer, "silo": silo.SiloServer}[kind](cfg)
    assert srv.verify == str(tmp_path / "home-ca.pem")


@pytest.mark.parametrize("kind", ALL)
@pytest.mark.parametrize("verify", [True, False])
def test_the_setting_reaches_the_request(make_cfg, monkeypatch, kind, verify):
    monkeypatch.setenv("CINESETS_URL", "https://media.example.com")
    cfg = make_cfg(kind)
    cfg["server"]["verify"] = verify
    srv = client(lambda k: cfg, kind, Answer(200, {"items": []} if kind == "silo" else []))
    srv.library_folders()
    assert srv.session.sent[0][2]["verify"] is verify


def test_silo_artwork_storage_gets_the_setting_too(make_cfg, monkeypatch):
    cfg = make_cfg("silo")
    cfg["server"]["verify"] = False
    srv = client(lambda k: cfg, "silo", Answer(200, {"items": [{"id": "77", "is_primary": True}]}),
                 Answer(200, {"backdrop_url": "https://storage.example.com/art/1.jpg?signature=abc"}))
    seen = []
    monkeypatch.setattr(silo.requests, "get", lambda url, **kw: seen.append(kw) or Answer(200, content=b"jpeg"))
    srv.backdrop_image("movie-tmdb-105")
    assert seen[0]["verify"] is False and srv.session.sent[1][2]["verify"] is False


def test_turning_the_check_off_warns_once_in_plain_words(make_cfg, monkeypatch, capsys):
    monkeypatch.setenv("CINESETS_URL", "https://media.example.com")
    cfg = make_cfg("emby")
    cfg["server"]["verify"] = False
    emby.EmbyServer(cfg)
    assert "server.verify is false" in capsys.readouterr().err
    monkeypatch.setenv("CINESETS_URL", "http://192.0.2.10:8096")   # plain http has no certificate to check
    cfg = make_cfg("emby")
    cfg["server"]["verify"] = False
    emby.EmbyServer(cfg)
    assert "server.verify" not in capsys.readouterr().err


@pytest.mark.parametrize("value, message", [("missing-ca.pem", "no CA certificate file at"), (5, "must be true, false"),
                                            ("", "must be true, false"), (None, "must be true, false")])
def test_a_wrong_setting_says_so(make_cfg, value, message):
    cfg = make_cfg("jellyfin")
    cfg["server"]["verify"] = value
    with pytest.raises(SystemExit, match=message):
        jellyfin.JellyfinServer(cfg)


def test_an_older_config_without_the_setting_checks_certificates(make_cfg):
    cfg = make_cfg("emby")
    del cfg["server"]["verify"]
    assert emby.EmbyServer(cfg).verify is True and config.DEFAULTS["server"]["verify"] is True


def test_detection_takes_the_setting(monkeypatch):
    seen = []

    def get(url, **kw):
        seen.append(kw.get("verify"))
        raise requests.ConnectionError("nothing there")
    monkeypatch.setattr(requests, "get", get)
    assert servers.detect("https://media.example.com", "/config/home-ca.pem") is None
    assert seen and set(seen) == {"/config/home-ca.pem"}
    seen.clear()
    servers.detect("https://media.example.com")
    assert set(seen) == {True}


# ---------------------------------------------------------------- server.url
@pytest.mark.parametrize("pasted, kept", [
    ("http://emby", "http://emby"),                                  # a host called emby keeps its name
    ("http://web:8096/", "http://web:8096"),
    ("http://web:8096/web/index.html#!/home", "http://web:8096"),
    ("http://192.0.2.10:8096/emby/web/index.html#!/home", "http://192.0.2.10:8096"),
    ("https://media.example.com/emby", "https://media.example.com"),
    ("http://192.0.2.10:8096/#!/home", "http://192.0.2.10:8096"),
    ("http://192.0.2.10:8096/web/index.html?x=1", "http://192.0.2.10:8096"),
])
def test_emby_tidies_only_the_path(pasted, kept):
    assert emby.EmbyServer.trim(pasted) == kept


@pytest.mark.parametrize("pasted, kept", [
    ("http://jellyfin", "http://jellyfin"),
    ("http://web", "http://web"),
    ("http://192.0.2.10:8096/web/#/home.html", "http://192.0.2.10:8096"),
    ("https://media.example.com/jellyfin/web/index.html#!/home", "https://media.example.com/jellyfin"),  # a base URL
])
def test_jellyfin_tidies_only_the_path(pasted, kept):
    assert jellyfin.JellyfinServer.trim(pasted) == kept


@pytest.mark.parametrize("host", ["emby", "web", "jellyfin"])
def test_setup_keeps_every_host_name(host):
    assert servers.trim(f"http://{host}") == f"http://{host}"
    assert servers.trim(f"http://{host}:8096/web/index.html#!/home") == f"http://{host}:8096"


@pytest.mark.parametrize("kind", ["emby", "jellyfin"])
def test_a_pasted_address_in_the_environment_is_tidied(make_cfg, monkeypatch, kind):
    monkeypatch.setenv("CINESETS_URL", "http://192.0.2.10:8096/web/index.html#!/home")
    assert make_cfg(kind)["server"]["url"] == "http://192.0.2.10:8096"


def test_tidying_the_address_loads_only_the_configured_server(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text('server: {type: silo, url: "http://192.0.2.10:8080/", api_key: k}\n')
    code = (f"import sys; from cinesets import config; print(config.load({str(path)!r})['server']['url']); "
            "print(sorted(m for m in sys.modules if m.startswith('cinesets.servers.')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert out.split("\n")[:2] == ["http://192.0.2.10:8080", str(["cinesets.servers.base", "cinesets.servers.silo"])]
