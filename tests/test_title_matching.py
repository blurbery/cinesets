# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Fixed franchise lists: the exact title and year first, then the same title written another way from that year or
one either side, never a remake from another year, and never one library item in two places."""
import time

import pytest

from cinesets.catalog import loose_title
from cinesets.engine import Engine
from conftest import FakeServer


def index_of(items, canon=()):
    """A library index from {id: (name, year)}; ids in canon hold a provider id, so they are the canonical copy."""
    return {"built": time.time(), "movie": {"imdb": {f"tt{i}": i for i in canon}, "tmdb": {}},
            "show": {"tvdb": {}, "imdb": {}, "tmdb": {}},
            "items": {i: {"n": n, "y": y, "b": True, "k": "movie"} for i, (n, y) in items.items()}}


def matched(make_cfg, titles, items, canon=()):
    coll = {"key": "m-test", "kind": "movie", "titles": titles}
    return Engine(make_cfg(), FakeServer()).resolve(coll, index_of(items, canon))


@pytest.mark.parametrize("wanted, server", [
    ("Alien³", "Alien 3"),
    ("Child's Play", "Child’s Play"),                     # curly and straight quotes
    ("Fast & Furious", "Fast and Furious"),
    ("The Lego Movie", "Lego Movie"),                      # a leading "The"
    ("Shōgun", "Shogun"),                                  # accents
    ("Die Hard: With a Vengeance", "Die Hard With a Vengeance"),
    ("The Hunger Games: Mockingjay - Part 1", "The Hunger Games: Mockingjay – Part 1"),
    ("SAW X", "Saw X"),
])
def test_the_same_title_written_another_way_matches(make_cfg, wanted, server):
    assert loose_title(wanted) == loose_title(server)
    assert matched(make_cfg, [(wanted, 2000)], {"a": (server, 2000)}) == (["a"], 1, 1)


def test_titles_that_differ_stay_apart():
    assert loose_title("Scream 2") != loose_title("Scream")
    assert loose_title("Theodore Rex") == "theodorerex"          # only a whole leading word "The" goes
    assert loose_title("") == loose_title(None) == ""
    assert loose_title(1917) == "1917"                          # an unquoted number in a collections file


def test_a_year_either_side_matches_but_not_two(make_cfg):
    titles = [("The Evil Dead", 1981)]
    assert matched(make_cfg, titles, {"a": ("The Evil Dead", 1982)})[0] == ["a"]
    assert matched(make_cfg, titles, {"a": ("The Evil Dead", 1980)})[0] == ["a"]
    assert matched(make_cfg, titles, {"a": ("The Evil Dead", 1983)})[0] == []
    assert matched(make_cfg, titles, {"a": ("The Evil Dead", None)})[0] == []


def test_exact_matches_come_first(make_cfg):
    items = {"near": ("Scream", 1997), "exact": ("scream", 1996)}
    assert matched(make_cfg, [("Scream", 1996)], items)[0] == ["exact"]
    items = {"near": ("Scream", 1997), "loose": ("SCREAM!", 1996)}
    assert matched(make_cfg, [("Scream", 1996)], items)[0] == ["loose"]      # the same year before one either side


def test_a_remake_never_fills_the_original(make_cfg):
    titles = [("Scream", 1996), ("Scream 2", 1997), ("Scream", 2022)]
    assert matched(make_cfg, titles, {"new": ("Scream", 2022)}) == (["new"], 3, 1)
    both = {"new": ("Scream", 2022), "old": ("Scream", 1996), "two": ("Scream 2", 1997)}
    assert matched(make_cfg, titles, both)[0] == ["old", "two", "new"]       # in the franchise's order


def test_one_item_fills_one_place(make_cfg):
    # the later entry's exact match is not taken by the earlier entry's second try
    assert matched(make_cfg, [("Saw", 2003), ("Saw", 2004)], {"a": ("Saw", 2004)}) == (["a"], 2, 1)
    # nor does a second try reuse an item another entry already has
    assert matched(make_cfg, [("Halloween", 1978), ("Halloween", 1979)], {"a": ("Halloween", 1978)})[0] == ["a"]
    # two copies, two places
    two = {"a": ("Halloween", 1978), "b": ("Halloween", 1979)}
    assert matched(make_cfg, [("Halloween", 1978), ("Halloween", 1979)], two)[0] == ["a", "b"]
    # the same entry twice in a list still gives the item once
    assert matched(make_cfg, [("Jaws", 1975), ("Jaws", 1975)], {"a": ("Jaws", 1975)})[0] == ["a"]


def test_the_canonical_copy_wins_on_the_second_try_too(make_cfg):
    items = {"copy": ("Alien 3", 1992), "canon": ("Alien 3", 1992)}
    assert matched(make_cfg, [("Alien³", 1992)], items, canon=["canon"])[0] == ["canon"]


def test_shows_and_movies_do_not_mix(make_cfg):
    index = index_of({"a": ("Fargo", 1996)})
    index["items"]["s"] = {"n": "Fargo", "y": 2014, "b": True, "k": "show"}
    eng = Engine(make_cfg(), FakeServer())
    assert eng.resolve({"key": "s-x", "kind": "show", "titles": [("Fargo", 1996)]}, index)[0] == []
    assert eng.resolve({"key": "m-x", "kind": "movie", "titles": [("Fargo", 1997)]}, index)[0] == ["a"]
