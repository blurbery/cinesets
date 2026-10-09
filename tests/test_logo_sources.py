# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""`cinesets logos` remembers which Commons file each logo came from, so a service's new logo reaches servers that
downloaded the old one, and logos that haven't changed aren't fetched again."""
import json
import os

from cinesets import logos
from test_logos import Answer, png


class Commons:
    """Every listed file is on Commons with a PNG thumbnail; notes which titles each run asked for."""

    def __init__(self, fail=()):
        self.headers, self.titles, self.fail = {}, [], set(fail)

    def get(self, url, params=None, timeout=None):
        if params:
            self.titles = params["titles"].split("|")
            pages = {str(n): {"title": t, "imageinfo": [{"thumburl": f"https://img/{n}.png"}]}
                     for n, t in enumerate(self.titles)}
            return Answer({"query": {"pages": pages}})
        n = int(url.rsplit("/", 1)[1][:-4])
        if self.titles[n] in self.fail:
            return Answer(status=503)
        return Answer(content=png())


def run(tmp_path, monkeypatch, commons):
    monkeypatch.setattr(logos.requests, "Session", lambda: commons)
    logos.download(str(tmp_path))
    return commons.titles


def every_logo():
    return {logos.file_name(k): t for k, t in logos.FILES.items()} | {
        logos.file_name(k, v): t for k, vs in logos.VARIANTS.items() for v, (_, t) in vs.items()}


def test_the_record_says_where_each_logo_came_from_and_nothing_is_fetched_twice(tmp_path, monkeypatch, capsys):
    asked = run(tmp_path, monkeypatch, Commons())
    assert sorted(asked) == sorted(every_logo().values())
    assert json.loads((tmp_path / logos.SOURCES).read_text()) == every_logo()
    asked = run(tmp_path, monkeypatch, Commons())
    assert asked == [] and "All logos already downloaded." in capsys.readouterr().out


def test_a_service_with_a_new_logo_is_fetched_again(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, Commons())
    record = json.loads((tmp_path / logos.SOURCES).read_text())
    record["peacock.png"] = "File:NBCUniversal Peacock Logo.svg"              # as a server from before the 2026 logo
    (tmp_path / logos.SOURCES).write_text(json.dumps(record))
    assert run(tmp_path, monkeypatch, Commons()) == [logos.FILES["peacock"]]
    assert json.loads((tmp_path / logos.SOURCES).read_text())["peacock.png"] == logos.FILES["peacock"]


def test_logos_from_before_the_record_are_fetched_once(tmp_path, monkeypatch):
    (tmp_path / "netflix.png").write_bytes(b"an old download")
    asked = run(tmp_path, monkeypatch, Commons())
    assert logos.FILES["netflix"] in asked and (tmp_path / "netflix.png").read_bytes() == png()
    assert run(tmp_path, monkeypatch, Commons()) == []


def test_a_failed_fetch_keeps_the_old_logo_and_tries_again_next_time(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, Commons())
    record = json.loads((tmp_path / logos.SOURCES).read_text())
    record["peacock.png"] = "File:NBCUniversal Peacock Logo.svg"
    (tmp_path / logos.SOURCES).write_text(json.dumps(record))
    (tmp_path / "peacock.png").write_bytes(b"the 2020 logo")
    run(tmp_path, monkeypatch, Commons(fail=[logos.FILES["peacock"]]))
    assert (tmp_path / "peacock.png").read_bytes() == b"the 2020 logo"
    assert run(tmp_path, monkeypatch, Commons()) == [logos.FILES["peacock"]]


def test_a_damaged_record_just_means_fetching_again(tmp_path, monkeypatch):
    (tmp_path / logos.SOURCES).write_text("[not a record")
    assert sorted(run(tmp_path, monkeypatch, Commons())) == sorted(every_logo().values())
    assert os.path.exists(tmp_path / "netflix.png")
