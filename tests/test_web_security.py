# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The dashboard's defences: request bodies, busy slots, sign-in limits, sessions, web.json, Host names and the media
server's API key never reaching the browser."""
import contextlib
import errno
import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from cinesets import config, posters, web
from cinesets.engine import SAFE_ID
from cinesets.lists import SLUG
from conftest import FakeServer, seed_index

API_KEY = "media-server-key-5f3a9c71"  # one that can't turn up in a reply by chance
YML = """collections:
  - key: m-bttf
    group: universes
    type: movie
    title: "Back to\\nthe Future"
    accent: blue
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
      - ["Back to the Future Part III", 1990]
  - key: m-netflix
    group: streaming
    type: movie
    title: "Netflix"
    logo: netflix
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
"""
ITEMS = {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie"),
         "m3": ("Back to the Future Part III", 1990, "movie")}
ROWS = [{"title": "Back to the Future", "mediatype": "movie", "imdb_id": "tt1", "id": 105},
        {"title": "Unknown Film", "mediatype": "movie", "imdb_id": "tt9", "id": 9}]


class Client:
    """Talks to the dashboard like the page does, keeping the session cookie, and keeps every reply it gets."""

    def __init__(self, base):
        self.base, self.cookie, self.replies = base, None, []

    def call(self, path, body=None, header=True, extra=None):
        headers = {"X-CineSets": "1"} if header else {}
        if self.cookie:
            headers["Cookie"] = f"cinesets={self.cookie}"
        headers.update(extra or {})
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status, data, got = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, data, got = e.code, e.read(), e.headers
        self.replies.append((path, status, data, str(got)))
        if got.get("Set-Cookie"):
            self.cookie = got["Set-Cookie"].split(";")[0].split("=", 1)[1] or None
        with contextlib.suppress(ValueError):
            data = json.loads(data)
        return status, data

    def sign_in(self, key):
        return self.call("/api/login", {"key": key})


class Site:
    def __init__(self, cfg, app, httpd):
        self.cfg, self.app, self.httpd = cfg, app, httpd
        self.port = httpd.server_address[1]
        self.key = web.read_access(web.access_file(cfg))["key"] if httpd.gate else None

    def client(self):
        return Client(f"http://127.0.0.1:{self.port}")


@contextlib.contextmanager
def running(make_cfg, kind="emby", **options):
    """A dashboard on a free port, against an in-memory server, with an API key that's easy to spot."""
    cfg = make_cfg(kind, YML)
    path = os.path.join(cfg["base_dir"], "config.yml")
    with open(path) as f:
        text = f.read()
    with open(path, "w") as f:
        f.write(text.replace('"test-key"', f'"{API_KEY}"'))
    seed_index(cfg, ITEMS)
    srv = FakeServer(kind)
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    app = web.Dashboard(path, server=srv)
    httpd = web.make_server(app, "127.0.0.1", 0, **options)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        yield Site(cfg, app, httpd)
    finally:
        httpd.shutdown()
        httpd.server_close()
        app.close()


def by_hand(port, method, path, headers, body=b""):
    """A request written out by hand, so a test can send a body slowly, partly or not at all."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    head = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
    sock.sendall((head + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n").encode() + body)
    return sock


def answer(sock, wait=5):
    """The reply to a request sent by hand: (status, its JSON). Times out rather than waiting for ever."""
    sock.settimeout(wait)
    data = b""
    while b"\r\n\r\n" not in data:
        piece = sock.recv(65536)
        assert piece, "the dashboard closed the connection without answering"
        data += piece
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    size = next(int(line.split(":", 1)[1]) for line in lines if line.lower().startswith("content-length:"))
    while len(body) < size:
        piece = sock.recv(65536)
        assert piece, "the reply was cut short"
        body += piece
    return int(lines[0].split()[1]), json.loads(body)


def signed_out_save(port, size):
    return by_hand(port, "POST", "/api/save", {"X-CineSets": "1", "Content-Type": "application/json",
                                               "Content-Length": size})


# ---------------------------------------------------------------- request bodies
@pytest.mark.parametrize("size", ["-1", "-5", "abc", "1e3", "+5", "9" * 5000])
def test_a_content_length_that_isnt_a_plain_number_is_refused_at_once(make_cfg, size):
    with running(make_cfg) as site:
        sock = by_hand(site.port, "POST", "/api/login", {"X-CineSets": "1", "Content-Length": size})
        with sock:
            status, out = answer(sock)               # read(-1) would wait here until the connection closed
        assert status == 400 and out["error"] == "Bad request"


def test_signed_out_requests_are_answered_without_waiting_for_their_body(make_cfg):
    with running(make_cfg) as site:
        took = time.monotonic()
        with signed_out_save(site.port, 1000) as sock:  # promises a body and never sends it
            status, out = answer(sock)
        assert status == 401 and "Sign in" in out["error"] and time.monotonic() - took < 3


def test_a_signed_out_request_still_gets_its_answer_after_sending_a_big_body(make_cfg):
    """The body is read and dropped after the answer, so the browser sees the 401 (and the sign-in card) rather than a
    broken connection halfway through sending. Nearly the most allowed, so it can't all wait in the socket buffers."""
    with running(make_cfg) as site:
        status, out = site.client().call("/api/save", {"posters": {"pad": "x" * (web.MAX_BODY - 1000)}})
        assert status == 401 and "Sign in" in out["error"]


def test_slow_uploads_and_signed_out_requests_cant_take_every_busy_slot(make_cfg):
    with running(make_cfg) as site:
        client = site.client()
        assert client.sign_in(site.key)[0] == 200
        stuck = [signed_out_save(site.port, 1000) for _ in range(web.BUSY_LIMIT)]
        stuck += [by_hand(site.port, "POST", "/api/login", {"X-CineSets": "1", "Content-Length": 100}, b'{"key": "')
                  for _ in range(web.BUSY_LIMIT)]
        try:
            time.sleep(0.5)                                   # all of them have arrived and are waiting
            assert client.call("/api/info")[0] == 200         # someone signed in still gets in
            assert client.call("/api/session")[1]["signed_in"] is True
        finally:
            for sock in stuck:
                sock.close()


def test_a_body_trickling_in_has_a_deadline(make_cfg, monkeypatch):
    monkeypatch.setattr(web.Handler, "body_seconds", 1)
    with running(make_cfg) as site:
        sock = by_hand(site.port, "POST", "/api/login", {"X-CineSets": "1", "Content-Length": 60}, b'{"key": "')
        stop = threading.Event()

        def trickle():  # a byte every 0.2 seconds: each one is in time for the connection's own timeout
            while not stop.wait(0.2):
                with contextlib.suppress(OSError):
                    sock.sendall(b"x")
        threading.Thread(target=trickle, daemon=True).start()
        took = time.monotonic()
        try:
            status, out = answer(sock)
        finally:
            stop.set()
            sock.close()
        assert status == 408 and "too long" in out["error"] and time.monotonic() - took < 4


def test_sign_in_bodies_are_small(make_cfg):
    with running(make_cfg) as site:
        with by_hand(site.port, "POST", "/api/login", {"X-CineSets": "1", "Content-Length": 5000}) as sock:
            status, out = answer(sock)
        assert status == 413 and "too big" in out["error"]
        assert site.client().sign_in(site.key)[0] == 200


# ---------------------------------------------------------------- signing in
def gate_with(tmp_path, monkeypatch, password=None):
    monkeypatch.setattr(web, "PBKDF2_ROUNDS", 1000)  # quick hashes for tests
    monkeypatch.setattr(web.time, "sleep", lambda s: None)
    path = str(tmp_path / "web.json")
    web.read_access(path)
    if password:
        web.set_password(path, password)
    return web.Gate(path)


def outcome(gate, given, address="203.0.113.5"):
    try:
        return 200 if gate.login(given, address) else None
    except web.Problem as e:
        return e.status


def test_the_access_key_always_signs_in_and_only_other_tries_are_limited(make_cfg, monkeypatch):
    monkeypatch.setattr(web, "PBKDF2_ROUNDS", 1000)
    monkeypatch.setattr(web.time, "sleep", lambda s: None)
    with running(make_cfg) as site:
        web.set_password(web.access_file(site.cfg), "correct horse battery")
        client = site.client()
        assert [client.sign_in(f"guess-{n}")[0] for n in range(5)] == [401] * 5
        status, out = client.sign_in("correct horse battery")
        assert status == 429 and "about 10 minutes" in out["error"] and "access key" in out["error"]
        assert client.sign_in(site.key)[0] == 200 and client.call("/api/info")[0] == 200


def test_tries_sent_together_are_counted_before_any_is_checked(tmp_path, monkeypatch):
    gate = gate_with(tmp_path, monkeypatch, "correct horse battery")
    checking = web.check_password

    def slow_check(stored, given):  # every try is still being checked when the others arrive
        threading.Event().wait(0.1)
        return checking(stored, given)
    monkeypatch.setattr(web, "check_password", slow_check)
    start, results = threading.Barrier(16), []

    def guess(n):
        start.wait()
        results.append(outcome(gate, f"guess-{n}"))
    threads = [threading.Thread(target=guess, args=(n,)) for n in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [401] * gate.TRIES + [429] * (16 - gate.TRIES)


def test_the_overall_limit_and_the_right_password(tmp_path, monkeypatch):
    gate = gate_with(tmp_path, monkeypatch, "correct horse battery")
    assert [outcome(gate, "correct horse battery") for _ in range(10)] == [200] * 10   # right ones don't count
    assert outcome(gate, "\ud800", "198.51.100.200") == 401                     # half a character is just a try
    assert [outcome(gate, "wrong", f"198.51.100.{n}") for n in range(gate.TRIES_ALL - 1)] == [401] * (gate.TRIES_ALL - 1)
    assert outcome(gate, "correct horse battery", "192.0.2.77") == 429          # everyone's tries are used up
    assert outcome(gate, gate.current()["key"], "192.0.2.77") == 200            # but the key still works


def test_old_tries_are_forgotten_and_the_wait_is_given_in_minutes(tmp_path, monkeypatch):
    gate = gate_with(tmp_path, monkeypatch, "correct horse battery")
    now = time.time()
    gate.fails = {f"198.51.100.{n}": [now - 700] for n in range(50)}
    gate.fails["*"] = [now - 700] * 50
    assert outcome(gate, "wrong", "203.0.113.5") == 401
    assert set(gate.fails) == {"203.0.113.5", "*"}                              # stale addresses are dropped
    gate.fails = {"203.0.113.5": [now - 60] * gate.TRIES, "*": [now - 60] * gate.TRIES}
    with pytest.raises(web.Problem, match="about 9 minutes") as refused:
        gate.login("correct horse battery", "203.0.113.5")
    assert refused.value.status == 429
    gate.fails = {"203.0.113.5": [now - 599.5] * gate.TRIES, "*": [now - 599.5] * gate.TRIES}
    with pytest.raises(web.Problem, match="about 1 minute before"):
        gate.login("wrong", "203.0.113.5")
    gate.fails = {"203.0.113.5": [now - 601] * gate.TRIES, "*": [now - 601] * gate.TRIES}
    assert outcome(gate, "correct horse battery") == 200                        # the window has passed


# ---------------------------------------------------------------- sessions
def test_changing_or_removing_the_password_signs_everyone_out(make_cfg, monkeypatch):
    monkeypatch.setattr(web, "PBKDF2_ROUNDS", 1000)
    with running(make_cfg) as site:
        path = web.access_file(site.cfg)
        client = site.client()
        assert client.sign_in(site.key)[0] == 200 and client.call("/api/info")[0] == 200
        web.set_password(path, "correct horse battery")
        assert client.call("/api/info")[0] == 401                               # the old session no longer works
        assert client.sign_in("correct horse battery")[0] == 200 and client.call("/api/info")[0] == 200
        web.set_password(path, "")
        assert client.call("/api/info")[0] == 401
        assert client.sign_in("correct horse battery")[0] == 401
        assert web.read_access(path)["key"] == site.key and client.sign_in(site.key)[0] == 200   # links still work


def test_the_command_says_a_password_change_signs_everyone_out(make_cfg, monkeypatch, capsys):
    monkeypatch.setattr(web, "PBKDF2_ROUNDS", 1000)

    class Terminal(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(web.sys, "stdin", Terminal())
    cfg = make_cfg()
    path = os.path.join(cfg["base_dir"], "config.yml")
    for typed, said in (("correct horse battery", "Password set, and everyone is signed out"),
                        ("", "Password removed, and everyone is signed out")):
        monkeypatch.setattr(web.getpass, "getpass", lambda prompt="": typed)
        web.manage(path, "set-password")
        assert said in capsys.readouterr().out


def test_an_overlong_session_cookie_is_simply_not_signed_in(make_cfg):
    with running(make_cfg) as site:
        client = site.client()
        for forged in ("9" * 5000 + "." + "0" * 64, "1" * 129, "9" * 20 + "." + "0" * 64):
            client.cookie = forged
            assert client.call("/api/info")[0] == 401                           # never a 500
        assert not site.httpd.gate.valid("9" * 5000 + ".x")


# ---------------------------------------------------------------- web.json, ids and Host names
def test_without_hard_links_web_json_is_never_readable_by_others(tmp_path, monkeypatch):
    def no_links(src, dst):
        raise OSError(errno.EPERM, "this filesystem has no hard links")
    monkeypatch.setattr(web.os, "link", no_links)
    monkeypatch.setattr(web.os, "chmod", lambda *a, **kw: None)  # so nothing can tighten it afterwards
    path = tmp_path / "data" / "web.json"
    before = os.umask(0)
    try:
        access = web.read_access(str(path))
    finally:
        os.umask(before)
    assert oct(os.stat(path).st_mode & 0o777) == "0o600" and access["key"] and access["secret"]
    assert os.listdir(tmp_path / "data") == ["web.json"]


def test_ids_lists_and_colours_cant_end_in_a_newline(make_cfg):
    assert SAFE_ID.match("m1") and not SAFE_ID.match("m1\n")
    assert SLUG.match("someone/best-heists") and not SLUG.match("someone/best-heists\n")
    assert posters.HEX.match("#ff3366") and not posters.HEX.match("#ff3366\n")
    with pytest.raises(SystemExit, match="accent must be one of"):
        posters.check_accent("#ff3366\n", "accent")
    with running(make_cfg) as site:
        client = site.client()
        client.sign_in(site.key)
        status, out = client.call("/api/thumb?id=m1%0A")
        assert status == 400 and "not an item id" in out["error"]


def test_web_hosts_is_checked_and_reaches_the_dashboard(make_cfg):
    assert web.check_hosts(None) == [] and web.check_hosts([]) == []
    assert web.check_hosts("cinesets.example.com") == ["cinesets.example.com"]
    assert web.check_hosts([" CineSets.Example.com.:8443 ", "box.tail1234.ts.net"]) == [
        "cinesets.example.com", "box.tail1234.ts.net"]
    for bad in ([""], [1], {"a": 1}, 5):
        with pytest.raises(SystemExit, match="hosts must be a list of names"):
            web.check_hosts(bad)
    cfg = make_cfg(extra="web: {hosts: [cinesets.example.com]}\n")
    assert web.check_hosts(cfg["web"]["hosts"]) == ["cinesets.example.com"]


@pytest.mark.parametrize("host, allowed", [
    ("cinesets.example.com", True), ("CINESETS.example.com.:443", True), ("127.0.0.1:{port}", True),
    ("localhost:{port}", True), ("[::1]:{port}", True), ("192.0.2.10:8095", True), ("[2001:db8::1]:8095", True),
    ("evil.example", False), ("cinesets.example.com.evil.example", False), ("", False),
])
def test_only_listed_names_are_answered_when_web_hosts_is_set(make_cfg, host, allowed):
    with running(make_cfg, hosts=["cinesets.example.com"]) as site:
        client = site.client()
        header = {"Host": host.format(port=site.port)}
        for path in ("/", "/api/session"):
            status, out = client.call(path, extra=header)
            assert (status == 200) == allowed
            if not allowed:
                assert status == 403 and "web: hosts" in out["error"]


def test_any_name_is_answered_without_web_hosts(make_cfg):
    with running(make_cfg) as site:
        assert site.client().call("/api/session", extra={"Host": "evil.example"})[0] == 200   # as before
    with running(make_cfg, sign_in=False, hosts=["cinesets.example.com"]) as site:
        assert site.httpd.hosts == set()                     # sign-in off answers this machine only, as before
        assert site.client().call("/api/session")[0] == 200


# ---------------------------------------------------------------- starting up
class StubServer:
    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        pass


@pytest.fixture
def start_up(monkeypatch):
    """serve() as far as its start-up messages, with the demo's dashboard and without listening anywhere. Gives what
    make_server was asked for."""
    got, dashboard = {}, web.Dashboard

    def make(app, host, port, sign_in, public, hosts=None):
        got.update(host=host, public=public, hosts=hosts)
        return StubServer()
    monkeypatch.setattr(web, "make_server", make)
    monkeypatch.setattr(web.signal, "signal", lambda *a: None)
    monkeypatch.setattr(web, "Dashboard", lambda cfg_path=None, demo=False: dashboard(demo=True))
    return got


def test_public_mode_warns_when_it_listens_beyond_this_machine(make_cfg, start_up, capsys):
    cfg = make_cfg(extra="web: {host: 0.0.0.0, port: 8196, public: true, hosts: [cinesets.example.com]}\n")
    web.serve(os.path.join(cfg["base_dir"], "config.yml"))
    out = capsys.readouterr().out
    assert "Warning: it listens on 0.0.0.0" in out and "X-Forwarded-Proto" in out and "127.0.0.1 only" in out
    assert start_up == {"host": "0.0.0.0", "public": True, "hosts": ["cinesets.example.com"]}
    web.serve(os.path.join(cfg["base_dir"], "config.yml"), host="127.0.0.1")
    assert "Warning" not in capsys.readouterr().out                            # behind a proxy on this machine


# ---------------------------------------------------------------- the media server's API key
@pytest.mark.parametrize("kind", ["emby", "jellyfin"])
def test_the_api_key_never_reaches_the_browser_from_any_route(make_cfg, monkeypatch, kind):
    monkeypatch.setattr(web, "fetch_list", lambda slug, data, patient=True: ROWS)
    monkeypatch.setattr("cinesets.engine.fetch_list", lambda slug, data, patient=True: ROWS)
    with running(make_cfg, kind) as site:
        assert site.app.cfg["server"]["api_key"] == API_KEY                    # it's loaded, so it could leak
        monkeypatch.setattr(site.app, "run_command", lambda command: [sys.executable, "-c", "print('planned')"])
        client = site.client()
        for path in ("/", "/app.js", "/app.css", "/icon.png", "/nowhere"):
            client.call(path, header=False)
        client.call("/api/session")
        client.call("/api/login", {"key": "wrong"})
        assert client.sign_in(site.key)[0] == 200
        client.call("/api/session")
        settings = client.call("/api/settings")[1]
        walked = [
            ("GET", "/api/info", None), ("GET", "/api/settings", None), ("GET", "/api/collections", None),
            ("GET", "/api/artwork?key=m-bttf", None), ("GET", "/api/thumb?id=m1", None),
            ("POST", "/api/preview", {"key": "m-bttf", "posters": {}}),
            ("POST", "/api/preview", {"key": "m-nope", "posters": {}}),
            ("POST", "/api/artwork", {"key": "m-bttf", "action": "choose", "item": "m2"}),
            ("POST", "/api/save", {k: settings[k] for k in ("posters", "collections", "limits", "version")}),
            ("POST", "/api/lists/check", {"list": "someone/best-heists"}),
            ("POST", "/api/lists/add", {"collection": {"title": "Heist", "type": "movie", "section": "universes",
                                                       "lists": ["someone/best-heists"]}}),
            ("POST", "/api/lists/remove", {"key": "m-heist"}),
            ("POST", "/api/text", {"key": "m-netflix", "label": "Films"}),
            ("POST", "/api/run", {"command": "plan"}),
        ]
        for method, path, body in walked:
            status = client.call(path, body if method == "POST" else None)[0]
            assert status < 500, (path, status)
            if path.split("?")[0] in ("/api/settings", "/api/collections", "/api/artwork", "/api/thumb", "/api/save",
                                      "/api/lists/check", "/api/lists/add", "/api/lists/remove"):
                assert status == 200, (path, status)
        for _ in range(50):
            if not client.call("/api/run")[1].get("running"):
                break
            time.sleep(0.1)
        for method, path in web.ROUTES:                                         # and every route, even new ones
            client.call(path, {} if method == "POST" else None)
        client.call("/api/logout", {})
        asked = {path for path, *_ in client.replies}
        assert {path for _, path in web.ROUTES} <= asked and {path for _, path in web.OPEN} <= asked
    for path, status, data, headers in client.replies:
        assert API_KEY.encode() not in data and API_KEY not in headers, path
