# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""What CineSets owns: collections that share a name, creates that finish late or fail, old records without a
name, forget, and what remove shows before it asks."""
import os

import pytest

from cinesets import catalog, cli
from cinesets.engine import Engine
from cinesets.servers import ServerError
from cinesets.store import load_json, save_json
from conftest import FakeServer, seed_index

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
NAME = "Movies - Back to the Future"
ITEMS = {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie"),
         "m3": ("Back to the Future Part III", 1990, "movie")}


def setup_run(make_cfg, yml=FRANCHISE):
    cfg = make_cfg("emby", yml)
    seed_index(cfg, ITEMS)
    srv = FakeServer("emby")
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    return cfg, srv, Engine(cfg, srv)


def state(cfg):
    return load_json(os.path.join(cfg.path("data_dir"), "state.json"), {})


def creates(srv):
    return [c for c in srv.calls if c[0] == "POST" and c[1].startswith("/Collections?")]


def test_its_own_collection_stays_its_own_when_another_takes_the_same_name(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    ours = state(cfg)["m-bttf"]["id"]
    theirs = srv.add_collection(NAME, ["m1"])        # made later, so a name -> id listing would keep theirs
    del srv.collections[ours]["members"][2]          # something for the next run to fix
    capsys.readouterr()
    eng.run("apply", catalog.load(cfg), 8)
    out = capsys.readouterr().out
    assert state(cfg)["m-bttf"]["id"] == ours and "deleted on the server" not in out and "!!" not in out
    assert srv.collections[ours]["members"] == ["m1", "m2", "m3"]
    assert srv.collections[theirs]["members"] == ["m1"] and not srv.collections[theirs]["meta"]
    assert len(srv.collections) == 2


def test_a_name_several_collections_share_is_never_made_again(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    a, b = srv.add_collection(NAME, ["m1"]), srv.add_collection(NAME, ["m2"])
    result = eng.run("apply", catalog.load(cfg), 8)
    out = capsys.readouterr().out
    assert "2 collections on the server are called 'Movies - Back to the Future'" in out
    assert not creates(srv) and set(srv.collections) == {a, b} and "id" not in state(cfg).get("m-bttf", {})
    assert result.failed == 1 and not result.ok


def test_adopt_refuses_a_name_several_collections_share(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    srv.add_collection(NAME, ["m1"])
    srv.add_collection(NAME, ["m2"])
    eng.adopt(catalog.load(cfg))
    assert "2 collections are called" in capsys.readouterr().out
    assert "id" not in state(cfg)["m-bttf"]


def test_adopt_records_the_name_it_found(make_cfg):
    yml = FRANCHISE.replace("    min: 2\n", '    min: 2\n    create_name: "Movies - Back to the Future (new)"\n')
    cfg, srv, eng = setup_run(make_cfg, yml)
    cid = srv.add_collection("Movies - Back to the Future (new)", ["m1"])
    eng.adopt(catalog.load(cfg))
    assert state(cfg)["m-bttf"] == {"id": cid, "name": "Movies - Back to the Future (new)"}


def test_a_late_create_is_claimed_with_its_name(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    save_json(eng.state_file, {"m-bttf": {"pending": {"name": NAME, "not": None}}})   # a record from before 1.5
    late = srv.add_collection(NAME, ["m1", "m2", "m3"])
    eng.run("apply", catalog.load(cfg), 8)
    assert state(cfg)["m-bttf"]["id"] == late and state(cfg)["m-bttf"]["name"] == NAME
    assert "pending" not in state(cfg)["m-bttf"]


def test_a_pending_create_never_claims_a_collection_that_was_there_before(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    theirs = srv.add_collection(NAME, ["m1"])
    save_json(eng.state_file, {"m-bttf": {"pending": {"name": NAME, "not": [theirs]}}})
    eng.run("apply", catalog.load(cfg), 8)
    assert "id" not in state(cfg)["m-bttf"] and "pending" not in state(cfg)["m-bttf"]
    assert not srv.collections[theirs]["meta"] and "already exists" in capsys.readouterr().out


def test_a_pending_create_claims_nothing_when_the_name_is_shared(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    save_json(eng.state_file, {"m-bttf": {"pending": {"name": NAME, "not": []}}})
    srv.add_collection(NAME, ["m1"])
    srv.add_collection(NAME, ["m2"])
    eng.run("apply", catalog.load(cfg), 8)
    assert "claiming none of them" in capsys.readouterr().out and "id" not in state(cfg)["m-bttf"]


def test_a_create_the_server_turned_down_is_not_left_pending(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    real = srv.call

    def refuse(method, path, **kw):
        if method == "POST" and path.startswith("/Collections?"):
            raise ServerError("POST /Collections -> 400 bad request", 400)
        return real(method, path, **kw)
    srv.call = refuse
    eng.run("apply", catalog.load(cfg), 8)
    assert "pending" not in state(cfg)["m-bttf"]
    srv.call = real
    mine = srv.add_collection(NAME, ["m1"])           # someone makes one with that name later: it isn't claimed
    eng.run("apply", catalog.load(cfg), 8)
    assert "id" not in state(cfg)["m-bttf"] and not srv.collections[mine]["meta"]


def test_a_create_that_timed_out_stays_pending_with_the_names_already_there(make_cfg):
    import requests
    cfg, srv, eng = setup_run(make_cfg)
    real = srv.call

    def slow(method, path, **kw):
        if method == "POST" and path.startswith("/Collections?"):
            raise requests.Timeout("simulated")
        return real(method, path, **kw)
    srv.call = slow
    eng.run("apply", catalog.load(cfg), 8)
    assert state(cfg)["m-bttf"]["pending"] == {"name": NAME, "not": []}


def test_an_old_record_without_a_name_is_not_deleted_once_it_leaves_the_file(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    cid = srv.add_collection("Somebody's favourites", ["m1"])   # the id now holds something else
    save_json(eng.state_file, {"m-old": {"id": cid}})           # an old record: no name, and not in the file
    assert eng.remove(["m-old"], catalog.load(cfg)) == 0 and cid in srv.collections
    out = capsys.readouterr().out
    assert "doesn't say what it named" in out and "cinesets forget m-old" in out


def test_an_old_record_without_a_name_still_works_while_it_is_in_the_file(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    cid = srv.add_collection(NAME, ["m1"])
    save_json(eng.state_file, {"m-bttf": {"id": cid}})
    eng.run("apply", catalog.load(cfg), 8)
    assert srv.collections[cid]["members"] == ["m1", "m2", "m3"] and state(cfg)["m-bttf"]["name"] == NAME
    save_json(eng.state_file, {"m-bttf": {"id": cid}})
    assert eng.remove(["m-bttf"], catalog.load(cfg)) == 1 and not srv.collections


def test_a_renamed_collection_points_to_forget_and_is_left_out_of_the_page_order(make_cfg, capsys):
    two = FRANCHISE + FRANCHISE.replace("collections:\n", "").replace("m-bttf", "m-bttf2").replace("Back to\\nthe", "Back to\\nThe")
    cfg, srv, eng = setup_run(make_cfg, two)
    eng.run("apply", catalog.load(cfg), 8)
    st = state(cfg)
    srv.collections[st["m-bttf"]["id"]]["Name"] = "My own favourites"
    arranged = []
    srv.arrange = lambda owned: arranged.append(dict(owned))
    capsys.readouterr()
    eng.run("apply", catalog.load(cfg), 8)
    assert "run: cinesets forget m-bttf" in capsys.readouterr().out
    assert arranged == [{"m-bttf2": st["m-bttf2"]["id"]}]


def test_a_collection_deleted_on_the_server_says_it_is_made_again(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    srv.collections.clear()
    capsys.readouterr()
    eng.run("plan", catalog.load(cfg), 8)
    assert "apply would make it again (unpick it to stop that)" in capsys.readouterr().out
    eng.run("apply", catalog.load(cfg), 8)
    assert "so it is being made again (unpick it to stop that)" in capsys.readouterr().out and len(srv.collections) == 1


def cli_run(monkeypatch, cfg, srv, *argv):
    monkeypatch.setattr(cli.servers, "connect", lambda cfg: srv)
    monkeypatch.setattr("sys.argv", ["cinesets", *argv, "--config", os.path.join(cfg["base_dir"], "config.yml")])
    cli.main()


def test_forget_drops_the_record_and_leaves_the_server_alone(make_cfg, monkeypatch, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    cid = state(cfg)["m-bttf"]["id"]
    srv.calls.clear()
    capsys.readouterr()
    cli_run(monkeypatch, cfg, srv, "forget", "m-bttf, m-nothing")
    out = capsys.readouterr().out
    assert "m-bttf" not in state(cfg) and cid in srv.collections and srv.calls == []
    assert "m-nothing: CineSets has no record of it" in out and "still picked in config.yml: m-bttf" in out
    assert eng.remove(["m-bttf"], catalog.load(cfg)) == 0 and cid in srv.collections


def test_forget_needs_keys_and_other_commands_take_none(make_cfg, monkeypatch):
    cfg, srv, eng = setup_run(make_cfg)
    with pytest.raises(SystemExit, match="forget needs the keys"):
        cli_run(monkeypatch, cfg, srv, "forget")
    with pytest.raises(SystemExit):
        cli_run(monkeypatch, cfg, srv, "apply", "m-bttf")


def test_remove_lists_the_names_before_asking(make_cfg, monkeypatch, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    monkeypatch.setattr("builtins.input", lambda prompt: print(prompt) or "no")
    capsys.readouterr()
    cli_run(monkeypatch, cfg, srv, "remove", "--group", " universes , kids")
    out = capsys.readouterr().out
    assert out.index(NAME) < out.index("Type yes") and "Nothing deleted." in out and len(srv.collections) == 1
