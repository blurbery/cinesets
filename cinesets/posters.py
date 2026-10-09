# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Collection posters: a gold section label, a big two-tone title bottom-left over the collection's own
artwork, or a streaming service logo for service collections. The `posters` settings in config.yml change the
colours, shading, text and font; at their defaults every poster comes out exactly as it always has."""
import colorsys
import functools
import io
import math
import os
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import fonts
from .config import ROOT

try:  # colour profiles: part of nearly every Pillow, but a build can leave them out
    from PIL import ImageCms
except ImportError:  # pragma: no cover
    ImageCms = None

FONT_DIR = os.path.join(ROOT, "assets", "fonts")
# fonts for the poster text, each in assets/fonts/<key> with its licence (all SIL Open Font License 1.1):
# key -> (name, file for the label and title, file for the subtitle, size, line height). Size evens out how big each
# font looks next to Poppins; line height is the step from one line to the next, in font sizes.
FONTS = {
    "poppins": ("Poppins", "Poppins-SemiBold.ttf", "Poppins-Regular.ttf", 1.0, 1.12),
    "bebas-neue": ("Bebas Neue", "BebasNeue-Regular.ttf", "BebasNeue-Regular.ttf", 1.2, 0.95),
    "abril-fatface": ("Abril Fatface", "AbrilFatface-Regular.ttf", "AbrilFatface-Regular.ttf", 1.0, 1.1),
    "cinzel-decorative": ("Cinzel Decorative", "CinzelDecorative-Bold.ttf", "CinzelDecorative-Regular.ttf", 0.9, 1.12),
    "limelight": ("Limelight", "Limelight-Regular.ttf", "Limelight-Regular.ttf", 0.95, 1.1),
    "bangers": ("Bangers", "Bangers-Regular.ttf", "Bangers-Regular.ttf", 1.15, 0.95),
    "creepster": ("Creepster", "Creepster-Regular.ttf", "Creepster-Regular.ttf", 1.1, 1.0),
    "audiowide": ("Audiowide", "Audiowide-Regular.ttf", "Audiowide-Regular.ttf", 0.9, 1.12),
    "rye": ("Rye", "Rye-Regular.ttf", "Rye-Regular.ttf", 0.95, 1.1),
    "pacifico": ("Pacifico", "Pacifico-Regular.ttf", "Pacifico-Regular.ttf", 0.95, 1.4),
    "titan-one": ("Titan One", "TitanOne-Regular.ttf", "TitanOne-Regular.ttf", 0.9, 1.05),
    "courier-prime": ("Courier Prime", "CourierPrime-Bold.ttf", "CourierPrime-Regular.ttf", 1.1, 1.05),
}
# the font to fall back on for letters the chosen font and Poppins don't have (Greek, Cyrillic and the rest of
# Vietnamese), in assets/fonts/noto-sans. It isn't one of the choices. Japanese, Chinese and Korean are in CJK.
FALLBACK = "noto-sans"
FACES = {**FONTS, FALLBACK: ("Noto Sans", "NotoSans-SemiBold.ttf", "NotoSans-Regular.ttf", 1.0, 1.12)}
# the last fallback, for Japanese, Chinese and Korean text: Noto Sans CJK, which fonts.py downloads into data/fonts the
# first time a poster needs it. Its files hold the same letters drawn the way each place writes them, a face each, and
# a poster's text picks one for all of it: kana make it Japanese and hangul Korean. Han characters with neither are
# drawn the Simplified Chinese way. Chinese is written in Han characters alone, so every Chinese poster comes to the
# default, while Japanese text nearly always has kana in it somewhere (and Korean hangul); Simplified is the form most
# Chinese readers use, and its face draws Traditional characters too. The faces' places in the files were read from
# the files: 0 JP, 1 KR, 2 SC, 3 TC, 4 HK, then the same five monospaced.
# face -> (name, file for the label and title, file for the subtitle, size, line height, its place in the files)
CJK = {
    "noto-sans-cjk-jp": ("Noto Sans CJK JP", fonts.BOLD, fonts.REGULAR, 0.9, 1.15, 0),
    "noto-sans-cjk-kr": ("Noto Sans CJK KR", fonts.BOLD, fonts.REGULAR, 0.9, 1.15, 1),
    "noto-sans-cjk-sc": ("Noto Sans CJK SC", fonts.BOLD, fonts.REGULAR, 0.9, 1.15, 2),
}
CJK_DEFAULT = "noto-sans-cjk-sc"
W, H = 1000, 1500
PAD = 78
LABEL_COLOUR = (240, 196, 92)

# accent = (title colour start, title colour end, tint for the backdrop wash)
ACCENTS = {
    "purple": ((176, 38, 255), (255, 122, 69), (60, 10, 110)),
    "pink": ((255, 45, 149), (255, 138, 61), (110, 10, 60)),
    "blue": ((92, 200, 255), (130, 150, 255), (30, 20, 120)),
    "gold": ((255, 190, 40), (255, 150, 20), (90, 55, 0)),
    "green": ((60, 230, 150), (40, 190, 230), (0, 70, 60)),
    "red": ((255, 70, 70), (255, 150, 60), (110, 10, 10)),
    "teal": ((0, 212, 255), (120, 110, 255), (0, 50, 100)),
    "orange": ((255, 150, 50), (255, 80, 90), (100, 40, 0)),
    "silver": ((240, 240, 248), (160, 172, 196), (36, 38, 52)),
    "ice": ((190, 240, 255), (120, 170, 255), (10, 40, 72)),
}

# settings under `posters:` in config.yml. Text settings apply to every poster; artwork, accent, shade, tint and the
# title settings leave streaming service posters as they are.
STYLE = {
    "artwork": "fixed",          # fixed, random or mosaic (see engine.Engine.poster_for)
    "mosaic": "3x3",             # artwork: mosaic only: a grid of 3x3 or 2x2 of the collection's own posters (mosaic.py)
    "accent": "auto",            # auto: each collection's own accent; or one accent name or #hex for every poster
    "shade": "medium",           # how dark the artwork is: light, medium, dark
    "tint": "normal",            # how strongly the accent colour washes over the artwork: strong, normal, subtle, none
    "title": "gradient",         # gradient (two-tone), solid (the accent's first colour) or white
    "font": "poppins",           # the font for all the text: one of FONTS
    "align": "left",             # left or centre
    "case": "normal",            # normal or upper
    "label": True,               # the small label at the top (Movies, TV Shows)
    "label_colour": "gold",      # gold, white, accent or #hex
    "subtitle_colour": "white",  # white, gold, accent or #hex
    # set by dragging in the dashboard: [x, y] as fractions of the poster. The label's y is its top edge and the
    # title's y the bottom of the title and subtitle, so extra lines grow upwards; x is the left edge, or the centre
    # when align is centre. None keeps the usual place.
    "label_position": None,
    "title_position": None,
    "title_size": 1.0,           # 0.5 to 2 times the usual size (long titles still shrink to fit the width)
    "label_size": 1.0,           # 0.5 to 2 times the usual size
    # a soft shadow behind the text: auto (text moved from its usual place, or over artwork too bright to read it on),
    # on or off
    "text_shadow": "auto",
    # streaming posters only: which logo (standard, alt or icon, where the service has one) and in what colours
    "logo": "standard",
    "logo_colour": "original",
}
CHOICES = {
    "artwork": ("fixed", "random", "mosaic"),
    "mosaic": ("2x2", "3x3"),
    "shade": ("light", "medium", "dark"),
    "tint": ("strong", "normal", "subtle", "none"),
    "title": ("gradient", "solid", "white"),
    "font": tuple(FONTS),
    "align": ("left", "centre"),
    "case": ("normal", "upper"),
    "text_shadow": ("auto", "on", "off"),
    "logo": ("standard", "alt", "icon"),
    "logo_colour": ("original", "white"),
}
TEXT_COLOURS = {"gold": LABEL_COLOUR, "white": (255, 255, 255)}
TEXT_SETTINGS = ("font", "align", "case", "label", "label_colour", "subtitle_colour")
LOGO_SETTINGS = ("logo", "logo_colour")
POSITIONS = ("label_position", "title_position")
SIZES = {"title_size": (0.5, 2.0), "label_size": (0.5, 2.0)}
LAYOUT = POSITIONS + tuple(SIZES)  # where text sits and how big: streaming posters keep their own
# shade: (artwork brightness, top darkening, bottom darkening, glow when there is no artwork)
SHADES = {"light": (0.92, 0.62, 0.86, 0.9), "medium": (0.78, 0.78, 0.95, 0.8), "dark": (0.62, 0.86, 1.0, 0.6)}
TINTS = {"strong": 0.56, "normal": 0.38, "subtle": 0.2, "none": 0.0}
HEX = re.compile(r"^#[0-9a-fA-F]{6}\Z")


def _hex(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def accent_colours(accent):
    """(title start, title end, backdrop tint) for an accent name, a "#hex" colour or a ["#start", "#end"] pair."""
    if isinstance(accent, str) and accent in ACCENTS:
        return ACCENTS[accent]
    pair = accent if isinstance(accent, (list, tuple)) else [accent]
    if 1 <= len(pair) <= 2 and all(isinstance(c, str) and HEX.match(c) for c in pair):
        c1 = _hex(pair[0])
        if len(pair) == 2:
            c2 = _hex(pair[1])
        else:  # the end colour is the start turned a little round the colour wheel, as with the built-in accents
            h, l, sat = colorsys.rgb_to_hls(*(v / 255 for v in c1))
            c2 = tuple(round(v * 255) for v in colorsys.hls_to_rgb((h + 0.07) % 1, l, sat))
        return c1, c2, tuple(int(v * 0.38) for v in c1)
    return ACCENTS["purple"]


def check_accent(accent, where):
    if not (isinstance(accent, str) and accent in ACCENTS) and accent_colours(accent) is ACCENTS["purple"]:
        raise SystemExit(f"{where}: accent must be one of {', '.join(ACCENTS)}, a colour like \"#ff3366\" or a pair "
                         f"like [\"#ff3366\", \"#ffaa00\"], not {accent!r}")


def _spellings(raw):
    raw = dict(raw)
    for us, au in (("label_color", "label_colour"), ("subtitle_color", "subtitle_colour")):
        if us in raw:
            raw.setdefault(au, raw.pop(us))
    if raw.get("align") == "center":
        raw["align"] = "centre"
    if isinstance(raw.get("font"), str):  # "Bebas Neue" or bebas_neue for bebas-neue
        raw["font"] = re.sub(r"[\s_]+", "-", raw["font"].strip().lower())
    return raw


def _settings(raw, where):
    """One full set of settings with defaults filled in. Bad values stop with a clear message."""
    unknown = sorted(set(raw) - set(STYLE))
    if unknown:
        print(f"Note: {where}: ignoring unknown settings {', '.join(map(str, unknown))}", file=sys.stderr)
    style = {k: raw.get(k, v) for k, v in STYLE.items()}
    if isinstance(style["text_shadow"], bool):  # YAML reads a bare on or off as true or false
        style["text_shadow"] = "on" if style["text_shadow"] else "off"
    for key, allowed in CHOICES.items():
        style[key] = str(style[key]).lower()
        if style[key] not in allowed:
            raise SystemExit(f"{where}: {key} must be one of {', '.join(allowed)}, not {raw.get(key)!r}")
    if style["accent"] != "auto":
        check_accent(style["accent"], where)
    if not isinstance(style["label"], bool):
        raise SystemExit(f"{where}: label must be true or false, not {style['label']!r}")
    for key in ("label_colour", "subtitle_colour"):
        if not (style[key] in ("gold", "white", "accent") or (isinstance(style[key], str) and HEX.match(style[key]))):
            raise SystemExit(f"{where}: {key} must be gold, white, accent or a colour like \"#ffffff\", "
                             f"not {style[key]!r}")
    number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    for key in POSITIONS:
        value = style[key]
        if value is not None:
            if not (isinstance(value, (list, tuple)) and len(value) == 2 and all(number(v) and 0 <= v <= 1 for v in value)):
                raise SystemExit(f"{where}: {key} must be two numbers from 0 to 1, like [0.08, 0.93], not {value!r}")
            style[key] = [round(float(v), 4) for v in value]
    for key, (low, high) in SIZES.items():
        if not (number(style[key]) and low <= style[key] <= high):
            raise SystemExit(f"{where}: {key} must be a number from {low} to {high}, not {style[key]!r}")
        style[key] = round(float(style[key]), 2)
    return style


LAYERS = ("sections", "overrides")  # settings for whole sections (by group), then single collections (by key)


def check_style(raw):
    """The `posters` settings from config.yml with defaults filled in, plus `sections` (settings for every collection
    in a section, by its group) and `overrides` (settings for single collections, by key). Either can hold any of
    them, artwork too. Bad values stop with a clear message."""
    raw = _spellings(raw or {})
    layers = {layer: raw.pop(layer, None) or {} for layer in LAYERS}
    style = _settings(raw, "config.yml posters")
    base = dict(style)
    for layer, entries in layers.items():
        if not isinstance(entries, dict):
            raise SystemExit(f"config.yml posters: {layer} must list keys, each with its own settings")
        style[layer] = {}
        for key, own in entries.items():
            where = f"config.yml posters {layer} {key}"
            if not isinstance(own, dict):
                raise SystemExit(f"{where}: must be a list of settings, like {{accent: red}}")
            own = _spellings(own)
            merged = _settings({**base, **own}, where)
            style[layer][str(key)] = {k: merged[k] for k in STYLE if k in own}
    return style


def style_for(style, key, group=None):
    """One collection's settings: those for every poster, then its section's, then its own."""
    style = style or STYLE
    out = {k: v for k, v in style.items() if k not in LAYERS}
    out.update((style.get("sections") or {}).get(group, {}))
    out.update((style.get("overrides") or {}).get(key, {}))
    return out


def style_changes(style, logo=False):
    """The settings that differ from the defaults and change this kind of poster, for its design record."""
    keys = TEXT_SETTINGS + LOGO_SETTINGS if logo else [k for k in STYLE if k not in ("artwork", "mosaic") + LOGO_SETTINGS]
    return {k: style[k] for k in keys if style and style[k] != STYLE[k]}


def _text_colour(value, accent):
    if value == "accent":
        return accent
    return TEXT_COLOURS.get(value) or _hex(value)


def _face(face):
    """A face's entry: (name, file for the label and title, file for the subtitle, size, line height), from FACES or
    CJK."""
    return FACES.get(face) or CJK[face]


@functools.lru_cache(maxsize=256)
def _font(face, size, subtitle=False):
    """One of FONTS (or a fallback) at a size: its file for the label and title, or for the subtitle. Each one is
    kept once loaded, as fitting text tries a font at many sizes."""
    if face in CJK:  # downloaded into data/fonts, its faces all in one file
        entry = CJK[face]
        return ImageFont.truetype(fonts.path(entry[2] if subtitle else entry[1]), size, index=entry[5])
    entry = FACES[face]
    return ImageFont.truetype(os.path.join(FONT_DIR, face, entry[2] if subtitle else entry[1]), size)


_DRAWN = {}  # (font, character) -> whether the font has that character


def _glyph(font, ch):
    box = font.getbbox(ch)
    img = Image.new("L", (max(1, box[2]) + 2, max(1, box[3]) + 2))
    ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=255)
    return img.size, img.tobytes()


def _missing(face, text):
    """The characters in the text the font doesn't have (it would draw its box for them)."""
    gaps = set()
    for ch in set(text):
        if ch.isspace():
            continue
        if (face, ch) not in _DRAWN:
            fonts = [_font(face, 40), _font(face, 40, subtitle=True)]
            # U+FFFF is never a character, so every font draws its missing-character box for it
            _DRAWN[(face, ch)] = all(_glyph(f, ch) != _glyph(f, "\uffff") for f in fonts)
        if not _DRAWN[(face, ch)]:
            gaps.add(ch)
    return gaps


def _draws(face, text):
    """Whether the font has every character in the text, rather than drawing its box for a missing one."""
    return not _missing(face, text)


def _cjk_face(text):
    """The Noto Sans CJK face for the text (see CJK), or None when it has no Japanese, Chinese or Korean letters or
    the font isn't downloaded."""
    if not fonts.wanted(text) or not fonts.ready():
        return None
    return "noto-sans-cjk-jp" if fonts.KANA.search(text) else "noto-sans-cjk-kr" if fonts.HANGUL.search(text) \
        else CJK_DEFAULT


def _with_font(style, *texts):
    """The style, switched to Poppins when its font is missing a character in any of the texts, or to Noto Sans
    when Poppins is missing one too. When neither has them all it's whichever is missing fewer, Poppins on a tie, so a
    star sign alone doesn't change the font. Japanese, Chinese or Korean text goes on to Noto Sans CJK once it's
    downloaded, when that's missing fewer still; without it, the text comes out as it did before."""
    face = style.get("font", "poppins")
    text = "".join(t for t in texts if t)
    if style.get("case") == "upper":
        text = text.upper()
    if _draws(face, text):
        return style
    better = min(("poppins", FALLBACK), key=lambda f: len(_missing(f, text)))
    cjk = _cjk_face(text)
    if cjk and len(_missing(cjk, text)) < len(_missing(better, text)):
        better = cjk
    return style if better == face else {**style, "font": better}


@functools.lru_cache(maxsize=1)
def _srgb():
    return ImageCms.createProfile("sRGB")


def _artwork(path):
    """Artwork as RGB, turned the right way up when its camera says so (EXIF orientation), and changed into sRGB
    when it carries another colour profile (Display P3, Adobe RGB), so its colours look as they do everywhere else."""
    img = Image.open(path)
    try:
        if img.getexif().get(0x0112, 1) != 1:  # 0x0112: orientation, 1 is the right way up
            img = ImageOps.exif_transpose(img)
    except Exception:  # a broken EXIF block: use the picture as it is
        pass
    icc = img.info.get("icc_profile")
    if icc and ImageCms is not None:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if "srgb" not in (ImageCms.getProfileDescription(profile) or "").lower():
                if img.mode not in ("RGB", "CMYK", "L"):
                    img = img.convert("RGB")
                img = ImageCms.profileToProfile(img, profile, _srgb(), outputMode="RGB")
        except Exception:  # a profile that can't be read or used: the colours as they are
            pass
    return img.convert("RGB")


MOST_PIXELS = 9_000_000  # the biggest the artwork is scaled up to whole; past this only the part that's used is


def _busiest(img, w):
    """Left edge of the w-wide window with the most going on (edges and brightness), preferring the centre unless
    another window is clearly richer."""
    spare = img.width - w
    if spare <= 0:
        return 0
    grey = img.convert("L")
    edges = grey.filter(ImageFilter.FIND_EDGES)
    interest = ImageChops.add(edges, grey.point(lambda v: v // 3)).resize((img.width, 1), Image.BOX)
    cols = list(interest.tobytes())
    weight = lambda x: 1 - 0.30 * abs(x - spare / 2) / (spare / 2)
    window = sum(cols[:w])
    best, left = window * weight(0), 0
    for x in range(1, spare + 1):
        window += cols[x + w - 1] - cols[x - 1]
        if window * weight(x) > best:
            best, left = window * weight(x), x
    return left


def _cover(img, w, h):
    """Scale to fill, then slide the crop window to the busiest/brightest part instead of the centre. Artwork of an
    odd shape, whose scaled copy would be huge (a 1920x50 strip would be 57,600 pixels wide), is looked over at a
    smaller size and only the part that's used is scaled up."""
    scale = max(w / img.width, h / img.height)
    sw, sh = round(img.width * scale) + 1, round(img.height * scale) + 1
    top = (sh - h) // 2
    if sw * sh <= MOST_PIXELS:
        img = img.resize((sw, sh), Image.LANCZOS)
        left = _busiest(img, w)
        return img.crop((left, top, left + w, top + h))
    left = 0
    if sw - w > 1:
        look = math.sqrt(MOST_PIXELS / (sw * sh))
        probe = img.resize((max(1, round(sw * look)), max(1, round(sh * look))), Image.LANCZOS)
        left = min(sw - w, round(_busiest(probe, max(1, round(w * look))) / look))
    across, down = sw / img.width, sh / img.height  # the scale each way, as if the whole picture were scaled
    return img.resize((w, h), Image.LANCZOS, box=(left / across, top / down, (left + w) / across, (top + h) / down))


def _gradient_text(base, xy, text, font, c1, c2):
    x, y = xy
    box = font.getbbox(text)
    # letters that reach left of or above where the text starts (a j, a swash) are kept, not cut off
    dx, dy = min(0, box[0]), min(0, box[1])
    x, y = x + dx, y + dy
    tw, th = box[2] - dx, box[3] - dy
    mask = Image.new("L", (tw + 8, th + 8), 0)
    ImageDraw.Draw(mask).text((-dx, -dy), text, font=font, fill=255)
    # the colours run left to right: one row is worked out, then stretched down to the height of the text
    row = Image.new("RGB", (mask.width, 1))
    last = max(1, mask.width - 1)
    row.putdata([tuple(round(c1[k] + (c2[k] - c1[k]) * (i / last)) for k in range(3)) for i in range(mask.width)])
    base.paste(row.resize(mask.size, Image.NEAREST), (x, y), mask)


def _background(backdrop, tint, shade_level="medium", tint_level="normal"):
    brightness, top_dark, bottom_dark, glow_level = SHADES[shade_level]
    if backdrop:
        bg = _cover(_artwork(backdrop), W, H)
        bg = Image.blend(bg, bg.convert("L").convert("RGB"), 0.35)
        if TINTS[tint_level]:
            bg = Image.blend(bg, Image.new("RGB", (W, H), tint), TINTS[tint_level])
        bg = bg.point(lambda v: int(v * brightness))
    else:
        bg = Image.new("RGB", (W, H), (8, 4, 20))
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse((W * 0.15, H * 0.18, W * 1.5, H * 1.05), fill=255)
        glow = glow.filter(ImageFilter.GaussianBlur(170))
        bright = tuple(min(255, int(c * 1.9) + 30) for c in tint)
        bg = Image.composite(Image.new("RGB", (W, H), bright), bg, glow.point(lambda v: int(v * glow_level)))
    # darken the top (label) and bottom (title) so text always reads
    shade = Image.new("L", (1, H))
    for y in range(H):
        t = y / H
        top = max(0.0, 1 - t / 0.30) * top_dark
        bot = max(0.0, (t - 0.42) / 0.58) ** 1.25 * bottom_dark
        shade.putpixel((0, y), int(255 * min(1.0, max(top, bot))))
    return Image.composite(Image.new("RGB", (W, H), (4, 2, 10)), bg, shade.resize((W, H)))


# the smallest each kind of text shrinks to before it's squeezed (see _squeeze); titles and subtitles always stopped at
# 60 before, and still do whenever they fit there
SMALLEST = {"title": 40, "subtitle": 32, "label": 28}
TINY = 12  # text still too wide at this size has its end cut off


def _fits(f, lines, max_w):
    return all(f.getbbox(t)[2] <= max_w for t in lines)


def _fit(face, lines, start, max_w, subtitle=False, least=60, smallest=60):
    """The font at the biggest size, from start down in steps of 4, at which every line fits max_w. Text stops at
    `least` when it fits there (titles and subtitles always came out at 60 or more, even from a smaller start), and
    otherwise goes on down to `smallest`, where a line can still be too wide (see _squeeze)."""
    # text grows with its size to within a few pixels, so a size the widest line at `start` says is well over the
    # width is passed over without measuring (measuring a long line in an ornate font is slow)
    widest = max(_font(face, start, subtitle).getbbox(t)[2] for t in lines)
    roomy = lambda size: widest * size / start <= max_w * 1.1
    size = start
    while size > least:
        if roomy(size):
            f = _font(face, size, subtitle)
            if _fits(f, lines, max_w):
                return f
        size -= 4
    size = least
    while True:
        if size - 4 < smallest:
            return _font(face, size, subtitle)
        if roomy(size):
            f = _font(face, size, subtitle)
            if _fits(f, lines, max_w):
                return f
        size -= 4


def _squeeze(face, lines, f, max_w, subtitle=False):
    """Text still too wide at its smallest size (one very long word, say), made just small enough to fit and, past
    TINY, cut short with an ellipsis. Returns the font and the lines."""
    widest = max(f.getbbox(t)[2] for t in lines)
    if widest <= max_w:
        return f, lines
    size = max(TINY, int(f.size * max_w / widest))
    f = _font(face, size, subtitle)
    while size > TINY and not _fits(f, lines, max_w):
        size -= 1
        f = _font(face, size, subtitle)
    end = "\u2026" if _draws(face, "\u2026") else "..."  # an ellipsis, or three dots in a font without one

    def cut(text):
        if f.getbbox(text)[2] <= max_w:
            return text
        most, least = len(text), 0  # the most characters that fit with the ellipsis after them
        while least < most:
            mid = (least + most + 1) // 2
            if f.getbbox(text[:mid].rstrip() + end)[2] <= max_w:
                least = mid
            else:
                most = mid - 1
        return text[:least].rstrip() + end
    return f, [cut(t) for t in lines]


# Japanese, Chinese and Korean lines can break between almost any two characters, but by their rules (kinsoku) a line
# never starts with closing punctuation, a small kana or the prolonged sound mark, and never ends with an opening bracket
NO_START = set("、。，．・：；！？‼⁇⁈⁉）」』】〉》〕］｝〙〗〞〟’”ー〜～…‥゛゜ゝゞヽヾ々〻ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ"
               "ｧｨｩｪｫｬｭｮｯｰﾞﾟ｡｣､･)]},.!?:;%") | {chr(c) for c in range(0x31F0, 0x3200)}  # and the small Ainu katakana
NO_END = set("「『【〈《（〔［｛〘〖〝‘“｢([{")


def _wrap_letters(f, line):
    """Japanese, Chinese or Korean text with no space to split at, split onto two lines between the two characters
    that leave the narrower widest line, as the rules above allow. A run of Latin letters or digits stays whole."""
    latin = lambda c: c.isalnum() and not fonts.wanted(c)
    best = None
    for i in range(1, len(line)):
        before, after = line[i - 1], line[i]
        if after in NO_START or before in NO_END or (latin(before) and latin(after)):
            continue
        widest = max(f.getlength(line[:i]), f.getlength(line[i:]))
        if best is None or widest < best[0]:
            best = (widest, [line[:i], line[i:]])
    return best[1] if best else [line]


def _wrap(face, line, size):
    """A one-line title too long for the poster, split onto two lines at the space that leaves the narrower widest
    line. Japanese, Chinese or Korean text drawn in Noto Sans CJK with no space in it splits between two characters
    instead (Korean, written with spaces, still splits at one)."""
    f = _font(face, size)
    words = line.split()
    if len(words) < 2 and face in CJK and fonts.wanted(line):
        return _wrap_letters(f, line.strip())
    widths, space = [f.getlength(w) for w in words], f.getlength(" ")
    best = None
    for i in range(1, len(words)):
        widest = max(sum(widths[:i]) + space * (i - 1), sum(widths[i:]) + space * (len(words) - i - 1))
        if best is None or widest < best[0]:
            best = (widest, [" ".join(words[:i]), " ".join(words[i:])])
    return best[1] if best else [line]


def _fit_title(face, lines, start, max_w):
    """The title's font and lines. It shrinks to fit, down to 60, as it always has. A one-line title that still
    doesn't fit goes onto two lines at its best space, and any title that still doesn't shrinks on below 60."""
    f = _fit(face, lines, start, max_w)
    if _fits(f, lines, max_w):
        return f, lines
    if len(lines) == 1:
        lines = _wrap(face, lines[0], start)
    f = _fit(face, lines, start, max_w, smallest=SMALLEST["title"])
    return _squeeze(face, lines, f, max_w)


def _title_text(style, title, subtitle):
    """The title's and subtitle's fonts and lines, fitted to the poster: (title font, lines, subtitle font or None,
    lines). The title and subtitle are already in their case."""
    face = style.get("font", "poppins")
    max_w = W - 2 * PAD
    size = style.get("title_size", 1.0) * _face(face)[3]
    tf, title_lines = _fit_title(face, title.split("\n"), round(150 * size), max_w)
    sub_lines = subtitle.split("\n") if subtitle else []
    sf = None
    if sub_lines:
        start = min(tf.size, round(132 * size))
        # a title that had to go below 60 takes its subtitle down with it, rather than the other way round
        sf = _fit(face, sub_lines, start, max_w, True, least=60 if tf.size >= 60 else start,
                  smallest=SMALLEST["subtitle"])
        sf, sub_lines = _squeeze(face, sub_lines, sf, max_w, subtitle=True)
    return tf, title_lines, sf, sub_lines


def _service_text(style, subtitle, name):
    """A streaming poster's subtitle and the service's name (drawn when there's no logo), fitted: (subtitle font,
    subtitle, name font, name). The subtitle is already in its case."""
    face = style.get("font", "poppins")
    max_w, scale = W - 2 * PAD, _face(face)[3]
    start = round(150 * scale)
    f = _fit(face, [subtitle], start, max_w, least=start, smallest=SMALLEST["title"])
    f, (subtitle,) = _squeeze(face, [subtitle], f, max_w)
    nf = _fit(face, [name], round(170 * scale), max_w, smallest=SMALLEST["title"])
    nf, (name,) = _squeeze(face, [name], nf, max_w)
    return f, subtitle, nf, name


def text_fixes(label, title, subtitle=None, style=None, logo=None):
    """How this poster's text comes out differently from posters drawn before these fixes, for its design record, so
    one drawn then is drawn again: "letters" when it's now in Noto Sans (some letters were boxes), "cjk" when it's in
    Noto Sans CJK (Japanese, Chinese or Korean letters were boxes until it was downloaded) and "fits" when it's now
    wrapped or shrunk further (it ran off the poster). Empty when it comes out as it always has. logo: for a streaming
    poster, whether its logo is drawn (rather than the service's name); None for any other poster."""
    style = style or STYLE
    upper = (lambda t: t.upper() if t else t) if style.get("case") == "upper" else (lambda t: t)
    name = title.replace("\n", " ")
    fixes = []
    if logo is None:
        style = _with_font(style, label, title, subtitle)
        tf, title_lines, sf, sub_lines = _title_text(style, upper(title), upper(subtitle))
        fits = tf.size < 60 or title_lines != upper(title).split("\n") or (sf and sf.size < 60) or \
            (subtitle and sub_lines != upper(subtitle).split("\n"))
    else:
        style = _with_font({k: v for k, v in style.items() if k not in LAYOUT}, label, subtitle, name)
        f, sub, nf, fitted = _service_text(style, upper(subtitle), name)
        fits = f.size < round(150 * _face(style.get("font", "poppins"))[3]) or sub != upper(subtitle) or \
            (not logo and (nf.size < 60 or fitted != name))
    face = style.get("font", "poppins")
    if face == FALLBACK:
        fixes.append("letters")
    elif face in CJK:
        fixes.append("cjk")
    place = _label_place(style, label)
    if fits or (place and (place[1].size < round(66 * style.get("label_size", 1.0) * _face(face)[3])
                           or place[0] != upper(label))):
        fixes.append("fits")
    return fixes


def _x(style, width):
    """Left edge of a line `width` wide in the usual place: the margin, or centred when align is centre."""
    return (W - width) // 2 if style["align"] == "centre" else PAD


def _moved_x(style, width, block_w, anchor, over=0):
    """Left edge of a line in a block moved to `anchor` (a fraction across), kept inside the poster. `over` is how
    far any letter reaches left of where its line starts (Cinzel's N does), so that stays on the poster too."""
    if style["align"] == "centre":
        centre = min(max(anchor * W, block_w / 2 + over), W - block_w / 2)
        return round(centre - width / 2)
    return round(min(max(anchor * W, over), W - block_w))


def _label_place(style, label):
    """Where the label goes: (text, font, x, y), or None when it is switched off. A long label shrinks to fit."""
    if not style["label"]:
        return None
    face = style.get("font", "poppins")
    label = label.upper() if style["case"] == "upper" else label
    start = round(66 * style.get("label_size", 1.0) * _face(face)[3])
    f = _fit(face, [label], start, W - 2 * PAD, least=start, smallest=SMALLEST["label"])
    f, (label,) = _squeeze(face, [label], f, W - 2 * PAD)
    box = f.getbbox(label)
    moved = style.get("label_position")
    if moved:
        x = _moved_x(style, box[2], box[2], moved[0], max(0, -box[0]))
        return label, f, x, round(min(max(moved[1] * H, 0), H - box[3]))
    return label, f, _x(style, box[2]), PAD


def _label(draw, place, colour):
    """Draw the label; its box (left, top, right, bottom) in pixels, or None when it is switched off."""
    if not place:
        return None
    text, f, x, y = place
    draw.text((x, y), text, font=f, fill=colour)
    box = f.getbbox(text)
    return (x, y, x + box[2], y + box[3])


def _shadow(img, parts):
    """A soft dark shadow under text: parts are (text, font, x, y). Lets text moved over bright artwork read."""
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)
    for text, f, x, y in parts:
        draw.text((x, y + max(3, f.size // 30)), text, font=f, fill=255)
    radius = max(6, max(f.size for _, f, _, _ in parts) // 12)
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(radius)).point(lambda v: int(v * 0.8))
    img.paste((0, 0, 0), (0, 0), mask)


# text that's hard to read on its artwork, a contrast below TRIGGER (as WCAG measures it, from 1 to 21), gets the
# artwork behind it darkened until it reaches READ. Artwork with the usual shading never comes near it.
TRIGGER, READ = 2.0, 3.0
MOST_DARKENING = 0.85
_LINEAR = [v / 255 / 12.92 if v <= 10 else ((v / 255 + 0.055) / 1.055) ** 2.4 for v in range(256)]


def _luminance(colour):
    """How bright a colour looks, from 0 (black) to 1 (white): WCAG's relative luminance."""
    return 0.2126 * _LINEAR[colour[0]] + 0.7152 * _LINEAR[colour[1]] + 0.0722 * _LINEAR[colour[2]]


def _contrast(a, b):
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _behind(img, box):
    """The luminance of the artwork in a box: the level a quarter of it is brighter than, so a bright patch behind
    part of the text counts."""
    counts = img.crop(box).convert("L").histogram()
    seen, quarter = 0, sum(counts) * 0.75
    for level, n in enumerate(counts):
        seen += n
        if seen >= quarter:
            return _LINEAR[level]
    return 0.0


def _lighter(colour, need):
    """The colour made lighter, keeping its hue, until its luminance reaches need (or it's white)."""
    h, light, s = colorsys.rgb_to_hls(*(v / 255 for v in colour))
    while _luminance(colour) < need and light < 1:
        light = min(1.0, light + 0.02)
        colour = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, light, s))
    return colour


def _readable(img, groups):
    """Make text readable on the artwork behind it. groups: (lines, colours), lines being [(text, font, x, y)] and
    colours what they're drawn in (both ends of a gradient). Where the artwork is too bright for a group, it's
    darkened under those lines, softly and only as much as they need. A text colour too dark to read even on black (a
    near-black accent) is lightened instead, keeping its hue. Returns each group's colours, and whether it was helped."""
    out, helped = [], []
    for lines, colours in groups:
        boxes = []
        for t, f, x, y in lines:  # where each line's letters are, on the poster
            b = f.getbbox(t)
            boxes.append((max(0, x + b[0]), max(0, y + b[1]), min(W, x + b[2]), min(H, y + b[3])))
        lines = [(line, box) for line, box in zip(lines, boxes) if box[0] < box[2] and box[1] < box[3]]
        behind = [_behind(img, box) for _, box in lines]
        text = min(_luminance(c) for c in colours)
        if not lines or min(_contrast(text, b) for b in behind) >= TRIGGER:
            out.append(colours)
            helped.append(False)
            continue
        if text < READ * 0.05 - 0.05:  # not even black behind it would let it read
            colours = [_lighter(c, READ * (max(behind) + 0.05) - 0.05) for c in colours]
            text = min(_luminance(c) for c in colours)
        # the most luminance the artwork can have behind it, aiming a little past READ as the patch's soft edge
        # takes some of the darkening back
        target = max(0.0, (text + 0.05) / (READ * 1.1) - 0.05)
        darken = sorted(((min(MOST_DARKENING, 1 - (target / b) ** (1 / 2.2)), line, box)
                         for (line, box), b in zip(lines, behind) if b > target), key=lambda d: d[0])
        if darken:
            # one soft patch as wide as the group, darker where a line needs more; it runs off the edge of the poster
            # when the text is near it, rather than leaving a light strip
            mask = Image.new("L", img.size, 0)
            draw = ImageDraw.Draw(mask)
            size = max(line[1].size for _, line, _ in darken)
            pad = round(size * 0.5)
            left, right = min(box[0] for _, box in lines) - pad, max(box[2] for _, box in lines) + pad
            left, right = -pad if left < PAD else left, W + pad if right > W - PAD else right
            for amount, line, box in darken:  # the most darkening wins where lines' patches overlap
                draw.rectangle((left, box[1] - pad, right, box[3] + pad), fill=round(255 * amount))
            img.paste((4, 2, 10), (0, 0), mask.filter(ImageFilter.GaussianBlur(max(6, size // 3))))
        out.append(colours)
        helped.append(True)
    return out, helped


def _fraction(box):
    return [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4), round(box[3] / H, 4)] if box else None


def poster_image(label, title, subtitle=None, accent="purple", backdrop=None, style=None):
    """The poster as an image, plus where its text sits: {"label": box or None, "title": box}, each box
    [left, top, right, bottom] as fractions of the poster (the dashboard draws its drag handles from these)."""
    style = _with_font(style or STYLE, label, title, subtitle)
    c1, c2, tint = accent_colours(accent if style["accent"] == "auto" else style["accent"])
    if style["case"] == "upper":
        title, subtitle = title.upper(), subtitle.upper() if subtitle else subtitle
    leading = _face(style.get("font", "poppins"))[4]
    tf, title_lines, sf, sub_lines = _title_text(style, title, subtitle)
    line_h = lambda f: int(f.size * leading)
    total = len(title_lines) * line_h(tf) + (len(sub_lines) * line_h(sf) if sf else 0)
    lines = [(t, tf) for t in title_lines] + [(t, sf) for t in sub_lines]
    boxes = [f.getbbox(t) for t, f in lines]
    block_w = max(box[2] for box in boxes)
    moved = style.get("title_position")
    if moved:
        over = max(0, -min(box[0] for box in boxes))
        y = round(min(max(moved[1] * H - total, 0), H - total))
        xs = [_moved_x(style, box[2], block_w, moved[0], over) for box in boxes]
    else:
        y = H - PAD - 30 - total
        xs = [_x(style, box[2]) for box in boxes]
    title_box = (min(xs), y, max(x + box[2] for x, box in zip(xs, boxes)), y + total)
    placed = []
    for (t, f), x in zip(lines, xs):
        placed.append((t, f, x, y))
        y += line_h(f)
    title_part, sub_part = placed[:len(title_lines)], placed[len(title_lines):]

    img = _background(backdrop, tint, style["shade"], style["tint"])
    label_place = _label_place(style, label)
    gradient = style["title"] == "gradient"
    title_colours = [c1, c2] if gradient else [c1] if style["title"] == "solid" else [(255, 255, 255)]
    colours, helped = _readable(img, [([label_place] if label_place else [], [_text_colour(style["label_colour"], c1)]),
                                      (title_part, title_colours),
                                      (sub_part, [_text_colour(style["subtitle_colour"], c1)])])
    shadow = style.get("text_shadow", "auto")
    parts = []
    if label_place and (shadow == "on" or (shadow == "auto" and (style.get("label_position") or helped[0]))):
        parts.append(label_place)
    if shadow == "on" or (shadow == "auto" and (moved or helped[1] or helped[2])):
        parts += placed
    if parts:
        _shadow(img, parts)
    draw = ImageDraw.Draw(img)
    label_box = _label(draw, label_place, colours[0][0])
    for t, f, x, at in title_part:
        if gradient:
            _gradient_text(img, (x, at), t, f, *colours[1])
        else:
            draw.text((x, at), t, font=f, fill=colours[1][0])
    for t, f, x, at in sub_part:
        draw.text((x, at), t, font=f, fill=colours[2][0])
    return img, {"label": _fraction(label_box), "title": _fraction(title_box)}


def make_poster(out_path, label, title, subtitle=None, accent="purple", backdrop=None, style=None):
    """label: 'Movies' / 'TV Shows'. title: coloured big text (may contain a newline). subtitle: white line(s).
    style: one collection's `posters` settings (style_for), or None for the defaults."""
    poster_image(label, title, subtitle, accent, backdrop, style)[0].save(out_path, "JPEG", quality=88, optimize=True)
    return out_path


# ---------------------------------------------------------------- streaming service posters
# logo key -> (accent colour, background tint)
SERVICES = {
    "netflix": ((229, 9, 20), (40, 2, 6)),
    "prime": ((0, 168, 225), (0, 22, 40)),
    "disney": ((96, 170, 255), (4, 16, 52)),
    "hbomax": ((255, 255, 255), (10, 8, 30)),
    "apple": ((240, 240, 240), (16, 16, 18)),
    "hulu": ((28, 231, 131), (2, 32, 18)),
    "paramount": ((60, 130, 255), (2, 14, 50)),
    "peacock": ((255, 255, 255), (18, 14, 26)),
    "stan": ((255, 255, 255), (2, 12, 40)),
    "binge": ((203, 4, 120), (28, 4, 30)),
    "iplayer": ((255, 76, 152), (40, 8, 24)),
    "channel4": ((170, 255, 137), (14, 26, 12)),
    "crunchyroll": ((255, 94, 0), (40, 14, 0)),
    "shudder": ((212, 0, 0), (32, 2, 4)),
}
# these brands are recoloured on dark backgrounds, a light logo or (Channel 4) its streaming green:
# (top colour, bottom colour)
LIGHT_ON_DARK = {"disney": ((255, 255, 255), (150, 215, 255)), "paramount": ((255, 255, 255), (225, 235, 255)),
                 "channel4": ((170, 255, 137), (170, 255, 137))}


def _logo_image(path, key, white=False):
    """Load a service logo; grey or black parts become white so the logo reads on a dark poster. white=True makes
    the whole logo white."""
    logo = Image.open(path).convert("RGBA")
    r, g, b, a = logo.split()
    rgb = Image.merge("RGB", (r, g, b))
    # the grey or black parts, worked out for the whole logo at once: seen (not see-through), colours less than 40
    # apart, and averaging under 140 (r + g + b at most 419, which the matrix below turns into 0)
    seen = a.point(lambda v: 255 if v else 0)
    spread = ImageChops.subtract(ImageChops.lighter(ImageChops.lighter(r, g), b),
                                 ImageChops.darker(ImageChops.darker(r, g), b))
    dark = rgb.convert("L", (1, 1, 1, -419))
    turn = ImageChops.multiply(ImageChops.multiply(seen, spread.point(lambda v: 255 if v < 40 else 0)),
                               dark.point(lambda v: 255 if v == 0 else 0))
    rgb.paste((255, 255, 255), (0, 0), turn)
    logo = Image.merge("RGBA", rgb.split() + (a,))
    box = logo.getbbox()
    logo = logo.crop(box) if box else logo
    if white:
        plain = Image.new("RGBA", logo.size, (255, 255, 255, 0))
        plain.putalpha(logo.split()[3])
        return plain
    if key in LIGHT_ON_DARK:
        top, bottom = LIGHT_ON_DARK[key]
        fill = Image.new("RGB", (1, logo.height))
        for y in range(logo.height):
            t = y / max(1, logo.height - 1)
            fill.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
        coloured = fill.resize(logo.size).convert("RGBA")
        coloured.putalpha(logo.split()[3])
        logo = coloured
    return logo


def logo_file(logos_dir, logo_key, style=None):
    """The downloaded logo a streaming poster shows: another version of it when one is chosen and has been
    downloaded, otherwise the standard one, or None when that hasn't been downloaded (the poster shows the name)."""
    version = (style or STYLE).get("logo", "standard")
    other = os.path.join(logos_dir, f"{logo_key}--{version}.png")
    if version != "standard" and os.path.exists(other):
        return other
    path = os.path.join(logos_dir, logo_key + ".png")
    return path if os.path.exists(path) else None


def make_logo_poster(out_path, label, logo_key, logos_dir, subtitle="Popular", backdrop=None, fallback_title=None,
                     style=None):
    """Service poster. If the logo file has not been downloaded (`cinesets logos`), the service name is drawn instead.
    Only the text settings in `style` apply here; the artwork, logo and layout always look the same."""
    img = logo_poster_image(label, logo_key, logos_dir, subtitle, backdrop, fallback_title, style)[0]
    img.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path


def logo_poster_image(label, logo_key, logos_dir, subtitle="Popular", backdrop=None, fallback_title=None, style=None):
    """The service poster as an image, plus where its text sits (see poster_image). Text cannot be moved here."""
    style = _with_font({k: v for k, v in (style or STYLE).items() if k not in LAYOUT}, label, subtitle,
                       (fallback_title or logo_key).replace("\n", " "))
    leading = _face(style.get("font", "poppins"))[4]
    colour, tint = SERVICES.get(logo_key, ((255, 255, 255), (16, 14, 22)))
    if backdrop:
        img = _cover(_artwork(backdrop), W, H).filter(ImageFilter.GaussianBlur(18))
        img = Image.blend(img, Image.new("RGB", (W, H), tint), 0.8)
    else:
        img = Image.new("RGB", (W, H), tint)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W * 0.02, H * 0.2, W * 0.98, H * 0.64), fill=255)
    img.paste(tuple(int(c * 0.6) for c in colour), (0, 0), glow.filter(ImageFilter.GaussianBlur(170)).point(lambda v: int(v * 0.32)))
    label_place = _label_place(style, label)
    subtitle = subtitle.upper() if style["case"] == "upper" else subtitle
    f, subtitle, nf, name = _service_text(style, subtitle, (fallback_title or logo_key).replace("\n", " "))
    line_h = int(f.size * leading)
    x, y = _x(style, f.getbbox(subtitle)[2]), H - PAD - 30 - line_h
    colours, _ = _readable(img, [([label_place] if label_place else [], [_text_colour(style["label_colour"], colour)]),
                                 ([(subtitle, f, x, y)], [_text_colour(style["subtitle_colour"], colour)])])
    draw = ImageDraw.Draw(img)
    label_box = _label(draw, label_place, colours[0][0])

    white = style.get("logo_colour") == "white"
    path = logo_file(logos_dir, logo_key, style)
    if path:
        logo = _logo_image(path, logo_key, white)
        most_w, most_h = W - 2 * PAD - 20, 360
        r = min(most_w / logo.width, most_h / logo.height)
        logo = logo.resize((int(logo.width * r), int(logo.height * r)), Image.LANCZOS)
        shadow = logo.split()[3].filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.6))
        lx, ly = (W - logo.width) // 2, int(H * 0.42) - logo.height // 2
        img.paste((0, 0, 0), (lx + 4, ly + 10), shadow)
        img.paste(logo, (lx, ly), logo)
    else:
        draw.text(((W - nf.getbbox(name)[2]) // 2, int(H * 0.42) - nf.size // 2), name, font=nf,
                  fill=(255, 255, 255) if white else colour)

    draw.text((x, y), subtitle, font=f, fill=colours[1][0])
    return img, {"label": _fraction(label_box), "title": _fraction((x, y, x + f.getbbox(subtitle)[2], y + line_h))}
