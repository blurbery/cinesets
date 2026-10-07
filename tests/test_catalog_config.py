# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Catalogue, settings, setup and the server client."""
import builtins
import getpass
import os
import re

import pytest
import yaml

from cinesets import catalog, cli, config, server

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------- shipped catalogue
def test_shipped_catalogue_loads_and_orders(make_cfg):
    colls = catalog.load(make_cfg())
    assert len(colls) >= 160
    order = [c["key"] for c in sorted(colls, key=lambda c: c["sort"])]
    assert order[:4] == ["m-trending", "s-trending", "m-trendingall", "s-trendingall"]
    groups = [c["group"] for c in sorted(colls, key=lambda c: c["sort"])]
    first_universe = groups.index("universes")
    assert set(groups[first_universe:]) == {"universes"}          # franchises last
    names = [c["name"].split(" - ", 1)[1].lower() for c in sorted(colls, key=lambda c: c["sort"]) if c["group"] == "universes"]
    stripped = [n[4:] if n.startswith("the ") else n for n in names]
    assert stripped == sorted(stripped)                           # A to Z, ignoring "The"


def test_shipped_catalogue_counts_match_readme(make_cfg):
    colls = catalog.load(make_cfg())
    readme = open(os.path.join(ROOT, "README.md")).read()
    franchises = sum(1 for c in colls if c.get("titles"))
    assert f"{franchises} movie franchises" in readme
    logos = {c["logo"] for c in colls if c.get("logo")}
    from cinesets import logos as logo_mod, posters
    assert logos <= set(logo_mod.FILES) and logos <= set(posters.SERVICES)


def test_readme_settings_examples_load(make_cfg):
    readme = open(os.path.join(ROOT, "README.md")).read()
    for name in ("Poster style",):
        block = re.search(r"```yaml\n(.*?)```", readme.split(f"## {name}", 1)[1], re.S).group(1)
        make_cfg(extra=block)                                         # loads without complaint


def test_readme_examples_load(make_cfg, tmp_path):
    readme = open(os.path.join(ROOT, "README.md")).read()
    section = readme.split("## Your own collections", 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(r"```yaml\n(.*?)```", section, re.S)
    extra = yaml.safe_load("collections:\n" + "".join(blocks))["collections"]
    cfg = make_cfg(collections_yml=yaml.safe_dump({"collections": extra}))
    keys = {c["key"] for c in catalog.load(cfg)}
    assert keys == {"m-heist", "m-karatekid"}
    cfg["collections_file"] = os.path.join(ROOT, "collections.yml")
    shipped = {c["key"] for c in catalog.load(cfg)}
    assert not keys & shipped                                     # examples don't clash with shipped keys


@pytest.mark.parametrize("bad, message", [
    ("collections:\n  - {key: m-a, group: g, type: movie, title: A}\n  - {key: m-a, group: g, type: movie, title: B}\n", "duplicate"),
    ("collections:\n  - {key: ../x, group: g, type: movie, title: A}\n", "key"),
    ("collections:\n  - {key: m-a, group: g, type: film, title: A}\n", "type"),
    ("collections:\n  - {key: m-a, type: movie, title: A}\n", "group"),
])
def test_catalogue_rejects_bad_entries(make_cfg, bad, message):
    with pytest.raises(SystemExit, match=message):
        catalog.load(make_cfg(collections_yml=bad))


def test_pin_and_nested_order(make_cfg):
    yml = ("collections:\n"
           "  - {key: m-z, group: genres, type: movie, title: Z}\n"
           "  - {key: m-y, group: charts, type: movie, title: Y}\n"
           "  - {key: m-x, group: streaming, type: movie, title: X, pin: 1}\n")
    order = [c["key"] for c in sorted(catalog.load(make_cfg(collections_yml=yml)), key=lambda c: c["sort"])]
    assert order == ["m-x", "m-y", "m-z"]


# ---------------------------------------------------------------- settings
def test_empty_environment_does_not_override(make_cfg, monkeypatch):
    monkeypatch.setenv("CINESETS_API_KEY", "")
    monkeypatch.setenv("CINESETS_URL", "")
    cfg = make_cfg()
    assert cfg["server"]["api_key"] == "test-key" and cfg["server"]["url"] == "http://127.0.0.1:8096"


def test_environment_overrides(make_cfg, monkeypatch):
    monkeypatch.setenv("CINESETS_API_KEY", "from-env")
    monkeypatch.setenv("CINESETS_SERVER", "jellyfin")
    cfg = make_cfg()
    assert cfg["server"]["api_key"] == "from-env" and cfg["server"]["type"] == "jellyfin"


@pytest.mark.parametrize("kind, message", [("silo", "coming soon"), ("plex", "emby or jellyfin")])
def test_server_type_checked(make_cfg, kind, message):
    with pytest.raises(SystemExit, match=message):
        make_cfg(kind)


def test_library_types(tmp_path):
    p = tmp_path / "c.yml"
    p.write_text('server: {api_key: k}\nlibraries: [{name: A, type: tvshows}, {name: B, type: Movies}]\n')
    assert [lib["type"] for lib in config.load(str(p))["libraries"]] == ["show", "movie"]
    p.write_text('server: {api_key: k}\nlibraries:\n')
    assert config.load(str(p))["libraries"] == []
    p.write_text('server: {api_key: k}\nlibraries: [{name: A, type: music}]\n')
    with pytest.raises(SystemExit, match="movie or show"):
        config.load(str(p))


# ---------------------------------------------------------------- setup
def test_setup_writes_private_valid_config(tmp_path, monkeypatch):
    answers = iter(["jellyfin", "192.0.2.10:8096"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": 'k"ey\\with: odd')
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [
        {"Name": 'Kid\'s "Films"', "CollectionType": "movies"}, {"Name": "Music", "CollectionType": "music"},
        {"Name": "TV: All", "CollectionType": "tvshows"}])
    out = tmp_path / "config.yml"
    cli.setup(str(out))
    assert oct(os.stat(out).st_mode & 0o777) == "0o600"
    cfg = config.load(str(out))
    assert cfg["server"] == {"type": "jellyfin", "url": "http://192.0.2.10:8096", "api_key": 'k"ey\\with: odd'}
    assert cfg["libraries"] == [{"name": 'Kid\'s "Films"', "type": "movie"}, {"name": "TV: All", "type": "show"}]


def test_setup_uses_cinesets_config(tmp_path, monkeypatch):
    target = tmp_path / "docker" / "config.yml"
    monkeypatch.setenv("CINESETS_CONFIG", str(target))
    answers = iter(["emby", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    cli.setup(None)
    assert target.exists()


def test_setup_stops_without_libraries(tmp_path, monkeypatch):
    answers = iter(["emby", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [{"Name": "Mixed", "CollectionType": None}])
    with pytest.raises(SystemExit, match="no Movies or TV"):
        cli.setup(str(tmp_path / "config.yml"))
    assert not (tmp_path / "config.yml").exists()


# ---------------------------------------------------------------- server client
class _Resp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers, self.text = status, headers or {}, ""


def test_redirects_are_refused(make_cfg, monkeypatch):
    srv = server.MediaServer(make_cfg())
    seen = {}

    def fake_request(method, url, **kw):
        seen.update(kw)
        return _Resp(302, {"Location": "https://sso.example.com/login"})
    monkeypatch.setattr(srv.session, "request", fake_request)
    with pytest.raises(server.ServerError, match="redirected"):
        srv.get("/Users")
    assert seen["allow_redirects"] is False


def test_paths_and_auth_per_server(make_cfg):
    emby = server.MediaServer(make_cfg("emby"))
    jelly = server.MediaServer(make_cfg("jellyfin"))
    assert emby.base.endswith("/emby") and not jelly.base.endswith("/emby")
    assert "Authorization" not in emby.session.headers and 'Token="test-key"' in jelly.session.headers["Authorization"]


@pytest.mark.parametrize("url, warns", [("http://127.0.0.1:8096", False), ("http://10.20.30.40:8096", False),
                                        ("http://emby:8096", False), ("http://100.101.102.103:8096", False),
                                        ("http://media.tail1234.ts.net:8096", False), ("http://media.example.com", True),
                                        ("https://media.example.com", False)])
def test_plain_http_warning(make_cfg, monkeypatch, capsys, url, warns):
    monkeypatch.setenv("CINESETS_URL", url)
    server.MediaServer(make_cfg())
    assert ("plain http" in capsys.readouterr().err) == warns


def test_version_shows_credit(capsys, monkeypatch):
    monkeypatch.setattr("sys.argv", ["cinesets", "version"])
    cli.main()
    out = capsys.readouterr().out
    assert "CineSets" in out and "blurbery" in out and "https://github.com/blurbery/cinesets" in out and "NO WARRANTY" in out


def test_setup_tightens_an_existing_file(tmp_path, monkeypatch):
    out = tmp_path / "config.yml"
    out.write_text("old")
    os.chmod(out, 0o644)
    answers = iter(["y", "emby", "http://192.0.2.10:8096/web/index.html#!/home"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    cli.setup(str(out))
    assert oct(os.stat(out).st_mode & 0o777) == "0o600"
    assert config.load(str(out))["server"]["url"] == "http://192.0.2.10:8096"   # pasted browser address trimmed


def test_setup_reports_a_rejected_key(tmp_path, monkeypatch):
    answers = iter(["emby", ""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "wrong")

    def rejected(self, path):
        raise server.ServerError("GET /Library/VirtualFolders -> 401", 401)
    monkeypatch.setattr(server.MediaServer, "get", rejected)
    with pytest.raises(SystemExit, match="rejected the API key"):
        cli.setup(str(tmp_path / "config.yml"))


def test_unknown_keys_are_skipped_but_nothing_matching_is_an_error(make_cfg, capsys):
    colls = catalog.load(make_cfg())
    picked = cli.select(colls, only="m-trending,m-gone-after-halloween")
    assert [c["key"] for c in picked] == ["m-trending"] and "m-gone-after-halloween" in capsys.readouterr().out
    assert cli.select(colls, group="seasonal,charts")                     # works with or without seasonal entries
    with pytest.raises(SystemExit, match="No collections match"):
        cli.select(colls, only="m-trendng")
    with pytest.raises(SystemExit, match="No collections match"):
        cli.select(colls, group="streamng")


def test_setup_trims_emby_web_address(tmp_path, monkeypatch):
    answers = iter(["emby", "http://192.0.2.10:8096/emby/web/index.html#!/home"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    cli.setup(str(tmp_path / "config.yml"))
    assert config.load(str(tmp_path / "config.yml"))["server"]["url"] == "http://192.0.2.10:8096"


# ---------------------------------------------------------------- poster settings
def test_example_config_loads_with_the_documented_defaults():
    from cinesets import posters
    cfg = config.load(os.path.join(ROOT, "config.example.yml"))
    assert cfg["order"] == config.DEFAULTS["order"] and cfg["alphabetical_groups"] == ["universes"]
    assert cfg["posters"] == {**posters.STYLE, "artwork": "random"}          # new installs get random artwork


@pytest.mark.parametrize("bad, message", [
    ("{shade: pitch}", "shade must be one of light, medium, dark"),
    ("{artwork: shuffle}", "artwork must be one of fixed, random"),
    ("{accent: beige}", "accent must be one of"),
    ("{accent: '#12345'}", "accent must be one of"),
    ("{label: maybe}", "label must be true or false"),
    ("{label_colour: '#zzzzzz'}", "label_colour must be gold, white, accent"),
    ("loud", "posters must be"),
])
def test_poster_settings_are_checked(make_cfg, bad, message):
    with pytest.raises(SystemExit, match=message):
        make_cfg(extra=f"posters: {bad}\n")


def test_poster_settings_defaults_and_spellings(make_cfg, capsys):
    from cinesets import posters
    assert make_cfg()["posters"] == posters.STYLE
    style = make_cfg(extra="posters: {align: center, label_color: white, Case: upper, accent: ['#ff0000', '#00ff00']}\n")["posters"]
    assert style["align"] == "centre" and style["label_colour"] == "white" and style["accent"] == ["#ff0000", "#00ff00"]
    assert "Case" in capsys.readouterr().err                          # unknown settings are noted, not fatal


def test_accent_colours():
    from cinesets import posters
    assert posters.accent_colours("teal") == posters.ACCENTS["teal"]
    assert posters.accent_colours(["#ff0000", "#0000ff"])[:2] == ((255, 0, 0), (0, 0, 255))
    start, end, tint = posters.accent_colours("#ff3366")
    assert start == (255, 51, 102) and end != start and tint == (96, 19, 38)
    assert posters.accent_colours("nonsense") == posters.ACCENTS["purple"]   # old behaviour for unknown names


def test_every_poster_setting_renders(tmp_path):
    from PIL import Image
    from cinesets import posters
    backdrop = tmp_path / "b.jpg"
    Image.new("RGB", (1920, 1080), (90, 120, 160)).save(backdrop)
    variants = [{}, {"accent": "#33ccff"}, {"shade": "light", "tint": "none"}, {"shade": "dark", "tint": "strong"},
                {"title": "solid"}, {"title": "white", "align": "centre", "case": "upper"},
                {"label": False, "subtitle_colour": "accent"}, {"label_colour": "#ffffff", "subtitle_colour": "gold"}]
    made = set()
    for i, change in enumerate(variants):
        style = posters.check_style(change)
        for art in (str(backdrop), None):
            out = tmp_path / f"p{i}{bool(art)}.jpg"
            posters.make_poster(str(out), "Movies", "Back to\nthe Future", "Saga", "blue", art, style)
            assert Image.open(out).size == (posters.W, posters.H)
            made.add(out.read_bytes())
        logo = tmp_path / f"l{i}.jpg"
        posters.make_logo_poster(str(logo), "TV Shows", "netflix", str(tmp_path), "Popular", None, "Netflix", style)
        assert Image.open(logo).size == (posters.W, posters.H)
    assert len(made) == 2 * len(variants)                              # every setting changes the picture


def test_streaming_posters_only_take_text_settings():
    from cinesets import posters
    style = posters.check_style({"accent": "red", "shade": "dark", "artwork": "random", "case": "upper"})
    assert posters.style_changes(style, logo=True) == {"case": "upper"}
    assert posters.style_changes(style) == {"accent": "red", "shade": "dark", "case": "upper"}
    assert posters.style_changes(posters.check_style({})) == {}

