# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""mdblist lists and the files CineSets keeps: waiting out a rate limit politely, what gets cached, the warning for a
list that keeps failing, and state.json's backup copy and checks."""
import json
import os
import time

import pytest

from cinesets import lists
from cinesets.store import load_json, save_json

ROWS = [{"mediatype": "movie", "rank": 1, "imdb_id": "tt1"}]


class Answer:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("no body")
        return self._data


@pytest.fixture
def mdblist(monkeypatch):
    """mdblist answering from a list of answers (the last one repeats), with every wait recorded instead of slept."""
    answers, asked, waits = [], [], []

    def get(url, timeout=None, headers=None):
        asked.append(url)
        return answers.pop(0) if len(answers) > 1 else answers[0]
    monkeypatch.setattr(lists.requests, "get", get)
    monkeypatch.setattr(lists.time, "sleep", waits.append)
    lists.new_run()
    yield answers, asked, waits
    lists.new_run()


def test_a_rate_limit_is_waited_out_without_a_wait_after_the_last_try(mdblist, tmp_path):
    answers, asked, waits = mdblist
    answers.append(Answer(429))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        lists.fetch_list("someone/one", str(tmp_path))
    assert len(asked) == 4 and waits == [20, 40, 60]


def test_retry_after_is_honoured_within_reason(mdblist, tmp_path):
    answers, asked, waits = mdblist
    answers += [Answer(429, headers={"Retry-After": "7"}), Answer(429, headers={"Retry-After": "3600"}), Answer(200, ROWS)]
    assert lists.fetch_list("someone/one", str(tmp_path)) == ROWS
    assert waits == [7.0, lists.RETRY_AFTER_MOST]


def test_once_one_list_used_up_its_tries_the_rest_of_the_run_tries_once(mdblist, tmp_path, capsys):
    answers, asked, waits = mdblist
    answers.append(Answer(429))
    for slug in ("someone/one", "someone/two", "someone/three"):
        with pytest.raises(RuntimeError):
            lists.fetch_list(slug, str(tmp_path))
    assert len(asked) == 4 + 1 + 1 and len(waits) == 3
    assert "the rest of this run tries each list once" in capsys.readouterr().out
    lists.new_run()                               # the next run is patient again
    asked.clear()
    with pytest.raises(RuntimeError):
        lists.fetch_list("someone/four", str(tmp_path))
    assert len(asked) == 4


@pytest.mark.parametrize("body", [["tt1", "tt2"], [ROWS[0], None], {"rows": ROWS}])
def test_only_a_list_of_rows_is_kept(mdblist, tmp_path, body):
    answers, asked, waits = mdblist
    answers.append(Answer(200, body))
    with pytest.raises(RuntimeError, match="ValueError"):
        lists.fetch_list("someone/odd", str(tmp_path))
    assert not os.path.exists(tmp_path / "lists" / "someone__odd.json")


def saved_copy(tmp_path, hours_old):
    path = tmp_path / "lists" / "someone__gone.json"
    save_json(str(path), {"at": time.time() - hours_old * 3600, "rows": ROWS})
    return path


def test_a_list_that_keeps_failing_is_named_every_run(mdblist, tmp_path, capsys):
    answers, asked, waits = mdblist
    path = saved_copy(tmp_path, 4)
    answers.append(Answer(404))
    for _ in range(2):
        assert lists.fetch_list("someone/gone", str(tmp_path)) == ROWS
        out = capsys.readouterr().out
        assert out.startswith("!! someone/gone: mdblist has answered HTTP 404 today")
        assert "copy it saved 4 h ago" in out and "may have been deleted or made private" in out
    record = json.loads(path.read_text())
    record["failing"] -= 5 * 86400                # five days on
    record["at"] -= 5 * 86400
    path.write_text(json.dumps(record))
    lists.fetch_list("someone/gone", str(tmp_path))
    assert "for 5 days, so CineSets is using the copy it saved 5 days ago" in capsys.readouterr().out
    answers[:] = [Answer(200, ROWS)]
    lists.fetch_list("someone/gone", str(tmp_path))
    assert "failing" not in json.loads(path.read_text())   # working again: the warning stops


def test_a_copy_that_cannot_be_read_is_treated_as_none(mdblist, tmp_path):
    answers, asked, waits = mdblist
    path = tmp_path / "lists" / "someone__odd.json"
    save_json(str(path), ["not", "a", "copy"])
    answers.append(Answer(200, ROWS))
    assert lists.fetch_list("someone/odd", str(tmp_path)) == ROWS


# ---------------------------------------------------------------- state.json
def test_state_keeps_the_version_before_as_a_backup(tmp_path):
    path = str(tmp_path / "state.json")
    save_json(path, {"m-one": {"id": "1"}})
    assert not os.path.exists(path + ".bak")
    save_json(path, {"m-one": {"id": "1"}, "m-two": {"id": "2"}})
    assert load_json(path + ".bak", None) == {"m-one": {"id": "1"}}
    assert load_json(path, None) == {"m-one": {"id": "1"}, "m-two": {"id": "2"}}
    save_json(str(tmp_path / "index.json"), {"built": 1})
    save_json(str(tmp_path / "index.json"), {"built": 2})
    assert sorted(os.listdir(tmp_path)) == ["index.json", "state.json", "state.json.bak"]   # caches get no copy


@pytest.mark.parametrize("text, words", [("null", "it holds null"), ("[]", "it holds list"), ('"x"', "it holds str")])
def test_state_of_the_wrong_kind_gets_a_clear_message(tmp_path, text, words):
    path = tmp_path / "state.json"
    path.write_text(text)
    with pytest.raises(SystemExit, match=words) as stop:
        load_json(str(path), {})
    assert "cinesets adopt" in str(stop.value)


def test_a_damaged_state_points_to_its_backup(tmp_path):
    path = str(tmp_path / "state.json")
    save_json(path, {"m-one": {"id": "1"}})
    save_json(path, {"m-one": {"id": "1"}})
    with open(path, "w") as f:
        f.write("{not json")
    with pytest.raises(SystemExit, match="replace it with state.json.bak"):
        load_json(path, {})
