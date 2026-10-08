# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""How a run ends: its Summary line and exit code, when it stops early, posters and artwork that fail without holding
back a collection's titles, and seasonal collections out of season."""
import datetime
import io
import os
import random

import pytest
import requests
from PIL import Image

from cinesets import catalog, cli
from cinesets.engine import Engine, in_season
from cinesets.servers import ServerError
from cinesets.store import load_json
from conftest import FakeServer, seed_index

ONE = """  - key: {key}
    group: universes
    type: movie
    title: "{title}"
    accent: blue
    min: {min}
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
      - ["Back to the Future Part III", 1990]
"""
ITEMS = {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie"),
         "m3": ("Back to the Future Part III", 1990, "movie")}


def catalogue(*entries):
    """collections.yml with these (key, title, min) franchises."""
    return "collections:\n" + "".join(ONE.format(key=k, title=t, min=m) for k, t, m in entries)


TWO = catalogue(("m-one", "One", 2), ("m-two", "Two", 2))


def setup_run(make_cfg, yml=TWO, kind="emby"):
    cfg = make_cfg(kind, yml)
    seed_index(cfg, ITEMS)
    srv = FakeServer(kind)
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    return cfg, srv, Engine(cfg, srv)


def state(cfg):
    return load_json(os.path.join(cfg.path("data_dir"), "state.json"), {})


def last_lines(out, n=1):
    return out.strip().splitlines()[-n:]


def failing(srv, when, error):
    """Make the fake server raise `error` for requests `when(method, path)` picks."""
    real = srv.call

    def call(method, path, **kw):
        if when(method, path):
            raise error
        return real(method, path, **kw)
    srv.call = call


# ---------------------------------------------------------------- the Summary line and the exit code
def test_apply_ends_with_a_summary_line(make_cfg, capsys):
    yml = TWO + catalogue(("m-big", "Big", 9)).replace("collections:\n", "")
    cfg, srv, eng = setup_run(make_cfg, yml)
    result = eng.run("apply", catalog.load(cfg), 8)
    out = capsys.readouterr().out
    assert last_lines(out) == ["Summary: 2 created, 1 left as they are (below the minimum)"] and result.ok
    assert "m-big: below its minimum (3 of 9 matches), so it is not made" in out
    result = eng.run("apply", catalog.load(cfg), 8)
    assert last_lines(capsys.readouterr().out) == ["Summary: 2 updated, 1 left as they are (below the minimum)"]


def test_below_the_minimum_says_it_is_left_as_it_is(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg), 8)
    with open(cfg.path("collections_file"), "w") as f:
        f.write(TWO.replace("min: 2", "min: 5"))
    capsys.readouterr()
    assert eng.run("apply", catalog.load(cfg), 8).ok
    out = capsys.readouterr().out
    assert "m-one: below its minimum (3 of 5 matches), so it is left as it is on the server" in out
    assert len(srv.collections) == 2 and srv.writes() and "skipped" not in out


def test_plan_says_what_apply_would_do(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    eng.run("apply", catalog.load(cfg)[:1], 8)
    capsys.readouterr()
    srv.calls.clear()
    eng.run("plan", catalog.load(cfg), 8)
    assert last_lines(capsys.readouterr().out) == ["Summary: 1 would create, 1 would update"] and srv.writes() == []


def test_plan_shows_matches_when_it_cannot_list_the_collections(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    failing(srv, lambda m, p: "BoxSet" in p, ServerError("GET /Items -> 403 forbidden", 403))
    assert eng.run("plan", catalog.load(cfg), 8).ok
    assert last_lines(capsys.readouterr().out) == ["Summary: 2 matched"]


def test_a_failed_list_fails_the_run_but_below_minimum_does_not(make_cfg, monkeypatch, capsys):
    yml = TWO + "  - {key: m-list, group: genres, type: movie, title: Listed, lists: [someone/gone]}\n"
    cfg, srv, eng = setup_run(make_cfg, yml)

    def gone(slug, data):
        raise RuntimeError(f"mdblist {slug}: HTTP 404")
    monkeypatch.setattr("cinesets.engine.fetch_list", gone)
    monkeypatch.setattr(cli.servers, "connect", lambda cfg: srv)
    monkeypatch.setattr("sys.argv", ["cinesets", "apply", "--config", os.path.join(cfg["base_dir"], "config.yml")])
    with pytest.raises(SystemExit) as stop:
        cli.main()
    assert stop.value.code == 1 and len(srv.collections) == 2
    assert last_lines(capsys.readouterr().out) == ["Summary: 2 created, 1 failed"]
    with open(cfg.path("collections_file"), "w") as f:
        f.write(TWO.replace("min: 2", "min: 5"))
    cli.main()                                         # below the minimum is fine: no SystemExit, so exit code 0
    assert last_lines(capsys.readouterr().out) == ["Summary: 2 left as they are (below the minimum)"]


@pytest.mark.parametrize("error, reason", [
    (ServerError("POST /Collections -> 401 unauthorised", 401), "the server turned down CineSets' API key (HTTP 401)"),
    (ServerError("POST /Collections -> 403 forbidden", 403), "the server turned down CineSets' API key (HTTP 403)"),
    (ServerError("POST /Collections -> 429 slow down", 429), "the server kept asking CineSets to slow down (HTTP 429)"),
    (ServerError("POST /Collections -> 502 bad gateway", 502), "the server had a problem (HTTP 502)"),
    (requests.ConnectionError("simulated"), "the server did not answer (ConnectionError)"),
])
def test_a_refused_key_a_lasting_429_or_a_dead_server_stops_the_run(make_cfg, capsys, error, reason):
    cfg, srv, eng = setup_run(make_cfg)
    tries = []
    failing(srv, lambda m, p: m == "POST" and p.startswith("/Collections?") and not tries.append(p), error)
    result = eng.run("apply", catalog.load(cfg), 8)
    assert len(tries) == 1 and not result.ok          # the second collection wasn't tried
    assert last_lines(capsys.readouterr().out, 2) == [f"Stopped early: {reason}", "Summary: 1 failed"]


def test_any_other_error_moves_on_to_the_next_collection(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    tries = []
    failing(srv, lambda m, p: m == "POST" and p.startswith("/Collections?") and not tries.append(p) and len(tries) == 1,
            ServerError("POST /Collections -> 400 bad request", 400))
    assert not eng.run("apply", catalog.load(cfg), 8).ok
    assert len(tries) == 2 and last_lines(capsys.readouterr().out) == ["Summary: 1 created, 1 failed"]


def test_an_error_outside_a_collection_stops_the_run_plainly(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    failing(srv, lambda m, p: "BoxSet" in p, ServerError("GET /Items -> 401 unauthorised", 401))
    result = eng.run("apply", catalog.load(cfg), 8)
    out = capsys.readouterr().out
    assert not result.ok and "Traceback" not in out and "!! GET /Items -> 401 unauthorised" in out
    assert last_lines(out, 2) == ["Stopped early: the server turned down CineSets' API key (HTTP 401)", "Summary: 1 failed"]


def test_cli_errors_outside_a_run_are_plain(make_cfg, monkeypatch):
    cfg, srv, eng = setup_run(make_cfg)
    failing(srv, lambda m, p: True, ServerError("The server did not accept the API key", 401))
    monkeypatch.setattr(cli.servers, "connect", lambda cfg: srv)
    monkeypatch.setattr("sys.argv", ["cinesets", "index", "--config", os.path.join(cfg["base_dir"], "config.yml")])
    with pytest.raises(SystemExit, match="^The server did not accept the API key$"):
        cli.main()
    failing(srv, lambda m, p: True, requests.ConnectionError("refused"))
    with pytest.raises(SystemExit, match=r"^The server did not answer \(ConnectionError\): refused$"):
        cli.main()


def test_slow_writes_stop_the_run(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg, TWO)
    cfg["slow_write_limit"] = -1
    assert not eng.run("apply", catalog.load(cfg), 8).ok and len(srv.collections) == 1
    assert last_lines(capsys.readouterr().out, 2)[0].startswith("Stopped early: the server is taking writes very slowly")


def test_asked_to_stop_between_collections(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    eng.halt = lambda: bool(srv.collections)          # asked to stop once the first one is made
    assert not eng.run("apply", catalog.load(cfg), 8).ok and len(srv.collections) == 1
    assert last_lines(capsys.readouterr().out, 2) == ["Stopped early: asked to stop", "Summary: 1 created"]


# ---------------------------------------------------------------- posters and artwork
def test_a_poster_that_cannot_be_drawn_does_not_freeze_the_titles(make_cfg, monkeypatch, capsys):
    cfg, srv, eng = setup_run(make_cfg, catalogue(("m-one", "One", 2)))
    eng.run("apply", catalog.load(cfg), 8)
    (coll,) = srv.collections.values()
    coll["members"].remove("m3")
    first = coll["image"]

    def broken(*a, **kw):
        raise OSError("simulated drawing problem")
    monkeypatch.setattr("cinesets.posters.make_poster", broken)
    with open(cfg.path("base_dir") + "/config.yml", "a") as f:
        f.write("posters: {shade: dark}\n")               # a new design, so the poster is drawn again
    from cinesets import config
    cfg2 = config.load(cfg.path("base_dir") + "/config.yml")
    capsys.readouterr()
    result = Engine(cfg2, srv).run("apply", catalog.load(cfg2), 8)
    out = capsys.readouterr().out
    assert coll["members"] == ["m1", "m2", "m3"] and coll["image"] == first   # titles synced, old poster kept
    assert "poster failed: simulated drawing problem; its titles are still updated" in out
    assert "without a new poster" in out and last_lines(out) == ["Summary: 1 failed"] and not result.ok
    assert "design" not in state(cfg)["m-one"]          # drawn again next run


def test_a_failed_poster_upload_still_sets_the_details(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    failing(srv, lambda m, p: m == "POST" and "/Images/" in p, ServerError("POST /Items/x/Images -> 400 too big", 400))
    result = eng.run("apply", catalog.load(cfg), 8)
    st = state(cfg)
    for key in ("m-one", "m-two"):                       # an upload error isn't a reason to stop: both were made
        coll = srv.collections[st[key]["id"]]
        assert coll["meta"]["Name"] == coll["Name"] and st[key]["meta"] and st[key]["name"] == coll["Name"]
        assert "poster" not in st[key] and not coll["image"]
    out = capsys.readouterr().out
    assert "the poster upload failed; it is tried again next run" in out and last_lines(out) == ["Summary: 2 failed"]
    assert not result.ok


def test_posters_ends_with_a_summary(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg)
    assert eng.run("posters", catalog.load(cfg), 8).ok
    assert last_lines(capsys.readouterr().out) == ["Summary: 2 posters made"] and srv.writes() == []


def noisy_jpeg():
    rng = random.Random(4)
    im = Image.new("RGB", (640, 360))
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(640 * 360)])
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def test_a_cut_off_backdrop_is_not_kept(make_cfg):
    cfg, srv, eng = setup_run(make_cfg)
    cut = noisy_jpeg()[:40000]
    with Image.open(io.BytesIO(cut)) as im:
        im.verify()                                      # what CineSets checked before: it passes
    srv.backdrop_image = lambda item_id, width=1920, quality=90: cut
    os.makedirs(eng.backdrops, exist_ok=True)
    assert eng.backdrop("m1") is None and os.listdir(eng.backdrops) == []


def test_a_broken_saved_backdrop_is_deleted_and_the_poster_still_made(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg, catalogue(("m-one", "One", 2)))
    os.makedirs(eng.backdrops, exist_ok=True)
    saved = os.path.join(eng.backdrops, "m1.jpg")
    with open(saved, "wb") as f:
        f.write(noisy_jpeg()[:40000])                    # left by an older version that only checked verify()
    assert eng.run("apply", catalog.load(cfg), 8).ok
    (coll,) = srv.collections.values()
    assert coll["image"] and not os.path.exists(saved) and "design" not in state(cfg)["m-one"]
    assert "downloaded again next run" in capsys.readouterr().out
    eng.run("apply", catalog.load(cfg), 8)               # the next run downloads it again and finishes the poster
    assert os.path.exists(saved) and state(cfg)["m-one"]["design"]


# ---------------------------------------------------------------- seasonal windows
@pytest.mark.parametrize("today, window, inside", [
    ("10-15", ["10-01", "10-31"], True), ("10-01", ["10-01", "10-31"], True), ("10-31", ["10-01", "10-31"], True),
    ("11-01", ["10-01", "10-31"], False), ("12-25", ["12-01", "01-06"], True), ("01-06", ["12-01", "01-06"], True),
    ("01-07", ["12-01", "01-06"], False), ("06-01", None, True),
])
def test_season_windows(today, window, inside):
    assert in_season(window, today) is inside


def days_from_today(n):
    return (datetime.date.today() + datetime.timedelta(days=n)).strftime("%m-%d")


def seasonal(window):
    return catalogue(("m-one", "One", 2)).replace("    min: 2\n", f'    min: 2\n    active: ["{window[0]}", "{window[1]}"]\n')


def test_a_collection_out_of_season_is_removed_and_not_made(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg, seasonal([days_from_today(-3), days_from_today(3)]))
    eng.run("apply", catalog.load(cfg), 8)
    assert len(srv.collections) == 1
    with open(cfg.path("collections_file"), "w") as f:
        f.write(seasonal([days_from_today(5), days_from_today(9)]))
    capsys.readouterr()
    srv.calls.clear()
    eng.run("plan", catalog.load(cfg), 8)
    out = capsys.readouterr().out
    assert "m-one" in out and "out of season" in out and "apply would delete 'Movies - One'" in out
    assert srv.writes() == []
    eng.run("apply", catalog.load(cfg), 8)
    assert not srv.collections and "m-one" not in state(cfg)
    assert "deleted 'Movies - One', as it is out of season" in capsys.readouterr().out
    eng.run("apply", catalog.load(cfg), 8)
    assert not srv.collections                           # and it isn't made again until its season


def test_a_renamed_collection_out_of_season_is_left_alone(make_cfg, capsys):
    cfg, srv, eng = setup_run(make_cfg, catalogue(("m-one", "One", 2)))
    eng.run("apply", catalog.load(cfg), 8)
    (cid, coll), = srv.collections.items()
    coll["Name"] = "Our family favourites"
    with open(cfg.path("collections_file"), "w") as f:
        f.write(seasonal([days_from_today(5), days_from_today(9)]))
    eng.run("apply", catalog.load(cfg), 8)
    assert cid in srv.collections and "not deleting it" in capsys.readouterr().out
