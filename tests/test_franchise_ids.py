# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Fixed franchise lists with TMDB ids, [title, year, id]: the id first, whatever the server calls the title, then the
title and year as before. Lists without ids keep working, and an id that isn't a positive whole number is an error."""
import random
import time

import pytest

from cinesets import catalog
from cinesets.engine import Engine
from conftest import FakeServer
from test_scale import empty_index, reference
from test_silo import by_slug, silo_run  # noqa: F401 (silo_run is a fixture)

ZOOTOPIA = """collections:
  - key: m-zootopia
    group: universes
    type: movie
    title: "Zootopia"
    min: 1
    titles:
      - ["Zootopia", 2016, 269149]
      - ["Zootopia 2", 2025]
"""


def index_of(items, kind="movie"):
    """A library index from {id: (name, year)} or {id: (name, year, TMDB id)}; the server's TMDB ids are text."""
    index = {"built": time.time(), "movie": {"imdb": {}, "tmdb": {}}, "show": {"tvdb": {}, "imdb": {}, "tmdb": {}},
             "items": {}}
    for iid, (name, year, *tmdb) in items.items():
        index["items"][iid] = {"n": name, "y": year, "b": True, "k": kind}
        if tmdb:
            index[kind]["tmdb"].setdefault(str(tmdb[0]), iid)
    return index


def matched(make_cfg, titles, items, kind="movie"):
    coll = {"key": "m-test", "kind": kind, "titles": titles}
    return Engine(make_cfg(), FakeServer()).resolve(coll, index_of(items, kind))


def test_the_id_finds_a_title_the_server_names_another_way(make_cfg):
    items = {"z": ("Zootropolis", 2016, 269149)}
    assert matched(make_cfg, [("Zootopia", 2016)], items) == ([], 1, 0)            # the name alone can't bridge it
    assert matched(make_cfg, [("Zootopia", 2016, 269149)], items) == (["z"], 1, 1)


def test_the_id_wins_over_a_film_the_name_and_year_would_pick(make_cfg):
    # the exact name and year: a copy the server has under the right name but another film's id
    items = {"other": ("Zootopia", 2016, 999001), "z": ("Zootropolis", 2016, 269149)}
    assert matched(make_cfg, [("Zootopia", 2016, 269149)], items)[0] == ["z"]
    # the loose second try: the Spanish-language Drácula shot alongside it in 1931, and the English one a year out
    items = {"spanish": ("Drácula", 1931, 13666), "english": ("Dracula", 1932, 138)}
    assert matched(make_cfg, [("Dracula", 1931)], items)[0] == ["spanish"]
    assert matched(make_cfg, [("Dracula", 1931, 138)], items)[0] == ["english"]


def test_the_id_wins_over_a_same_named_remake(make_cfg):
    # a remake the server dates a year out, so the loose try alone would take it for the original
    items = {"remake": ("The Lion King", 1995, 420818), "original": ("The Lion King (1994)", 1994, 8587)}
    assert matched(make_cfg, [("The Lion King", 1994)], items)[0] == ["remake"]
    assert matched(make_cfg, [("The Lion King", 1994, 8587)], items)[0] == ["original"]


def test_an_item_found_by_its_id_fills_one_place(make_cfg):
    items = {"z": ("Zootropolis", 2016, 269149)}
    assert matched(make_cfg, [("Zootopia", 2016, 269149), ("Zootropolis", 2016)], items) == (["z"], 2, 1)
    assert matched(make_cfg, [("Zootropolis", 2016), ("Zootopia", 2016, 269149)], items) == (["z"], 2, 1)
    assert matched(make_cfg, [("Zootopia", 2016, 269149), ("Zootopia", 2016, 269149)], items) == (["z"], 2, 1)


def test_ids_are_tried_for_every_place_before_any_name(make_cfg):
    # place 0 (no id) would take "b" by its name, but "b" is place 1's by id; place 0 still gets "a" a year out
    items = {"a": ("Saw", 2005), "b": ("Saw", 2004, 176)}
    assert matched(make_cfg, [("Saw", 2004), ("Saw", 2004, 176)], items)[0] == ["a", "b"]


def test_an_id_not_in_the_library_falls_back_to_the_name(make_cfg):
    assert matched(make_cfg, [("Zootopia", 2016, 269149)], {"a": ("Zootopia", 2016)})[0] == ["a"]
    assert matched(make_cfg, [("Zootopia", 2016, 269149)], {"a": ("zootopia", 2017, 5)})[0] == ["a"]
    assert matched(make_cfg, [("Zootopia", 2016, 269149)], {"a": ("Zootopia", 2026, 5)})[0] == []


def test_lists_with_and_without_ids_keep_their_order(make_cfg):
    titles = [("Zootopia", 2016, 269149), ("Zootopia 2", 2025), ("Back to the Future", 1985, 105)]
    items = {"bttf": ("Back to the Future", 1985, 105), "z2": ("Zootopia 2", 2025), "z": ("Zootropolis", 2016, 269149)}
    assert matched(make_cfg, titles, items) == (["z", "z2", "bttf"], 3, 3)
    assert matched(make_cfg, [(t, y) for t, y, *_ in titles], items) == (["z2", "bttf"], 3, 2)


def test_a_show_list_looks_its_ids_up_among_shows(make_cfg):
    """TMDB numbers movies and TV shows separately, so one number can be a film and a show."""
    eng = Engine(make_cfg(), FakeServer())
    index = index_of({"film": ("Some Film", 1999, 1399)})
    index["items"]["got"] = {"n": "Game of Thrones", "y": 2011, "b": True, "k": "show"}
    index["show"]["tmdb"]["1399"] = "got"
    assert eng.resolve({"key": "s-x", "kind": "show", "titles": [("GoT", 2011, 1399)]}, index)[0] == ["got"]
    assert eng.resolve({"key": "m-x", "kind": "movie", "titles": [("GoT", 2011, 1399)]}, index)[0] == ["film"]


def test_ids_from_an_emby_library(make_cfg):
    cfg = make_cfg("emby", ZOOTOPIA)
    srv = FakeServer()
    srv.add_library("Movies", [("e1", "Zootropolis", 2016, "Movie", {"Tmdb": "269149", "Imdb": "tt2948356"}),
                               ("e2", "Zootopia 2", 2025, "Movie", {})])
    srv.add_library("TV Shows", [])
    eng = Engine(cfg, srv)
    assert eng.resolve(catalog.load(cfg)[0], eng.build_index()) == (["e1", "e2"], 2, 2)


def test_ids_from_silo_content_ids(silo_run):
    """Silo names a title by the id it was added with (movie-tmdb-269149), and the index files it under that id."""
    silo_run.fake.items["movie-tmdb-269149"] = {"title": "Zootropolis", "year": 2016, "lib": "1",
                                                "genres": ["Animation"], "ids": {}}
    cfg, srv, eng = silo_run(ZOOTOPIA)
    coll = catalog.load(cfg)[0]
    index = eng.build_index()
    assert index["movie"]["tmdb"]["269149"] == "movie-tmdb-269149"
    assert eng.resolve(coll, index) == (["movie-tmdb-269149"], 2, 1)
    eng.run("apply", [coll], 1)
    assert set(by_slug(silo_run.fake, "cinesets-m-zootopia")["items"]) == {"movie-tmdb-269149"}


def test_matching_with_ids_is_the_same_as_reading_every_title_each_time(make_cfg):
    """test_scale's reference with ids in the mix: ids that are in the library, ids that aren't, one id wanted twice,
    and names and years that point at other items than the ids do."""
    rng = random.Random(7)
    eng = Engine(make_cfg(), FakeServer())
    names = [f"Title {n}" for n in range(40)]
    index = empty_index({})
    for n in range(2000):
        kind = rng.choice(["movie", "show"])
        index["items"][f"i{n}"] = {"n": rng.choice(names), "y": rng.choice([1999, 2000, 2001]), "b": True, "k": kind}
        if rng.random() < 0.5:
            index[kind]["tmdb"].setdefault(str(rng.randint(1, 3000)), f"i{n}")
    short = {iid: catalog.loose_title(it["n"]) for iid, it in index["items"].items()}
    for n in range(300):
        titles = [(rng.choice(names + ["Nowhere"]), rng.choice([1998, 1999, 2000, 2001, 2002]),
                   *([rng.randint(1, 3000)] if rng.random() < 0.6 else [])) for _ in range(rng.randint(1, 6))]
        coll = {"key": f"f{n}", "kind": rng.choice(["movie", "show"]), "titles": titles}
        assert eng.resolve(coll, index)[0] == reference(coll, index, short)


# ------------------------------------------------------------ the collections file

def test_entries_with_and_without_ids_load(make_cfg):
    coll = catalog.load(make_cfg(collections_yml=ZOOTOPIA))[0]
    assert coll["titles"] == [("Zootopia", 2016, 269149), ("Zootopia 2", 2025, None)]


def test_a_custom_collections_file_with_and_without_ids_loads(make_cfg):
    cfg = make_cfg()
    with open(cfg.path("custom_collections"), "w") as f:
        f.write("collections:\n"
                "  - {key: m-mine-old, group: universes, type: movie, title: Heat, min: 1, titles: [[Heat, 1995]]}\n"
                "  - {key: m-mine-ids, group: universes, type: movie, title: Heat, subtitle: Ronin, min: 1,"
                " titles: [[Heat, 1995, 949], [Ronin, 1998]]}\n")
    colls = {c["key"]: c for c in catalog.load(cfg)}
    assert colls["m-mine-old"]["titles"] == [("Heat", 1995, None)]
    assert colls["m-mine-ids"]["titles"] == [("Heat", 1995, 949), ("Ronin", 1998, None)]


@pytest.mark.parametrize("tmdb", ["0", "-5", '"269149"', "2.5", "true", "null", "[269149]", "tt2948356"])
def test_an_id_must_be_a_positive_whole_number(make_cfg, tmdb):
    cfg = make_cfg(collections_yml=ZOOTOPIA.replace("269149]", f"{tmdb}]"))
    with pytest.raises(SystemExit, match="m-zootopia: the TMDB id of 'Zootopia' must be a positive whole number"):
        catalog.load(cfg)


@pytest.mark.parametrize("entry", ['["Zootopia"]', '["Zootopia", 2016, 269149, 1]', '"Zootopia"', "{Zootopia: 2016}"])
def test_an_entry_must_be_a_title_and_year_and_maybe_an_id(make_cfg, entry):
    cfg = make_cfg(collections_yml=ZOOTOPIA.replace('["Zootopia", 2016, 269149]', entry))
    with pytest.raises(SystemExit, match=r"m-zootopia: each of its titles must be \[title, year\] or \[title, year, "
                                         r"TMDB id\]"):
        catalog.load(cfg)


def test_shipped_ids_are_whole_numbers_and_each_film_has_one(make_cfg):
    """Every id in collections.yml is a positive whole number, no collection has one twice, and a film in two
    franchises (Alien vs. Predator, say) has the same id in both."""
    fixed = [c for c in catalog.load(make_cfg()) if c.get("titles")]
    by_id, by_film = {}, {}
    for c in fixed:
        ids = [tmdb for _, _, tmdb in c["titles"] if tmdb is not None]
        assert len(set(ids)) == len(ids), c["key"]
        for title, year, tmdb in c["titles"]:
            if tmdb is None:
                continue
            assert isinstance(tmdb, int) and not isinstance(tmdb, bool) and tmdb > 0, (c["key"], title, tmdb)
            assert by_id.setdefault(tmdb, (title, year)) == (title, year), (c["key"], title, tmdb)
            assert by_film.setdefault((title, year), tmdb) == tmdb, (c["key"], title, tmdb)
