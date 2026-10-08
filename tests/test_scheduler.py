# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The scheduler: when jobs run, a failed job tried again within the hour, its times kept across restarts, and
SIGTERM. Also settings files that don't load: kept settings, clear messages and notes about unknown settings."""
import os
import signal
import subprocess
import sys
import time

import pytest

from cinesets import cli, config
from cinesets.engine import Engine
from cinesets.servers import ServerError
from cinesets.store import load_json, save_json
from conftest import FakeServer, seed_index

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YML = """collections:
  - key: m-one
    group: universes
    type: movie
    title: One
    min: 1
    titles: [["Back to the Future", 1985]]
  - key: m-two
    group: universes
    type: movie
    title: Two
    min: 1
    titles: [["Back to the Future Part II", 1989]]
"""
WEEKLY = {"every_hours": 168, "all": True}


def job_record(cfg):
    return load_json(os.path.join(cfg.path("data_dir"), "schedule.json"), {}).get(cli.job_name(WEEKLY))


def scheduler(make_cfg, monkeypatch):
    """A config with one weekly job, a fake server behind it, and a sleep that ends the scheduler's loop."""
    cfg = make_cfg("emby", YML, "schedule: [{every_hours: 168, all: true}]\n")
    seed_index(cfg, {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie")})
    srv = FakeServer("emby")
    srv.add_item("m1", "Back to the Future")
    srv.add_item("m2", "Back to the Future Part II")
    monkeypatch.setattr(cli.servers, "connect", lambda cfg: srv)

    def sleep(seconds):
        if seconds >= 300:                      # the scheduler's wait between rounds, not a pause between writes
            raise cli.Stopped()                 # as SIGTERM does while it waits
    monkeypatch.setattr(cli.time, "sleep", sleep)
    path = os.path.join(cfg["base_dir"], "config.yml")
    return cfg, srv, lambda: cli.schedule(cfg, Engine(cfg, srv), path)


@pytest.mark.parametrize("last, ago, due", [
    (None, None, True), ({"ok": True}, None, True), ({"at": "soon", "ok": True}, None, True),
    ({"ok": True}, 167 * 3600, False), ({"ok": True}, 168 * 3600, True), ({}, 167 * 3600, False),
    ({"ok": False}, 50 * 60, False), ({"ok": False}, 61 * 60, True),
])
def test_when_a_job_is_due(last, ago, due):
    now = 10 ** 9
    if ago is not None:
        last = {**last, "at": now - ago}
    assert cli.job_due(WEEKLY, last, now) is due
    assert cli.job_due({"every_hours": 0.5}, {"at": now - 31 * 60, "ok": False}, now)   # never later than its turn


def test_a_job_that_ran_is_not_run_again_after_a_restart(make_cfg, monkeypatch, capsys):
    cfg, srv, run = scheduler(make_cfg, monkeypatch)
    run()
    assert len(srv.collections) == 2 and job_record(cfg)["ok"] is True
    assert "Scheduler stopped." in capsys.readouterr().out
    srv.calls.clear()
    run()                                       # a restart: nothing is due yet
    assert srv.calls == [] and "--- " not in capsys.readouterr().out


def test_a_job_that_stopped_early_is_tried_again_in_about_an_hour(make_cfg, monkeypatch, capsys):
    cfg, srv, run = scheduler(make_cfg, monkeypatch)
    real = srv.call

    def down(method, path, **kw):
        if "BoxSet" in path:
            raise ServerError("GET /Items -> 503 unavailable", 503)
        return real(method, path, **kw)
    srv.call = down
    run()
    assert job_record(cfg)["ok"] is False and "tried again in about an hour" in capsys.readouterr().out
    srv.call = real
    run()
    assert not srv.collections                  # not straight away
    times = os.path.join(cfg.path("data_dir"), "schedule.json")
    save_json(times, {cli.job_name(WEEKLY): {"at": time.time() - 3700, "ok": False}})
    run()
    assert len(srv.collections) == 2 and job_record(cfg)["ok"] is True


def test_a_job_that_raised_is_tried_again_too(make_cfg, monkeypatch, capsys):
    cfg, srv, run = scheduler(make_cfg, monkeypatch)
    srv.libraries = {}
    os.remove(os.path.join(cfg.path("data_dir"), "index.json"))   # so the index is built, and its library is missing
    run()
    assert "!! job 1 stopped: library 'Movies' not found" in capsys.readouterr().out
    assert job_record(cfg)["ok"] is False


def test_sigterm_during_a_job_stops_between_collections(make_cfg, monkeypatch, capsys):
    cfg, srv, run = scheduler(make_cfg, monkeypatch)
    real = srv.call

    def create_then_stop(method, path, **kw):
        r = real(method, path, **kw)
        if method == "POST" and path.startswith("/Collections?"):
            os.kill(os.getpid(), signal.SIGTERM)   # docker stop, part way through the job
        return r
    srv.call = create_then_stop
    before = signal.getsignal(signal.SIGTERM)
    run()
    out = capsys.readouterr().out
    assert len(srv.collections) == 1 and "Stopped early: asked to stop" in out and "Scheduler stopped." in out
    assert job_record(cfg)["ok"] is False and signal.getsignal(signal.SIGTERM) is before


@pytest.mark.skipif(not hasattr(signal, "SIGTERM") or os.name == "nt", reason="needs SIGTERM")
def test_docker_stop_stops_the_scheduler_cleanly(tmp_path):
    """Python is PID 1 in the container, where SIGTERM is ignored unless something handles it."""
    (tmp_path / "config.yml").write_text('server: {type: emby, url: "http://127.0.0.1:9", api_key: "test-key"}\n'
                                         "libraries: [{name: Movies, type: movie}]\n")
    save_json(str(tmp_path / "data" / "schedule.json"),
              {cli.job_name(job): {"at": time.time(), "ok": True} for job in cli.DEFAULT_SCHEDULE})
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    for name in ("CINESETS_URL", "CINESETS_API_KEY", "CINESETS_SERVER", "CINESETS_CONFIG"):
        env.pop(name, None)
    proc = subprocess.Popen([sys.executable, "-m", "cinesets", "schedule", "--config", str(tmp_path / "config.yml")],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(20):                      # past any warnings Python prints first
            line = proc.stdout.readline()
            if "scheduler:" in line or not line:
                break
        assert "scheduler: 3 jobs" in line
        time.sleep(0.5)
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=20)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0 and "Scheduler stopped." in out and "---" not in out


def test_an_unknown_job_setting_is_noted(make_cfg, monkeypatch, capsys):
    cfg, srv, run = scheduler(make_cfg, monkeypatch)
    cfg["schedule"] = [{"every_hours": 168, "grop": "charts"}]
    save_json(os.path.join(cfg.path("data_dir"), "schedule.json"),
              {cli.job_name(cfg["schedule"][0]): {"at": time.time(), "ok": True}})
    run()
    assert "doesn't know grop" in capsys.readouterr().out


# ---------------------------------------------------------------- settings files that don't load
@pytest.mark.parametrize("text", ["server: [unclosed\n", "- just\n- a list\n", "plain words\n"])
def test_the_scheduler_keeps_the_settings_from_before_when_config_breaks(make_cfg, capsys, text):
    cfg = make_cfg()
    path = os.path.join(cfg["base_dir"], "config.yml")
    with open(path, "w") as f:
        f.write(text)
    kept, same = cli.reload(path, cfg, "engine")
    assert kept is cfg and same == "engine" and "settings from before" in capsys.readouterr().out


@pytest.mark.parametrize("text, words", [("server: [unclosed\n", "isn't valid YAML"),
                                         ("- just\n- a list\n", "should hold settings like `server:`")])
def test_a_broken_config_gets_a_message_not_a_traceback(tmp_path, monkeypatch, text, words):
    (tmp_path / "config.yml").write_text(text)
    monkeypatch.setattr("sys.argv", ["cinesets", "plan", "--config", str(tmp_path / "config.yml")])
    with pytest.raises(SystemExit, match=words):
        cli.main()


def test_a_broken_custom_collections_file_gets_a_message(make_cfg, monkeypatch):
    cfg = make_cfg()
    with open(cfg.path("custom_collections"), "w") as f:
        f.write("collections:\n  - {key: m-x, title: [oops\n")
    monkeypatch.setattr("sys.argv", ["cinesets", "list", "--config", os.path.join(cfg["base_dir"], "config.yml")])
    with pytest.raises(SystemExit, match="A collections file isn't valid YAML"):
        cli.main()


def test_unknown_settings_are_noted_but_never_stop_anything(make_cfg, capsys):
    config._warned.clear()
    cfg = make_cfg(extra="colections: {sections: [charts]}\nweb: {prot: 9000}\nlimits: {sections: {genres: 40}}\n"
                         "schedule: [{every_hours: 6, all: true}]\n")
    out = capsys.readouterr().out
    assert "doesn't know the setting `colections`, so it is ignored (did you mean `collections`?)" in out
    assert "`web.prot`" in out and "(did you mean `web.port`?)" in out
    assert "limits" not in out and "schedule" not in out and "posters" not in out
    assert cfg["collections"]["sections"] == "all" and cfg["limits"]["sections"] == {"genres": 40}
    make_cfg(extra="colections: {sections: [charts]}\n")
    assert "colections" not in capsys.readouterr().out     # once per run of CineSets, not on every load


def test_every_setting_in_the_example_is_known(capsys):
    config._warned.clear()
    config.load(os.path.join(ROOT, "config.example.yml"))
    assert "doesn't know" not in capsys.readouterr().out
