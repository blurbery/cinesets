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

from cinesets import catalog, cli, config
from cinesets.servers import emby as server

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
    for name in ("Picking collections", "Poster style"):
        block = re.search(r"```yaml\n(.*?)```", readme.split(f"## {name}", 1)[1], re.S).group(1)
        make_cfg(extra=block)                                         # loads without complaint


def test_preview_page_settings_load(make_cfg):
    page = open(os.path.join(ROOT, "docs", "preview.md")).read()
    blocks = re.findall(r"```yaml\n(.*?)```", page, re.S)
    assert len(blocks) >= 5
    for block in blocks:
        for one in re.split(r"\n(?=# )", block):                     # the looks are separate examples
            make_cfg(extra=one)


def test_scenes_are_original_and_repeatable():
    from cinesets import scenes
    assert len(scenes.SCENES) >= 10
    a, b = scenes.make("city", 160, 90), scenes.make("city", 160, 90)
    assert a.size == (160, 90) and a.tobytes() == b.tobytes()


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


def test_server_type_checked(make_cfg):
    with pytest.raises(SystemExit, match="emby, jellyfin or silo"):
        make_cfg("plex")
    assert make_cfg("silo")["server"]["type"] == "silo"


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
@pytest.fixture(autouse=True)
def emby_found(monkeypatch):
    """Setup asks the server what it is; these tests talk to no server, so it is Emby unless a test says otherwise."""
    monkeypatch.setattr(cli, "detect_server", lambda url: ("emby", url, None))


class _Info:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


@pytest.mark.parametrize("answers, found", [
    ({"/System/Info/Public": (200, {"ProductName": "Jellyfin Server", "Version": "10.11.0"})}, "jellyfin"),
    ({"/System/Info/Public": (200, {"ServerName": "media", "Version": "4.9.0.0", "Id": "abc"})}, "emby"),
    ({"/System/Info/Public": (404, None), "/emby/System/Info/Public": (200, {"ProductName": "Emby Server"})}, "emby"),
    ({"/System/Info/Public": (200, None), "/emby/System/Info/Public": (500, None)}, None),
    ({"/api/v2/system/info": (200, {"server_version": "abc", "api_major": 2, "contract_digest": "d"}),
      "/System/Info/Public": (200, {"ProductName": "Jellyfin Server"})}, "silo"),
    ({"/Branding/Configuration": (200, {"LoginDisclaimer": "Silo provides Jellyfin-compatible app support."}),
      "/System/Info/Public": (200, {"ProductName": "Jellyfin Server"})}, "silo"),   # its Jellyfin port: setup asks for Silo's own
    ({"/api/v2/system/info": (200, None), "/Branding/Configuration": (200, {"LoginDisclaimer": ""}),
      "/System/Info/Public": (200, {"ProductName": "Jellyfin Server"})}, "jellyfin"),
])
def test_setup_works_out_the_server_from_its_address(monkeypatch, answers, found):
    import requests as req
    seen = {}

    def fake_get(url, **kw):
        seen.update(kw)
        path = url.split("8096", 1)[1] if "8096" in url else None
        if path not in answers:
            raise req.ConnectionError("nothing there")
        return _Info(*answers[path])
    monkeypatch.undo()
    monkeypatch.setattr(req, "get", fake_get)
    assert (cli.detect_server("http://192.0.2.10:8096") or [None])[0] == found
    assert seen["allow_redirects"] is False and "X-Emby-Token" not in (seen.get("headers") or {})   # no key sent


def test_setup_asks_when_it_cannot_tell(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "detect_server", lambda url: None)
    answers = iter(["192.0.2.10:8096", "jellyfin"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    cli.setup(str(tmp_path / "config.yml"))
    assert config.load(str(tmp_path / "config.yml"))["server"]["type"] == "jellyfin"


def test_setup_writes_private_valid_config(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "detect_server", lambda url: ("jellyfin", url, None))
    answers = iter(["192.0.2.10:8096"])
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
    answers = iter([""])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    cli.setup(None)
    assert target.exists()


def test_setup_stops_without_libraries(tmp_path, monkeypatch):
    answers = iter([""])
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
    answers = iter(["y", "http://192.0.2.10:8096/web/index.html#!/home"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "key")
    monkeypatch.setattr(server.MediaServer, "get", lambda self, path: [{"Name": "Movies", "CollectionType": "movies"}])
    cli.setup(str(out))
    assert oct(os.stat(out).st_mode & 0o777) == "0o600"
    assert config.load(str(out))["server"]["url"] == "http://192.0.2.10:8096"   # pasted browser address trimmed


def test_setup_reports_a_rejected_key(tmp_path, monkeypatch):
    answers = iter([""])
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
    answers = iter(["http://192.0.2.10:8096/emby/web/index.html#!/home"])
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
    assert cfg["posters"] == {**posters.STYLE, "artwork": "random", "sections": {}, "overrides": {}}   # new installs get random artwork
    assert cfg["collections"] == {"sections": "all", "include": [], "exclude": []}


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
    assert make_cfg()["posters"] == {**posters.STYLE, "sections": {}, "overrides": {}}
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


# ---------------------------------------------------------------- picking collections
PICK_YML = """collections:
  - {key: m-trending, group: charts, type: movie, title: Trending, pin: 1}
  - {key: s-trending, group: charts, type: show, title: Trending, pin: 1}
  - {key: m-new, group: charts, type: movie, title: New}
  - {key: m-action, group: genres, type: movie, title: Action}
  - {key: m-comedy, group: genres, type: movie, title: Comedy}
  - {key: m-bttf, group: universes, type: movie, title: Back to the Future}
  - {key: m-mine, group: my-picks, type: movie, title: Mine}
"""


def keys_of(colls):
    return [c["key"] for c in colls]


@pytest.mark.parametrize("pick, expected", [
    ("", ["m-trending", "s-trending", "m-new", "m-action", "m-comedy", "m-bttf", "m-mine"]),
    ("collections: all\n", ["m-trending", "s-trending", "m-new", "m-action", "m-comedy", "m-bttf", "m-mine"]),
    ("collections: {sections: [genres]}\n", ["m-action", "m-comedy"]),
    ("collections: {sections: [charts, genres], exclude: [m-new, m-comedy]}\n", ["m-trending", "s-trending", "m-action"]),
    ("collections: {sections: [], include: [m-bttf, m-new]}\n", ["m-new", "m-bttf"]),
    ("collections: {sections: genres, include: m-bttf, exclude: m-bttf}\n", ["m-action", "m-comedy"]),  # exclude wins
])
def test_pick_sections_include_and_exclude(make_cfg, pick, expected):
    cfg = make_cfg(collections_yml=PICK_YML, extra=pick)
    assert keys_of(catalog.picked(cfg, catalog.load(cfg))) == expected


def test_pick_notes_names_that_are_gone(make_cfg, capsys):
    cfg = make_cfg(collections_yml=PICK_YML, extra="collections: {sections: [genres, gone], include: [m-halloween]}\n")
    assert keys_of(catalog.picked(cfg, catalog.load(cfg))) == ["m-action", "m-comedy"]
    out = capsys.readouterr().out
    assert "gone" in out and "m-halloween" in out


def test_pick_must_be_all_or_settings(make_cfg):
    with pytest.raises(SystemExit, match="collections must be"):
        make_cfg(extra="collections: some\n")
    with pytest.raises(SystemExit, match="include must be a list"):
        make_cfg(extra="collections: {include: {a: 1}}\n")


def test_sections_have_names_in_page_order(make_cfg):
    cfg = make_cfg(collections_yml=PICK_YML)
    colls = catalog.load(cfg)
    names = [(g, members[0]["section"]) for g, members in catalog.sections(cfg, colls)]
    assert names == [("charts", "Trending and charts"), ("genres", "Popular genres"),
                     ("universes", "Franchises and studios"), ("my-picks", "My picks")]
    cfg = make_cfg(collections_yml=PICK_YML + "sections: {my-picks: Hand picked}\n")
    assert catalog.load(cfg)[-1]["section"] == "Hand picked"


def test_list_shows_every_collection_by_section(make_cfg, capsys):
    cfg = make_cfg(collections_yml=PICK_YML, extra="collections: {sections: [genres], include: [m-new]}\n")
    colls = catalog.load(cfg)
    cli.show_list(cfg, colls, catalog.picked(cfg, colls))
    lines = capsys.readouterr().out.splitlines()
    assert "Trending and charts (section: charts), 1 of 3 picked" in lines
    assert any(line.startswith("  [x] m-new ") for line in lines) and any(line.startswith("  [ ] m-trending ") for line in lines)
    assert sum(line.startswith("  [") for line in lines) == len(colls)        # one line per collection


@pytest.mark.parametrize("seed", range(8))
def test_pick_block_round_trips_and_keeps_the_rest_of_the_file(make_cfg, seed):
    import random
    cfg = make_cfg(collections_yml=PICK_YML)
    colls = catalog.load(cfg)
    want = set(random.Random(seed).sample(keys_of(colls), seed % len(colls)))
    path = cfg["base_dir"] + "/config.yml"
    with open(path, "a") as f:
        f.write("# my note\ncollections: {sections: [charts]}\n\n# after\ndefaults: {min_items: 3}\n")
    os.chmod(path, 0o644)
    cli.write_pick(path, cli.pick_block(cfg, colls, want))
    text = open(path).read()
    assert "# my note\ncollections:" in text and "\n\n# after\ndefaults: {min_items: 3}\n" in text
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"                      # it holds the API key
    again = config.load(path)
    assert set(keys_of(catalog.picked(again, catalog.load(again)))) == want and again["defaults"]["min_items"] == 3


def test_pick_block_is_short(make_cfg):
    cfg = make_cfg(collections_yml=PICK_YML)
    colls = catalog.load(cfg)
    every = set(keys_of(colls))
    assert "sections: all\n  include: []\n  exclude: []" in cli.pick_block(cfg, colls, every)
    assert "sections: all\n  include: []\n  exclude:\n    - m-new\n" in cli.pick_block(cfg, colls, every - {"m-new"})
    block = cli.pick_block(cfg, colls, {"m-action", "m-comedy", "m-bttf"})
    assert "sections: [genres, universes]\n  include: []\n  exclude: []" in block


def test_pick_asks_section_by_section(make_cfg, monkeypatch, capsys):
    cfg = make_cfg(collections_yml=PICK_YML)
    path = cfg["base_dir"] + "/config.yml"
    # charts: choose 1 and 3; genres: none; universes: all; my-picks: Enter keeps it (all picked now)
    answers = iter(["c", "9", "1,3", "n", "a", ""])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    cli.pick(path)
    again = config.load(path)
    assert keys_of(catalog.picked(again, catalog.load(again))) == ["m-trending", "m-new", "m-bttf", "m-mine"]
    out = capsys.readouterr().out
    assert "Use numbers from 1 to 3" in out and "Picked 4 of 7" in out and "test-key" not in out


def test_pick_needs_a_terminal(make_cfg, monkeypatch):
    cfg = make_cfg(collections_yml=PICK_YML)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit, match="run it in a terminal"):
        cli.pick(cfg["base_dir"] + "/config.yml")


def test_numbers():
    assert cli._numbers("1, 3,5-7", 9) == {1, 3, 5, 6, 7}
    assert cli._numbers("", 3) == set()
    for bad in ("0", "4", "2-1", "a", "1-x"):
        assert cli._numbers(bad, 3) is None


def test_asking_for_an_unpicked_collection_says_so(make_cfg, capsys):
    cfg = make_cfg(collections_yml=PICK_YML, extra="collections: {sections: [genres]}\n")
    colls = catalog.load(cfg)
    chosen = catalog.picked(cfg, colls)
    unpicked = [c for c in colls if c not in chosen]
    assert keys_of(cli.select(chosen, only="m-action,m-trending", unpicked=unpicked)) == ["m-action"]
    assert "not picked in config.yml (collections), skipped: m-trending" in capsys.readouterr().out
    # the default schedule's trending job must not bring back trending for someone who left it out
    with pytest.raises(SystemExit, match="none of those are picked"):
        cli.select(chosen, only="m-trending,s-trending", unpicked=unpicked)
    with pytest.raises(SystemExit, match="none of those are picked"):
        cli.select(chosen, group="charts", unpicked=unpicked)
