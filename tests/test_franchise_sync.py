# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The franchise check (tests/e2e/check_franchises.py): which films come in and go from a fixed list as TMDB's
collections change, rewriting only those lines of collections.yml, and the checks catalog.load makes on its fields."""
import os
import sys

import pytest
import yaml

from cinesets import catalog

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "e2e"))
import check_franchises as cf  # noqa: E402

TODAY = "2026-11-19"
WICK = {245891: ("John Wick", "2014-10-22"), 324552: ("John Wick: Chapter 2", "2017-02-08"),
        1000001: ("John Wick: Chapter 5", "")}


def test_a_film_comes_in_once_it_is_out():
    titles = [["John Wick", 2014, 245891]]
    new, added, out = cf.plan(titles, WICK, {}, set(), TODAY)
    assert new == [["John Wick", 2014, 245891], ["John Wick: Chapter 2", 2017, 324552]]
    assert added == [["John Wick: Chapter 2", 2017, 324552]] and out == []


def test_announced_films_wait_for_their_release_date():
    parts = {**WICK, 1000002: ("John Wick: Chapter 6", "2026-11-20")}
    new, added, _ = cf.plan([], parts, {}, set(), TODAY)
    assert [e[2] for e in new] == [245891, 324552]                    # no date, or tomorrow: not yet
    assert [e[2] for e in cf.plan([], parts, {}, set(), "2026-11-20")[0]] == [245891, 324552, 1000002]


def test_a_film_already_listed_stays_before_its_release_with_its_own_title_and_year():
    titles = [["John Wick: Chapter Five", 2027, 1000001], ["John Wick", 2014, 245891]]
    new, added, out = cf.plan(titles, WICK, {}, set(), TODAY)
    assert new[:2] == titles and out == []
    assert added == [["John Wick: Chapter 2", 2017, 324552]]          # new films go at the end


def test_a_film_tmdb_drops_goes_unless_it_is_added_by_hand():
    titles = [["John Wick", 2014, 245891], ["Ballerina", 2025, 541671]]
    new, _, out = cf.plan(titles, WICK, {}, set(), TODAY)
    assert out == [["Ballerina", 2025, 541671]] and [e[2] for e in new] == [245891, 324552]
    new, added, out = cf.plan(titles, WICK, {541671: ("Ballerina", "2025-06-04")}, set(), TODAY)
    assert out == [] and [e[2] for e in new] == [245891, 541671, 324552]


def test_skipped_films_stay_out():
    titles = [["John Wick", 2014, 245891], ["John Wick: Chapter 2", 2017, 324552]]
    new, added, out = cf.plan(titles, WICK, {}, {324552}, TODAY)
    assert [e[2] for e in new] == [245891] and out == [["John Wick: Chapter 2", 2017, 324552]] and added == []


class FakeTMDB:
    def __init__(self, cols, movies=None):
        self.cols, self.movies = cols, movies or {}

    def collection(self, cid):
        if cid not in self.cols:
            raise cf.Problem(f"TMDB has nothing at /collection/{cid}")
        return self.cols[cid]

    def movie(self, mid):
        return {mid: self.movies[mid]}


FILE = """# a comment that stays
collections:

  # --- Franchises
  - key: m-johnwick
    group: universes
    type: movie
    title: "John\\nWick"
    tmdb_collections: [404609]
    tmdb_add: [541671]
    titles:
      - ["John Wick", 2014, 245891]   # the first one
      - ["Ballerina", 2025, 541671]
      - ["Old Spin-off", 2020, 999]
    min: 2
  - key: m-other
    group: universes
    type: movie
    title: "Other"
    titles:
      - ["Other", 2000, 5]
"""


def run(tmp_path, monkeypatch, *args, cols=None):
    path = tmp_path / "collections.yml"
    if not path.exists():
        path.write_text(FILE, encoding="utf-8")
    fake = FakeTMDB(cols or {404609: {**WICK, 1000003: ("Wick: Ünïcode \"Quoted\"", "2026-01-02")}},
                    {541671: ("Ballerina", "2025-06-04")})
    monkeypatch.setattr(cf, "TMDB", lambda key: fake)
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    return cf.main([str(path), *args]), path


def test_the_check_says_what_would_change_and_leaves_the_file(tmp_path, monkeypatch, capsys):
    status, path = run(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert status == 1 and path.read_text(encoding="utf-8") == FILE
    assert '+ ["John Wick: Chapter 2", 2017, 324552]' in out and '- ["Old Spin-off", 2020, 999]' in out
    assert "1 franchise lists checked against TMDB, 1 would change." in out


def test_write_changes_only_the_titles_and_a_second_check_passes(tmp_path, monkeypatch):
    status, path = run(tmp_path, monkeypatch, "--write")
    text = path.read_text(encoding="utf-8")
    assert status == 0
    assert '      - ["John Wick", 2014, 245891]   # the first one' in text       # kept lines are untouched
    assert "Old Spin-off" not in text and "# a comment that stays" in text
    doc = yaml.safe_load(text)
    wick, other = doc["collections"]
    assert wick["titles"] == [["John Wick", 2014, 245891], ["Ballerina", 2025, 541671],
                              ["John Wick: Chapter 2", 2017, 324552], ['Wick: Ünïcode "Quoted"', 2026, 1000003]]
    assert wick["min"] == 2 and other["titles"] == [["Other", 2000, 5]]
    assert run(tmp_path, monkeypatch)[0] == 0


def test_no_key_and_a_missing_collection_are_problems(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    assert cf.main([str(tmp_path / "none.yml")]) == 2
    assert "Set TMDB_API_KEY" in capsys.readouterr().out
    status, _ = run(tmp_path, monkeypatch, cols={1: {}})
    assert status == 2 and "Problem: TMDB has nothing at /collection/404609" in capsys.readouterr().out


def test_a_refused_key_stops_the_run_with_one_message(tmp_path, monkeypatch, capsys):
    class Refused(FakeTMDB):
        def collection(self, cid):
            raise cf.Unreadable("TMDB refused the key")
    path = tmp_path / "collections.yml"
    path.write_text(FILE + FILE.split("collections:\n", 1)[1].replace("m-johnwick", "m-again"), encoding="utf-8")
    monkeypatch.setattr(cf, "TMDB", lambda key: Refused({}))
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    assert cf.main([str(path)]) == 2
    assert capsys.readouterr().out.count("TMDB refused the key") == 1


@pytest.mark.parametrize("entry, problem", [
    ({"tmdb_add": [1], "titles": [["A", 2000, 1]]}, "need tmdb_collections"),
    ({"tmdb_collections": [1]}, "needs titles"),
    ({"tmdb_collections": [1], "titles": [["A", 2000]]}, "give every title its TMDB id"),
    ({"tmdb_collections": [1], "tmdb_add": [2], "tmdb_skip": [2], "titles": [["A", 2000, 1]]}, "both"),
    ({"tmdb_collections": "1", "titles": [["A", 2000, 1]]}, "must be a list of TMDB ids"),
])
def test_entries_the_check_cannot_work_with(entry, problem):
    results, problems = cf.check({"collections": [{"key": "m-x", **entry}]}, FakeTMDB({1: {}}), TODAY)
    assert results == [] and len(problems) == 1 and problem in problems[0]


def test_a_token_goes_in_a_header_and_a_key_as_a_parameter():
    token = cf.TMDB("eyJhbGciOi.test")
    assert token.session.headers["Authorization"] == "Bearer eyJhbGciOi.test" and "api_key" not in token.params
    key = cf.TMDB("0123abcd")
    assert key.params["api_key"] == "0123abcd" and "Authorization" not in key.session.headers


class Answer:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}

    def json(self):
        return {"parts": []}


@pytest.mark.parametrize("status, headers", [(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}), (503, {})])
def test_tmdb_busy_or_down_three_times_stops_the_run(monkeypatch, status, headers):
    waits = []
    monkeypatch.setattr(cf.time, "sleep", waits.append)
    tmdb = cf.TMDB("0123abcd")
    monkeypatch.setattr(tmdb.session, "get", lambda *a, **k: Answer(status, headers))
    with pytest.raises(cf.Unreadable, match=f"TMDB answered {status} for /collection/1 three times"):
        tmdb.collection(1)
    assert waits == [10, 10] if status == 429 else waits == [5, 5]


def test_tmdb_answers_after_a_slow_down(monkeypatch):
    answers = [Answer(429, {"Retry-After": "3"}), Answer(200)]
    monkeypatch.setattr(cf.time, "sleep", lambda s: None)
    tmdb = cf.TMDB("0123abcd")
    monkeypatch.setattr(tmdb.session, "get", lambda *a, **k: answers.pop(0))
    assert tmdb.collection(1) == {} and not answers


def test_retry_after_reads_seconds_and_caps_them():
    assert [cf.retry_after(x) for x in ("3", " 7 ", "600", "0", None, "", "soon")] == [3, 7, 60, 1, 10, 10, 10]


ONE = """collections:
  - key: m-one
    group: universes
    type: movie
    title: "One"
    min: 2
"""


@pytest.mark.parametrize("extra", ["    tmdb_collections: 404609\n", "    tmdb_add: [0]\n", "    tmdb_skip: [true]\n",
                                   '    tmdb_collections: ["404609"]\n'])
def test_catalogue_tmdb_fields_must_be_lists_of_ids(make_cfg, extra):
    cfg = make_cfg(collections_yml=ONE + extra + '    titles: [["A", 2000, 1], ["B", 2001, 2], ["C", 2002, 3]]\n')
    with pytest.raises(SystemExit, match="must be a list of TMDB ids"):
        catalog.load(cfg)


def test_catalogue_tmdb_fields_need_a_fixed_list(make_cfg):
    cfg = make_cfg(collections_yml=ONE + "    tmdb_collections: [404609]\n    lists: [a/b]\n")
    with pytest.raises(SystemExit, match="needs titles"):
        catalog.load(cfg)


def test_every_shipped_franchise_names_its_tmdb_collections(make_cfg):
    fixed = [c for c in catalog.load(make_cfg()) if c.get("titles")]
    assert fixed
    for c in fixed:
        assert c.get("tmdb_collections"), c["key"]
        assert all(tmdb for _, _, tmdb in c["titles"]), c["key"]
        assert not set(c.get("tmdb_add") or []) & set(c.get("tmdb_skip") or []), c["key"]
