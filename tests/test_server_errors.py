# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""What a refused request says: what went wrong and what to do about it, in plain English, with the HTTP status
kept on the error (the engine stops a run on a 5xx). Also certificates CineSets doesn't trust, at setup and after,
and an API key that can't see an administrator."""
import pytest
import requests

from cinesets import cli, servers
from cinesets.servers import RETRIES, ServerError
from test_server_retries import ALL, EMBY_LIKE, Answer, client, waits  # noqa: F401 (waits is a fixture)

UNTRUSTED = requests.exceptions.SSLError(
    "HTTPSConnectionPool(host='media.example.com', port=8920): Max retries exceeded with url: /System/Info/Public "
    "(Caused by SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
    "self-signed certificate (_ssl.c:1006)')))")
PLAIN_PORT = requests.exceptions.SSLError("[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1006)")


def refusal(srv, call):
    with pytest.raises(ServerError) as e:
        call(srv)
    return e.value


@pytest.mark.parametrize("kind", ALL)
@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_key_says_where_to_make_one(make_cfg, waits, kind, status):
    srv = client(make_cfg, kind, Answer(status, {"detail": "Authentication required"} if kind == "silo" else None))
    e = refusal(srv, lambda s: s.library_folders())
    assert e.status == status and srv.KEY_PAGE in str(e) and "administrator" in str(e) and "server.api_key" in str(e)


@pytest.mark.parametrize("kind", ALL)
def test_nothing_at_the_api_means_the_address_is_wrong(make_cfg, waits, kind):
    srv = client(make_cfg, kind, Answer(404, text="<html><body>Not Found</body></html>"))
    e = refusal(srv, lambda s: s.library_folders())
    assert e.status == 404 and "server.url is probably not" in str(e) and "<html>" not in str(e)


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_a_missing_item_is_not_blamed_on_the_address(make_cfg, waits, kind):
    srv = client(make_cfg, kind, Answer(404, text="Item not found"))
    e = refusal(srv, lambda s: s.backdrop_image("m1"))
    assert e.status == 404 and "server.url" not in str(e)


def test_a_title_silo_no_longer_has_is_not_blamed_on_the_address(make_cfg, waits):
    srv = client(make_cfg, "silo", Answer(404, {"title": "Not Found", "status": 404, "detail": "not found"}))
    e = refusal(srv, lambda s: s.get("/catalog/items/series-tvdb-1"))
    assert e.status == 404 and "server.url" not in str(e)   # add_items and the id lookups rely on this 404


@pytest.mark.parametrize("kind", ALL)
def test_a_poster_too_big_for_a_proxy_says_how_to_let_it_through(make_cfg, waits, kind):
    too_big = Answer(413, text="<html><head><title>413 Request Entity Too Large</title></head></html>")
    answers = [too_big] if kind == "silo" else [Answer(200, {"Id": "9", "ImageTags": {}}), too_big]
    srv = client(make_cfg, kind, *answers)
    e = refusal(srv, lambda s: s.upload_poster("9", b"jpeg", "admin"))
    assert e.status == 413 and "client_max_body_size" in str(e) and "proxy" in str(e)


@pytest.mark.parametrize("kind", ALL)
def test_rate_limiting_that_lasts_says_so(make_cfg, waits, kind):
    srv = client(make_cfg, kind, *[Answer(429)] * (RETRIES + 1))
    e = refusal(srv, lambda s: s.library_folders())
    assert e.status == 429 and "limiting how often" in str(e) and "write_pause" in str(e)


@pytest.mark.parametrize("kind", ALL)
def test_an_untrusted_certificate_says_how_to_set_verify(make_cfg, monkeypatch, waits, kind):
    monkeypatch.setenv("CINESETS_URL", "https://media.example.com:8920")
    srv = client(make_cfg, kind, UNTRUSTED)
    e = refusal(srv, lambda s: s.library_folders())
    assert "https://media.example.com:8920 isn't trusted" in str(e) and "server.verify" in str(e)
    assert len(srv.session.sent) == 1 and not waits      # no use trying again


@pytest.mark.parametrize("kind", ALL)
def test_https_to_a_plain_http_port_is_not_called_a_certificate_problem(make_cfg, monkeypatch, waits, kind):
    monkeypatch.setenv("CINESETS_URL", "https://media.example.com:8096")
    srv = client(make_cfg, kind, PLAIN_PORT)
    with pytest.raises(requests.exceptions.SSLError):
        srv.library_folders()


def test_setup_says_when_the_certificate_is_not_trusted(monkeypatch):
    def get(url, **kw):
        raise UNTRUSTED
    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(SystemExit) as e:
        cli.find_server("https://media.example.com:8920")
    text = str(e.value)
    assert "isn't trusted" in text and "server.verify" in text and "terminal" in text  # and how to get past setup


def test_setup_still_just_does_not_recognise_https_on_a_plain_port(monkeypatch):
    def get(url, **kw):
        raise PLAIN_PORT
    monkeypatch.setattr(requests, "get", get)
    assert servers.detect("https://media.example.com:8096") is None


@pytest.mark.parametrize("kind", EMBY_LIKE)
def test_a_key_that_sees_no_administrator_says_so(make_cfg, waits, kind):
    srv = client(make_cfg, kind, Answer(200, [{"Id": "u1", "Policy": {"IsAdministrator": False}}, {"Id": "u2"}]))
    e = refusal(srv, lambda s: s.admin_user())
    assert "no administrator" in str(e) and srv.KEY_PAGE in str(e)
    srv = client(make_cfg, kind, Answer(200, [{"Id": "u1"}, {"Id": "u2", "Policy": {"IsAdministrator": True}}]))
    assert srv.admin_user() == "u2"
