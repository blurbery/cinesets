# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The dashboard's run log, run results, small previews, list checks and collection names, as the page uses them."""
import io
import os
import re
import sys
import time

from PIL import Image

from cinesets import web
from test_web import ROOT, site  # noqa: F401 (site is the signed-in dashboard fixture)


def wait_for_run(call, since=0):
    for _ in range(100):
        status = call(f"/api/run?since={since}")[1]
        if not status["running"]:
            return status
        time.sleep(0.05)
    raise AssertionError("the run didn't finish")


def fake_run(app, monkeypatch, script):
    monkeypatch.setattr(app, "run_command", lambda command: [sys.executable, "-c", script])


# ---------------------------------------------------------------- the run log and how the run went
def test_the_log_keeps_growing_past_the_lines_kept(site, monkeypatch):
    call, cfg, srv, app, client = site
    fake_run(app, monkeypatch, "for i in range(1, 701): print(f'line {i}')")
    assert call("/api/run", {"command": "apply"})[1] == {"started": True}
    status = wait_for_run(call)
    assert status["total"] == 700 and len(status["lines"]) == 500 and status["skipped"] == 200
    assert status["lines"][0] == "line 201" and status["lines"][-1] == "line 700" and status["exit"] == 0
    later = call("/api/run?since=650")[1]                                 # only what the page doesn't have yet
    assert later["lines"] == [f"line {i}" for i in range(651, 701)] and later["skipped"] == 0
    assert later["run"] == status["run"] and later["total"] == 700
    assert call("/api/run?since=700")[1]["lines"] == []
    assert call("/api/run?since=nine")[0] == 400
    old = call("/api/run")[1]                                             # without since: the reply as it always was
    assert set(old) == {"running", "command", "lines", "exit"} and len(old["lines"]) == 500


def test_problems_the_summary_and_stopping_early_are_reported(site, monkeypatch):
    call, cfg, srv, app, client = site
    fake_run(app, monkeypatch, "import sys; print('m-a  list 10'); print('!! m-b: the list is gone'); "
                               "print('!! m-c: poster failed: no art'); print('Stopped early: the server is slow'); "
                               "print('Summary: 3 created, 40 updated, 1 failed'); sys.exit(1)")
    call("/api/run", {"command": "apply"})
    status = wait_for_run(call)
    assert status["problems"] == 2 and status["summary"] == "3 created, 40 updated, 1 failed"
    assert status["stopped"] == "the server is slow" and status["exit"] == 1
    first = status["run"]
    fake_run(app, monkeypatch, "print('Summary: nothing to do')")
    call("/api/run", {"command": "plan"})
    status = wait_for_run(call, since=5)                                 # a new run: a new id, and its own lines
    assert status["run"] != first and status["problems"] == 0 and status["stopped"] is None
    assert status["summary"] == "nothing to do" and status["total"] == 1 and status["command"] == "plan"


def test_a_fresh_dashboard_has_no_run(site):
    status = site[0]("/api/run?since=12")[1]
    assert status["run"] is None and status["total"] == 0 and status["lines"] == [] and status["exit"] is None


# ---------------------------------------------------------------- previews and the list check
def test_small_previews_are_plain_pictures(site):
    call = site[0]
    status, data, headers = call("/api/preview", {"key": "m-bttf", "posters": {}, "size": "small"}, raw=True)
    assert status == 200 and headers["Content-Type"] == "image/jpeg"
    assert Image.open(io.BytesIO(data)).size == web.TILE == (300, 450)
    assert call("/api/preview", {"key": "m-bttf", "posters": {}, "size": "huge"})[0] == 400
    assert "layout" in call("/api/preview", {"key": "m-bttf", "posters": {}, "size": "full"})[1]


def test_info_gives_the_smallest_collection_a_run_makes(site):
    assert site[0]("/api/info")[1]["min_items"] == 2                     # from defaults: {min_items: 2} in config.yml


# ---------------------------------------------------------------- two collections can't share a name
def test_words_that_would_copy_another_collections_name_are_refused(site):
    call, cfg, srv, app, client = site
    path = cfg.path("custom_collections")
    status, out = call("/api/text", {"key": "m-bttf", "title": "Netflix"})   # Movies - Netflix is m-netflix's name
    assert status == 400 and "'Movies - Netflix' (m-netflix)" in out["error"]
    status, out = call("/api/text", {"key": "m-bttf", "title": "NETFLIX"})   # case doesn't make it different
    assert status == 400 and not os.path.exists(path)                       # and nothing was written
    assert call("/api/text", {"key": "m-bttf", "title": "Back to\nthe Future"})[0] == 200   # its own name is fine
    assert call("/api/text", {"key": "m-bttf", "title": "Back to the Future", "subtitle": "Trilogy"})[0] == 200
    before = open(path).read()
    assert call("/api/text", {"key": "m-netflix", "label": "Movies", "title": "Back to the Future",
                              "subtitle": "Trilogy"})[0] == 400
    assert open(path).read() == before                                      # the file is put back as it was
    names = {c["key"]: c["name"] for s in call("/api/collections")[1]["sections"] for c in s["collections"]}
    assert names == {"m-bttf": "Movies - Back to the Future Trilogy", "m-netflix": "Movies - Netflix"}


# ---------------------------------------------------------------- the page itself
def static(name):
    with open(os.path.join(ROOT, "cinesets", "static", name), encoding="utf-8") as f:
        return f.read()


def test_the_page_keeps_to_its_rules():
    page, script, css = static("index.html"), static("app.js"), static("app.css")
    assert " style=" not in page and "<script>" not in page                 # the CSP allows no inline style or script
    ids = re.findall(r'id="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    for name in re.findall(r'\$\("([a-z0-9-]+)"\)', script):                # every element the script looks up exists
        assert name in ids, name
    assert "\u2014" not in page + script + css                              # no em dashes
    assert 'api("api/run?since=' in script and 'body.size = "small"' in script