# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Mosaic posters (posters: artwork: mosaic): the settings at every level, how tiles are picked and kept from run to
run, the fallback to one artwork, the design record, each server's own poster, and the dashboard's previews and
Shuffle, in demo mode and against the in-memory server."""
import io
import json
import os
import random
import time

import pytest
from PIL import Image

from cinesets import catalog, cli, config, mosaic, posters, scenes, web
from cinesets.engine import Engine
from cinesets.servers import ServerError
from cinesets.store import load_json, save_json
from conftest import FakeServer
from test_server_retries import Answer, client, waits  # noqa: F401 (waits is a fixture)
from test_silo import silo_run  # noqa: F401 (a fixture)
from test_web import decode, key_of, start

FILMS = [(f"f{n}", f"Film {n}", 1990 + n) for n in range(1, 13)]   # twelve made-up films, f1 to f12


def collection(key="m-heist", group="universes", films=FILMS, more=""):
    title = key.split("-", 1)[1].title()
    return (f"  - key: {key}\n    group: {group}\n    type: movie\n    title: {title}\n    accent: gold\n    min: 2\n{more}"
            "    titles:\n" + "".join(f'      - ["{name}", {year}]\n' for _, name, year in films))


def yml(*parts):
    return "collections:\n" + "".join(parts or [collection()])


def seed(cfg, films=FILMS, no_poster=(), old=False):
    """A fresh library index. old: one from before posters were noted, without "p"."""
    items = {i: {"n": n, "y": y, "b": True, "k": "movie", **({} if old else {"p": i not in no_poster})}
             for i, n, y in films}
    save_json(os.path.join(cfg.path("data_dir"), "index.json"),
              {"built": time.time(), "movie": {"imdb": {}, "tmdb": {}}, "show": {"tvdb": {}, "imdb": {}, "tmdb": {}},
               "items": items})


def setup(make_cfg, posters_yml="posters: {artwork: mosaic}\n", collections=None, seed_rng=1, **index):
    cfg = make_cfg("emby", collections or yml(), posters_yml)
    seed(cfg, **index)
    srv = FakeServer("emby")
    for iid, name, _ in FILMS:
        srv.add_item(iid, name)
    return cfg, srv, Engine(cfg, srv, rng=random.Random(seed_rng))


def run(eng, cfg):
    return eng.run("apply", catalog.load(cfg), 2)


def state(cfg, key="m-heist"):
    return load_json(os.path.join(cfg.path("data_dir"), "state.json"), {}).get(key, {})


def design(cfg, key="m-heist"):
    return json.loads(state(cfg, key)["design"])


def uploads(srv):
    return [c for c in srv.writes() if "/Images/" in c[1]]


def poster_reads(srv):
    return [path for method, path in srv.calls if method == "GET" and "/Images/Primary" in path]


def rewrite(cfg, text):
    with open(cfg.path("collections_file"), "w") as f:
        f.write(text)


# ---------------------------------------------------------------- settings
def test_artwork_and_the_grid_can_be_set_at_every_level():
    style = posters.check_style({"artwork": "random", "mosaic": "2X2",
                                 "sections": {"universes": {"artwork": "mosaic"}, "genres": {"artwork": "fixed"}},
                                 "overrides": {"m-marvel": {"artwork": "mosaic", "mosaic": "2x2"}, "m-bond": {"mosaic": "3x3"}}})
    assert (style["artwork"], style["mosaic"]) == ("random", "2x2")
    assert style["sections"] == {"universes": {"artwork": "mosaic"}, "genres": {"artwork": "fixed"}}
    pick = lambda key, group: (lambda s: (s["artwork"], s["mosaic"]))(posters.style_for(style, key, group))
    assert pick("m-marvel", "universes") == ("mosaic", "2x2")
    assert pick("m-bond", "universes") == ("mosaic", "3x3")
    assert pick("m-action", "genres") == ("fixed", "2x2") and pick("m-new", "charts") == ("random", "2x2")
    assert posters.check_style({})["mosaic"] == "3x3" and posters.check_style({})["artwork"] == "fixed"


@pytest.mark.parametrize("raw, words", [
    ({"artwork": "collage"}, "config.yml posters: artwork must be one of fixed, random, mosaic, not 'collage'"),
    ({"mosaic": "4x4"}, "config.yml posters: mosaic must be one of 2x2, 3x3, not '4x4'"),
    ({"sections": {"universes": {"mosaic": 3}}}, "posters sections universes: mosaic must be one of 2x2, 3x3, not 3"),
    ({"overrides": {"m-marvel": {"artwork": "grid"}}}, "posters overrides m-marvel: artwork must be one of"),
])
def test_bad_mosaic_settings_say_what_is_allowed(raw, words):
    with pytest.raises(SystemExit) as e:
        posters.check_style(raw)
    assert words in str(e.value)


def test_mosaic_settings_round_trip_through_config_yml(tmp_path):
    style = posters.check_style({"sections": {"universes": {"artwork": "mosaic"}},
                                 "overrides": {"m-marvel": {"artwork": "mosaic", "mosaic": "2x2"}}})
    path = tmp_path / "c.yml"
    path.write_text("server: {api_key: k}\n" + config.posters_block(style))
    assert config.load(str(path))["posters"] == style


def test_reshuffle_knows_about_mosaics_at_every_level():
    assert not cli.shuffles(posters.check_style({}))
    assert cli.shuffles(posters.check_style({"artwork": "random"}))
    assert cli.shuffles(posters.check_style({"sections": {"genres": {"artwork": "mosaic"}}}))
    assert cli.shuffles(posters.check_style({"overrides": {"m-a": {"artwork": "random"}}}))


# ---------------------------------------------------------------- picking and laying out the tiles
def test_the_grid_fills_the_poster_with_thin_gutters_between_tiles():
    for n in (2, 3):
        boxes = mosaic.cells(n)
        assert len(boxes) == n * n
        assert {b[0] for b in boxes} >= {0} and max(b[2] for b in boxes) == posters.W and max(b[3] for b in boxes) == posters.H
        lefts = sorted({b[0] for b in boxes})
        rights = sorted({b[2] for b in boxes})
        assert all(lefts[k + 1] - rights[k] == mosaic.GAP for k in range(n - 1))   # one gutter between neighbours
        for left, top, right, bottom in boxes:
            assert abs((right - left) / (bottom - top) - 2 / 3) < 0.02            # each tile about a 2:3 poster


def test_compose_puts_each_poster_in_its_place(tmp_path):
    colours = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30)]
    paths = []
    for n, colour in enumerate(colours):
        paths.append(str(tmp_path / f"t{n}.jpg"))
        Image.new("RGB", (400, 600), colour).save(paths[-1])
    grid = Image.open(mosaic.compose(paths, 2, str(tmp_path / "grid.jpg")))
    assert grid.size == (posters.W, posters.H)
    for (left, top, right, bottom), colour in zip(mosaic.cells(2), colours):
        got = grid.getpixel(((left + right) // 2, (top + bottom) // 2))
        assert all(abs(a - b) < 12 for a, b in zip(got, colour))
    assert max(grid.getpixel((500, 300))) < 30                                    # the gutter is dark


def test_kept_tiles_keep_their_places_and_only_the_ones_that_left_are_replaced():
    ids = [f"i{n}" for n in range(40)]
    rng = random.Random(4)
    tiles, spares = mosaic.pick(ids, lambda i: True, None, 9, rng)
    assert len(set(tiles)) == 9 and set(tiles) <= set(ids[:mosaic.PICK_FROM])
    assert tiles == sorted(tiles, key=ids.index)                                  # a new grid in the collection's order
    again, _ = mosaic.pick(list(reversed(ids)), lambda i: True, tiles, 9, rng)
    assert again == tiles                                                         # the list changed order: same grid
    gone = tiles[4]
    after, _ = mosaic.pick([i for i in ids if i != gone], lambda i: True, tiles, 9, rng)
    assert after[:4] + after[5:] == tiles[:4] + tiles[5:] and after[4] not in tiles   # only that place changed
    assert mosaic.pick(ids, lambda i: True, tiles, 4, rng)[0] == tiles[:4]       # 3x3 to 2x2 keeps the first four
    fresh, _ = mosaic.pick(ids, lambda i: True, tiles, 9, rng, fresh=True)
    assert not set(fresh) & set(tiles)                                            # a reshuffle, away from the old ones
    far = [f"i{n}" for n in range(30, 40)]                                        # a tile further down is still kept
    assert mosaic.pick(ids, lambda i: True, far[:9], 9, rng)[0] == far[:9]
    assert mosaic.pick(ids[:8], lambda i: True, None, 9, rng) == ([], [])         # too few for the grid
    assert mosaic.pick(ids, lambda i: i != "i0", ["i0"] + tiles[1:], 9, rng)[0][0] != "i0"   # no poster, no tile


def test_a_poster_that_cannot_be_had_gives_its_place_to_a_spare():
    files = {"a": "a.jpg", "c": "c.jpg", "d": "d.jpg"}
    assert mosaic.fetch(["a", "b", "c"], ["d"], files.get) == [("a", "a.jpg"), ("d", "d.jpg"), ("c", "c.jpg")]
    assert mosaic.fetch(["a", "b", "c"], [], files.get) is None
    asked = []
    assert mosaic.fetch(["x", "y"], ["z", "w", "v"], lambda i: asked.append(i)) is None
    assert len(asked) == mosaic.TRIES                                             # a struggling server isn't asked forever


def test_demo_tiles_are_made_up_films():
    assert set(mosaic.DEMO_FILMS) == set(scenes.SCENES)
    img = mosaic.demo_poster("stage")
    assert img.size == (mosaic.TILE_WIDTH, mosaic.TILE_WIDTH * 3 // 2) and img.mode == "RGB"
    words = " ".join(mosaic.DEMO_FILMS.values()).lower()
    assert not any(w in words for w in ("emby", "jellyfin", "silo", "plex"))


# ---------------------------------------------------------------- runs
def test_a_mosaic_poster_is_a_grid_of_the_collections_own_posters(make_cfg):
    cfg, srv, eng = setup(make_cfg)
    assert run(eng, cfg).ok
    st = state(cfg)
    tiles = st["tiles"]
    assert len(set(tiles)) == 9 and set(tiles) <= {i for i, _, _ in FILMS}
    assert design(cfg)[-1] == "artwork:mosaic:3x3:" + ",".join(tiles)
    assert sorted(poster_reads(srv)) == sorted(f"/Items/{i}/Images/Primary?maxWidth=400&quality=90" for i in tiles)
    assert not [p for _, p in srv.calls if "/Images/Backdrop" in p]               # no single artwork needed
    assert sorted(os.listdir(os.path.join(cfg.path("data_dir"), "tiles"))) == sorted(f"{i}.jpg" for i in tiles)
    assert not [f for f in os.listdir(cfg.path("data_dir")) if f.startswith("mosaic-")]   # the grid isn't left behind
    assert len(uploads(srv)) == 1
    srv.calls.clear()
    run(eng, cfg)
    assert srv.writes() == [] and poster_reads(srv) == []                         # nothing drawn or fetched again


def test_tiles_stay_put_while_the_list_changes(make_cfg):
    cfg, srv, eng = setup(make_cfg)
    run(eng, cfg)
    tiles = state(cfg)["tiles"]
    rewrite(cfg, yml(collection(films=list(reversed(FILMS)))))
    srv.calls.clear()
    run(eng, cfg)
    assert srv.writes() == [] and state(cfg)["tiles"] == tiles                    # a reordered list changes nothing
    gone = tiles[2]
    rewrite(cfg, yml(collection(films=[f for f in FILMS if f[0] != gone])))
    srv.calls.clear()
    run(eng, cfg)
    now = state(cfg)["tiles"]
    assert now[:2] + now[3:] == tiles[:2] + tiles[3:] and now[2] not in tiles     # only the tile that left is replaced
    assert design(cfg)[-1].endswith(",".join(now)) and len(uploads(srv)) == 1
    assert poster_reads(srv) == [f"/Items/{now[2]}/Images/Primary?maxWidth=400&quality=90"]   # the others are kept


def test_reshuffle_picks_new_tiles_unless_they_were_picked_in_the_dashboard(make_cfg):
    cfg, srv, eng = setup(make_cfg)
    run(eng, cfg)
    first = state(cfg)["tiles"]
    srv.calls.clear()
    eng.reshuffle = True
    run(eng, cfg)
    second = state(cfg)["tiles"]
    assert second != first and set(second) != set(first) and len(uploads(srv)) == 1
    st = load_json(eng.state_file, {})
    st["m-heist"]["tiles_chosen"] = True
    save_json(eng.state_file, st)
    srv.calls.clear()
    run(eng, cfg)
    assert state(cfg)["tiles"] == second and srv.writes() == []


def test_too_few_posters_means_one_artwork_said_once(make_cfg, capsys):
    cfg, srv, eng = setup(make_cfg, no_poster={"f9", "f10", "f11", "f12"})          # eight posters, a 3x3 needs nine
    run(eng, cfg)
    out = capsys.readouterr().out
    assert "m-heist: too few of its titles have posters for a 3x3 mosaic, so its poster has one artwork" in out
    st = state(cfg)
    assert "tiles" not in st and st["backdrop_item"] == "f1" and design(cfg)[-1] == "artwork:mosaic:3x3:too few"
    assert [p for _, p in srv.calls if "/Images/Backdrop" in p] and not poster_reads(srv)
    srv.calls.clear()
    run(eng, cfg)
    assert srv.writes() == [] and "too few" not in capsys.readouterr().out      # not said again while nothing changed
    with open(os.path.join(cfg["base_dir"], "config.yml"), "a") as f:
        f.write("posters: {artwork: mosaic, overrides: {m-heist: {mosaic: 2x2}}}\n")
    cfg = config.load(os.path.join(cfg["base_dir"], "config.yml"))
    eng = Engine(cfg, srv, rng=random.Random(2))
    run(eng, cfg)
    assert len(state(cfg)["tiles"]) == 4 and design(cfg)[-1].startswith("artwork:mosaic:2x2:f")


def test_a_poster_that_cannot_be_fetched_gives_its_place_to_another(make_cfg, capsys):
    cfg, srv, eng = setup(make_cfg)
    real, broken = srv.poster_image, {"f1", "f2"}
    srv.poster_image = lambda item, width=400, quality=90: b"not a picture" if item in broken else real(item, width, quality)
    run(eng, cfg)
    tiles = state(cfg)["tiles"]
    assert len(tiles) == 9 and not broken & set(tiles) and design(cfg)[-1].endswith(",".join(tiles))
    assert not [f for f in os.listdir(os.path.join(cfg.path("data_dir"), "tiles")) if not f.endswith(".jpg")]
    srv.calls.clear()
    run(eng, cfg)
    assert srv.writes() == []                                                     # the design kept is the one drawn


def test_when_the_posters_cannot_be_fetched_the_mosaic_is_tried_again_next_run(make_cfg, capsys):
    cfg, srv, eng = setup(make_cfg)
    real = srv.poster_image
    srv.poster_image = lambda item, width=400, quality=90: b""
    run(eng, cfg)
    assert "not enough of its posters could be fetched for a mosaic" in capsys.readouterr().out
    assert len(poster_reads(srv)) == 0 and design(cfg)[-1] == "artwork:mosaic:3x3:not fetched"
    assert len(uploads(srv)) == 1                                                 # one artwork meanwhile
    srv.poster_image = real
    srv.calls.clear()
    run(eng, cfg)
    assert len(state(cfg)["tiles"]) == 9 and len(uploads(srv)) == 1              # the mosaic, this time


def test_the_grid_size_alone_changes_no_other_poster(make_cfg):
    cfg, srv, eng = setup(make_cfg, posters_yml="")
    run(eng, cfg)
    before = state(cfg)["design"]
    with open(os.path.join(cfg["base_dir"], "config.yml"), "a") as f:
        f.write("posters: {mosaic: 2x2}\n")
    cfg = config.load(os.path.join(cfg["base_dir"], "config.yml"))
    srv.calls.clear()
    run(Engine(cfg, srv), cfg)
    assert state(cfg)["design"] == before and srv.writes() == []


def test_an_index_from_before_posters_were_noted_still_makes_a_mosaic(make_cfg):
    cfg, srv, eng = setup(make_cfg, old=True)
    run(eng, cfg)
    assert len(state(cfg)["tiles"]) == 9


def test_sections_and_single_collections_choose_their_own_artwork(make_cfg):
    colls = yml(collection(), collection("m-caper", "genres"), collection("m-score", "charts"))
    extra = "posters: {artwork: fixed, sections: {universes: {artwork: mosaic}}, overrides: {m-caper: {artwork: random}}}\n"
    cfg, srv, eng = setup(make_cfg, extra, colls)
    run(eng, cfg)
    assert len(state(cfg, "m-heist")["tiles"]) == 9
    assert state(cfg, "m-caper")["artwork"] == "random" and "tiles" not in state(cfg, "m-caper")
    assert "artwork" not in state(cfg, "m-score") and state(cfg, "m-score")["backdrop_item"]


def test_streaming_posters_ignore_mosaic(make_cfg):
    colls = yml(collection("m-netflix", "streaming", more="    logo: netflix\n"))
    cfg, srv, eng = setup(make_cfg, collections=colls)
    run(eng, cfg)
    st = state(cfg, "m-netflix")
    assert "tiles" not in st and "logo:netflix" in design(cfg, "m-netflix")
    assert not [p for p in design(cfg, "m-netflix") if str(p).startswith("artwork:")] and not poster_reads(srv)


def test_pinned_and_chosen_artwork_come_before_a_mosaic(make_cfg):
    colls = yml(collection(), collection("m-pinned", more="    backdrop_item: f3\n"))
    cfg, srv, eng = setup(make_cfg, collections=colls)
    save_json(eng.state_file, {"m-heist": {"artwork": "chosen", "backdrop_item": "f5"}})
    run(eng, cfg)
    assert "tiles" not in state(cfg, "m-heist") and "artwork:chosen:f5" in design(cfg, "m-heist")
    assert "tiles" not in state(cfg, "m-pinned") and state(cfg, "m-pinned")["backdrop_item"] == "f3"


def test_the_index_notes_which_titles_have_a_poster(make_cfg):
    cfg = make_cfg("emby", yml())
    srv = FakeServer("emby")
    srv.add_library("Movies", [(i, name, year, "Movie", {}) for i, name, year in FILMS])
    srv.add_library("TV Shows", [])
    del srv.items["f2"]["ImageTags"]
    index = Engine(cfg, srv).build_index()
    assert index["items"]["f1"]["p"] is True and index["items"]["f2"]["p"] is False


# ---------------------------------------------------------------- each server's own poster
@pytest.mark.parametrize("kind", ["emby", "jellyfin"])
def test_emby_and_jellyfin_send_the_titles_primary_image(kind):
    srv = FakeServer(kind)
    raw = srv.poster_image("m1", 400, 90)
    assert srv.calls == [("GET", "/Items/m1/Images/Primary?maxWidth=400&quality=90")]
    assert Image.open(io.BytesIO(raw)).format == "JPEG"


def test_silo_sends_the_poster_from_its_signed_link_without_the_api_key(silo_run):
    cfg, srv, eng = silo_run()
    assert Image.open(io.BytesIO(srv.poster_image("movie-tmdb-105"))).format == "JPEG"
    srv.poster_image("movie-tmdb-165", 300)
    (first, h1), (second, h2) = silo_run.downloads
    assert first.startswith("https://storage.example.com/art/movie-tmdb-105-poster.jpg?size=medium")
    assert "size=small" in second and not (h1 or {}).get("Authorization") and not (h2 or {}).get("Authorization")
    with pytest.raises(ServerError, match="has no poster"):
        srv.poster_image("movie-imdb-tt0133093")
    index = eng.build_index()
    assert index["items"]["movie-tmdb-105"]["p"] is True and index["items"]["movie-imdb-tt0133093"]["p"] is False


def test_silos_own_poster_link_gets_the_key_and_storage_only_the_same_host(make_cfg, monkeypatch, waits):
    asked = []
    profile = Answer(200, {"items": [{"id": "77", "is_primary": True}]})
    srv = client(make_cfg, "silo", profile, Answer(200, {"poster_url": "/api/v2/art/p.jpg"}),
                 Answer(302, headers={"Location": "https://storage.example.com/p.jpg?signature=abc"}))
    monkeypatch.setattr("cinesets.servers.silo.requests.get",
                        lambda url, **kw: asked.append((url, kw)) or Answer(200, content=b"jpeg"))
    assert srv.poster_image("movie-tmdb-105") == b"jpeg"
    assert "image_size=medium" in srv.session.sent[1][1]
    assert srv.session.sent[2][1] == "http://127.0.0.1:8096/api/v2/art/p.jpg"     # Silo's own address, with the key
    assert asked[0][0] == "https://storage.example.com/p.jpg?signature=abc" and "headers" not in asked[0][1]
    srv = client(make_cfg, "silo", profile, Answer(200, {"poster_url": "https://storage.example.com/p.jpg"}))
    monkeypatch.setattr("cinesets.servers.silo.requests.get",
                        lambda url, **kw: Answer(302, headers={"Location": "http://192.0.2.99/admin"}))
    with pytest.raises(ServerError, match="another host"):
        srv.poster_image("movie-tmdb-105")


SILO_YML = """collections:
  - key: m-eighties
    group: universes
    type: movie
    title: Eighties
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
      - ["Back to the Future Part III", 1990]
      - ["The Matrix", 1999]
      - ["Short Circuit Nine", 1986]
"""


def test_a_silo_mosaic_uses_only_titles_with_posters(silo_run):
    silo_run.fake.items["movie-tmdb-9001"] = {"title": "Short Circuit Nine", "year": 1986, "lib": "1",
                                              "genres": ["Comedy"], "ids": {}}
    cfg, srv, eng = silo_run(SILO_YML, "posters: {artwork: mosaic, mosaic: 2x2}\n")
    eng.run("apply", catalog.load(cfg), 2)
    st = load_json(eng.state_file, {})["m-eighties"]
    assert sorted(st["tiles"]) == ["movie-tmdb-105", "movie-tmdb-165", "movie-tmdb-196", "movie-tmdb-9001"]
    posters_fetched = [(url, h) for url, h in silo_run.downloads if "-poster.jpg" in url]
    assert len(posters_fetched) == 4 and not any((h or {}).get("Authorization") for _, h in posters_fetched)


# ---------------------------------------------------------------- the dashboard
def test_demo_previews_show_a_mosaic_of_made_up_films():
    app = web.Dashboard(demo=True)
    try:
        out = app.preview({"key": "m-scifi", "posters": {"artwork": "mosaic"}})
        names = out["artwork"]["tiles"]
        assert decode(out).size == (600, 900) and len(names) == 9 and set(names) <= set(mosaic.DEMO_FILMS.values())
        two = app.preview({"key": "m-scifi", "posters": {"overrides": {"m-scifi": {"artwork": "mosaic", "mosaic": "2x2"}}}})
        assert two["artwork"]["tiles"] == names[:4]                              # the same pick, in a smaller grid
        assert "tiles" not in app.preview({"key": "m-netflix", "posters": {"artwork": "mosaic"}})["artwork"]
        assert "tiles" not in app.preview({"key": "m-scifi", "posters": {}})["artwork"]
        small = app.preview({"key": "m-scifi", "posters": {"artwork": "mosaic"}, "size": "small"})
        assert small[0] == "image/jpeg" and Image.open(io.BytesIO(small[1])).size == web.TILE
        # Shuffle on a poster the page has just made a mosaic (not saved) picks new tiles, kept like a choice
        assert app.choose({"key": "m-scifi", "action": "shuffle", "posters": {"artwork": "mosaic"}}) == {
            "mode": "auto", "item": None, "tiles": "chosen"}
        kept = app.state["m-scifi"]["tiles"]
        assert len(kept) == 9 and app.state["m-scifi"]["tiles_chosen"]
        shown = app.preview({"key": "m-scifi", "posters": {"artwork": "mosaic"}})["artwork"]["tiles"]
        assert shown == [mosaic.DEMO_FILMS[i.split("-", 1)[1]] for i in kept]
        assert app.choose({"key": "m-scifi", "action": "auto"}) == {"mode": "auto", "item": None}
        assert "tiles" not in app.state["m-scifi"] and "tiles_chosen" not in app.state["m-scifi"]
        # without a mosaic, Shuffle still picks one artwork
        assert app.choose({"key": "m-scifi", "action": "shuffle", "posters": {"artwork": "fixed"}})["mode"] == "chosen"
        assert app.info()["choices"]["artwork"] == ["fixed", "random", "mosaic"]
    finally:
        app.close()


@pytest.fixture
def mosaic_site(make_cfg):
    """A running, signed-in dashboard on the in-memory server, with twelve films (f1 has no poster)."""
    cfg = make_cfg("emby", yml(), "defaults: {min_items: 2}\n")
    seed(cfg, no_poster={"f1"})
    srv = FakeServer("emby")
    for iid, name, _ in FILMS:
        srv.add_item(iid, name)
    app = web.Dashboard(os.path.join(cfg["base_dir"], "config.yml"), server=srv)
    httpd, client_ = start(app)
    client_.sign_in(key_of(cfg))
    yield client_.call, cfg, srv, app
    httpd.shutdown()
    httpd.server_close()
    app.close()
    assert not any(b"test-key" in b for b in client_.bodies)


def test_the_dashboard_previews_and_shuffles_a_mosaic_that_the_next_run_keeps(mosaic_site):
    call, cfg, srv, app = mosaic_site
    page = {"overrides": {"m-heist": {"artwork": "mosaic"}}}
    status, out = call("/api/preview", {"key": "m-heist", "posters": page})
    assert status == 200 and len(out["artwork"]["tiles"]) == 9 and "Film 1" not in out["artwork"]["tiles"]
    assert len(os.listdir(os.path.join(cfg.path("data_dir"), "tiles"))) == 9    # kept for the run, small
    status, out = call("/api/preview", {"key": "m-heist", "posters": {**page, "overrides": {"m-heist": {
        "artwork": "mosaic", "mosaic": "2x2"}}}})
    assert len(out["artwork"]["tiles"]) == 4
    status, out = call("/api/artwork", {"key": "m-heist", "action": "shuffle", "posters": page})
    assert status == 200 and out == {"mode": "auto", "item": None, "tiles": "chosen"}
    chosen = load_json(os.path.join(cfg.path("data_dir"), "state.json"), {})["m-heist"]["tiles"]
    assert call("/api/collections")[1]["sections"][0]["collections"][0]["artwork"]["tiles"] == "chosen"
    version = call("/api/settings")[1]["version"]
    assert call("/api/save", {"posters": page, "collections": {"sections": "all"}, "version": version})[0] == 200
    eng = Engine(config.load(app.cfg_path), srv)
    eng.reshuffle = True                                                         # tiles picked here stay
    eng.run("apply", catalog.load(eng.cfg), 2)
    assert state(cfg)["tiles"] == chosen and design(cfg)[-1] == "artwork:mosaic:3x3:" + ",".join(chosen)
    assert call("/api/artwork", {"key": "m-heist", "action": "auto"})[1] == {"mode": "auto", "item": None}
    assert "tiles" not in state(cfg)
    status, out = call("/api/preview", {"key": "m-heist", "posters": {"overrides": {"m-heist": {"artwork": "mosaic",
                                                                                                   "mosaic": "3x3"}}}})
    assert status == 200 and len(out["artwork"]["tiles"]) == 9


def test_the_dashboard_says_when_a_mosaic_has_too_few_posters(mosaic_site):
    call, cfg, srv, app = mosaic_site
    seed(cfg, no_poster={f"f{n}" for n in range(1, 6)})                           # seven posters left
    app.index = app.engine.get_index()
    status, out = call("/api/preview", {"key": "m-heist", "posters": {"artwork": "mosaic"}})
    assert status == 200 and out["artwork"]["item"] and "Too few of its titles have posters" in out["artwork"]["note"]
    status, out = call("/api/artwork", {"key": "m-heist", "action": "shuffle", "posters": {"artwork": "mosaic"}})
    assert status == 400 and "Too few" in out["error"]
