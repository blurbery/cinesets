# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Streaming logos: downloading them, drawing them, and redrawing posters made before they were there."""
import io
import json
import os
import random

import pytest
import requests
from PIL import Image, ImageChops

from cinesets import __version__, catalog, logos, posters
from cinesets.engine import Engine
from cinesets.store import load_json
from conftest import FakeServer, seed_index


def png(colour=(229, 9, 20, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", (40, 12), colour).save(buf, "PNG")
    return buf.getvalue()


class Answer:
    def __init__(self, data=None, content=b"", status=200, kind="image/png"):
        self.data, self.content, self.status_code, self.ok = data, content, status, status < 400
        self.headers = {"Content-Type": kind}

    def json(self):
        return self.data


class Commons:
    """Wikimedia Commons as `cinesets logos` sees it: Disney+'s file renamed, Prime Video's with no PNG thumbnail,
    and Hulu's download cut off."""
    RENAMED = "File:Disney+ logo (2024).svg"

    def __init__(self):
        self.headers, self.asked = {}, []

    def get(self, url, params=None, timeout=None):
        self.asked.append((url, params))
        if params:
            tidied = "File:Disney+ Logo.svg"
            pages = {"1": {"title": logos.FILES["netflix"], "imageinfo": [{"thumburl": "https://img/netflix.png"}]},
                     "2": {"title": self.RENAMED, "imageinfo": [{"thumburl": "https://img/disney.png"}]},
                     "3": {"title": logos.FILES["prime"], "imageinfo": [{"url": "https://img/prime.svg"}]},
                     "4": {"title": logos.FILES["hulu"], "imageinfo": [{"thumburl": "https://img/hulu.png"}]},
                     "-1": {"title": logos.FILES["stan"], "missing": ""}}
            answer = {"normalized": [{"from": logos.FILES["disney"], "to": tidied}],
                      "redirects": [{"from": tidied, "to": self.RENAMED}], "pages": pages}
            return Answer({"query": answer if params.get("redirects") == 1 else {"pages": pages}})
        if "hulu" in url:
            raise requests.ConnectionError("cut off")
        return Answer(content=png())


def test_logos_follow_renamed_files_and_one_bad_answer_stops_nothing(tmp_path, monkeypatch, capsys):
    commons = Commons()
    monkeypatch.setattr(logos.requests, "Session", lambda: commons)
    logos.download(str(tmp_path))
    agent = commons.headers["User-Agent"]
    assert agent.startswith(f"CineSets/{__version__} (") and "https://github.com/blurbery/cinesets" in agent
    assert commons.asked[0][1]["redirects"] == 1
    assert sorted(os.listdir(tmp_path)) == ["disney.png", "netflix.png", logos.SOURCES]   # nothing half written
    out = capsys.readouterr().out
    assert "prime: not found" in out and "hulu: download failed (ConnectionError)" in out and "stan: not found" in out


def test_a_logo_is_swapped_in_whole_or_not_at_all(tmp_path, monkeypatch):
    path = tmp_path / "netflix.png"
    path.write_bytes(b"the logo from last time")
    with pytest.raises(TypeError):
        logos._save(str(path), object())                                           # fails while writing
    monkeypatch.setattr(logos.os, "replace", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        logos._save(str(path), png())                                              # stopped just before swapping
    assert path.read_bytes() == b"the logo from last time" and os.listdir(tmp_path) == ["netflix.png"]
    monkeypatch.undo()
    logos._save(str(path), png())
    assert path.read_bytes() == png() and os.listdir(tmp_path) == ["netflix.png"]
    plain = tmp_path / "plain.png"                                                 # the permissions any file gets
    plain.write_bytes(png())
    assert os.stat(path).st_mode & 0o777 == os.stat(plain).st_mode & 0o777


# ---------------------------------------------------------------- drawing the logo
def old_logo_image(path, key, white=False):
    """How a logo was loaded before: pixel by pixel."""
    logo = Image.open(path).convert("RGBA")
    px = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = px[x, y]
            if a and max(r, g, b) - min(r, g, b) < 40 and (r + g + b) / 3 < 140:
                px[x, y] = (255, 255, 255, a)
    box = logo.getbbox()
    logo = logo.crop(box) if box else logo
    if white:
        plain = Image.new("RGBA", logo.size, (255, 255, 255, 0))
        plain.putalpha(logo.split()[3])
        return plain
    if key in posters.LIGHT_ON_DARK:
        top, bottom = posters.LIGHT_ON_DARK[key]
        fill = Image.new("RGB", (1, logo.height))
        for y in range(logo.height):
            t = y / max(1, logo.height - 1)
            fill.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
        coloured = fill.resize(logo.size).convert("RGBA")
        coloured.putalpha(logo.split()[3])
        logo = coloured
    return logo


def test_logos_are_drawn_as_they_were_only_faster(tmp_path):
    rng = random.Random(7)
    # colours right on the edges: 39, 40 and 41 apart, averaging just under, on and over 140, see-through or not
    edges = [(r, g, b, a) for r in (0, 99, 139, 140, 141, 200) for g in (r, r + 39, r + 40, r + 41, max(0, r - 39))
             for b in (r, 139, 140, 141) for a in (0, 1, 128, 255) if g <= 255]
    edges += [(139, 140, 140, 255), (140, 140, 140, 255), (140, 140, 139, 255), (120, 159, 140, 9)]
    pixels = edges + [tuple(rng.randrange(256) for _ in range(3)) + (rng.choice((0, 1, 77, 255)),) for _ in range(8000)]
    img = Image.new("RGBA", (100, (len(pixels) + 99) // 100))
    img.putdata(pixels + [(0, 0, 0, 0)] * (img.width * img.height - len(pixels)))
    path = tmp_path / "logo.png"
    img.save(path)
    for key, white in (("netflix", False), ("disney", False), ("netflix", True)):
        before, now = old_logo_image(path, key, white), posters._logo_image(str(path), key, white)
        assert before.size == now.size and max(hi for _, hi in ImageChops.difference(before, now).getextrema()) <= 1


# ---------------------------------------------------------------- redrawing posters made before the logo was there
STREAMING = """collections:
  - key: m-netflix
    group: streaming
    type: movie
    title: "Netflix"
    subtitle: "Popular"
    accent: red
    logo: netflix
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
"""
ITEMS = {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie")}


def test_a_streaming_poster_is_redrawn_once_its_logo_is_downloaded(make_cfg):
    cfg = make_cfg("emby", STREAMING, "posters: {logo: icon}\n")
    seed_index(cfg, ITEMS)
    srv = FakeServer("emby")
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    eng = Engine(cfg, srv)
    design = lambda: json.loads(load_json(eng.state_file, {})["m-netflix"]["design"])
    uploads = lambda: [c for c in srv.writes() if "/Images/" in c[1]]

    eng.run("apply", catalog.load(cfg), 2)
    assert uploads() and not any(str(p).startswith("logo-file:") for p in design())  # no logo yet: the name
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)
    assert not uploads()                                                              # and it stays put
    os.makedirs(eng.logos, exist_ok=True)
    with open(os.path.join(eng.logos, "netflix.png"), "wb") as f:
        f.write(png())
    eng.run("apply", catalog.load(cfg), 2)
    assert uploads() and design()[-2].startswith("logo-file:netflix.png:")           # the logo, drawn at last
    srv.calls.clear()
    with open(os.path.join(eng.logos, "netflix--icon.png"), "wb") as f:              # the chosen version arrives
        f.write(png((0, 200, 0, 255)))
    eng.run("apply", catalog.load(cfg), 2)
    assert uploads() and design()[-2].startswith("logo-file:netflix--icon.png:")
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)
    assert not uploads()
