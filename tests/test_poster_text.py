# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Poster text: long text that stays on the poster, text that reads on bright artwork, and the artwork behind it."""
import io
import struct

import pytest
from PIL import Image, ImageChops, ImageDraw

from cinesets import posters, scenes

W, H, PAD = posters.W, posters.H, posters.PAD
MAX_W = W - 2 * PAD
SILVER = {"accent": "silver", "tint": "none", "label_colour": "white", "case": "upper"}


def old_fit(face, lines, start, max_w, subtitle=False):
    """How text was fitted before: down in steps of 4, never below 60."""
    size = start
    while size > 60:
        f = posters._font(face, size, subtitle)
        if all(f.getbbox(t)[2] <= max_w for t in lines):
            return f
        size -= 4
    return posters._font(face, 60, subtitle)


def art(tmp_path, name, colour=None, size=(1600, 900)):
    """Artwork saved to a file: one colour, or one of the made-up scenes."""
    path = tmp_path / f"{name}.png"
    (Image.new("RGB", size, colour) if colour else scenes.make(name, *size)).save(path)
    return str(path)


def inside(box, margin=0.0):
    return margin - 0.001 <= box[0] < box[2] <= 1 - margin + 0.001 and 0 <= box[1] < box[3] <= 1


# ---------------------------------------------------------------- long text
def test_a_long_title_goes_onto_two_lines_at_its_best_space():
    f, lines = posters._fit_title("poppins", ["The Lord of the Rings Collection"], 150, MAX_W)
    assert lines == ["The Lord of the", "Rings Collection"] and f.size > 60
    assert all(f.getbbox(t)[2] <= MAX_W for t in lines)
    assert old_fit("poppins", ["The Lord of the Rings Collection"], 150, MAX_W).getbbox("The Lord of the Rings Collection")[2] > MAX_W


def test_titles_that_fitted_before_come_out_the_same():
    titles = [["Back to", "the Future"], ["Marvel Universe"], ["Pirates of the Caribbean"], ["Movies - Netflix Popular"],
              ["Star Trek"], ["Kids Ages 3-8"], ["How to Train Your Dragon"]]
    for face in posters.FONTS:
        for case in (str, str.upper):
            for title in titles:
                lines = [case(t) for t in title]
                before = old_fit(face, lines, round(150 * posters.FONTS[face][3]), MAX_W)
                if all(before.getbbox(t)[2] <= MAX_W for t in lines):
                    f, now = posters._fit_title(face, lines, round(150 * posters.FONTS[face][3]), MAX_W)
                    assert (f.size, now) == (before.size, lines), (face, lines)


def test_text_that_cannot_shrink_enough_is_squeezed_then_cut_short():
    word = "Supercalifragilisticexpialidociousandthensomemoreletters"  # one word, no space to wrap at
    f, lines = posters._fit_title("poppins", [word], 150, MAX_W)
    assert lines == [word] and f.size < posters.SMALLEST["title"] and f.getbbox(word)[2] <= MAX_W
    f, lines = posters._fit_title("poppins", ["Lots of words " * 40], 150, MAX_W)
    assert len(lines) == 2 and lines[0].endswith("…") and all(f.getbbox(t)[2] <= MAX_W for t in lines)
    assert f.size == posters.TINY


@pytest.mark.parametrize("face", sorted(posters.FONTS))
def test_long_text_stays_inside_the_poster_in_every_font(face, tmp_path):
    title = "The Unbelievably Long Story of Everybody Who Came Along Too"     # 59 characters, the dashboard's most
    label, subtitle = "Movies Picked By The Whole Fam", "And Their Neighbours And Their Pets Too"  # 30 and 39
    for align in ("left", "centre"):
        for moved in (None, {"title_position": [0, 0.5], "label_position": [0, 0.1]},
                      {"title_position": [1, 0.95], "label_position": [1, 0], "title_size": 2, "label_size": 2}):
            raw = {"font": face, "align": align, "case": "upper", **(moved or {})}
            # the title wraps; with no spaces (only tried in the usual place) it can't, so it's squeezed
            for text in (title, title.replace(" ", "")) if not moved and align == "left" else (title,):
                _, layout = posters.poster_image(label, text, subtitle, "blue", None, posters.check_style(raw))
                margin = 0 if moved else PAD / W
                assert inside(layout["title"], margin) and inside(layout["label"], margin), (raw, text, layout)
    logo = posters.logo_poster_image(label, "netflix", str(tmp_path), subtitle, None, "Netflix", posters.check_style({"font": face}))
    assert inside(logo[1]["title"], PAD / W) and inside(logo[1]["label"], PAD / W)


def test_a_label_shrinks_to_fit_but_a_short_one_keeps_its_size():
    place = posters._label_place(posters.check_style({"case": "upper"}), "Movies Picked By The Whole Fam")
    assert place[1].size < 66 and place[1].getbbox(place[0])[2] <= MAX_W
    assert posters._label_place(posters.check_style({}), "TV Shows")[1].size == 66


LONG = """collections:
  - key: m-rings
    group: universes
    type: movie
    title: "The Lord of the Rings Collection"
    accent: gold
    min: 2
    titles:
      - ["Back to the Future", 1985]
      - ["Back to the Future Part II", 1989]
"""


def test_a_poster_whose_text_ran_off_is_drawn_again_once(make_cfg):
    from conftest import FakeServer, seed_index
    from cinesets import catalog
    from cinesets.engine import Engine
    from cinesets.store import load_json, save_json
    cfg = make_cfg("emby", LONG)
    seed_index(cfg, {"m1": ("Back to the Future", 1985, "movie"), "m2": ("Back to the Future Part II", 1989, "movie")})
    srv = FakeServer("emby")
    srv.add_item("m1", "Back to the Future")
    srv.add_item("m2", "Back to the Future Part II")
    eng = Engine(cfg, srv)
    uploads = lambda: [c for c in srv.writes() if "/Images/" in c[1]]
    eng.run("apply", catalog.load(cfg), 2)
    state = load_json(eng.state_file, {})
    assert state["m-rings"]["design"].endswith('"text:fits"]')
    # as an older version left it: its record, and its poster with the title running off
    state["m-rings"]["design"] = state["m-rings"]["design"].replace(', "text:fits"', "")
    state["m-rings"]["poster"] = "the old poster"
    save_json(eng.state_file, state)
    (coll,) = srv.collections.values()
    coll["image"] = b"the old poster"
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)
    assert uploads()                                                                  # drawn again, on the poster now
    srv.calls.clear()
    eng.run("apply", catalog.load(cfg), 2)
    assert not uploads()                                                              # and only once
    assert posters.text_fixes("Movies", "Back to\nthe Future", "Saga", posters.check_style({})) == []
    assert posters.text_fixes("TV Shows", "Ωμέγα", None, posters.check_style({})) == ["letters"]
    assert posters.text_fixes("TV Shows", "Stan", "Popular Right Now In Every Single Country", posters.check_style({}), True) == ["fits"]


# ---------------------------------------------------------------- text that reads on bright artwork
def line_contrast(img, box, colours):
    """Contrast between the text's dimmest colour and the artwork in the top strip of a box (its first line), taking
    the artwork as the level a quarter of the strip is darker than (the letters are the light part)."""
    left, top, right, bottom = box[0] * W, box[1] * H, box[2] * W, box[3] * H
    counts = img.crop((round(left), round(top), round(right), round(top + (bottom - top) * 0.3))).convert("L").histogram()
    seen, level = 0, 0
    for level, n in enumerate(counts):
        seen += n
        if seen >= sum(counts) / 4:
            break
    text = min(posters._luminance(c) for c in colours)
    return posters._contrast(text, posters._LINEAR[level])


def test_silver_text_on_white_artwork_is_darkened_behind_until_it_reads(tmp_path, monkeypatch):
    white = art(tmp_path, "white", (255, 255, 255))
    style = posters.check_style(SILVER)
    silver = posters.ACCENTS["silver"][:2]
    img, layout = posters.poster_image("Movies", "Back to\nthe Future", "Saga", "blue", white, style)
    assert line_contrast(img, layout["title"], silver) >= 2.8
    monkeypatch.setattr(posters, "_readable", lambda img, groups: ([c for _, c in groups], [False] * len(groups)))
    before, _ = posters.poster_image("Movies", "Back to\nthe Future", "Saga", "blue", white, style)
    assert line_contrast(before, layout["title"], silver) < 2.0                  # how it was: hard to read


def test_the_default_look_on_white_artwork_reads_too(tmp_path):
    img, layout = posters.poster_image("Movies", "Back to\nthe Future", None, "purple", art(tmp_path, "white", (255, 255, 255)))
    assert line_contrast(img, layout["title"], posters.ACCENTS["purple"][:2]) >= 2.8


def test_typical_artwork_looks_just_as_it_did(tmp_path, monkeypatch):
    looks = [{}, SILVER, {"title": "white", "align": "centre", "case": "upper", "label_colour": "white", "tint": "subtle"},
             {"shade": "dark", "tint": "strong", "subtitle_colour": "accent"}]
    pictures = [art(tmp_path, "desert", size=(960, 540)), art(tmp_path, "grey", (128, 128, 128))]
    cases = [(p, look, "purple") for p in pictures for look in looks]            # purple: the darkest accent
    draw = lambda p, look, accent: posters.poster_image("Movies", "Back to\nthe Future", "Saga", accent, p,
                                                        posters.check_style(look))[0].tobytes()
    now = [draw(*c) for c in cases]
    monkeypatch.setattr(posters, "_readable", lambda img, groups: ([c for _, c in groups], [False] * len(groups)))
    assert now == [draw(*c) for c in cases]


def test_a_near_black_accent_is_lightened_keeping_its_hue():
    import colorsys
    img = Image.new("RGB", (W, H), (20, 18, 30))
    line = ("Dark", posters._font("poppins", 150), PAD, 1100)
    (colours,), (helped,) = posters._readable(img, [([line], [(16, 16, 40)])])
    assert helped and posters._contrast(posters._luminance(colours[0]), posters._behind(img, (PAD, 1100, 400, 1260))) >= 3
    hue = lambda c: colorsys.rgb_to_hls(*(v / 255 for v in c))[0]
    assert abs(hue(colours[0]) - hue((16, 16, 40))) < 0.02
    assert posters._readable(img, [([line], [(255, 190, 40)])]) == ([[(255, 190, 40)]], [False])  # gold reads as it is


def test_the_shadow_comes_with_the_help_unless_it_is_switched_off(tmp_path, monkeypatch):
    white, grey = art(tmp_path, "white", (255, 255, 255)), art(tmp_path, "grey", (110, 110, 110))
    draw = lambda p, **raw: posters.poster_image("Movies", "Back to\nthe Future", "Saga", "blue", p,
                                                 posters.check_style({**SILVER, **raw}))[0]
    assert draw(white).tobytes() != draw(white, text_shadow="off").tobytes()     # auto: helped text gets a shadow
    assert draw(grey).tobytes() == draw(grey, text_shadow="off").tobytes()       # nothing to help, no shadow
    darkened = draw(white, text_shadow="off").getpixel((40, 960))[0]
    monkeypatch.setattr(posters, "_readable", lambda img, groups: ([c for _, c in groups], [False] * len(groups)))
    assert darkened < draw(white, text_shadow="off").getpixel((40, 960))[0] - 30  # off still darkens behind the text


def test_the_gradient_is_drawn_as_it_was():
    def old_gradient(base, xy, text, font, c1, c2):
        x, y = xy
        box = font.getbbox(text)
        dx, dy = min(0, box[0]), min(0, box[1])
        x, y = x + dx, y + dy
        mask = Image.new("L", (box[2] - dx + 8, box[3] - dy + 8), 0)
        ImageDraw.Draw(mask).text((-dx, -dy), text, font=font, fill=255)
        grad = Image.new("RGB", mask.size)
        px = grad.load()
        for i in range(mask.width):
            t = i / max(1, mask.width - 1)
            col = tuple(round(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
            for j in range(mask.height):
                px[i, j] = col
        base.paste(grad, (x, y), mask)

    for face, text, colours in (("poppins", "Back to", posters.ACCENTS["purple"][:2]), ("cinzel-decorative", "Nolan", ((1, 2, 3), (254, 128, 7))),
                                ("pacifico", "Jaws", posters.ACCENTS["silver"][:2]), ("bebas-neue", "I", posters.ACCENTS["ice"][:2])):
        before, now = Image.new("RGB", (900, 300), (9, 9, 9)), Image.new("RGB", (900, 300), (9, 9, 9))
        old_gradient(before, (100, 50), text, posters._font(face, 150), *colours)
        posters._gradient_text(now, (100, 50), text, posters._font(face, 150), *colours)
        assert max(hi for _, hi in ImageChops.difference(before, now).getextrema()) <= 1


# ---------------------------------------------------------------- the artwork behind the text
def test_odd_shaped_artwork_is_never_blown_up_whole(monkeypatch):
    asked = []
    real = Image.Image.resize
    monkeypatch.setattr(Image.Image, "resize", lambda self, size, *a, **k: asked.append(size) or real(self, size, *a, **k))
    for size in ((1920, 50), (50, 1920)):
        out = posters._cover(Image.new("RGB", size, (90, 120, 160)), W, H)
        assert out.size == (W, H)
    assert max(w * h for w, h in asked) <= posters.MOST_PIXELS * 1.01      # 1920x50 used to become 57,601x1,501


def test_tall_artwork_crops_as_it_did():
    img = Image.new("RGB", (100, 1000), (90, 120, 160))
    d = ImageDraw.Draw(img)
    for y in range(0, 1000, 23):
        d.line((0, y, 100, y + 40), fill=(250, 220, 90), width=3)
    scale = max(W / img.width, H / img.height)
    whole = img.resize((round(img.width * scale) + 1, round(img.height * scale) + 1), Image.LANCZOS)  # how it was done
    top = (whole.height - H) // 2
    before = whole.crop((0, top, W, top + H))
    assert max(hi for _, hi in ImageChops.difference(before, posters._cover(img, W, H)).getextrema()) <= 1


def test_artwork_is_turned_by_its_exif_orientation(tmp_path):
    img = Image.new("RGB", (300, 200), (0, 0, 255))
    img.paste((255, 0, 0), (0, 0, 150, 200))                      # left half red
    exif = Image.Exif()
    exif[0x0112] = 6                                               # shown turned a quarter clockwise
    path = tmp_path / "turned.jpg"
    img.save(path, exif=exif.tobytes())
    out = posters._artwork(str(path))
    assert out.size == (200, 300)
    assert out.getpixel((100, 20))[0] > 200 and out.getpixel((100, 280))[2] > 200   # red on top, blue below


def test_artwork_with_another_colour_profile_is_changed_into_srgb(tmp_path):
    ImageCms = pytest.importorskip("PIL.ImageCms")
    # a made-up profile: sRGB's, with its red and blue swapped, so its "red" is really blue
    data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    tags = {}
    for i in range(struct.unpack(">I", data[128:132])[0]):
        sig, offset, size = struct.unpack(">4sII", data[132 + i * 12:144 + i * 12])
        tags[sig] = (i, offset, size)
    (r, r_at, r_size), (b, b_at, b_size) = tags[b"rXYZ"], tags[b"bXYZ"]
    struct.pack_into(">4sII", data, 132 + r * 12, b"rXYZ", b_at, b_size)
    struct.pack_into(">4sII", data, 132 + b * 12, b"bXYZ", r_at, r_size)
    profile = bytes(data).replace("sRGB".encode("utf-16-be"), "Swap".encode("utf-16-be")).replace(b"sRGB", b"Swap")
    assert "srgb" not in ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(profile))).lower()
    path = tmp_path / "swapped.png"
    Image.new("RGB", (40, 30), (255, 0, 0)).save(path, icc_profile=profile)
    red, green, blue = posters._artwork(str(path)).getpixel((5, 5))
    assert blue > 200 and red < 60
    plain = tmp_path / "srgb.png"                                  # an sRGB profile changes nothing
    Image.new("RGB", (40, 30), (255, 0, 0)).save(plain, icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    assert posters._artwork(str(plain)).getpixel((5, 5)) == (255, 0, 0)
    broken = tmp_path / "broken.png"                               # nor does one that can't be read
    Image.new("RGB", (40, 30), (255, 0, 0)).save(broken, icc_profile=b"not a profile")
    assert posters._artwork(str(broken)).getpixel((5, 5)) == (255, 0, 0)
