# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Libraries of every size: a big one is read through once for all the franchises, not once per franchise, and a
tiny one (or one that has lost its titles) never ends up with an empty collection."""
import os
import random
import time

from cinesets import catalog
from cinesets.engine import Engine
from cinesets.store import save_json
from conftest import FakeServer, seed_index

FRANCHISE = """collections:
  - key: m-bttf
    group: universes
    type: movie
    title: "Back to\\nthe Future"
    min: 0
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
  - key: m-gone
    group: universes
    type: movie
    title: "Not Here"
    min: 0
    titles:
      - ["A Film Nobody Has", 1971]
"""
PICKS = """collections:
  - key: m-picks
    group: charts
    type: movie
    title: Picks
    min: 1
    lists: [someone/picks]
"""


class CountingItems(dict):
    """index["items"] that counts how often it is read through."""
    scans = 0

    def items(self):
        self.scans += 1
        return super().items()


def empty_index(items):
    return {"built": time.time(), "movie": {"imdb": {}, "tmdb": {}}, "show": {"tvdb": {}, "imdb": {}, "tmdb": {}},
            "items": items}


def reference(coll, index):
    """Franchise matching as it was before titles_in, reading every title in the index for each franchise."""
    kind = coll["kind"]
    canon = set(index[kind]["imdb"].values()) | set(index[kind]["tmdb"].values())
    want = {(t.lower(), y) for t, y in coll["titles"]}
    found = {}
    for iid, it in index["items"].items():
        if it.get("k", kind) != kind:
            continue
        k = ((it.get("n") or "").lower(), it.get("y"))
        if k in want and (k not in found or (iid in canon and found[k] not in canon)):
            found[k] = iid
    return [found[(t.lower(), y)] for t, y in coll["titles"] if (t.lower(), y) in found]


def test_franchises_read_a_big_library_once(make_cfg):
    eng = Engine(make_cfg(), FakeServer())
    items = CountingItems((f"m{n}", {"n": f"Film {n}", "y": 1950 + n % 70, "b": True, "k": "movie"}) for n in range(30000))
    index = empty_index(items)
    franchises = [{"key": f"m-f{n}", "kind": "movie",
                   "titles": [(f"Film {n * 7 + j}", 1950 + (n * 7 + j) % 70) for j in range(7)] + [("Missing", 1990)]}
                  for n in range(65)]
    for n, coll in enumerate(franchises):
        assert eng.resolve(coll, index) == ([f"m{n * 7 + j}" for j in range(7)], 8, 7)
    assert items.scans == 1                                # once for all 65, not once each
    other = empty_index({"x1": {"n": "Film 0", "y": 1950, "b": True, "k": "movie"}})
    assert eng.resolve(franchises[0], other)[0] == ["x1"]  # a new index is read afresh


def test_matching_is_the_same_as_reading_every_title_each_time(make_cfg):
    """Copies of a title in several libraries, the canonical one later, names in other cases or missing, the same name
    in other years, an index from before titles had a kind, and franchises whose titles are all missing."""
    rng = random.Random(5)
    eng = Engine(make_cfg(), FakeServer())
    names = [f"Title {n}" for n in range(60)]
    index = empty_index({})
    for n in range(3000):
        name = rng.choice(names)
        name = None if rng.random() < 0.02 else name.upper() if rng.random() < 0.1 else name
        kind = rng.choice(["movie", "show", None])
        index["items"][f"i{n}"] = {"n": name, "y": rng.choice([1999, 2000, 2001, None]), "b": True,
                                   **({"k": kind} if kind else {})}
        if rng.random() < 0.4:                             # this copy holds a provider id, so it is canonical
            index[kind or rng.choice(["movie", "show"])][rng.choice(["imdb", "tmdb"])].setdefault(f"tt{n}", f"i{n}")
    for n in range(300):
        titles = [(rng.choice(names + ["Nowhere"]), rng.choice([1999, 2000, 2001, 1990])) for _ in range(rng.randint(1, 6))]
        coll = {"key": f"f{n}", "kind": rng.choice(["movie", "show"]), "titles": titles}
        assert eng.resolve(coll, index)[0] == reference(coll, index)
    missing = {"key": "none", "kind": "movie", "titles": [("Nowhere", 1990)]}
    assert eng.resolve(missing, index) == ([], 1, 0)


def test_the_run_lets_its_index_go(make_cfg):
    cfg = make_cfg("emby", FRANCHISE)
    seed_index(cfg, {"m1": ("Back to the Future", 1985, "movie")})
    eng = Engine(cfg, FakeServer())
    eng.run("plan", catalog.load(cfg), 8)
    assert eng._titles is None                             # nothing held while a scheduler sleeps between jobs


def test_no_collection_is_made_or_emptied_with_no_matches_even_at_min_0(make_cfg, capsys):
    cfg = make_cfg("emby", FRANCHISE)
    seed_index(cfg, {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie")})
    srv = FakeServer()
    srv.add_item("m1", "Back to the Future")
    srv.add_item("m2", "Back to the Future Part II")
    eng = Engine(cfg, srv)
    eng.run("apply", catalog.load(cfg), 0)
    (coll,) = srv.collections.values()                    # m-gone has nothing in the library, so it is not made
    assert coll["members"] == ["m1", "m2"]
    out = capsys.readouterr().out
    assert "m-gone: no matches, so it is not made" in out and "!!" not in out
    seed_index(cfg, {"x1": ("Something Else", 2001, "movie")})   # the library has lost both films
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 0)
    assert coll["members"] == ["m1", "m2"] and srv.writes() == []
    assert "m-bttf: no matches, so it is left as it is on the server" in capsys.readouterr().out


def test_a_title_without_a_name_does_not_stop_the_run(make_cfg, monkeypatch, capsys):
    monkeypatch.setattr("cinesets.engine.fetch_list", lambda slug, data: [{"mediatype": "movie", "rank": 1, "imdb_id": "tt1"}])
    cfg = make_cfg("emby", PICKS)
    index = empty_index({"m1": {"n": None, "y": 2001, "b": True, "k": "movie"}})
    index["movie"]["imdb"]["tt1"] = "m1"
    save_json(os.path.join(cfg.path("data_dir"), "index.json"), index)
    Engine(cfg, FakeServer()).run("plan", catalog.load(cfg), 1)
    assert "using    1  | ?" in capsys.readouterr().out
