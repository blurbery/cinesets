# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Silo, against an in-memory Silo that answers the /api/v2 requests CineSets makes: the real SiloServer client runs
on top of it, from the library index to the collections, their posters and their order on the page."""
import builtins
import getpass
import io
import json
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from cinesets import catalog, cli, config
from cinesets.engine import Engine
from cinesets.servers import ServerError, silo
from cinesets.store import load_json

KEY = "sa_test"
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
  - key: s-drama
    group: genres
    type: show
    title: Drama
    min: 2
    lists: [someone/drama]
    exclude_genres: [Talk]
"""
MOVIES = [("movie-tmdb-105", "Back to the Future", 1985), ("movie-tmdb-165", "Back to the Future Part II", 1989),
          ("movie-tmdb-196", "Back to the Future Part III", 1990), ("movie-imdb-tt0133093", "The Matrix", 1999)]
ANIME = [("movie-tmdb-129", "Spirited Away", 2001), ("movie-tmdb-128", "Princess Mononoke", 1997),
         ("movie-tmdb-4935", "Howl's Moving Castle", 2004)]
SHOWS = [  # content id, title, year, genres, the other ids Silo knows
    ("series-tvdb-305288", "Stranger Things", 2016, ["Drama"], {"imdb_id": "tt4574334", "tmdb_id": "66732"}),
    ("series-tvdb-289574", "The Late Show", 2015, ["Talk"], {"imdb_id": "tt3697842", "tmdb_id": "63770"}),
    ("series-tvdb-121361", "Game of Thrones", 2011, ["Drama"], {"imdb_id": "tt0944947", "tmdb_id": "1399-game-of-thrones"}),
    ("series-tmdb-95396", "Severance", 2022, ["Drama"], {"imdb_id": "tt11280740"}),
]
LIST = [  # what the list gives: matched by TVDB, by IMDb only, by TMDB only, and a talk show to leave out
    {"mediatype": "show", "rank": 1, "tvdbid": 305288},
    {"mediatype": "show", "rank": 2, "imdb_id": "tt0944947"},
    {"mediatype": "show", "rank": 3, "id": 95396},
    {"mediatype": "show", "rank": 4, "tvdbid": 289574},
]


def jpeg(colour=(30, 60, 90)):
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(buf, "JPEG")
    return buf.getvalue()


class Resp:
    def __init__(self, status=200, data=None, headers=None, content=b""):
        self.status_code, self._data, self.headers, self.content = status, data, headers or {}, content
        self.text = json.dumps(data) if data is not None else ""

    def json(self):
        if self._data is None:
            raise ValueError("no body")
        return self._data


def problem(status, detail):
    return Resp(status, {"type": "about:blank", "title": "Error", "status": status, "detail": detail},
                {"Content-Type": "application/problem+json"})


class FakeSilo:
    """Libraries, titles and library collections in memory, behind the same paths and rules as Silo's /api/v2."""

    def __init__(self):
        self.libraries = [{"id": "1", "name": "Movies", "type": "movies"}, {"id": "2", "name": "TV Shows", "type": "series"},
                          {"id": "3", "name": "Concerts", "type": "mixed"}, {"id": "4", "name": "Movies Anime", "type": "movies"}]
        self.items = {}
        for cid, title, year in MOVIES:
            self.items[cid] = {"title": title, "year": year, "lib": "1", "genres": ["Adventure"], "ids": {}}
        for cid, title, year in ANIME:
            self.items[cid] = {"title": title, "year": year, "lib": "4", "genres": ["Animation"], "ids": {}}
        for cid, title, year, genres, ids in SHOWS:
            self.items[cid] = {"title": title, "year": year, "lib": "2", "genres": genres, "ids": ids}
        self.collections = {}
        self.order = {"1": [], "2": [], "3": [], "4": []}
        self.revision = 1
        self.calls = []
        self.next_id = 500
        self.rate_limit = 0
        self.not_admin = False

    def add_collection(self, title, lib, kind="manual"):
        cid = str(self.next_id)
        self.next_id += 1
        self.collections[cid] = {"id": cid, "title": title, "slug": title.lower(), "library_ids": [lib],
                                 "collection_type": kind, "description": "", "sort_config": {}, "items": {},
                                 "poster": None}
        self.order[lib].append(cid)
        return cid

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]

    @staticmethod
    def page(rows, q, size=2):
        start = int(q.get("cursor", 0))
        more = start + size < len(rows)
        return {"items": rows[start:start + size], "total": len(rows),
                "page": {"has_more": more, **({"next_cursor": str(start + size)} if more else {})}}

    def request(self, method, url, timeout=None, allow_redirects=True, headers=None, json=None, files=None, **kw):
        u = urlparse(url)
        path = u.path[len("/api/v2"):]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.calls.append((method, path + (f"?{u.query}" if u.query else "")))
        headers = {**self.headers, **(headers or {})}
        if headers.get("Authorization") != f"Bearer {KEY}":
            return problem(401, "Authentication required")
        if self.rate_limit:
            self.rate_limit -= 1
            return Resp(429, {"detail": "slow down"}, {"Retry-After": "0"})
        parts = path.strip("/").split("/")
        if path == "/profiles":
            return Resp(data={"items": [{"id": "77", "name": "Main", "is_primary": True}]})
        if path == "/libraries":
            return Resp(data={"items": self.libraries})
        if path == "/catalog":
            assert headers.get("X-Profile-Id") == "77", "the catalogue needs the profile header"
            typ = "movie" if q["type"] == "movie" else "series"
            rows = [{"content_id": cid, "type": typ, "title": it["title"], "year": it["year"], "genres": it["genres"],
                     "backdrop_thumbhash": "x"} for cid, it in self.items.items()
                    if it["lib"] == q["library_id"] and cid.startswith(typ)]
            return Resp(data=self.page(rows, q))
        if parts[:2] == ["catalog", "items"]:
            it = self.items.get(parts[2])
            if not it:
                return problem(404, "not found")
            cid = parts[2]
            return Resp(data={"content_id": cid, "title": it["title"], "genres": it["genres"],
                              "backdrop_url": f"https://storage.example.com/art/{cid}.jpg?signature=abc",
                              **{f"{k}_id": v for k, v in silo.content_ids(cid).items()}, **it["ids"]})
        if parts[0] != "admin" or parts[1] != "collections":
            return problem(404, f"no route {method} {path}")
        if self.not_admin:
            return problem(403, "Administrator access required")
        rest = parts[2:]
        if rest == ["capabilities"]:
            return Resp(data={"types": ["manual"]})
        if rest == [] and method == "GET":
            return Resp(data={"items": [self.view(c) for c in self.collections.values()], "groups": []})
        if rest == [] and method == "POST":
            assert json["collection_type"] == "manual" and "items" not in json
            assert all(lib in self.order for lib in json["library_ids"])
            if any(c["slug"] == json.get("slug") for c in self.collections.values()):
                return problem(409, "slug already used")
            cid = self.add_collection(json["title"], json["library_ids"][0])
            c = self.collections[cid]
            c.update(slug=json.get("slug"), library_ids=json["library_ids"], description=json.get("description", ""))
            for lib in json["library_ids"][1:]:
                self.order[lib].append(cid)
            return Resp(201, self.view(c))
        if rest == ["order"] and method == "GET":
            return Resp(data={"library_id": q["library_id"], "group_id": None, "ordered_ids": list(self.order[q["library_id"]]),
                              "has_more": False}, headers={"ETag": f'"order-{self.revision}"'})
        if rest == ["order"] and method == "PUT":
            if headers.get("If-Match") not in ("*", f'"order-{self.revision}"'):
                return problem(412, "stale")
            if sorted(json["ordered_ids"]) != sorted(self.order[json["library_id"]]):
                return problem(422, "ordered_ids must list every collection in the library")
            self.order[json["library_id"]] = list(json["ordered_ids"])
            self.revision += 1
            return Resp(data={"ordered_ids": json["ordered_ids"]})
        c = self.collections.get(rest[0])
        if not c:
            return problem(404, "collection not found")
        if len(rest) == 1:
            if method == "GET":
                return Resp(data=self.view(c, poster_url=False))
            if not headers.get("If-Match"):
                return problem(428, "If-Match required")
            if method == "PATCH":
                c.update({k: v for k, v in json.items() if k in ("title", "description", "sort_config")})
                if "library_ids" in json:
                    for lib, ids in self.order.items():
                        if lib in json["library_ids"] and c["id"] not in ids:
                            ids.append(c["id"])
                        elif lib not in json["library_ids"] and c["id"] in ids:
                            ids.remove(c["id"])
                    c["library_ids"] = list(json["library_ids"])
                return Resp(data=self.view(c))
            if method == "DELETE":
                del self.collections[rest[0]]
                for ids in self.order.values():
                    if rest[0] in ids:
                        ids.remove(rest[0])
                return Resp(204)
        if rest[1:] == ["poster"] and method == "PUT":
            c["poster"] = files["image"][1]
            return Resp(data=self.view(c))
        if rest[1:] == ["items"]:
            rows = [{"collection_id": c["id"], "media_item_id": i, "position": p} for i, p in c["items"].items()]
            return Resp(data=self.page(rows, q))
        if len(rest) == 3 and rest[1] == "items":
            item = rest[2]
            if c["collection_type"] != "manual":
                return problem(409, "not a manual collection")
            if method == "PUT":
                if item not in self.items or self.items[item]["lib"] not in c["library_ids"]:
                    return problem(404, "item not in the collection's libraries")
                assert isinstance(json["position"], int)
                c["items"].setdefault(item, json["position"])
                return Resp(204)
            if method == "DELETE":
                if item not in c["items"]:
                    return problem(404, "not a member")
                del c["items"][item]
                return Resp(204)
        return problem(404, f"no route {method} {path}")

    def view(self, c, poster_url=True):
        thumb = "th-" + str(hash(c["poster"]))[-6:] if c["poster"] else ""
        return {"id": c["id"], "title": c["title"], "slug": c["slug"], "library_ids": c["library_ids"],
                "collection_type": c["collection_type"], "description": c["description"], "sort_config": c["sort_config"],
                "poster_thumbhash": thumb, "poster_url": "https://storage.example.com/p.jpg" if thumb and poster_url else "",
                "item_count": len(c["items"])}

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


@pytest.fixture
def silo_run(make_cfg, monkeypatch):
    """A config for Silo, the fake Silo behind the real client, and lists from memory."""
    monkeypatch.setattr(silo.time, "sleep", lambda s: None)
    rows = [dict(r) for r in LIST]
    monkeypatch.setattr("cinesets.engine.fetch_list", lambda slug, data: rows)
    fake = FakeSilo()
    downloads = []

    def storage_get(url, **kw):
        downloads.append((url, kw.get("headers")))
        return Resp(content=jpeg())
    monkeypatch.setattr(silo.requests, "get", storage_get)

    def make(yml=YML, extra=""):
        cfg = make_cfg("silo", yml, extra)
        cfg["server"]["api_key"] = KEY
        srv = silo.SiloServer(cfg)
        fake.headers = dict(srv.session.headers)
        srv.session = fake
        return cfg, srv, Engine(cfg, srv)
    make.fake, make.rows, make.downloads = fake, rows, downloads
    return make


def by_slug(fake, slug):
    return next(c for c in fake.collections.values() if c["slug"] == slug)


def test_apply_makes_manual_collections_in_the_libraries_of_their_type(silo_run):
    cfg, srv, eng = silo_run()
    eng.run("apply", catalog.load(cfg), 2)
    fake = silo_run.fake
    bttf, drama = by_slug(fake, "cinesets-m-bttf"), by_slug(fake, "cinesets-s-drama")
    assert bttf["title"] == "Movies - Back to the Future" and bttf["library_ids"] == ["1"]
    assert set(bttf["items"]) == {"movie-tmdb-105", "movie-tmdb-165", "movie-tmdb-196"}
    assert bttf["sort_config"] == {"field": "release_date", "order": "asc"} and "Updated automatically" in bttf["description"]
    # matched by TVDB, by IMDb and by TMDB (both looked up from Silo), with the talk show left out
    assert drama["library_ids"] == ["2"] and drama["sort_config"] == {"field": "title", "order": "asc"}
    assert set(drama["items"]) == {"series-tvdb-305288", "series-tvdb-121361", "series-tmdb-95396"}
    assert sorted(drama["items"].values()) == [0, 1, 2]
    assert bttf["poster"] and drama["poster"] and Image.open(io.BytesIO(drama["poster"])).size[0] > 64
    # the genres came with the titles, so leaving the talk show out took no requests beyond the one id lookup per show
    assert len([c for c in fake.calls if c[1].startswith("/catalog/items/") and "?" not in c[1]]) == len(SHOWS)
    st = load_json(eng.state_file, {})
    assert st["m-bttf"]["id"] == bttf["id"] and st["s-drama"]["poster"]


def test_a_second_run_changes_nothing(silo_run):
    cfg, srv, eng = silo_run()
    eng.run("apply", catalog.load(cfg), 2)
    silo_run.fake.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)
    assert silo_run.fake.writes() == []


def test_list_changes_add_and_remove_titles(silo_run):
    cfg, srv, eng = silo_run()
    eng.run("apply", catalog.load(cfg), 2)
    silo_run.rows.pop(1)                                   # Game of Thrones left the list
    silo_run.rows.append({"mediatype": "show", "rank": 9, "imdb_id": "tt0944947"})  # and came back lower down
    silo_run.rows.pop(0)                                   # Stranger Things left it
    eng.run("apply", catalog.load(cfg), 2)
    drama = by_slug(silo_run.fake, "cinesets-s-drama")
    assert set(drama["items"]) == {"series-tmdb-95396", "series-tvdb-121361"}


def test_show_ids_are_looked_up_once(silo_run):
    cfg, srv, eng = silo_run()
    eng.build_index()
    lookups = [c for c in silo_run.fake.calls if c[1].startswith("/catalog/items/")]
    assert len(lookups) == len(SHOWS)
    silo_run.fake.calls.clear()
    index = eng.build_index()
    assert not [c for c in silo_run.fake.calls if c[1].startswith("/catalog/items/")]
    assert index["show"]["imdb"]["tt0944947"] == "series-tvdb-121361"
    assert index["show"]["tmdb"]["1399"] == "series-tvdb-121361"         # 1399-game-of-thrones, kept as the number
    assert index["movie"]["imdb"]["tt0133093"] == "movie-imdb-tt0133093"  # a film Silo knows by its IMDb id
    assert "Concerts" not in json.dumps(silo_run.fake.calls)


def test_titles_silo_no_longer_has_are_skipped(silo_run, capsys):
    cfg, srv, eng = silo_run()
    eng.get_index()
    del silo_run.fake.items["series-tmdb-95396"]           # gone since the index was built
    eng.run("apply", catalog.load(cfg), 2)
    drama = by_slug(silo_run.fake, "cinesets-s-drama")
    assert set(drama["items"]) == {"series-tvdb-305288", "series-tvdb-121361"}
    assert "1 titles were not in Silo any more" in capsys.readouterr().out


def test_busy_answers_are_retried(silo_run):
    cfg, srv, eng = silo_run()
    silo_run.fake.rate_limit = 3
    eng.run("apply", catalog.load(cfg), 2)
    assert len(silo_run.fake.collections) == 2


def test_collections_follow_the_page_order_and_others_keep_their_place(silo_run):
    fake = silo_run.fake
    theirs = fake.add_collection("Netflix Movies", "1")
    yml = YML + """  - key: m-action
    group: genres
    type: movie
    title: Action
    min: 1
    titles:
      - ["The Matrix", 1999]
"""
    cfg, srv, eng = silo_run(yml)
    colls = catalog.load(cfg)
    eng.run("apply", [c for c in colls if c["key"] == "m-bttf"], 1)   # made first, so Silo puts it first
    eng.run("apply", colls, 1)
    bttf, action = by_slug(fake, "cinesets-m-bttf")["id"], by_slug(fake, "cinesets-m-action")["id"]
    # genres come before franchises on the page; the collection CineSets didn't make stays at the top
    assert fake.order["1"] == [theirs, action, bttf]
    fake.calls.clear()
    eng.run("apply", colls, 1)
    assert fake.writes() == []


def test_remove_deletes_only_its_own(silo_run):
    fake = silo_run.fake
    theirs = fake.add_collection("Movies - Something", "1")
    cfg, srv, eng = silo_run()
    colls = catalog.load(cfg)
    eng.run("apply", colls, 2)
    assert eng.remove(eng.owned_keys(), colls) == 2
    assert list(fake.collections) == [theirs]       # the fake also refuses a delete without If-Match


def test_a_collection_with_their_name_is_not_touched(silo_run, capsys):
    fake = silo_run.fake
    theirs = fake.add_collection("Movies - Back to the Future", "1")
    cfg, srv, eng = silo_run()
    eng.run("apply", catalog.load(cfg), 2)
    assert "already exists and was not created by CineSets" in capsys.readouterr().out
    assert fake.collections[theirs]["items"] == {} and not fake.collections[theirs]["poster"]


def test_artwork_comes_from_the_signed_link_without_the_api_key(silo_run):
    cfg, srv, eng = silo_run()
    raw = srv.backdrop_image("movie-tmdb-105")
    assert Image.open(io.BytesIO(raw)).size == (64, 36)
    (url, headers), = silo_run.downloads
    assert url.startswith("https://storage.example.com/") and not (headers or {}).get("Authorization")


def test_a_key_that_is_not_an_administrators_says_so(silo_run):
    cfg, srv, eng = silo_run()
    silo_run.fake.not_admin = True
    with pytest.raises(ServerError, match="belongs to an administrator"):
        srv.admin_user()


def test_a_wrong_key_says_so(silo_run):
    cfg, srv, eng = silo_run()
    srv.session.headers = {"Authorization": "Bearer wrong"}
    with pytest.raises(ServerError, match="did not accept the API key"):
        srv.library_folders()


# ---------------------------------------------------------------- setup on a Silo-only server
def test_silo_finds_its_own_address_from_its_jellyfin_port(monkeypatch, capsys):
    pages = {"http://192.0.2.10:8096/Branding/Configuration": {"LoginDisclaimer": "Silo provides Jellyfin-compatible app support."},
             "http://192.0.2.10:8096/System/Info/Public": {"ProductName": "Jellyfin Server"},
             "http://192.0.2.10:8080/api/v2/system/info": {"api_major": 2, "contract_digest": "d"}}

    def get(url, **kw):
        assert "Authorization" not in (kw.get("headers") or {})   # no key goes out while finding the server
        return Resp(200, pages[url]) if url in pages else Resp(404, {})
    monkeypatch.setattr(silo.requests, "get", get)
    assert silo.SiloServer.detect("http://192.0.2.10:8096") == ("silo", "http://192.0.2.10:8080", silo.COMPAT_NOTE)
    assert cli.find_server("http://192.0.2.10:8096") == ("http://192.0.2.10:8080", "silo")
    assert "Jellyfin-compatible port" in capsys.readouterr().out
    del pages["http://192.0.2.10:8080/api/v2/system/info"]          # Silo isn't on 8080: setup has to ask
    assert silo.SiloServer.detect("http://192.0.2.10:8096") == ("silo", None, silo.COMPAT_NOTE)


def test_setup_asks_for_silos_address_when_it_is_not_on_8080(monkeypatch):
    answers = {"https://media.example.com:8096": ("silo", None, silo.COMPAT_NOTE),
               "https://silo.example.com": ("silo", "https://silo.example.com", None)}
    monkeypatch.setattr(cli, "detect_server", lambda url: answers.get(url))
    monkeypatch.setattr(builtins, "input", lambda prompt="": "silo.example.com/")
    with pytest.raises(SystemExit, match="did not answer"):
        cli.find_server("https://media.example.com:8096")   # http://silo.example.com is not where Silo is
    monkeypatch.setattr(builtins, "input", lambda prompt="": "https://silo.example.com/")
    assert cli.find_server("https://media.example.com:8096") == ("https://silo.example.com", "silo")


def test_setup_takes_a_pasted_silo_page_address(monkeypatch):
    monkeypatch.setattr(cli, "detect_server", lambda url: ("silo", url, None) if url == "http://192.0.2.10:8080" else None)
    assert cli.find_server("http://192.0.2.10:8080/collections/server") == ("http://192.0.2.10:8080", "silo")


def test_setup_writes_a_silo_config_with_the_biggest_library_of_each_type_first(tmp_path, monkeypatch, silo_run):
    fake = silo_run.fake
    fake.libraries.insert(0, fake.libraries.pop(3))      # Movies Anime was added to Silo first; Movies has more films
    monkeypatch.setattr(cli, "detect_server", lambda url: ("silo", url, None))
    answers = iter(["192.0.2.10:8080"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": KEY)
    real_init = silo.SiloServer.__init__

    def init(self, cfg):
        real_init(self, cfg)
        fake.headers = dict(self.session.headers)
        self.session = fake
    monkeypatch.setattr(silo.SiloServer, "__init__", init)
    out = tmp_path / "config.yml"
    cli.setup(str(out))
    cfg = config.load(str(out))
    assert cfg["server"] == {"type": "silo", "url": "http://192.0.2.10:8080", "api_key": KEY}
    assert cfg["libraries"] == [{"name": "Movies", "type": "movie"}, {"name": "Movies Anime", "type": "movie"},
                                {"name": "TV Shows", "type": "show"}]                # the mixed library is left out


# ---------------------------------------------------------------- one library per collection
THREE_LIBRARIES = "libraries: [{name: Movies, type: movie}, {name: Movies Anime, type: movie}, {name: TV Shows, type: show}]\n"
MIXED = YML + """  - key: m-picks
    group: charts
    type: movie
    title: Picks
    min: 2
    limit: 3
    lists: [someone/picks]
  - key: m-ghibli
    group: universes
    type: movie
    title: Studio Ghibli
    min: 2
    titles:
      - ["Spirited Away", 2001]
      - ["Princess Mononoke", 1997]
      - ["Howl's Moving Castle", 2004]
"""
PICKS = [{"mediatype": "movie", "rank": 1, "id": 105}, {"mediatype": "movie", "rank": 2, "id": 129},
         {"mediatype": "movie", "rank": 3, "imdb_id": "tt0133093"}, {"mediatype": "movie", "rank": 4, "id": 165}]


def lists_by_slug(monkeypatch, rows):
    monkeypatch.setattr("cinesets.engine.fetch_list", lambda slug, data: PICKS if slug == "someone/picks" else rows)


def test_each_collection_lives_in_the_library_most_of_its_titles_are_in(silo_run, monkeypatch):
    lists_by_slug(monkeypatch, silo_run.rows)
    cfg, srv, eng = silo_run(MIXED, THREE_LIBRARIES)
    eng.run("apply", catalog.load(cfg), 2)
    fake = silo_run.fake
    picks, ghibli = by_slug(fake, "cinesets-m-picks"), by_slug(fake, "cinesets-m-ghibli")
    # mostly Movies, so it lives there; Spirited Away (Movies Anime) is left out and the next title fills its place
    assert picks["library_ids"] == ["1"] and set(picks["items"]) == {"movie-tmdb-105", "movie-imdb-tt0133093", "movie-tmdb-165"}
    assert ghibli["library_ids"] == ["4"] and len(ghibli["items"]) == 3
    assert ghibli["id"] in fake.order["4"] and ghibli["id"] not in fake.order["1"]
    assert all(c["library_ids"] in (["1"], ["2"], ["4"]) for c in fake.collections.values())


def test_a_collection_in_several_libraries_moves_to_its_own(silo_run, monkeypatch):
    lists_by_slug(monkeypatch, silo_run.rows)
    cfg, srv, eng = silo_run(MIXED, THREE_LIBRARIES)
    eng.run("apply", catalog.load(cfg), 2)
    fake = silo_run.fake
    picks = by_slug(fake, "cinesets-m-picks")
    picks["library_ids"] = ["1", "4"]               # as an earlier version left it: in every movie library
    fake.order["4"].append(picks["id"])
    picks["items"]["movie-tmdb-129"] = 9           # with a title from Movies Anime
    cfg, srv, eng = silo_run(MIXED, THREE_LIBRARIES)
    eng.run("apply", catalog.load(cfg), 2)
    assert picks["library_ids"] == ["1"] and "movie-tmdb-129" not in picks["items"]
    assert picks["id"] not in fake.order["4"]
    fake.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)
    assert fake.writes() == []


def test_an_install_without_the_library_record_makes_it(silo_run, monkeypatch):
    lists_by_slug(monkeypatch, silo_run.rows)
    cfg, srv, eng = silo_run(MIXED, THREE_LIBRARIES)
    eng.get_index()
    import os
    os.remove(srv.where_file)                      # an index built by a version that kept no record
    cfg, srv, eng = silo_run(MIXED, THREE_LIBRARIES)
    eng.run("apply", catalog.load(cfg), 2)
    assert by_slug(silo_run.fake, "cinesets-m-ghibli")["library_ids"] == ["4"]
    assert load_json(srv.where_file, {})["movie-tmdb-129"] == ["4"]


def test_a_collection_moves_out_of_the_first_library_only_when_it_is_clearly_themed(silo_run, monkeypatch):
    two_thirds = [{"mediatype": "movie", "rank": 1, "id": 129}, {"mediatype": "movie", "rank": 2, "id": 128},
                  {"mediatype": "movie", "rank": 3, "id": 105}]
    half = [{"mediatype": "movie", "rank": 1, "id": 129}, {"mediatype": "movie", "rank": 2, "id": 105}]
    yml = YML + "".join(f"""  - key: m-{key}
    group: charts
    type: movie
    title: {key}
    min: 1
    lists: [someone/{key}]
""" for key in ("themed", "mixed"))
    monkeypatch.setattr("cinesets.engine.fetch_list", lambda slug, data: {"someone/themed": two_thirds, "someone/mixed": half}.get(slug, silo_run.rows))
    cfg, srv, eng = silo_run(yml, THREE_LIBRARIES)
    eng.run("apply", catalog.load(cfg), 1)
    themed, mixed = by_slug(silo_run.fake, "cinesets-m-themed"), by_slug(silo_run.fake, "cinesets-m-mixed")
    assert themed["library_ids"] == ["4"] and set(themed["items"]) == {"movie-tmdb-129", "movie-tmdb-128"}
    assert mixed["library_ids"] == ["1"] and set(mixed["items"]) == {"movie-tmdb-105"}   # half and half: the first library
