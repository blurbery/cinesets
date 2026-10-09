# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The Japanese, Chinese and Korean font: downloading it when it's first needed (from a fake GitHub, never the real
one), drawing that text in it, and leaving every other poster exactly as it was."""
import hashlib
import json
import os
import re
import threading
import time
import types

import pytest
import requests

from cinesets import __version__, catalog, cli, fonts, posters, web
from cinesets.engine import Engine
from cinesets.store import load_json
from conftest import FakeServer, seed_index

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTO = os.path.join(ROOT, "assets", "fonts", posters.FALLBACK)
GREEK, CYRILLIC, VIETNAMESE = "Ωμέγα", "Москва", "Người Phán Xử"


class Reply:
    """One file from GitHub, streamed in pieces; `cut` breaks the connection after the first piece."""

    def __init__(self, data, cut=False):
        self.data, self.cut = data, cut
        self.status_code = 200 if data is not None else 404
        self.ok = data is not None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, size):
        for i in range(0, len(self.data), size):
            yield self.data[i:i + size]
            if self.cut:
                raise requests.ConnectionError("cut off")


class GitHub:
    """raw.githubusercontent.com as the download sees it: each file's bytes, a broken connection, or a wait first."""

    def __init__(self, files=None, fail=None, cut=False, gate=None):
        self.headers, self.asked = {}, []
        self.files, self.fail, self.cut, self.gate = dict(files or {}), fail, cut, gate

    def get(self, url, stream=False, timeout=None):
        self.asked.append((url, stream, timeout))
        if self.gate:
            self.gate.wait(10)
        if self.fail:
            raise self.fail
        return Reply(self.files.get(url.rsplit("/", 1)[1]), self.cut)


def use(monkeypatch, hub):
    """Send the font's downloads to `hub`, and only the font's: requests itself is left alone."""
    fake = types.SimpleNamespace(Session=lambda: hub, RequestException=requests.RequestException,
                                 __version__=requests.__version__)
    monkeypatch.setattr(fonts, "requests", fake)
    return hub


@pytest.fixture(autouse=True)
def on_its_own(monkeypatch):
    """No font in use, no failures remembered and no real downloads: GitHub that refuses unless a test fakes it."""
    monkeypatch.setitem(fonts._where, "folder", None)
    monkeypatch.setattr(fonts, "_failed", {})
    monkeypatch.setattr(fonts, "_busy", set())
    use(monkeypatch, GitHub(fail=AssertionError("the test tried to download from GitHub")))
    posters._font.cache_clear()
    yield
    posters._font.cache_clear()


def stand_in(monkeypatch):
    """Noto Sans CJK, played by Noto Sans: its files' bytes as the CJK files (FILES pinned to them), one face in each,
    and said to draw every character, so text offered to it wrongly would move to it and show up."""
    data = {fonts.BOLD: open(os.path.join(NOTO, "NotoSans-SemiBold.ttf"), "rb").read(),
            fonts.REGULAR: open(os.path.join(NOTO, "NotoSans-Regular.ttf"), "rb").read()}
    monkeypatch.setattr(fonts, "FILES", {n: (hashlib.sha256(d).hexdigest(), len(d)) for n, d in data.items()})
    monkeypatch.setattr(posters, "CJK", {k: v[:5] + (0,) for k, v in posters.CJK.items()})
    real = posters._missing
    monkeypatch.setattr(posters, "_missing", lambda face, text: set() if face in posters.CJK else real(face, text))
    posters._font.cache_clear()
    return data


def put(folder, data):
    os.makedirs(folder, exist_ok=True)
    for name, content in data.items():
        with open(os.path.join(folder, name), "wb") as f:
            f.write(content)


# ---------------------------------------------------------------- what's downloaded
def test_the_font_is_pinned_to_one_commit_and_each_face_is_where_the_files_have_it():
    assert re.fullmatch(r"[0-9a-f]{40}", fonts.COMMIT)
    assert fonts.SOURCE == f"https://raw.githubusercontent.com/notofonts/noto-cjk/{fonts.COMMIT}/Sans/OTC/"
    assert set(fonts.FILES) == {"NotoSansCJK-Bold.ttc", "NotoSansCJK-Regular.ttc"}
    for sha, size in fonts.FILES.values():
        assert re.fullmatch(r"[0-9a-f]{64}", sha) and 18 << 20 < size < 20 << 20
    # read from the files themselves: 0 JP, 1 KR, 2 SC (then TC, HK and the monospaced ones)
    assert {k: (v[0], v[5]) for k, v in posters.CJK.items()} == {
        "noto-sans-cjk-jp": ("Noto Sans CJK JP", 0), "noto-sans-cjk-kr": ("Noto Sans CJK KR", 1),
        "noto-sans-cjk-sc": ("Noto Sans CJK SC", 2)}
    assert all(v[1:3] == (fonts.BOLD, fonts.REGULAR) for v in posters.CJK.values())   # Bold for SemiBold, as Poppins
    assert posters.CJK_DEFAULT == "noto-sans-cjk-sc"
    assert not set(posters.CJK) & (set(posters.FACES) | set(posters.CHOICES["font"]))  # never a choice
    with open(os.path.join(ROOT, "NOTICE")) as f:
        notice = " ".join(f.read().split())
    assert "Noto Sans CJK" in notice and "not included" in notice and "github.com/notofonts/noto-cjk" in notice


def test_which_text_needs_it():
    for text in ("千と千尋", "カタカナ", "ひらがな", "기생충", "卧虎藏龙", "臥虎藏龍", "\U00020b9f", "ﾊﾟﾗｻｲﾄ"):
        assert fonts.wanted("Movies", text), text
    for text in ("Back to the Future", GREEK, CYRILLIC, VIETNAMESE, "Stars ★", "「」", "ＡＢＣ", "Shōgun", "", None):
        assert not fonts.wanted(text), text


def test_the_font_downloads_once_checked_and_swapped_in_whole(tmp_path, monkeypatch, capsys):
    data = {fonts.BOLD: b"bold " * 300_000, fonts.REGULAR: b"regular " * 200_000}
    monkeypatch.setattr(fonts, "FILES", {n: (hashlib.sha256(d).hexdigest(), len(d)) for n, d in data.items()})
    hub = use(monkeypatch, GitHub(data))
    folder = str(tmp_path / "fonts")
    fonts.download(folder)
    assert sorted(os.listdir(folder)) == sorted(data) and fonts.ready(folder)      # nothing half written left behind
    assert all(open(os.path.join(folder, n), "rb").read() == d for n, d in data.items())
    assert [(url, stream) for url, stream, _ in hub.asked] == [(fonts.SOURCE + n, True) for n in fonts.FILES]
    assert all(timeout for _, _, timeout in hub.asked)
    agent = hub.headers["User-Agent"]
    assert agent.startswith(f"CineSets/{__version__} (") and "https://github.com/blurbery/cinesets" in agent
    assert "Downloading the Japanese, Chinese and Korean font" in capsys.readouterr().out
    fonts.download(folder)                                                          # once: it's there now
    assert len(hub.asked) == 2 and "already downloaded" in capsys.readouterr().out
    fonts.download(folder, force=True)
    assert len(hub.asked) == 4


@pytest.mark.parametrize("hub, words", [
    (GitHub({fonts.BOLD: b"not the font", fonts.REGULAR: b"not the font"}), "SHA-256"),
    (GitHub({fonts.BOLD: b"x" * 5000, fonts.REGULAR: b"x" * 5000}), "bigger"),
    (GitHub({fonts.BOLD: b"x" * 3000, fonts.REGULAR: b"x" * 3000}, cut=True), "ConnectionError"),
    (GitHub({}), "404"),
    (GitHub(fail=requests.Timeout("slow")), "Timeout"),
])
def test_a_font_that_is_cut_off_or_not_the_right_file_is_never_used(tmp_path, monkeypatch, hub, words):
    monkeypatch.setattr(fonts, "FILES", {fonts.BOLD: ("0" * 64, 4000), fonts.REGULAR: ("0" * 64, 4000)})
    use(monkeypatch, hub)
    folder = str(tmp_path / "fonts")
    with pytest.raises(fonts.FontError, match=words):
        fonts.download(folder)
    assert os.listdir(folder) == [] and not fonts.ready(folder)


def test_a_download_that_takes_too_long_is_given_up(tmp_path, monkeypatch):
    data = {fonts.BOLD: b"bold " * 1000, fonts.REGULAR: b"regular " * 1000}
    monkeypatch.setattr(fonts, "FILES", {n: (hashlib.sha256(d).hexdigest(), len(d)) for n, d in data.items()})
    monkeypatch.setattr(fonts, "MOST_SECONDS", -1)                                    # both files share one deadline
    use(monkeypatch, GitHub(data))
    with pytest.raises(fonts.FontError, match="minutes"):
        fonts.download(str(tmp_path))
    assert os.listdir(tmp_path) == []


def test_a_file_already_downloaded_is_kept_when_the_other_fails(tmp_path, monkeypatch):
    good = b"bold " * 1000
    monkeypatch.setattr(fonts, "FILES", {fonts.BOLD: (hashlib.sha256(good).hexdigest(), len(good)),
                                         fonts.REGULAR: ("0" * 64, 5000)})
    hub = use(monkeypatch, GitHub({fonts.BOLD: good, fonts.REGULAR: b"y" * 5000}))
    folder = str(tmp_path / "fonts")
    with pytest.raises(fonts.FontError):
        fonts.download(folder)
    assert os.listdir(folder) == [fonts.BOLD] and not fonts.ready(folder)
    with pytest.raises(fonts.FontError):
        fonts.download(folder)
    assert hub.asked[-1][0].endswith(fonts.REGULAR) and len(hub.asked) == 3          # only the one it still needs


def test_a_failed_download_is_said_once_and_tried_again_later(tmp_path, monkeypatch, capsys):
    hub = use(monkeypatch, GitHub(fail=requests.ConnectionError("no route")))
    folder = str(tmp_path / "fonts")
    assert fonts.ensure(folder) is False
    out = capsys.readouterr().out
    assert out.count("!! Couldn't download the Japanese, Chinese and Korean font") == 1 and "cinesets fonts" in out
    assert fonts.ensure(folder) is False and fonts.ensure(folder) is False
    assert len(hub.asked) == 1 and capsys.readouterr().out == ""                     # not again within the hour
    assert fonts.state(folder)[0] == "failed" and "ConnectionError" in fonts.state(folder)[1]
    assert fonts.ensure(folder, again=True) is False and len(hub.asked) == 2          # a run tries each time
    when, why = fonts._failed[folder]
    fonts._failed[folder] = (when - fonts.RETRY_AFTER - 1, why)                       # an hour on
    assert fonts.ensure(folder) is False and len(hub.asked) == 3


# ---------------------------------------------------------------- drawing with it
def test_without_the_font_the_text_comes_out_as_before(tmp_path):
    fonts.use(str(tmp_path / "fonts"))                                                # nothing downloaded there
    assert posters._with_font({"font": "rye"}, "Movies", "千と千尋")["font"] == "poppins"
    assert posters._with_font({"font": "poppins"}, "Movies", "Ωμέγα 千")["font"] == posters.FALLBACK
    assert posters.text_fixes("Movies", "千と千尋") == []


def test_japanese_chinese_and_korean_text_is_drawn_in_noto_sans_cjk(tmp_path, monkeypatch):
    put(str(tmp_path / "fonts"), stand_in(monkeypatch))
    fonts.use(str(tmp_path / "fonts"))
    face = lambda *texts, **style: posters._with_font({"font": "rye", **style}, *texts)["font"]
    assert face("Movies", "千と千尋の神隠し") == "noto-sans-cjk-jp"                   # kana: Japanese
    assert face("TV Shows", "기생충") == "noto-sans-cjk-kr"                           # hangul: Korean
    assert face("Movies", "卧虎藏龙") == face("映画", "東京物語") == posters.CJK_DEFAULT  # Han alone
    assert face("Movies", "Studio Ghibli\nスタジオジブリ", "Collection") == "noto-sans-cjk-jp"  # all of it, label too
    assert face("映画", "東京物語", "コレクション") == "noto-sans-cjk-jp"              # the poster's text as a whole
    assert face("Movies", "千と千尋", case="upper") == "noto-sans-cjk-jp"
    assert face("Movies", "Ωμέγα 千") == "noto-sans-cjk-sc"                          # fewer boxes than Noto Sans
    assert posters.text_fixes("Movies", "千と千尋") == ["cjk"]                         # so it's drawn again
    img, layout = posters.poster_image("Movies", "千と千尋の神隠し", "スタジオジブリ", "purple")
    assert img.size == (posters.W, posters.H) and layout["title"]


def test_posters_without_japanese_chinese_or_korean_text_draw_byte_identically(tmp_path, monkeypatch):
    samples = [("Movies", "Back to\nthe Future", "Saga", {"font": f}) for f in ("poppins", "rye", "bebas-neue")]
    samples += [(label, text, sub, {"font": f, "case": case}) for label, text, sub in (
        ("TV Shows", GREEK, "Σειρά"), ("Movies", CYRILLIC, "Фильмы"), ("TV Shows", VIETNAMESE, None),
        ("Movies", "Stars ★", "Collection"), ("Movies", "Ωμέγα ★", None), ("Movies", "Shōgun", None),
        ("Movies", "The Lord of the Rings The Return of the King Extended Edition", None),   # wrapped at a space
        ("Movies", "Supercalifragilisticexpialidociousnessesque", "Saga"))                   # squeezed and cut
        for f, case in (("poppins", "normal"), ("creepster", "upper"))]

    def draw_all():
        out = []
        for label, title, sub, raw in samples:
            style = posters.check_style(raw)
            img, layout = posters.poster_image(label, title, sub, "red", None, style)
            out.append((img.tobytes(), layout, posters.text_fixes(label, title, sub, style)))
            logo = posters.logo_poster_image(label, "netflix", str(tmp_path), sub or "Popular", None, title, style)
            out.append((logo[0].tobytes(), logo[1], posters.text_fixes(label, title, sub or "Popular", style, False)))
        return out
    before = draw_all()                                                               # no font, as today
    put(str(tmp_path / "fonts"), stand_in(monkeypatch))
    fonts.use(str(tmp_path / "fonts"))
    assert fonts.ready() and posters._with_font({}, "Movies", "千と千尋")["font"] in posters.CJK
    assert draw_all() == before                                                       # and with it, to the byte


# ---------------------------------------------------------------- long titles: wrapped between characters
LONG_JP = "ハリーポッターとアズカバンの囚人と炎のゴブレットと謎のプリンス"   # no spaces
LONG_KR = "반지의 제왕 반지 원정대 확장판 특별 편집본 감독판 리마스터"        # Korean is written with spaces


def with_cjk(tmp_path, monkeypatch):
    put(str(tmp_path / "fonts"), stand_in(monkeypatch))
    fonts.use(str(tmp_path / "fonts"))


def test_a_long_japanese_title_wraps_onto_two_lines_inside_the_poster(tmp_path, monkeypatch):
    with_cjk(tmp_path, monkeypatch)
    style = posters._with_font(posters.STYLE, "Movies", LONG_JP)
    assert style["font"] == "noto-sans-cjk-jp"
    tf, lines, _, _ = posters._title_text(style, LONG_JP, None)
    assert len(lines) == 2 and "".join(lines) == LONG_JP                              # nothing cut off
    assert abs(len(lines[0]) - len(lines[1])) <= 2                                    # the most even split
    assert tf.size > posters.SMALLEST["title"] and all(tf.getbbox(t)[2] <= posters.W - 2 * posters.PAD for t in lines)
    left, top, right, bottom = posters.poster_image("Movies", LONG_JP, None, "purple")[1]["title"]
    assert 0 <= left < right <= 1 and 0 <= top < bottom <= 1
    assert posters.text_fixes("Movies", LONG_JP) == ["cjk", "fits"]


@pytest.mark.parametrize("title", [
    "あいうえおかきくけこーさしすせそたちつてと",       # the even split would start a line with ー
    "あいうえおかきくけこ。さしすせそたちつてと",       # or with 。
    "あいうえおかきくけこっさしすせそたちつてと",       # or with a small kana
    "あいうえおかきくけこ」」さしすせそたちつてと",     # or with either closing bracket
    "あいうえおかきくけ「こさしすせそたちつてと",       # or end one with 「
])
def test_lines_never_start_with_closing_punctuation_or_end_with_an_opening_bracket(tmp_path, monkeypatch, title):
    with_cjk(tmp_path, monkeypatch)
    lines = posters._wrap("noto-sans-cjk-jp", title, 100)
    assert len(lines) == 2 and "".join(lines) == title
    assert lines[1][0] not in posters.NO_START and lines[0][-1] not in posters.NO_END
    assert lines[1][0] not in "。ー」っ" and lines[0][-1] != "「"
    assert abs(len(lines[0]) - len(lines[1])) <= 3                                    # still close to even


def test_latin_letters_in_japanese_stay_together(tmp_path, monkeypatch):
    with_cjk(tmp_path, monkeypatch)
    lines = posters._wrap("noto-sans-cjk-jp", "あいうえおABCDEFGHIJKLMNかきくけこ", 100)
    assert len(lines) == 2 and any("ABCDEFGHIJKLMN" in line for line in lines)


def test_a_long_korean_title_still_breaks_at_a_space(tmp_path, monkeypatch):
    with_cjk(tmp_path, monkeypatch)
    style = posters._with_font(posters.STYLE, "TV Shows", LONG_KR)
    assert style["font"] == "noto-sans-cjk-kr"
    lines = posters._title_text(style, LONG_KR, None)[1]
    assert len(lines) == 2 and " ".join(lines) == LONG_KR                             # split where a space was


def test_without_the_font_long_titles_come_out_as_before(tmp_path):
    fonts.use(str(tmp_path / "fonts"))                                                # nothing downloaded there
    style = posters._with_font(posters.STYLE, "Movies", LONG_JP)
    assert style["font"] == "poppins" and posters._wrap("poppins", LONG_JP, 100) == [LONG_JP]
    assert len(posters._title_text(style, LONG_JP, None)[1]) == 1                     # one line of boxes, as before


# ---------------------------------------------------------------- runs: downloaded when first needed
YML = """collections:
  - key: m-spirited
    group: universes
    type: movie
    title: "千と千尋の神隠し"
    accent: purple
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
  - key: m-parasite
    group: universes
    type: movie
    title: "기생충"
    accent: green
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
  - key: m-bttf
    group: universes
    type: movie
    title: "Back to\\nthe Future"
    accent: blue
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
"""
ITEMS = {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie")}


def test_a_poster_drawn_before_the_font_arrived_is_drawn_again_with_it(make_cfg, monkeypatch, capsys):
    cfg = make_cfg("emby", YML)
    seed_index(cfg, ITEMS)
    srv = FakeServer("emby")
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    data = stand_in(monkeypatch)
    hub = use(monkeypatch, GitHub(fail=requests.ConnectionError("no route")))
    eng = Engine(cfg, srv)
    designs = lambda: {k: json.loads(v["design"]) for k, v in load_json(eng.state_file, {}).items()}
    uploads = lambda: len([c for c in srv.writes() if "/Images/" in c[1]])

    eng.run("apply", catalog.load(cfg), 2)                                            # GitHub can't be reached
    first = designs()
    out = capsys.readouterr().out
    assert uploads() == 3 and out.count("!! Couldn't download") == 1 and len(hub.asked) == 1  # once for the run
    assert not any(str(p).startswith("text:") for d in first.values() for p in d)     # drawn as before
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)                                            # the next run tries again, once
    assert uploads() == 0 and len(hub.asked) == 2 and capsys.readouterr().out.count("!! Couldn't download") == 1

    hub.fail, hub.files = None, data                                                  # and now it's there
    eng.run("apply", catalog.load(cfg), 2)
    now = designs()
    assert "Downloading the Japanese, Chinese and Korean font" in capsys.readouterr().out
    assert fonts.ready(eng.fonts) and sorted(os.listdir(eng.fonts)) == sorted(fonts.FILES)
    assert uploads() == 2 and now["m-bttf"] == first["m-bttf"]                         # only the two with that text
    assert now["m-spirited"][-1] == now["m-parasite"][-1] == "text:cjk"
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)
    assert uploads() == 0 and len(hub.asked) == 4                                     # downloaded once, kept


def test_the_fonts_command_downloads_it_ahead_of_time(make_cfg, monkeypatch, capsys):
    cfg = make_cfg("emby", YML)
    hub = use(monkeypatch, GitHub(stand_in(monkeypatch)))
    command = lambda *more: monkeypatch.setattr(
        "sys.argv", ["cinesets", "fonts", *more, "--config", os.path.join(cfg["base_dir"], "config.yml")]) or cli.main()
    folder = os.path.join(cfg.path("data_dir"), "fonts")
    command()
    assert fonts.ready(folder) and "Downloading" in capsys.readouterr().out
    command()
    assert len(hub.asked) == 2 and "already downloaded" in capsys.readouterr().out
    hub.fail = requests.ConnectionError("no route")
    with pytest.raises(SystemExit, match="Could not download the Japanese, Chinese and Korean font"):
        command("--force")
    assert fonts.ready(folder)                                                         # the copy it had is kept


# ---------------------------------------------------------------- the dashboard
def test_the_dashboard_starts_the_download_and_never_waits_for_it(make_cfg, monkeypatch):
    cfg = make_cfg("emby", YML, "defaults: {min_items: 2}\n")
    seed_index(cfg, ITEMS)
    srv = FakeServer("emby")
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    gate = threading.Event()
    hub = use(monkeypatch, GitHub(stand_in(monkeypatch), gate=gate))
    app = web.Dashboard(os.path.join(cfg["base_dir"], "config.yml"), server=srv)
    try:
        assert "font" not in app.preview({"key": "m-bttf"}) and hub.asked == []        # nothing to download for it
        assert app.preview({"key": "m-spirited", "size": "small"})[0] == "image/jpeg" and hub.asked == []
        began = time.monotonic()
        res = app.preview({"key": "m-spirited"})                                       # GitHub is slow today
        assert time.monotonic() - began < 5 and res["font"] == "downloading" and res["image"]
        assert web.ROUTES[("GET", "/api/font")](app, {}, {}) == {"font": "downloading", "message": None}
        assert app.preview({"key": "m-parasite"})["font"] == "downloading"
        gate.set()
        for _ in range(100):
            if app.font()["font"] != "downloading":
                break
            time.sleep(0.05)
        assert app.font() == {"font": "ready", "message": None} and len(hub.asked) == 2  # downloaded once
        assert "font" not in app.preview({"key": "m-spirited"})
        assert posters._with_font(posters.STYLE, "Movies", "千と千尋の神隠し")["font"] == "noto-sans-cjk-jp"
    finally:
        gate.set()
        app.close()


def test_the_dashboard_says_when_the_download_failed(make_cfg, monkeypatch):
    cfg = make_cfg("emby", YML, "defaults: {min_items: 2}\n")
    seed_index(cfg, ITEMS)
    srv = FakeServer("emby")
    for iid, (name, _, _) in ITEMS.items():
        srv.add_item(iid, name)
    hub = use(monkeypatch, GitHub(fail=requests.ConnectionError("no route")))
    app = web.Dashboard(os.path.join(cfg["base_dir"], "config.yml"), server=srv)
    try:
        assert app.preview({"key": "m-spirited"})["font"] == "downloading"
        for _ in range(100):
            if app.font()["font"] != "downloading":
                break
            time.sleep(0.05)
        status = app.font()
        assert status["font"] == "failed" and "Japanese, Chinese and Korean font" in status["message"]
        assert app.preview({"key": "m-spirited"})["font"] == "failed" and len(hub.asked) == 1  # not again for an hour
    finally:
        app.close()


def test_the_demo_never_downloads_it():
    app = web.Dashboard(demo=True)
    try:
        res = app.preview({"key": "m-action", "text": {"title": "千と千尋の神隠し"}})
        assert res["image"] and "font" not in res and app.font() == {"font": "missing", "message": None}
    finally:
        app.close()
