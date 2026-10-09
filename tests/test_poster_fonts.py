# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Poster fonts: Noto Sans for the letters the fonts don't have, and fonts kept once loaded."""
import os

from PIL import ImageFont

from cinesets import posters

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GREEK, CYRILLIC, VIETNAMESE = "Ωμέγα", "Москва", "Người Phán Xử"


def test_noto_sans_ships_with_its_licence_but_is_not_a_choice():
    name, title_file, subtitle_file, size, leading = posters.FACES[posters.FALLBACK]
    folder = os.path.join(ROOT, "assets", "fonts", posters.FALLBACK)
    for file in (title_file, subtitle_file):
        ImageFont.truetype(os.path.join(folder, file), 40)
    with open(os.path.join(folder, "OFL.txt")) as f:
        licence = f.read()
    assert "SIL OPEN FONT LICENSE" in licence.upper() and "The Noto Project Authors" in licence
    with open(os.path.join(ROOT, "NOTICE")) as f:
        notice = " ".join(f.read().split())
    assert "Noto Sans (Copyright 2022 The Noto Project Authors)" in notice
    assert posters.FALLBACK not in posters.FONTS and posters.FALLBACK not in posters.CHOICES["font"]
    assert set(posters.FACES) == set(posters.FONTS) | {posters.FALLBACK}


def test_greek_cyrillic_and_vietnamese_are_drawn_in_noto_sans():
    for text in (GREEK, CYRILLIC, VIETNAMESE):
        assert not posters._draws("poppins", text) and posters._draws(posters.FALLBACK, text)
        for face in ("poppins", "rye", "bebas-neue"):
            assert posters._with_font({"font": face}, "TV Shows", text)["font"] == posters.FALLBACK
    assert posters._with_font({"font": "rye", "case": "upper"}, "Movies", "ω")["font"] == posters.FALLBACK  # Ω, upper


def test_the_fallback_only_moves_text_when_it_helps():
    assert posters._with_font({"font": "rye"}, "Movies", "Shōgun")["font"] == "poppins"            # Poppins has ō
    assert posters._with_font({"font": "poppins"}, "Movies", "Back to the Future") == {"font": "poppins"}
    assert posters._with_font({"font": "poppins"}, "Movies", "Stars ★")["font"] == "poppins"       # neither has ★
    assert posters._with_font({"font": "rye"}, "Movies", "千と千尋")["font"] == "poppins"           # nor Japanese, as before
    assert posters._with_font({"font": "poppins"}, "Movies", "Ωμέγα ★")["font"] == posters.FALLBACK  # fewer boxes


def test_a_greek_title_draws_letters_not_boxes():
    style = posters.check_style({"font": "rye"})
    greek = posters.poster_image("TV Shows", GREEK, None, "red", None, style)[0]
    noto = posters.poster_image("TV Shows", GREEK, None, "red", None, {**style, "font": posters.FALLBACK})[0]
    assert greek.tobytes() == noto.tobytes()


def test_fonts_are_kept_once_loaded(monkeypatch):
    posters._font.cache_clear()
    loaded = []
    real = ImageFont.truetype
    monkeypatch.setattr(ImageFont, "truetype", lambda *a, **k: loaded.append(a) or real(*a, **k))
    for _ in range(3):
        posters._fit("poppins", ["The Lord of the Rings Collection"], 150, 844)
    assert len(loaded) == len(set(loaded)) and posters._font("poppins", 60) is posters._font("poppins", 60)
