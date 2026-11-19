# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The optional TMDB key: franchises following their TMDB collections when CineSets runs, the copy kept on disk, the
key in config.yml or the environment, and setting it in setup and on the dashboard. Whenever there is no key or no
answer, the franchise lists that come with CineSets are used."""
import getpass
import json
import os
import time

import pytest

from cinesets import catalog, cli, config, tmdb
from cinesets.engine import Engine
from conftest import FakeServer
from test_franchise_ids import index_of
from test_web import site  # noqa: F401 (a fixture)

WICK = {"key": "m-johnwick", "titles": [("John Wick", 2014, 245891)], "tmdb_collections": [404609],
        "tmdb_add": [541671], "tmdb_skip": [1]}
PARTS = {245891: ("John Wick", "2014-10-22"), 324552: ("John Wick: Chapter 2", "2017-02-08"),
         1: ("A Skipped One", "2015-01-01"), 9: ("John Wick: Chapter 5", "")}
KEYED = {"tmdb": {"api_key": "k"}}


class FakeClient:
    calls, fail = [], None

    def __init__(self, key, patient=True):
        self.key, self.patient = key, patient

    def collection(self, cid):
        FakeClient.calls.append(("collection", cid, self.patient))
        if FakeClient.fail:
            raise FakeClient.fail
        return dict(PARTS)

    def movie(self, mid):
        FakeClient.calls.append(("movie", mid, self.patient))
        if FakeClient.fail:
            raise FakeClient.fail
        return {mid: ("Ballerina", "2025-06-04")}


@pytest.fixture
def fake_tmdb(monkeypatch):
    FakeClient.calls, FakeClient.fail = [], None
    monkeypatch.setattr(tmdb, "Client", FakeClient)
    tmdb.new_run()
    yield FakeClient
    tmdb.new_run()


def age(path, hours):
    data = json.loads(path.read_text())
    data["at"] -= hours * 3600
    path.write_text(json.dumps(data))


def test_without_a_key_or_a_collection_the_shipped_list_is_used(fake_tmdb, tmp_path):
    assert tmdb.live_titles(WICK, {"tmdb": {"api_key": ""}}, str(tmp_path)) is WICK["titles"]
    assert tmdb.live_titles({**WICK, "tmdb_collections": None}, KEYED, str(tmp_path)) == WICK["titles"]
    assert fake_tmdb.calls == []


def test_with_a_key_films_that_are_out_come_in(fake_tmdb, tmp_path, capsys):
    got = tmdb.live_titles(WICK, KEYED, str(tmp_path), today="2026-11-19")
    assert got == [("John Wick", 2014, 245891), ("John Wick: Chapter 2", 2017, 324552), ("Ballerina", 2025, 541671)]
    assert "m-johnwick: new from TMDB: John Wick: Chapter 2 (2017), Ballerina (2025)" in capsys.readouterr().out


def test_answers_are_kept_for_a_day(fake_tmdb, tmp_path):
    tmdb.live_titles(WICK, KEYED, str(tmp_path))
    assert len(fake_tmdb.calls) == 2
    tmdb.live_titles(WICK, KEYED, str(tmp_path))
    assert len(fake_tmdb.calls) == 2                                   # both answers saved and still fresh
    age(tmp_path / "tmdb" / "collection-404609.json", 25)
    tmdb.live_titles(WICK, KEYED, str(tmp_path))
    assert fake_tmdb.calls[2:] == [("collection", 404609, True)]       # the film's copy lasts a week


def test_tmdb_down_uses_the_saved_copy_then_the_shipped_list(fake_tmdb, tmp_path, capsys):
    first = tmdb.live_titles(WICK, KEYED, str(tmp_path))
    age(tmp_path / "tmdb" / "collection-404609.json", 25)
    fake_tmdb.fail = tmdb.Unreadable("TMDB didn't answer (ConnectionError)")
    assert tmdb.live_titles(WICK, KEYED, str(tmp_path)) == first
    assert "TMDB didn't answer (ConnectionError), so CineSets is using the copy it saved 25 h ago" in capsys.readouterr().out
    assert tmdb.live_titles(WICK, KEYED, str(tmp_path / "elsewhere")) == WICK["titles"]
    assert "m-johnwick: TMDB didn't answer (ConnectionError), so it uses the list that comes with CineSets" \
        in capsys.readouterr().out


def test_a_refused_key_is_said_once_a_run(fake_tmdb, tmp_path, capsys):
    fake_tmdb.fail = tmdb.Refused("TMDB refused the key")
    other = {**WICK, "key": "m-other"}
    assert tmdb.live_titles(WICK, KEYED, str(tmp_path)) == WICK["titles"]
    assert tmdb.live_titles(other, KEYED, str(tmp_path)) == WICK["titles"]
    assert capsys.readouterr().out.count("TMDB refused the API key") == 1 and len(fake_tmdb.calls) == 1
    tmdb.new_run()
    tmdb.live_titles(WICK, KEYED, str(tmp_path))
    assert len(fake_tmdb.calls) == 2                                   # the next run tries the key again


def test_a_damaged_copy_is_asked_for_again(fake_tmdb, tmp_path):
    (tmp_path / "tmdb").mkdir()
    (tmp_path / "tmdb" / "collection-404609.json").write_text('{"at": "soon", "films": 5}')
    assert len(tmdb.live_titles(WICK, KEYED, str(tmp_path))) == 3


FRANCHISE = """collections:
  - key: m-johnwick
    group: universes
    type: movie
    title: "John Wick"
    min: 1
    tmdb_collections: [404609]
    tmdb_skip: [1]
    titles:
      - ["John Wick", 2014, 245891]
"""


def test_runs_match_the_films_tmdb_adds(make_cfg, fake_tmdb):
    index = index_of({"m1": ("John Wick", 2014, 245891), "m2": ("John Wick: Chapter 2", 2017, 324552)})
    cfg = make_cfg(collections_yml=FRANCHISE)
    coll = catalog.load(cfg)[0]
    assert Engine(cfg, FakeServer()).resolve(coll, index) == (["m1"], 1, 1)
    cfg = make_cfg(collections_yml=FRANCHISE, extra='tmdb: {api_key: "k"}\n')
    engine = Engine(cfg, FakeServer())
    assert engine.resolve(coll, index) == (["m1", "m2"], 2, 2)
    engine.patient = False                                             # the dashboard asks TMDB once, briefly
    engine.data = os.path.join(engine.data, "fresh")
    engine.resolve(coll, index)
    assert fake_tmdb.calls[-1] == ("collection", 404609, False)


# ---------------------------------------------------------------- the key in config.yml or the environment
def test_the_key_comes_from_config_or_the_environment(make_cfg, monkeypatch):
    monkeypatch.delenv("CINESETS_TMDB_API_KEY", raising=False)
    assert make_cfg()["tmdb"] == {"api_key": "", "from_env": False}
    assert make_cfg(extra='tmdb: {api_key: " abc "}\n')["tmdb"] == {"api_key": "abc", "from_env": False}
    monkeypatch.setenv("CINESETS_TMDB_API_KEY", "from-env")
    assert make_cfg(extra='tmdb: {api_key: "abc"}\n')["tmdb"] == {"api_key": "from-env", "from_env": True}


@pytest.mark.parametrize("block", ["tmdb: 5\n", "tmdb: {api_key: 12345}\n", "tmdb: [a]\n"])
def test_a_tmdb_block_that_isnt_a_key_is_an_error(make_cfg, block):
    with pytest.raises(SystemExit, match="tmdb"):
        make_cfg(extra=block)


def test_a_config_holding_only_a_tmdb_key_is_kept_private(tmp_path, monkeypatch):
    monkeypatch.delenv("CINESETS_API_KEY", raising=False)
    path = tmp_path / "config.yml"
    path.write_text('server: {type: emby, url: "http://127.0.0.1:8096", api_key: ""}\ntmdb: {api_key: "k"}\n')
    os.chmod(path, 0o644)
    config.load(str(path))
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


def test_the_tmdb_block_is_written_in_place(make_cfg):
    cfg = make_cfg(extra="# keep me\ntmdb:\n  api_key: \"old\"\nlabels: {movie: Films}\n")
    path = os.path.join(cfg["base_dir"], "config.yml")
    config.write_block(path, "tmdb", config.tmdb_block('n"ew\\key'))
    again = config.load(path)
    assert again["tmdb"]["api_key"] == 'n"ew\\key' and again["labels"]["movie"] == "Films"
    assert open(path).read().count("tmdb:") == 1 and "# keep me" in open(path).read()


def test_the_example_config_has_an_empty_tmdb_key(monkeypatch):
    monkeypatch.delenv("CINESETS_TMDB_API_KEY", raising=False)
    cfg = config.load(os.path.join(config.ROOT, "config.example.yml"))
    assert cfg["tmdb"] == {"api_key": "", "from_env": False}


# ---------------------------------------------------------------- setup
class Checked:
    tried = []

    def __init__(self, key, patient=True):
        self.key = key

    def check(self):
        Checked.tried.append(self.key)
        if self.key == "bad":
            raise tmdb.Refused("TMDB refused the key")
        if self.key == "offline":
            raise tmdb.Unreadable("TMDB didn't answer (ConnectionError)")


@pytest.fixture
def setup_file(tmp_path, monkeypatch):
    Checked.tried = []
    monkeypatch.setattr(tmdb, "Client", Checked)
    path = tmp_path / "config.yml"
    path.write_text('server: {type: emby, url: "http://127.0.0.1:8096", api_key: "k"}\ntmdb:\n  api_key: ""\n')
    return path


def answer(monkeypatch, *keys):
    replies = iter(keys)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(replies))


def test_setup_can_skip_the_tmdb_key(setup_file, monkeypatch, capsys):
    before = setup_file.read_text()
    answer(monkeypatch, "")
    cli.ask_tmdb(str(setup_file))
    assert setup_file.read_text() == before and "Skipped" in capsys.readouterr().out and Checked.tried == []


def test_setup_checks_the_tmdb_key_before_saving_it(setup_file, monkeypatch, capsys):
    answer(monkeypatch, "bad", " good ")
    cli.ask_tmdb(str(setup_file))
    assert Checked.tried == ["bad", "good"] and config.load(str(setup_file))["tmdb"]["api_key"] == "good"
    out = capsys.readouterr().out
    assert "TMDB turned that key down" in out and tmdb.CREDIT in out


def test_setup_keeps_a_key_tmdb_couldnt_check(setup_file, monkeypatch):
    answer(monkeypatch, "offline")
    cli.ask_tmdb(str(setup_file))
    assert config.load(str(setup_file))["tmdb"]["api_key"] == "offline"


def test_setup_gives_up_after_three_refused_keys(setup_file, monkeypatch, capsys):
    answer(monkeypatch, "bad", "bad", "bad")
    cli.ask_tmdb(str(setup_file))
    assert config.load(str(setup_file))["tmdb"]["api_key"] == "" and "Skipped the TMDB key" in capsys.readouterr().out


# ---------------------------------------------------------------- the dashboard
@pytest.fixture
def keyed_site(site, monkeypatch):
    Checked.tried = []
    monkeypatch.setattr(tmdb, "Client", Checked)
    monkeypatch.delenv("CINESETS_TMDB_API_KEY", raising=False)
    return site


def test_the_dashboard_saves_and_removes_the_tmdb_key(keyed_site):
    call, cfg, srv, app, client = keyed_site
    s = call("/api/settings")[1]
    assert s["tmdb"] == {"set": False, "from_env": False, "credit": tmdb.CREDIT}
    status, out = call("/api/tmdb", {"key": " secret-tmdb ", "version": s["version"]})
    assert status == 200 and out["saved"] and out["tmdb"]["set"] and Checked.tried == ["secret-tmdb"]
    assert out["version"] == config.file_version(app.cfg_path)
    assert config.load(app.cfg_path)["tmdb"]["api_key"] == "secret-tmdb"
    assert "# keep me" in open(app.cfg_path).read() and oct(os.stat(app.cfg_path).st_mode & 0o777) == "0o600"
    assert call("/api/settings")[1]["tmdb"]["set"] is True
    status, out = call("/api/tmdb", {"key": "", "version": out["version"]})
    assert status == 200 and out["tmdb"]["set"] is False and config.load(app.cfg_path)["tmdb"]["api_key"] == ""
    assert not any(b"secret-tmdb" in b for b in client.bodies)       # the key never goes back to the page


def test_the_dashboard_turns_down_a_bad_key_and_keeps_the_file(keyed_site):
    call, cfg, srv, app, client = keyed_site
    version = call("/api/settings")[1]["version"]
    before = open(app.cfg_path).read()
    status, out = call("/api/tmdb", {"key": "bad", "version": version})
    assert status == 400 and "TMDB turned that key down" in out["error"]
    status, out = call("/api/tmdb", {"key": "offline", "version": version})
    assert status == 502 and "Couldn't check the key with TMDB" in out["error"]
    for body in ({"key": "two words"}, {"key": 5}, {"key": "x" * 1001}, {}):
        assert call("/api/tmdb", {**body, "version": version})[0] == 400
    assert open(app.cfg_path).read() == before


def test_the_dashboard_keeps_changes_made_elsewhere(keyed_site):
    call, cfg, srv, app, client = keyed_site
    version = call("/api/settings")[1]["version"]
    with open(app.cfg_path, "a") as f:
        f.write("# changed by hand\n")
    status, out = call("/api/tmdb", {"key": "good", "version": version})
    assert status == 409 and config.load(app.cfg_path)["tmdb"]["api_key"] == ""


def test_a_key_from_the_environment_is_changed_there(keyed_site, monkeypatch):
    call, cfg, srv, app, client = keyed_site
    monkeypatch.setenv("CINESETS_TMDB_API_KEY", "from-env")
    later = time.time() + 5
    os.utime(app.cfg_path, (later, later))                             # the dashboard reads config.yml again
    s = call("/api/settings")[1]
    assert s["tmdb"] == {"set": True, "from_env": True, "credit": tmdb.CREDIT}
    status, out = call("/api/tmdb", {"key": "good", "version": s["version"]})
    assert status == 400 and "CINESETS_TMDB_API_KEY" in out["error"] and Checked.tried == []
    assert not any(b"from-env" in b for b in client.bodies)
