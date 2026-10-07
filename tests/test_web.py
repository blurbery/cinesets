# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The dashboard against the in-memory server: signing in, previews, artwork choices, saving and runs."""
import base64
import contextlib
import io
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from PIL import Image

from cinesets import catalog, cli, config, posters, web
from cinesets.engine import Engine
from cinesets.store import load_json
from conftest import FakeServer, seed_index

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


class Client:
    """Talks to a running dashboard like the page does: the X-CineSets header on every API call, and the session
    cookie the server set at sign-in sent back."""

    def __init__(self, base):
        self.base, self.cookie, self.bodies = base, None, []

    def call(self, path, body=None, raw=False, header=True, extra=None):
        headers = {"X-CineSets": "1"} if header else {}
        if self.cookie:
            headers["Cookie"] = f"cinesets={self.cookie}"
        headers.update(extra or {})
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                status, data, got = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, data, got = e.code, e.read(), e.headers
        self.bodies.append(data)
        if got.get("Set-Cookie"):
            self.cookie = got["Set-Cookie"].split(";")[0].split("=", 1)[1] or None
        if raw:
            return status, data, got
        return status, json.loads(data)

    def sign_in(self, key):
        return self.call("/api/login", {"key": key})


def start(app):
    httpd = web.make_server(app, "127.0.0.1", 0)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return httpd, Client(f"http://127.0.0.1:{httpd.server_address[1]}")


def key_of(cfg):
    return web.read_access(web.access_file(cfg))["key"]


@pytest.fixture
def site(make_cfg):
    """A running dashboard on a free port, signed in: (call, cfg, fake server, dashboard, client)."""
    cfg = make_cfg("emby", YML, "# keep me\ndefaults: {min_items: 2}\n")
    seed_index(cfg, ITEMS)
    srv = FakeServer("emby")
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    app = web.Dashboard(os.path.join(cfg["base_dir"], "config.yml"), server=srv)
    httpd, client = start(app)
    assert client.sign_in(key_of(cfg)) == (200, {"signed_in": True})
    yield client.call, cfg, srv, app, client
    httpd.shutdown()
    httpd.server_close()
    app.close()
    assert not any(b"test-key" in b for b in client.bodies)          # the API key never reaches the page


# ---------------------------------------------------------------- signing in and keeping others out
def test_signing_in_and_out(site):
    call, cfg, srv, app, client = site
    assert call("/api/session")[1] == {"signed_in": True, "demo": False, "sign_in": True, "password": False}
    assert call("/api/logout", {})[1] == {"signed_in": False} and client.cookie is None
    status, body = call("/api/info")
    assert status == 401 and "Sign in" in body["error"]
    assert call("/api/session")[1]["signed_in"] is False
    assert client.sign_in("wrong")[0] == 401
    assert client.sign_in(key_of(cfg))[0] == 200 and call("/api/info")[0] == 200


def test_the_session_cookie_is_locked_down(site):
    call, cfg, srv, app, client = site
    cookie = call("/api/login", {"key": key_of(cfg)}, raw=True)[2]["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Max-Age=" in cookie
    assert "Path=" not in cookie and "Secure" not in cookie       # scoped to the API folder; plain http on a LAN works
    cookie = call("/api/login", {"key": key_of(cfg)}, raw=True, extra={"X-Forwarded-Proto": "https"})[2]["Set-Cookie"]
    assert "; Secure" in cookie                                      # behind an HTTPS proxy
    for forged in ("9999999999.0000", "abc.def", "1.", "²²²." + "0" * 64):
        client.cookie = forged
        assert call("/api/info")[0] == 401


def test_requests_without_the_dashboard_header_are_refused(site):
    call = site[0]
    for path, body in (("/api/info", None), ("/api/save", {}), ("/api/login", {"key": "x"}), ("/api/session", None)):
        status, out = call(path, body, header=False)
        assert status == 403 and "dashboard page" in out["error"]


def test_wrong_keys_are_rate_limited(site, monkeypatch):
    call, cfg, srv, app, client = site
    monkeypatch.setattr(web.time, "sleep", lambda s: None)
    assert [client.sign_in(f"guess-{n}")[0] for n in range(6)] == [401] * 5 + [429]
    assert client.sign_in(key_of(cfg))[0] == 429                     # even the right key waits it out


def test_password_sign_in_and_a_new_key_signs_everyone_out(site):
    call, cfg, srv, app, client = site
    path = web.access_file(cfg)
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    with pytest.raises(SystemExit, match="at least 12"):
        web.set_password(path, "short")
    web.set_password(path, "correct horse battery")
    assert call("/api/session")[1]["password"] is True
    assert client.sign_in("correct horse battery")[0] == 200
    old = key_of(cfg)
    time.sleep(0.01)
    web.new_key(path)
    assert call("/api/info")[0] == 401 and key_of(cfg) != old        # the old cookie no longer works
    assert client.sign_in(old)[0] == 401 and client.sign_in("correct horse battery")[0] == 200
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_the_link_carries_the_key_after_the_hash(site):
    cfg = site[1]
    assert web.link(cfg, "127.0.0.1", 8095) == f"http://127.0.0.1:8095/#key={key_of(cfg)}"


def test_page_and_static_files_are_a_fixed_list(site):
    call = site[0]
    status, data, headers = call("/", header=False, raw=True)
    assert status == 200 and b"app.js" in data and "script-src 'self'" in headers["Content-Security-Policy"]
    assert b'src="/' not in data and b'href="/' not in data          # relative, so a proxy can serve it under a path
    for path in ("/app.css", "/app.js", "/icon.png"):
        assert call(path, header=False, raw=True)[0] == 200
    assert call("/icon.png", header=False, raw=True)[2]["Content-Type"] == "image/png"
    script = call("/app.js", raw=True)[1]
    assert b"X-CineSets-Token" not in script and b'fetch("/' not in script and b'"/api' not in script
    for path in ("/../cinesets/config.py", "/static/app.js", "/web.py", "/%2e%2e/config.yml", "/api/../config.yml"):
        assert call(path, raw=True)[0] == 404


def test_bodies_must_be_json_objects(site):
    assert site[0]("/api/save", ["not", "an", "object"])[0] == 400


def test_too_many_requests_at_once_get_busy_not_queued(site, monkeypatch):
    app = site[3]
    monkeypatch.setattr(web, "BUSY_LIMIT", 0)
    httpd, client = start(app)
    try:
        status, out = client.call("/api/session")
        assert status == 503 and "busy" in out["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------------------------------------------------------------- what the page shows
def test_info_settings_and_collections(site):
    call = site[0]
    info = call("/api/info")[1]
    assert info["server"] == "emby" and info["can_apply"] and "silver" in info["accents"]
    assert info["defaults"]["title_position"] is None and info["limits"] == {"title_size": [0.5, 2.0], "label_size": [0.5, 2.0]}
    settings = call("/api/settings")[1]
    assert settings["collections"] == {"sections": "all", "include": [], "exclude": []} and settings["version"]
    sections = call("/api/collections")[1]["sections"]
    assert [s["key"] for s in sections] == ["streaming", "universes"]
    netflix = sections[0]["collections"][0]
    assert netflix["streaming"] and netflix["name"] == "Movies - Netflix" and netflix["artwork"]["mode"] == "auto"


def decode(preview):
    head, data = preview["image"].split(",", 1)
    assert head == "data:image/jpeg;base64"
    return Image.open(io.BytesIO(base64.b64decode(data)))


def test_preview_draws_the_unsaved_settings_and_reports_the_layout(site):
    call = site[0]
    status, out = call("/api/preview", {"key": "m-bttf", "posters": {}})
    assert status == 200 and decode(out).size == (600, 900) and out["draggable"] and out["artwork"]["item"] == "m1"
    assert out["layout"]["label"][:2] == [0.078, 0.052]                 # the usual place
    moved = {"title_position": [0.5, 0.6], "align": "centre", "label": False, "overrides": {"m-bttf": {"accent": "red"}}}
    status, out = call("/api/preview", {"key": "m-bttf", "posters": moved, "artwork": "m3"})
    title = out["layout"]["title"]
    assert out["layout"]["label"] is None and abs(title[3] - 0.6) < 0.002 and abs((title[0] + title[2]) / 2 - 0.5) < 0.01
    assert out["artwork"] == {"item": "m3", "name": "Back to the Future Part III"}
    status, out = call("/api/preview", {"key": "m-netflix", "posters": moved})
    assert status == 200 and out["streaming"] and not out["draggable"]


@pytest.mark.parametrize("body, status, words", [
    ({"key": "m-bttf", "posters": {"shade": "pitch"}}, 400, "Poster settings: shade must be one of"),
    ({"key": "m-bttf", "posters": {"title_position": [2, 0]}}, 400, "two numbers from 0 to 1"),
    ({"key": "m-bttf", "posters": {"overrides": {"m-bttf": {"artwork": "random"}}}}, 400, "artwork can only be set"),
    ({"key": "m-nope", "posters": {}}, 404, "no collection called"),
    ({"key": "m-bttf", "posters": {}, "artwork": "../../etc"}, 400, "not an item id"),
    ({"key": "m-bttf", "posters": {}, "artwork": "m404"}, 404, "not in your library"),
])
def test_bad_previews_are_turned_down_with_a_message(site, body, status, words):
    got, out = site[0]("/api/preview", body)
    assert got == status and words in out["error"]


# ---------------------------------------------------------------- artwork
def test_artwork_choices_are_kept_and_used_by_the_next_run(site):
    call, cfg, srv, app, client = site
    out = call("/api/artwork?key=m-bttf")[1]
    assert [c["id"] for c in out["candidates"]] == ["m1", "m2", "m3"] and out["mode"] == "auto"
    assert call("/api/artwork", {"key": "m-bttf", "action": "choose", "item": "m2"})[1] == {"mode": "chosen", "item": "m2"}
    state = load_json(os.path.join(cfg.path("data_dir"), "state.json"), {})
    assert state["m-bttf"] == {"backdrop_item": "m2", "artwork": "chosen"}
    eng = Engine(config.load(app.cfg_path), srv)
    eng.reshuffle = True                                              # a reshuffle leaves chosen artwork alone
    eng.run("apply", catalog.load(eng.cfg), 2)
    st = load_json(eng.state_file, {})["m-bttf"]
    assert st["backdrop_item"] == "m2" and st["artwork"] == "chosen" and "artwork:chosen:m2" in st["design"]
    shuffled = call("/api/artwork", {"key": "m-bttf", "action": "shuffle"})[1]
    assert shuffled["mode"] == "chosen" and shuffled["item"] in {"m1", "m3"}
    assert call("/api/artwork", {"key": "m-bttf", "action": "auto"})[1] == {"mode": "auto", "item": None}
    assert call("/api/artwork", {"key": "m-netflix", "action": "shuffle"})[0] == 400        # streaming keeps its own
    assert call("/api/artwork", {"key": "m-bttf", "action": "choose", "item": "m9"})[0] == 404


def test_artwork_changes_wait_for_nobody_while_a_run_holds_the_lock(site):
    call, cfg, srv, app, client = site
    with app.engine.lock():
        status, out = call("/api/artwork", {"key": "m-bttf", "action": "choose", "item": "m2"})
    assert status == 409 and "in progress" in out["error"]


def test_thumbnails_come_through_the_dashboard(site):
    call, cfg, srv, app, client = site
    status, data, headers = call("/api/thumb?id=m1", raw=True)
    assert status == 200 and headers["Content-Type"] == "image/jpeg" and Image.open(io.BytesIO(data)).size == (64, 36)
    assert os.path.exists(os.path.join(cfg.path("data_dir"), "thumbs", "m1.jpg"))
    assert call("/api/thumb?id=..%2Fx", raw=True)[0] == 400


# ---------------------------------------------------------------- saving and running
def test_save_writes_both_blocks_keeps_the_rest_and_a_backup(site):
    call, cfg, srv, app, client = site
    path = app.cfg_path
    os.chmod(path, 0o644)
    before = open(path).read()
    settings = {"posters": {"artwork": "random", "accent": "#ff3366", "title_position": [0.5, 0.62], "align": "centre",
                            "overrides": {"m-bttf": {"accent": "teal", "label_position": [0.1, 0.1]}}},
                "collections": {"sections": ["universes"], "include": [], "exclude": []},
                "version": call("/api/settings")[1]["version"]}
    status, out = call("/api/save", settings)
    assert status == 200 and out["saved"] and out["version"] == config.file_version(path)
    assert open(path + ".bak").read() == before and oct(os.stat(path + ".bak").st_mode & 0o777) == "0o600"
    text = open(path).read()
    assert "# keep me\ndefaults: {min_items: 2}" in text and oct(os.stat(path).st_mode & 0o777) == "0o600"
    again = config.load(path)
    assert again["posters"]["accent"] == "#ff3366" and again["posters"]["title_position"] == [0.5, 0.62]
    assert again["posters"]["overrides"] == {"m-bttf": {"accent": "teal", "label_position": [0.1, 0.1]}}
    assert again["collections"]["sections"] == ["universes"]
    assert call("/api/settings")[1]["posters"]["accent"] == "#ff3366"
    assert call("/api/save", {"posters": {"case": "shouty"}, "collections": {}})[0] == 400
    assert config.load(path)["posters"]["case"] == "normal"               # nothing written after a bad setting


def test_a_save_over_changes_made_elsewhere_is_refused(site):
    call, cfg, srv, app, client = site
    version = call("/api/settings")[1]["version"]
    with open(app.cfg_path, "a") as f:
        f.write("# edited by hand meanwhile\n")
    status, out = call("/api/save", {"posters": {"shade": "dark"}, "collections": {}, "version": version})
    assert status == 409 and "changed since it was loaded" in out["error"]
    assert "shade: dark" not in open(app.cfg_path).read()
    fresh = call("/api/settings")[1]["version"]
    assert call("/api/save", {"posters": {"shade": "dark"}, "collections": {}, "version": fresh})[0] == 200


def test_the_scheduler_reads_config_again_before_each_job(make_cfg, capsys):
    cfg = make_cfg()
    path = os.path.join(cfg["base_dir"], "config.yml")
    with open(path, "a") as f:
        f.write("posters: {shade: dark}\n")
    fresh, engine = cli.reload(path, cfg, None)
    assert fresh["posters"]["shade"] == "dark" and engine.style["shade"] == "dark"
    with open(path, "a") as f:
        f.write("posters: {shade: pitch}\n")
    kept, same = cli.reload(path, fresh, engine)
    assert kept is fresh and same is engine and "settings from before" in capsys.readouterr().out


def test_one_run_at_a_time_and_its_output_is_shown(site, monkeypatch):
    call, cfg, srv, app, client = site
    monkeypatch.setattr(app, "run_command", lambda command: [sys.executable, "-c",
                                                             "import time; print('first'); time.sleep(0.6); print('done')"])
    assert call("/api/run", {"command": "apply"})[1] == {"started": True}
    assert call("/api/run", {"command": "plan"})[0] == 409
    assert call("/api/run", {"command": "rm"})[0] == 400
    for _ in range(50):
        status = call("/api/run")[1]
        if not status["running"]:
            break
        time.sleep(0.1)
    assert status == {"running": False, "command": "apply", "lines": ["first", "done"], "exit": 0}


def test_demo_mode_needs_no_server_no_sign_in_and_saves_nothing():
    app = web.Dashboard(demo=True)
    httpd, client = start(app)
    try:
        assert client.call("/api/session")[1] == {"signed_in": True, "demo": True, "sign_in": False, "password": False}
        assert client.call("/api/info")[1]["server"] == "demo" and not app.info()["can_apply"]
        bttf = app.preview({"key": "m-backtothefuture", "posters": {"case": "upper"}})
        assert decode(bttf).size == (600, 900) and bttf["artwork"]["item"].startswith("scene-")
        assert len(app.artwork({"key": "m-action"})["candidates"]) >= 10
        assert app.choose({"key": "m-action", "action": "choose", "item": "scene-city"})["item"] == "scene-city"
        assert app.save({"posters": {"shade": "dark"}, "collections": {"sections": ["kids"]}})["saved"] is False
        assert app.settings()["posters"]["shade"] == "dark"
        with pytest.raises(web.Problem, match="Demo mode"):
            app.start_run({"command": "apply"})
        assert len(app.thumb({"id": "scene-moon"})) > 1000
    finally:
        httpd.shutdown()
        httpd.server_close()
        app.close()


# ---------------------------------------------------------------- text positions and overrides in the poster code
def test_moved_text_stays_on_the_poster_and_the_default_place_is_unchanged():
    style = posters.style_for(posters.check_style({}), "x")
    _, usual = posters.poster_image("Movies", "Back to\nthe Future", "Saga", "blue", None, style)
    assert usual["label"][:2] == [0.078, 0.052] and usual["title"][3] == 0.928
    corner = posters.check_style({"title_position": [1, 0], "label_position": [1, 1], "title_size": 2, "label_size": 2})
    _, moved = posters.poster_image("Movies", "Back to\nthe Future", "Saga", "blue", None, corner)
    for box in moved.values():
        assert 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1
    assert moved["title"][1] == 0 and moved["label"][3] == 1
    small = posters.check_style({"label_size": 0.5, "title_size": 0.5})
    _, shrunk = posters.poster_image("Movies", "Back to\nthe Future", "Saga", "blue", None, small)
    width = lambda box: box[2] - box[0]
    assert abs(width(shrunk["label"]) / width(usual["label"]) - 0.5) < 0.05       # the label box halves
    assert width(shrunk["title"]) < width(usual["title"]) * 0.7
    with pytest.raises(SystemExit, match="label_size must be a number from 0.5 to 2.0"):
        posters.check_style({"label_size": 3})


def test_overrides_apply_to_one_collection_only():
    style = posters.check_style({"accent": "gold", "label_color": "white",
                                 "overrides": {"m-a": {"accent": "#00ff00", "align": "center"}}})
    assert posters.style_for(style, "m-a")["accent"] == "#00ff00" and posters.style_for(style, "m-a")["align"] == "centre"
    assert posters.style_for(style, "m-b")["accent"] == "gold" and posters.style_for(style, "m-a")["label_colour"] == "white"
    with pytest.raises(SystemExit, match="overrides m-a: title_size"):
        posters.check_style({"overrides": {"m-a": {"title_size": 9}}})


def test_sections_sit_between_every_poster_and_one_collection():
    style = posters.check_style({"accent": "gold", "shade": "dark", "sections": {"genres": {"accent": "red", "case": "upper"}},
                                 "overrides": {"m-action": {"accent": "#00ff00"}}})
    action, comedy, other = (posters.style_for(style, k, g) for k, g in
                             (("m-action", "genres"), ("m-comedy", "genres"), ("m-bttf", "universes")))
    assert (action["accent"], action["case"], action["shade"]) == ("#00ff00", "upper", "dark")
    assert (comedy["accent"], comedy["case"]) == ("red", "upper") and (other["accent"], other["case"]) == ("gold", "normal")
    with pytest.raises(SystemExit, match="sections genres: artwork can only be set"):
        posters.check_style({"sections": {"genres": {"artwork": "random"}}})


def test_section_settings_reach_the_next_run(make_cfg):
    from conftest import FakeServer as Fake
    cfg = make_cfg("emby", YML, "posters: {sections: {universes: {case: upper}}}\n")
    seed_index(cfg, ITEMS)
    srv = Fake("emby")
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    eng = Engine(cfg, srv)
    eng.run("apply", catalog.load(cfg), 2)
    state = load_json(eng.state_file, {})
    style_part = lambda key: next((json.loads(p[6:]) for p in json.loads(state[key]["design"]) if str(p).startswith("style:")), {})
    assert style_part("m-bttf") == {"case": "upper"} and style_part("m-netflix") == {}   # only that section


def test_posters_block_round_trips(tmp_path):
    style = posters.check_style({"artwork": "random", "title_position": [0.5, 0.6], "title_size": 1.2,
                                 "sections": {"genres": {"shade": "light"}},
                                 "overrides": {"m-a": {"accent": ["#ff0000", "#0000ff"]}}})
    path = tmp_path / "c.yml"
    path.write_text("server: {api_key: k}\n" + config.posters_block(style))
    assert config.load(str(path))["posters"] == style
    assert "label_position" not in config.posters_block(posters.check_style({}))   # unset positions aren't written


def test_text_shadow_is_for_moved_text_unless_switched_on_or_off(tmp_path):
    path = tmp_path / "c.yml"
    path.write_text("server: {api_key: k}\nposters: {text_shadow: off}\n")
    assert config.load(str(path))["posters"]["text_shadow"] == "off"          # YAML's bare off still means off
    with pytest.raises(SystemExit, match="text_shadow must be one of auto, on, off"):
        posters.check_style({"text_shadow": "glow"})
    draw = lambda **change: posters.poster_image("Movies", "Kids", "Popular", "green", None,
                                                 posters.check_style(change))[0].tobytes()
    moved = {"title_position": [0.5, 0.5], "align": "centre"}
    assert draw() == draw(text_shadow="off")                                  # auto: nothing moved, no shadow
    assert draw() != draw(text_shadow="on")
    assert draw(**moved) != draw(**moved, text_shadow="off")                  # auto: moved text gets one


# ---------------------------------------------------------------- mdblist lists and your own collections
ROWS = [{"title": "Back to the Future", "mediatype": "movie", "imdb_id": "tt1", "id": 105},
        {"title": "Back to the Future Part II", "mediatype": "movie", "imdb_id": "tt2", "id": 165},
        {"title": "Unknown Film", "mediatype": "movie", "imdb_id": "tt9", "id": 9},
        {"title": "A Show", "mediatype": "show", "imdb_id": "tt8", "id": 8}]


@pytest.fixture
def lists_site(site, monkeypatch):
    """The dashboard with mdblist answered locally, and a library index that knows two of the list's films."""
    call, cfg, srv, app, client = site
    asked = []
    monkeypatch.setattr(web, "fetch_list", lambda slug, data, patient=True: asked.append((slug, patient)) or ROWS)
    monkeypatch.setattr("cinesets.engine.fetch_list", lambda slug, data, patient=True: ROWS)
    app.index["movie"]["imdb"].update({"tt1": "m1", "tt2": "m2"})
    return call, cfg, srv, app, asked


@pytest.mark.parametrize("text, slug", [
    ("https://mdblist.com/lists/someone/best-heists", "someone/best-heists"),
    ("mdblist.com/lists/someone/best-heists/?sort=rank", "someone/best-heists"),
    ("someone/best-heists", "someone/best-heists"),
    ("https://evil.example.com/lists/someone/x", None),
    ("someone/../../etc", None),
    ("https://mdblist.com/someone", None),
    ("", None),
])
def test_list_addresses(text, slug):
    from cinesets.lists import slug_of
    assert slug_of(text) == slug


def test_checking_a_list_shows_what_it_would_bring(lists_site):
    call, cfg, srv, app, asked = lists_site
    status, out = call("/api/lists/check", {"list": "https://mdblist.com/lists/someone/best-heists"})
    assert status == 200 and out["list"] == "someone/best-heists" and out["type"] == "movie"
    assert (out["titles"], out["movies"], out["shows"]) == (4, 3, 1) and out["in_library"] == {"movie": 2, "show": 0}
    assert out["url"] == "https://mdblist.com/lists/someone/best-heists" and asked == [("someone/best-heists", False)]
    assert call("/api/lists/check", {"list": "https://example.com/x"})[0] == 400


def test_a_new_collection_from_lists_goes_in_its_own_file(lists_site):
    call, cfg, srv, app, asked = lists_site
    new = {"title": "Heist", "subtitle": "Movies", "type": "movie", "section_name": "My lists", "accent": "#ff3366",
           "lists": ["https://mdblist.com/lists/someone/best-heists"], "limit": 25}
    status, out = call("/api/lists/add", {"collection": new})
    assert status == 200 and out["key"] == "m-heist-movies"
    path = cfg.path("custom_collections")
    text = open(path).read()
    assert text.startswith("# Collections added in the CineSets dashboard") and "someone/best-heists" in text
    sections = {s["key"]: s for s in call("/api/collections")[1]["sections"]}
    mine = sections["my-lists"]["collections"][0]
    assert sections["my-lists"]["name"] == "My lists" and mine["custom"] and mine["limit"] == 25
    assert mine["lists"] == ["someone/best-heists"]
    assert call("/api/lists/add", {"collection": new})[1]["key"] == "m-heist-movies-2"    # keys stay unique
    for bad in ({**new, "lists": ["nope"]}, {**new, "title": ""}, {**new, "type": "film"}, {**new, "limit": 0},
                {**new, "accent": "beige"}, {**new, "section_name": ""}):
        assert call("/api/lists/add", {"collection": bad})[0] == 400
    removed = call("/api/lists/remove", {"key": "m-heist-movies-2"})[1]
    assert removed["removed"] and "stays there" in removed["message"]
    assert "m-heist-movies-2" not in {c["key"] for c in catalog.load(config.load(app.cfg_path))}


def test_lists_can_be_added_to_existing_collections_but_not_franchises(lists_site, make_cfg):
    call, cfg, srv, app, asked = lists_site
    custom = cfg.path("custom_collections")
    with open(custom, "w") as f:  # a list-based collection of the user's, to add more lists to
        f.write("collections:\n  - {key: m-mine, group: universes, type: movie, title: Mine, lists: [a/b]}\n")
    status, out = call("/api/lists/add", {"key": "m-mine", "lists": ["someone/more"]})
    assert status == 200 and out["lists"] == ["a/b", "someone/more"]
    assert call("/api/lists/add", {"key": "m-bttf", "lists": ["someone/more"]})[0] == 400      # fixed titles
    assert call("/api/lists/remove", {"key": "m-mine", "list": "someone/more"})[0] == 200
    assert call("/api/lists/remove", {"key": "m-mine", "list": "a/b"})[0] == 400                # keep one list
    assert call("/api/lists/remove", {"key": "m-bttf"})[0] == 400                               # built in


def test_added_lists_extend_a_built_in_collection(make_cfg):
    cfg = make_cfg(collections_yml="collections:\n  - {key: m-a, group: genres, type: movie, title: A, lists: [x/one]}\n"
                                   "  - {key: m-f, group: universes, type: movie, title: F, titles: [[F, 2000]]}\n")
    with open(cfg.path("custom_collections"), "w") as f:
        f.write("sections: {mine: Mine}\ncollections:\n  - {key: m-a, add_lists: [x/two]}\n"
                "  - {key: m-new, group: mine, type: show, title: New, lists: [x/three]}\n"
                "  - {key: m-a, group: genres, type: movie, title: Clash, lists: [x/four]}\n")
    colls = {c["key"]: c for c in catalog.load(cfg)}
    assert colls["m-a"]["lists"] == ["x/one", "x/two"] and colls["m-a"]["added_lists"] == ["x/two"]
    assert colls["m-new"]["custom"] and colls["m-new"]["section"] == "Mine" and colls["m-a"]["title"] == "A"
    with open(cfg.path("custom_collections"), "w") as f:
        f.write("collections:\n  - {key: m-f, add_lists: [x/two]}\n")
    with pytest.raises(SystemExit, match="fixed list of titles"):
        catalog.load(cfg)
    with open(cfg.path("custom_collections"), "w") as f:
        f.write("collections:\n  - {key: m-b, group: g, type: movie, title: B, lists: ['../etc']}\n")
    with pytest.raises(SystemExit, match="not an mdblist list"):
        catalog.load(cfg)


def test_demo_mode_adds_collections_only_in_memory(monkeypatch):
    monkeypatch.setattr(web, "fetch_list", lambda slug, data, patient=True: ROWS)
    app = web.Dashboard(demo=True)
    try:
        assert app.check_list({"list": "someone/best-heists"})["in_library"] is None
        out = app.add({"collection": {"title": "Heist", "type": "movie", "section": "genres", "lists": ["someone/best-heists"]}})
        assert out["key"] in app.catalogue() and app.cfg.path("custom_collections").startswith(app.work)
        assert not os.path.exists(os.path.join(config.ROOT, "custom-collections.yml"))
    finally:
        app.close()


# ---------------------------------------------------------------- how many titles
def test_collection_sizes_cap_every_collection_and_can_be_set_per_section_or_collection(make_cfg):
    yml = ("collections:\n  - {key: m-a, group: genres, type: movie, title: A, lists: [x/a], limit: 20}\n"
           "  - {key: m-b, group: genres, type: movie, title: B, lists: [x/b]}\n"
           "  - {key: m-c, group: charts, type: movie, title: C, lists: [x/c]}\n"
           "  - {key: m-f, group: universes, type: movie, title: F, titles: [[F, 2000]]}\n")
    sizes = lambda extra: {c["key"]: c.get("limit") for c in catalog.load(make_cfg(collections_yml=yml, extra=extra))}
    assert sizes("") == {"m-a": 20, "m-b": 150, "m-c": 150, "m-f": None}
    assert sizes("limits: {most: 25}\n") == {"m-a": 20, "m-b": 25, "m-c": 25, "m-f": None}     # a cap, never more
    assert sizes("limits: {most: 25, sections: {genres: 60}, collections: {m-a: 5}}\n") == {
        "m-a": 5, "m-b": 60, "m-c": 25, "m-f": None}                                          # own numbers win
    with pytest.raises(SystemExit, match="most must be a number"):
        make_cfg(extra="limits: {most: 0}\n")


def test_a_small_size_is_not_skipped_for_having_fewer_than_the_minimum(site, monkeypatch):
    call, cfg, srv, app, client = site
    monkeypatch.setattr("cinesets.engine.fetch_list", lambda slug, data, patient=True: ROWS)
    app.engine.index = None
    index = app.engine.get_index()
    index["movie"]["imdb"].update({"tt1": "m1", "tt2": "m2", "tt3": "m3"})
    from cinesets.store import save_json
    save_json(app.engine.index_file, index)
    with open(cfg.path("custom_collections"), "w") as f:
        f.write("collections:\n  - {key: m-two, group: genres, type: movie, title: Two, lists: [a/b]}\n")
    with open(app.cfg_path, "a") as f:
        f.write("limits: {collections: {m-two: 2}}\n")
    fresh = config.load(app.cfg_path)
    eng = Engine(fresh, srv)
    eng.run("apply", [c for c in catalog.load(fresh) if c["key"] == "m-two"], 8)
    assert any(v["Name"] == "Movies - Two" and len(v["members"]) == 2 for v in srv.collections.values())


def test_save_writes_collection_sizes(site):
    call, cfg, srv, app, client = site
    s = call("/api/settings")[1]
    assert s["limits"] == {"most": None, "sections": {}, "collections": {}}
    body = {"posters": s["posters"], "collections": s["collections"], "version": s["version"],
            "limits": {"most": 25, "sections": {"universes": 40}, "collections": {}}}
    assert call("/api/save", body)[0] == 200
    assert config.load(app.cfg_path)["limits"]["most"] == 25
    body = {**body, "version": call("/api/settings")[1]["version"], "limits": {"most": 5000}}
    assert call("/api/save", body)[0] == 400


# ---------------------------------------------------------------- local without sign-in, or public behind it
def test_sign_in_can_be_off_only_for_a_browser_on_this_machine(make_cfg):
    cfg = make_cfg("emby", YML)
    seed_index(cfg, ITEMS)
    app = web.Dashboard(os.path.join(cfg["base_dir"], "config.yml"), server=FakeServer("emby"))
    try:
        with pytest.raises(SystemExit, match="only be turned off when the dashboard listens on this machine"):
            web.make_server(app, "0.0.0.0", 0, sign_in=False)
        httpd = web.make_server(app, "127.0.0.1", 0, sign_in=False)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        client = Client(f"http://127.0.0.1:{httpd.server_address[1]}")
        assert client.call("/api/session")[1] == {"signed_in": True, "demo": False, "sign_in": False, "password": False}
        assert client.call("/api/info")[0] == 200                                   # no sign-in needed here
        for header in ({"X-Forwarded-For": "203.0.113.5"}, {"Tailscale-User-Login": "someone"}, {"Via": "1.1 caddy"},
                       {"Host": "cinesets.example.com"}, {"Host": "evil.example:8095"}):
            status, out = client.call("/api/info", extra=header)
            assert status == 403 and "only answers a browser on the machine" in out["error"]
        assert client.call("/", header=False, raw=True, extra={"X-Forwarded-For": "203.0.113.5"})[0] == 403
        httpd.shutdown()
        httpd.server_close()
    finally:
        app.close()


def test_public_mode_takes_sign_ins_only_over_https(make_cfg):
    cfg = make_cfg("emby", YML)
    seed_index(cfg, ITEMS)
    app = web.Dashboard(os.path.join(cfg["base_dir"], "config.yml"), server=FakeServer("emby"))
    try:
        with pytest.raises(SystemExit, match="public dashboard needs sign-in"):
            web.make_server(app, "127.0.0.1", 0, sign_in=False, public=True)
        httpd = web.make_server(app, "127.0.0.1", 0, public=True)
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        client = Client(f"http://127.0.0.1:{httpd.server_address[1]}")
        status, out = client.sign_in(key_of(cfg))
        assert status == 403 and "over HTTPS" in out["error"] and client.cookie is None
        status, data, headers = client.call("/api/login", {"key": key_of(cfg)}, raw=True, extra={"X-Forwarded-Proto": "https"})
        assert status == 200 and "; Secure" in headers["Set-Cookie"] and "max-age" in headers["Strict-Transport-Security"]
        httpd.shutdown()
        httpd.server_close()
    finally:
        app.close()


def test_web_settings_in_config(make_cfg):
    assert make_cfg()["web"] == {"host": "127.0.0.1", "port": 8095, "sign_in": True, "public": False}
    for bad, words in (("web: {port: 0}", "port must be"), ("web: {sign_in: maybe}", "sign_in must be true or false"),
                       ("web: [x]", "web must have")):
        with pytest.raises(SystemExit, match=words):
            make_cfg(extra=bad + "\n")


# ---------------------------------------------------------------- changing a collection's words
def test_a_streaming_collections_words_can_be_changed_and_put_back(site):
    call, cfg, srv, app, client = site
    status, out = call("/api/preview", {"key": "m-netflix", "posters": {}, "text": {"subtitle": "Top Picks", "label": "Films"}})
    assert status == 200 and out["streaming"]
    status, out = call("/api/text", {"key": "m-netflix", "label": "Films", "subtitle": "Top Picks"})
    assert status == 200 and out["name"] == "Films - Netflix Top Picks" and "renamed" in out["message"]
    netflix = {c["key"]: c for s in call("/api/collections")[1]["sections"] for c in s["collections"]}["m-netflix"]
    assert netflix["text"] == {"label": "Films", "title": "Netflix", "subtitle": "Top Picks"}
    assert netflix["edited_text"] == ["label", "subtitle"]
    assert "Films - Netflix Top Picks" in {c["name"] for c in catalog.load(config.load(app.cfg_path))}
    for bad in ({"title": ""}, {"label": "x" * 31}, {"title": "one\ntwo\nthree"}, {"subtitle": "a\nb"}):
        assert call("/api/text", {"key": "m-netflix", **bad})[0] == 400
        assert call("/api/preview", {"key": "m-netflix", "posters": {}, "text": bad})[0] == 400
    assert call("/api/text", {"key": "m-netflix", "reset": True})[1]["name"] == "Movies - Netflix"
    assert not os.path.exists(cfg.path("custom_collections")) or "m-netflix" not in open(cfg.path("custom_collections")).read()


def test_renaming_keeps_the_collection_and_renames_it_on_the_server(site):
    call, cfg, srv, app, client = site
    eng = Engine(config.load(app.cfg_path), srv)
    eng.run("apply", catalog.load(eng.cfg), 2)
    (cid,) = [c for c, v in srv.collections.items() if v["Name"] == "Movies - Back to the Future"]
    call("/api/text", {"key": "m-bttf", "title": "Back to\nthe Future", "subtitle": "Trilogy"})
    eng = Engine(config.load(app.cfg_path), srv)
    eng.run("apply", catalog.load(eng.cfg), 2)
    assert srv.collections[cid]["Name"] == "Movies - Back to the Future Trilogy" and len(srv.collections) == 2


# ---------------------------------------------------------------- streaming logos
def test_streaming_posters_can_use_another_logo_or_a_white_one(tmp_path):
    from cinesets import logos
    folder = tmp_path / "logos"
    folder.mkdir()
    for name, colour in (("netflix.png", (229, 9, 20, 255)), ("netflix--icon.png", (0, 200, 0, 255))):
        Image.new("RGBA", (300, 100), colour).save(folder / name)
    draw = lambda **change: posters.logo_poster_image("Movies", "netflix", str(folder), "Popular", None, "Netflix",
                                                      posters.check_style(change))[0]
    centre = lambda img: img.getpixel((500, 630))
    assert centre(draw())[0] > 150                                            # the standard (red) logo
    assert centre(draw(logo="icon"))[1] > 150 and centre(draw(logo="icon"))[0] < 100   # the icon (green here)
    assert min(centre(draw(logo_colour="white"))) > 200                       # all white
    assert draw(logo="alt").tobytes() == draw().tobytes()                     # no alternative: the standard logo
    assert logos.file_name("netflix") == "netflix.png" and logos.file_name("netflix", "icon") == "netflix--icon.png"
    assert set(logos.VARIANTS) <= set(logos.FILES)
    assert posters.style_changes(posters.check_style({"logo": "icon", "shade": "dark"}), logo=True) == {"logo": "icon"}
    assert posters.style_changes(posters.check_style({"logo": "icon"})) == {}  # other posters don't change


def test_logo_versions_are_listed_for_the_page(site):
    info = site[0]("/api/info")[1]
    assert [v["key"] for v in info["logo_versions"]["prime"]] == ["standard", "alt", "icon"]
    assert info["logo_versions"]["stan"] == [{"key": "standard", "label": "Standard", "downloaded": False}]
    netflix = [c for s in site[0]("/api/collections")[1]["sections"] for c in s["collections"] if c["key"] == "m-netflix"]
    assert netflix[0]["service"] == "netflix"


# ---------------------------------------------------------------- starting and stopping
def test_dashboards_starting_together_share_one_access_key(tmp_path, monkeypatch):
    """Several dashboards (or a dashboard and `web --link`) making the access file at once: all get the same key, and
    none reads it half written, even when writing it is slow."""
    import json as json_module
    real_dumps = json_module.dumps

    def slow_dump(obj, f, **kw):
        text = real_dumps(obj, **kw)
        f.write(text[:10])
        f.flush()
        time.sleep(0.2)  # another process looking now would find half a file
        f.write(text[10:])
    monkeypatch.setattr(web.json, "dump", slow_dump)
    path = str(tmp_path / "data" / "web.json")
    start, keys, errors = threading.Barrier(6), [], []

    def open_dashboard():
        start.wait()
        try:
            keys.append(web.read_access(path)["key"])
        except SystemExit as e:
            errors.append(str(e))
    threads = [threading.Thread(target=open_dashboard) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(keys) == 6 and len(set(keys)) == 1
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    assert sorted(os.listdir(tmp_path / "data")) == ["web.json"]   # no half-made files left beside it


@pytest.mark.skipif(not hasattr(signal, "SIGTERM") or os.name == "nt", reason="needs SIGTERM")
def test_a_stopped_dashboard_tidies_up(tmp_path):
    """docker stop and systemctl stop send SIGTERM: the dashboard stops cleanly and takes its temporary folder with it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "TMPDIR": str(tmp_path), "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "cinesets", "web", "--demo", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), timeout=1):
                break
            time.sleep(0.2)
        assert [p for p in os.listdir(tmp_path) if p.startswith("cinesets-web-")]   # it made its folder
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0 and "Dashboard stopped." in out
    assert not [p for p in os.listdir(tmp_path) if p.startswith("cinesets-web-")]
