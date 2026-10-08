# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The shipped catalogue's data (names, years, minimums, seasons) and the checks catalog.load makes on any file."""
import datetime

import pytest

from cinesets import catalog

ONE = """collections:
  - key: m-one
    group: seasonal
    type: movie
    title: "One"
"""


def test_every_shipped_collection_has_its_own_name(make_cfg, capsys):
    colls = catalog.load(make_cfg())
    names = [c["name"] for c in colls]
    assert len(names) == len(set(names))
    assert "Note:" not in capsys.readouterr().out


def test_fixed_lists_have_real_years_and_a_minimum_they_can_reach(make_cfg):
    latest = datetime.date.today().year + 1
    fixed = [c for c in catalog.load(make_cfg()) if c.get("titles")]
    assert fixed
    for c in fixed:
        for title, year in c["titles"]:
            assert isinstance(title, str) and title.strip() == title and title, (c["key"], title)
            assert isinstance(year, int) and 1900 <= year <= latest, (c["key"], title, year)
        assert len(set(c["titles"])) == len(c["titles"]), c["key"]
        # a library missing one film still gets the collection, unless the franchise is a pair (one film is no set)
        assert 2 <= c.get("min", 8) < max(len(c["titles"]), 3), c["key"]


def test_list_minimums_are_sensible(make_cfg):
    for c in catalog.load(make_cfg()):
        if not c.get("titles") and "min" in c:
            assert isinstance(c["min"], int) and 1 <= c["min"] <= c["limit"], c["key"]


def test_seasonal_collections_have_a_window(make_cfg):
    colls = catalog.load(make_cfg())
    seasonal = [c for c in colls if c["group"] == "seasonal"]
    assert seasonal and all(c.get("active") for c in seasonal)
    days = [datetime.date(2028, 1, 1) + datetime.timedelta(days=n) for n in range(366)]   # a leap year
    for c in colls:
        if c.get("active"):
            inside = [d for d in days if catalog.in_season(c, d)]
            assert 0 < len(inside) < 366, c["key"]                       # part of the year, not none or all of it


def test_in_season_counts_both_ends_and_runs_past_new_year():
    halloween, christmas = {"active": ["10-01", "11-01"]}, {"active": ["11-20", "01-06"]}
    assert catalog.in_season(halloween, datetime.date(2026, 10, 1))
    assert catalog.in_season(halloween, datetime.date(2026, 11, 1))
    assert not catalog.in_season(halloween, datetime.date(2026, 11, 2))
    assert not catalog.in_season(halloween, datetime.date(2026, 9, 30))
    assert catalog.in_season(christmas, datetime.date(2026, 12, 25))
    assert catalog.in_season(christmas, datetime.date(2027, 1, 6))
    assert not catalog.in_season(christmas, datetime.date(2027, 1, 7))
    assert not catalog.in_season(christmas, datetime.date(2026, 11, 19))
    assert catalog.in_season({"active": ["02-29", "02-29"]}, datetime.date(2028, 2, 29))
    assert catalog.in_season({}) and catalog.in_season({"active": None})


@pytest.mark.parametrize("value", [
    '"10-01"', '["10-01"]', '["10-01", "11-01", "12-01"]', '["13-01", "01-01"]', '["02-30", "03-01"]',
    '["1-5", "2-6"]', "[2026-10-01, 2026-11-01]", '["10/01", "11/01"]', "[1001, 1101]", "{from: 10-01}",
])
def test_active_must_be_two_days_of_the_year(make_cfg, value):
    cfg = make_cfg(collections_yml=ONE + f"    lists: [a/b]\n    active: {value}\n")
    with pytest.raises(SystemExit, match="m-one: active must be two days of the year"):
        catalog.load(cfg)


def test_a_good_window_loads(make_cfg):
    cfg = make_cfg(collections_yml=ONE + '    lists: [a/b]\n    active: ["11-20", "01-06"]\n')
    assert catalog.load(cfg)[0]["active"] == ["11-20", "01-06"]
    assert "active" not in catalog.load(make_cfg(collections_yml=ONE + "    lists: [a/b]\n"))[0]


def test_two_collections_with_one_name_are_a_note_not_an_error(make_cfg, capsys):
    cfg = make_cfg(collections_yml=ONE + "    lists: [a/b]\n" + ONE.split("\n", 1)[1].replace("m-one", "m-two")
                   + "    lists: [c/d]\n")
    assert [c["key"] for c in catalog.load(cfg)] == ["m-one", "m-two"]
    out = capsys.readouterr().out
    assert "m-one and m-two are both called 'Movies - One'" in out


def test_a_custom_collection_named_like_a_shipped_one_still_loads(make_cfg, capsys):
    cfg = make_cfg()
    with open(cfg.path("custom_collections"), "w") as f:
        f.write('collections:\n  - {key: m-mine, group: charts, type: movie, title: "Trending", subtitle: "Top 20",'
                ' lists: [a/b]}\n')
    keys = [c["key"] for c in catalog.load(cfg)]
    assert "m-mine" in keys and "m-trending" in keys
    assert "m-trending and m-mine are both called 'Movies - Trending Top 20'" in capsys.readouterr().out


def test_lists_added_to_what_is_now_a_fixed_list_are_skipped(make_cfg, capsys):
    """John Wick and Middle-earth were list based; lists the dashboard added to them must not stop the file loading."""
    cfg = make_cfg()
    with open(cfg.path("custom_collections"), "w") as f:
        f.write("collections:\n  - {key: m-johnwick, add_lists: [someone/more-wick], subtitle: Mine}\n")
    wick = {c["key"]: c for c in catalog.load(cfg)}["m-johnwick"]
    assert wick["titles"] and "added_lists" not in wick and wick["subtitle"] == "Mine"
    assert "m-johnwick is a fixed list of titles, so the lists added to it are skipped" in capsys.readouterr().out
