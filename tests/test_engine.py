# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Engine behaviour against an in-memory server: create, update, shrink, ownership and failure handling."""
import os

import pytest
import requests

from cinesets import catalog
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
