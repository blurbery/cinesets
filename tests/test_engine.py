# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Engine behaviour against an in-memory server: create, update, shrink, ownership and failure handling."""
import json
import os
import random

import pytest
import requests

from cinesets import catalog, config
from cinesets.engine import Engine
from cinesets.store import load_json
from conftest import FakeServer, Resp, seed_index

FRANCHISE = """collections:
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
"""
ITEMS = {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie"),
         "m3": ("Back to the Future Part III", 1990, "movie"), "s1": ("Back to the Future", 1985, "show")}


def setup_run(make_cfg, kind="emby", yml=FRANCHISE):
    cfg = make_cfg(kind, yml)
    seed_index(cfg, ITEMS)
    srv = FakeServer(kind)
    for iid, (name, _, k) in ITEMS.items():
        srv.add_item(iid, name, "Movie" if k == "movie" else "Series")
    return cfg, srv, Engine(cfg, srv)


def state(cfg):
    return load_json(os.path.join(cfg.path("data_dir"), "state.json"), {})


@pytest.mark.parametrize("kind", ["emby", "jellyfin"])
def test_create_then_nothing_to_do(make_cfg, kind):
    cfg, srv, eng = setup_run(make_cfg, kind)
    eng.run("apply", catalog.load(cfg), 8)
    (cid, coll), = srv.collections.items()
    assert coll["members"] == ["m1", "m2", "m3"]          # the TV show with the same name is not used
    assert coll["Name"] == "Movies - Back to the Future"
    assert coll["meta"]["ForcedSortName"].startswith("+07")  # franchises sort last
    assert coll["image"]                                  # poster uploaded
    locks = set(coll["meta"]["LockedFields"])
    assert ("SortName" in locks) == (kind == "emby")       # Jellyfin has no SortName lock field
    assert state(cfg)["m-bttf"]["id"] == cid

    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 8)
    assert srv.writes() == []                             # second run changes nothing


@pytest.mark.parametrize("kind", ["emby", "jellyfin"])
def test_shrinks_when_a_title_leaves_the_list(make_cfg, kind):
    cfg, srv, eng = setup_run(make_cfg, kind)
    eng.run("apply", catalog.load(cfg), 8)
    smaller = FRANCHISE.replace('      - ["Back to the Future Part III", 1990]\n', "")
    with open(cfg.path("collections_file"), "w") as f:
        f.write(smaller)
    eng.run("apply", catalog.load(cfg), 8)
    (coll,) = srv.collections.values()
    assert coll["members"] == ["m1", "m2"]


def test_refuses_existing_collection_with_same_name(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    theirs = srv.add_collection("Movies - Back to the Future", ["m1"])
    eng.run("apply", catalog.load(cfg), 8)
    assert srv.collections[theirs]["members"] == ["m1"] and not srv.collections[theirs]["meta"]
    assert len(srv.collections) == 1 and "id" not in state(cfg).get("m-bttf", {})


def test_refuses_when_server_hands_back_a_collection_it_does_not_own(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    srv.reuse_same_name = True
    theirs = srv.add_collection("Movies - Back to the Future (full list)", ["m1"])
    yml = FRANCHISE.replace("    min: 2\n", '    min: 2\n    create_name: "Movies - Back to the Future (full list)"\n')
    open(cfg.path("collections_file"), "w").write(yml)
    eng.run("apply", catalog.load(cfg), 8)
    assert srv.collections[theirs]["members"] == ["m1"] and not srv.collections[theirs]["meta"]


def test_recovers_a_collection_made_before_a_timeout(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    srv.timeout_on_create = True
    eng.run("apply", catalog.load(cfg), 8)          # the server made it, then timed out: claim it and stop
    (cid, coll), = srv.collections.items()
    assert state(cfg)["m-bttf"]["id"] == cid and not coll["image"]
    srv.timeout_on_create = False
    eng.run("apply", catalog.load(cfg), 8)          # the next run finishes it
    assert len(srv.collections) == 1 and coll["image"] and coll["Name"] == "Movies - Back to the Future"


def test_skips_titles_the_server_no_longer_has(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    del srv.items["m3"]                                    # deleted since the index was built
    eng.run("apply", catalog.load(cfg), 8)
    (coll,) = srv.collections.values()
    assert "m3" not in coll["members"]


def test_broken_backdrop_is_not_kept_and_poster_still_made(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    srv.fail_backdrop = True
    eng.run("apply", catalog.load(cfg), 8)
    (coll,) = srv.collections.values()
    assert coll["image"]
    backdrops = os.path.join(cfg.path("data_dir"), "backdrops")
    assert not [f for f in os.listdir(backdrops) if f.endswith((".jpg", ".part"))]


def test_timeout_stops_the_run(make_cfg):
    second = FRANCHISE.split("collections:\n")[1].replace("m-bttf", "m-bttf2").replace("Back to\\nthe Future\"", "Again\"")
    cfg, srv, eng = setup_run(make_cfg, yml=FRANCHISE + second)
    real, attempts = srv.call, []

    def slow(method, path, **kw):
        if method == "POST" and path.startswith("/Collections?"):
            attempts.append(path)
            raise requests.Timeout("simulated")
        return real(method, path, **kw)
    srv.call = slow
    eng.run("apply", catalog.load(cfg), 8)
    assert len(attempts) == 1  # the second collection was not tried after the timeout


def test_late_create_is_claimed_next_run(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    real = srv.call

    def late(method, path, **kw):
        if method == "POST" and path.startswith("/Collections?"):
            raise requests.Timeout("simulated: the server finishes the create after we gave up")
        return real(method, path, **kw)
    srv.call = late
    eng.run("apply", catalog.load(cfg), 8)
    assert not srv.collections and state(cfg)["m-bttf"]["pending"]["name"] == "Movies - Back to the Future"
    late_id = srv.add_collection("Movies - Back to the Future", ["m1", "m2", "m3"])  # it appears later
    srv.call = real
    eng.run("apply", catalog.load(cfg), 8)
    assert state(cfg)["m-bttf"]["id"] == late_id and srv.collections[late_id]["image"]


def test_adopt_then_update(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    old = srv.add_collection("Movies - Back to the Future", ["m1"])
    eng.adopt(catalog.load(cfg))
    eng.run("apply", catalog.load(cfg), 8)
    assert srv.collections[old]["members"] == ["m1", "m2", "m3"] and srv.collections[old]["image"]


def test_adopt_skips_collections_owned_by_another_entry(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    owner_id = state(cfg)["m-bttf"]["id"]
    second = FRANCHISE.split("collections:\n")[1].replace("m-bttf", "m-other")
    with open(cfg.path("collections_file"), "w") as f:
        f.write(FRANCHISE + second)
    eng.adopt(catalog.load(cfg))
    assert "id" not in state(cfg).get("m-other", {}) and state(cfg)["m-bttf"]["id"] == owner_id


def test_remove_deletes_only_its_own(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    theirs = srv.add_collection("Somebody's list", ["m1"])
    eng.run("apply", catalog.load(cfg), 8)
    assert eng.remove(eng.owned_keys(), catalog.load(cfg)) == 1
    assert list(srv.collections) == [theirs] and "m-bttf" not in state(cfg)


def test_damaged_cache_is_ignored_but_damaged_state_stops(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    with open(os.path.join(cfg.path("data_dir"), "index.json"), "w") as f:
        f.write("{not json")
    from cinesets.store import load_json as lj
    assert lj(os.path.join(cfg.path("data_dir"), "index.json"), "default") == "default"
    seed_index(cfg, ITEMS)
    with open(os.path.join(cfg.path("data_dir"), "state.json"), "w") as f:
        f.write("{not json")
    with pytest.raises(SystemExit, match="damaged"):
        eng.run("apply", catalog.load(cfg), 8)


def test_plan_and_posters_make_no_server_writes(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("plan", catalog.load(cfg), 8)
    eng.run("posters", catalog.load(cfg), 8)
    assert srv.writes() == [] and not srv.collections


def test_skips_collections_below_minimum(make_cfg):
    cfg, srv, eng = setup_run(make_cfg, yml=FRANCHISE.replace("    min: 2\n", ""))
    eng.run("apply", catalog.load(cfg), 8)
    assert not srv.collections


def test_poster_the_server_did_not_keep_is_uploaded_again(make_cfg, monkeypatch):
    import cinesets.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "sleep", lambda s: None)
    cfg, srv, eng = setup_run(make_cfg)
    srv.drop_posters = 1
    eng.run("apply", catalog.load(cfg), 8)
    (coll,) = srv.collections.values()
    assert not coll["image"] and "poster" not in state(cfg)["m-bttf"]
    eng.run("apply", catalog.load(cfg), 8)
    assert coll["image"] and state(cfg)["m-bttf"]["poster"]


def test_remove_works_after_the_entry_left_the_file(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    with open(cfg.path("collections_file"), "w") as f:
        f.write("collections: []\n")
    assert eng.remove(eng.owned_keys(), catalog.load(cfg)) == 1 and not srv.collections


def test_renamed_collection_is_left_alone(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    (cid, coll), = srv.collections.items()
    coll["Name"] = "My own favourites"          # the id now belongs to something the user renamed
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 8)
    assert srv.writes() == []
    assert eng.remove(eng.owned_keys(), catalog.load(cfg)) == 0 and cid in srv.collections


def test_collection_deleted_on_the_server_is_made_again(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    srv.collections.clear()
    eng.run("apply", catalog.load(cfg), 8)
    (coll,) = srv.collections.values()
    assert coll["members"] == ["m1", "m2", "m3"]


def test_existing_name_is_refused_before_creating(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    srv.add_collection("Movies - Back to the Future (full list)", ["m1"])
    yml = FRANCHISE.replace("    min: 2\n", '    min: 2\n    create_name: "Movies - Back to the Future (full list)"\n')
    with open(cfg.path("collections_file"), "w") as f:
        f.write(yml)
    eng.run("apply", catalog.load(cfg), 8)
    assert not [c for c in srv.calls if c[0] == "POST" and c[1].startswith("/Collections?")]


# ------------------------------------------------------------ Jellyfin 12
class GroupingServer(FakeServer):
    """Jellyfin 12 without a user: a library listing shows a collection in place of the titles in it, unless asked
    not to with CollapseBoxSetItems=false."""

    def __init__(self):
        super().__init__("jellyfin")
        self.films = [{"Id": f"m{n}", "Name": f"Film {n}", "ProductionYear": 2000, "ProviderIds": {"Imdb": f"tt{n:07d}"}}
                      for n in range(1, 4)]

    def call(self, method, path, timeout=120, **kw):
        if path == "/Library/VirtualFolders":
            return Resp(data=[{"Name": "Movies", "ItemId": "lib-movies"}, {"Name": "TV Shows", "ItemId": "lib-tv"}])
        if "ParentId=lib-" in path:
            self.calls.append((method, path))
            if "ParentId=lib-tv" in path:
                return Resp(data={"Items": []})
            if "StartIndex=0&" not in path:
                return Resp(data={"Items": []})
            if "CollapseBoxSetItems=false" in path:
                return Resp(data={"Items": self.films})
            return Resp(data={"Items": [self.films[2], {"Id": "box", "Name": "Movies - Films", "Type": "BoxSet"}]})
        return super().call(method, path, timeout, **kw)


def test_index_keeps_titles_that_are_in_collections(make_cfg):
    cfg = make_cfg("jellyfin")
    index = Engine(cfg, GroupingServer()).build_index()
    assert sorted(index["items"]) == ["m1", "m2", "m3"]
    assert sorted(index["movie"]["imdb"].values()) == ["m1", "m2", "m3"]


# ------------------------------------------------------------ libraries and collections of any size
def item_reads(srv):
    return [c for c in srv.calls if c[0] == "GET" and c[1].startswith("/Items?")]


@pytest.mark.parametrize("cap", [None, 7])
def test_index_reads_the_whole_library_even_from_short_pages(make_cfg, monkeypatch, cap):
    import cinesets.engine as engine_mod
    monkeypatch.setattr(engine_mod.time, "sleep", lambda s: None)
    cfg = make_cfg()
    srv = FakeServer()
    srv.page_cap = cap  # a server or proxy that sends fewer items per page than CineSets asks for
    srv.add_library("Movies", [(f"m{n}", f"Film {n}", 2000, "Movie", {"Imdb": f"tt{n:07d}"}) for n in range(25)])
    srv.add_library("TV Shows", [(f"s{n}", f"Show {n}", 2010, "Series", {"Tvdb": str(n)}) for n in range(3)])
    index = Engine(cfg, srv).build_index()
    assert len(index["movie"]["imdb"]) == 25 and len(index["show"]["tvdb"]) == 3 and len(index["items"]) == 28
    # every page, plus the empty page that ends each library
    assert len(item_reads(srv)) == (5 + 2 if cap else 2 + 2)


@pytest.mark.parametrize("kind", ["emby", "jellyfin"])
def test_collections_and_their_titles_are_read_across_pages(make_cfg, kind):
    cfg, srv, eng = setup_run(make_cfg, kind)
    srv.page_cap = 2
    ids = [srv.add_collection(f"Collection {n}", ["m1", "m2", "m3"]) for n in range(5)]
    assert sorted(eng.existing_collections().values()) == sorted(ids)
    assert eng.members(ids[0], "admin") == {"m1", "m2", "m3"}


def test_short_pages_do_not_cause_writes(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    srv.page_cap = 1
    eng.run("apply", catalog.load(cfg), 8)
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 8)
    assert srv.writes() == []          # all three titles were seen, so none is added again


def test_a_server_that_ignores_paging_is_read_once_and_reported(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    srv.page_cap, srv.ignore_start = 2, True
    cid = srv.add_collection("Collection", ["m1", "m2", "m3"])
    assert eng.members(cid, "admin") == {"m1", "m2"}
    assert len(item_reads(srv)) == 2   # it stopped instead of asking for the same page forever
    assert "sent the same page" in capsys.readouterr().out


# ---------------------------------------------------------------- poster settings and random artwork
WITH_ARTWORK = FRANCHISE.replace("    min: 2\n", '    min: 2\n    backdrop_title: "Back to the Future"\n')


def random_run(make_cfg, extra="posters: {artwork: random}\n", yml=WITH_ARTWORK, seed=1):
    cfg = make_cfg("emby", yml, extra)
    seed_index(cfg, ITEMS)
    srv = FakeServer("emby")
    for iid, (name, _, k) in ITEMS.items():
        srv.add_item(iid, name, "Movie" if k == "movie" else "Series")
    return cfg, srv, Engine(cfg, srv, rng=random.Random(seed))


def uploads(srv):
    return [c for c in srv.writes() if "/Images/" in c[1]]


def test_default_settings_keep_the_design_record_of_older_versions(make_cfg):
    """Posters made before the poster settings existed must not be rebuilt and uploaded again."""
    for extra in ("", "posters: {artwork: fixed, accent: auto, shade: medium, label: true}\n"):
        cfg, srv, eng = random_run(make_cfg, extra)
        eng.run("apply", catalog.load(cfg), 8)
        assert state(cfg)["m-bttf"]["design"] == json.dumps(
            ["Movies", "Back to\nthe Future", None, "blue", None, "Back to the Future"])
        assert state(cfg)["m-bttf"]["backdrop_item"] == "m1" and "artwork" not in state(cfg)["m-bttf"]


def test_random_artwork_ignores_backdrop_title_and_stays_put(make_cfg):
    picks = set()
    for seed in range(6):
        cfg, srv, eng = random_run(make_cfg, seed=seed)
        eng.run("apply", catalog.load(cfg), 8)
        st = state(cfg)["m-bttf"]
        assert st["backdrop_item"] in {"m1", "m2", "m3"} and st["artwork"] == "random"
        picks.add(st["backdrop_item"])
        srv.calls.clear()
        eng.run("apply", catalog.load(cfg), 8)
        assert srv.writes() == []                              # the pick is kept, nothing uploaded again
        os.remove(os.path.join(cfg.path("data_dir"), "state.json"))
    assert len(picks) > 1                                      # installs don't all get the same picture


def test_reshuffle_picks_different_artwork(make_cfg):
    cfg, srv, eng = random_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    first = state(cfg)["m-bttf"]["backdrop_item"]
    srv.calls.clear()
    eng.reshuffle = True
    eng.run("apply", catalog.load(cfg), 8)
    assert state(cfg)["m-bttf"]["backdrop_item"] != first and len(uploads(srv)) == 1


def test_switching_to_random_replaces_the_fixed_pick(make_cfg):
    cfg, srv, eng = random_run(make_cfg, "")
    eng.run("apply", catalog.load(cfg), 8)
    assert state(cfg)["m-bttf"]["backdrop_item"] == "m1"
    with open(cfg.path("base_dir") + "/config.yml", "a") as f:
        f.write("posters: {artwork: random}\n")
    cfg2 = config.load(cfg.path("base_dir") + "/config.yml")
    srv.calls.clear()
    Engine(cfg2, srv, rng=random.Random(3)).run("apply", catalog.load(cfg2), 8)
    assert state(cfg)["m-bttf"]["backdrop_item"] in {"m2", "m3"} and len(uploads(srv)) == 1


def test_a_colour_change_keeps_the_random_picture(make_cfg):
    cfg, srv, eng = random_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    first = state(cfg)["m-bttf"]["backdrop_item"]
    with open(cfg.path("base_dir") + "/config.yml", "a") as f:
        f.write("posters: {artwork: random, accent: \"#ff3366\", case: upper}\n")
    cfg2 = config.load(cfg.path("base_dir") + "/config.yml")
    srv.calls.clear()
    eng2 = Engine(cfg2, srv, rng=random.Random(99))
    eng2.run("apply", catalog.load(cfg2), 8)
    assert state(cfg)["m-bttf"]["backdrop_item"] == first and len(uploads(srv)) == 1   # new colours, same picture
    srv.calls.clear()
    eng2.run("apply", catalog.load(cfg2), 8)
    assert srv.writes() == []


def test_streaming_and_pinned_posters_are_not_randomised(make_cfg):
    yml = WITH_ARTWORK + ('  - key: m-netflix\n    group: streaming\n    type: movie\n    title: "Netflix"\n    logo: netflix\n'
                          '    min: 2\n    backdrop_title: "Back to the Future Part III"\n    titles:\n'
                          '      - ["Back to the Future", 1985]\n      - ["Back to the Future Part II", 1989]\n'
                          '      - ["Back to the Future Part III", 1990]\n')
    yml = yml.replace('    backdrop_title: "Back to the Future"\n', '    backdrop_item: m2\n', 1)
    cfg, srv, eng = random_run(make_cfg, yml=yml)
    eng.run("apply", catalog.load(cfg), 8)
    st = state(cfg)
    assert st["m-netflix"]["backdrop_item"] == "m3" and "artwork" not in st["m-netflix"]
    assert st["m-bttf"]["backdrop_item"] == "m2" and "artwork" not in st["m-bttf"]


# ---------------------------------------------------------------- unpicking
def test_unpicked_collections_are_kept_until_removed(make_cfg, monkeypatch, capsys):
    from cinesets import cli
    two = FRANCHISE + FRANCHISE.replace("collections:\n", "").replace("m-bttf", "m-bttf2").replace("Back to\\nthe", "Back to\\nThe")
    cfg, srv, eng = setup_run(make_cfg, yml=two)
    eng.run("apply", catalog.load(cfg), 8)
    assert len(srv.collections) == 2
    with open(cfg.path("base_dir") + "/config.yml", "a") as f:
        f.write("collections: {exclude: [m-bttf2]}\n")
    path = cfg.path("base_dir") + "/config.yml"
    monkeypatch.setattr(cli, "MediaServer", lambda cfg: srv)
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["cinesets", "apply", "--config", path])
    cli.main()
    assert len(srv.collections) == 2                                         # unpicking never deletes
    assert "not picked any more" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["cinesets", "remove", "--unpicked", "--yes", "--config", path])
    cli.main()
    assert [c["Name"] for c in srv.collections.values()] == ["Movies - Back to the Future"]


def test_random_artwork_comes_from_the_top_titles_and_a_pick_further_down_is_kept(make_cfg):
    from cinesets.engine import RANDOM_FROM
    cfg, srv, eng = random_run(make_cfg)
    candidates = [f"i{n}" for n in range(60)]
    for seed in range(40):
        eng.rng = random.Random(seed)
        assert eng.random_pick(candidates, {}, set()) in candidates[:RANDOM_FROM]
    st = {"backdrop_item": "i50", "artwork": "random"}      # picked when it was near the top; the list has moved on
    assert eng.random_pick(candidates, st, set()) == "i50"
    eng.reshuffle = True
    assert eng.random_pick(candidates, st, set()) in candidates[:RANDOM_FROM]
