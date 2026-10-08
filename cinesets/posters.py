# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Collection posters: a gold section label, a big two-tone title bottom-left over the collection's own
artwork, or a streaming service logo for service collections. The `posters` settings in config.yml change the
colours, shading, text and font; at their defaults every poster comes out exactly as it always has."""
import colorsys
import os
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .config import ROOT

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
    "artwork": "fixed",          # fixed or random (see engine.Engine.poster_for)
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
    "text_shadow": "auto",       # a soft shadow behind the text: auto (only text moved from its usual place), on, off
    # streaming posters only: which logo (standard, alt or icon, where the service has one) and in what colours
    "logo": "standard",
    "logo_colour": "original",
}
CHOICES = {
    "artwork": ("fixed", "random"),
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
    in a section, by its group) and `overrides` (settings for single collections, by key). Either can hold anything
    but artwork. Bad values stop with a clear message."""
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
            if "artwork" in own:
                raise SystemExit(f"{where}: artwork can only be set for every poster")
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
    keys = TEXT_SETTINGS + LOGO_SETTINGS if logo else [k for k in STYLE if k != "artwork" and k not in LOGO_SETTINGS]
    return {k: style[k] for k in keys if style and style[k] != STYLE[k]}


def _text_colour(value, accent):
    if value == "accent":
        return accent
    return TEXT_COLOURS.get(value) or _hex(value)


def _font(face, size, subtitle=False):
    """One of FONTS at a size: its file for the label and title, or for the subtitle."""
    entry = FONTS[face]
    return ImageFont.truetype(os.path.join(FONT_DIR, face, entry[2] if subtitle else entry[1]), size)


_DRAWN = {}  # (font, character) -> whether the font has that character


def _glyph(font, ch):
    box = font.getbbox(ch)
    img = Image.new("L", (max(1, box[2]) + 2, max(1, box[3]) + 2))
    ImageDraw.Draw(img).text((0, 0), ch, font=font, fill=255)
    return img.size, img.tobytes()


def _draws(face, text):
    """Whether the font has every character in the text, rather than drawing its box for a missing one."""
    for ch in set(text):
        if ch.isspace():
            continue
        if (face, ch) not in _DRAWN:
            fonts = [_font(face, 40), _font(face, 40, subtitle=True)]
            # U+FFFF is never a character, so every font draws its missing-character box for it
            _DRAWN[(face, ch)] = all(_glyph(f, ch) != _glyph(f, "\uffff") for f in fonts)
        if not _DRAWN[(face, ch)]:
            return False
    return True


def _with_font(style, *texts):
    """The style, switched to Poppins when its font is missing a character in any of the texts."""
    face = style.get("font", "poppins")
    text = "".join(t for t in texts if t)
    if style.get("case") == "upper":
        text = text.upper()
    return style if face == "poppins" or _draws(face, text) else {**style, "font": "poppins"}


def _cover(img, w, h):
    """Scale to fill, then slide the crop window to the busiest/brightest part instead of the centre."""
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale) + 1, round(img.height * scale) + 1), Image.LANCZOS)
    top = (img.height - h) // 2
    spare = img.width - w
    if spare <= 0:
        return img.crop((0, top, w, top + h))
    grey = img.convert("L")
    edges = grey.filter(ImageFilter.FIND_EDGES)
    interest = ImageChops.add(edges, grey.point(lambda v: v // 3)).resize((img.width, 1), Image.BOX)
    cols = list(interest.tobytes())
    # prefer the centre unless another window is clearly richer
    weight = lambda x: 1 - 0.30 * abs(x - spare / 2) / (spare / 2)
    window = sum(cols[:w])
    best, left = window * weight(0), 0
    for x in range(1, spare + 1):
        window += cols[x + w - 1] - cols[x - 1]
        if window * weight(x) > best:
            best, left = window * weight(x), x
    return img.crop((left, top, left + w, top + h))


def _gradient_text(base, xy, text, font, c1, c2):
    x, y = xy
    box = font.getbbox(text)
    # letters that reach left of or above where the text starts (a j, a swash) are kept, not cut off
    dx, dy = min(0, box[0]), min(0, box[1])
    x, y = x + dx, y + dy
    tw, th = box[2] - dx, box[3] - dy
    mask = Image.new("L", (tw + 8, th + 8), 0)
    ImageDraw.Draw(mask).text((-dx, -dy), text, font=font, fill=255)
    grad = Image.new("RGB", mask.size)
    px = grad.load()
    for i in range(mask.width):
        t = i / max(1, mask.width - 1)
        col = tuple(round(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        for j in range(mask.height):
            px[i, j] = col
    base.paste(grad, (x, y), mask)


def _background(backdrop, tint, shade_level="medium", tint_level="normal"):
    brightness, top_dark, bottom_dark, glow_level = SHADES[shade_level]
    if backdrop:
        bg = _cover(Image.open(backdrop).convert("RGB"), W, H)
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


def _fit(face, lines, start, max_w, subtitle=False):
    size = start
    while size > 60:
        f = _font(face, size, subtitle)
        if all(f.getbbox(t)[2] <= max_w for t in lines):
            return f
        size -= 4
    return _font(face, 60, subtitle)


def _x(style, font, text):
    """Left edge of a line in the usual place: the margin, or centred when align is centre."""
    return (W - font.getbbox(text)[2]) // 2 if style["align"] == "centre" else PAD


def _moved_x(style, width, block_w, anchor):
    """Left edge of a line in a block moved to `anchor` (a fraction across), kept inside the poster."""
    if style["align"] == "centre":
        centre = min(max(anchor * W, block_w / 2), W - block_w / 2)
        return round(centre - width / 2)
    return round(min(max(anchor * W, 0), W - block_w))


def _label_place(style, label):
    """Where the label goes: (text, font, x, y), or None when it is switched off."""
    if not style["label"]:
        return None
    face = style.get("font", "poppins")
    f = _font(face, round(66 * style.get("label_size", 1.0) * FONTS[face][3]))
    label = label.upper() if style["case"] == "upper" else label
    box = f.getbbox(label)
    moved = style.get("label_position")
    if moved:
        return label, f, _moved_x(style, box[2], box[2], moved[0]), round(min(max(moved[1] * H, 0), H - box[3]))
    return label, f, _x(style, f, label), PAD


def _label(draw, style, label, accent):
    """Draw the label; its box (left, top, right, bottom) in pixels, or None when it is switched off."""
    place = _label_place(style, label)
    if not place:
        return None
    text, f, x, y = place
    draw.text((x, y), text, font=f, fill=_text_colour(style["label_colour"], accent))
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


def _fraction(box):
    return [round(box[0] / W, 4), round(box[1] / H, 4), round(box[2] / W, 4), round(box[3] / H, 4)] if box else None


def poster_image(label, title, subtitle=None, accent="purple", backdrop=None, style=None):
    """The poster as an image, plus where its text sits: {"label": box or None, "title": box}, each box
    [left, top, right, bottom] as fractions of the poster (the dashboard draws its drag handles from these)."""
    style = _with_font(style or STYLE, label, title, subtitle)
    c1, c2, tint = accent_colours(accent if style["accent"] == "auto" else style["accent"])
    if style["case"] == "upper":
        title, subtitle = title.upper(), subtitle.upper() if subtitle else subtitle
    title_lines = title.split("\n")
    sub_lines = subtitle.split("\n") if subtitle else []
    max_w = W - 2 * PAD
    face = style.get("font", "poppins")
    scale, leading = FONTS[face][3:]
    size = style.get("title_size", 1.0) * scale
    tf = _fit(face, title_lines, round(150 * size), max_w)
    sf = _fit(face, sub_lines, min(tf.size, round(132 * size)), max_w, subtitle=True) if sub_lines else None
    line_h = lambda f: int(f.size * leading)
    total = len(title_lines) * line_h(tf) + (len(sub_lines) * line_h(sf) if sf else 0)
    lines = [(t, tf) for t in title_lines] + [(t, sf) for t in sub_lines]
    block_w = max(f.getbbox(t)[2] for t, f in lines)
    moved = style.get("title_position")
    if moved:
        y = round(min(max(moved[1] * H - total, 0), H - total))
        place = lambda f, t: _moved_x(style, f.getbbox(t)[2], block_w, moved[0])
    else:
        y = H - PAD - 30 - total
        place = lambda f, t: _x(style, f, t)
    title_box = (min(place(f, t) for t, f in lines), y, max(place(f, t) + f.getbbox(t)[2] for t, f in lines), y + total)

    img = _background(backdrop, tint, style["shade"], style["tint"])
    shadow = style.get("text_shadow", "auto")
    parts = []
    if shadow == "on" or (shadow == "auto" and style.get("label_position")):
        parts += [_label_place(style, label)] if style["label"] else []
    if shadow == "on" or (shadow == "auto" and moved):
        at = y
        for t, f in lines:
            parts.append((t, f, place(f, t), at))
            at += line_h(f)
    if parts:
        _shadow(img, parts)
    draw = ImageDraw.Draw(img)
    label_box = _label(draw, style, label, c1)
    for t in title_lines:
        if style["title"] == "gradient":
            _gradient_text(img, (place(tf, t), y), t, tf, c1, c2)
        else:
            draw.text((place(tf, t), y), t, font=tf, fill=c1 if style["title"] == "solid" else (255, 255, 255))
        y += line_h(tf)
    sub_colour = _text_colour(style["subtitle_colour"], c1)
    for t in sub_lines:
        draw.text((place(sf, t), y), t, font=sf, fill=sub_colour)
        y += line_h(sf)
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
}
# these brands switch to a light logo on dark backgrounds: (top colour, bottom colour)
LIGHT_ON_DARK = {"disney": ((255, 255, 255), (150, 215, 255)), "paramount": ((255, 255, 255), (225, 235, 255))}


def _logo_image(path, key, white=False):
    """Load a service logo; grey or black parts become white so the logo reads on a dark poster. white=True makes
    the whole logo white."""
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
    face = style.get("font", "poppins")
    scale, leading = FONTS[face][3:]
    colour, tint = SERVICES.get(logo_key, ((255, 255, 255), (16, 14, 22)))
    if backdrop:
        img = _cover(Image.open(backdrop).convert("RGB"), W, H).filter(ImageFilter.GaussianBlur(18))
        img = Image.blend(img, Image.new("RGB", (W, H), tint), 0.8)
    else:
        img = Image.new("RGB", (W, H), tint)
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W * 0.02, H * 0.2, W * 0.98, H * 0.64), fill=255)
    img.paste(tuple(int(c * 0.6) for c in colour), (0, 0), glow.filter(ImageFilter.GaussianBlur(170)).point(lambda v: int(v * 0.32)))
    draw = ImageDraw.Draw(img)
    label_box = _label(draw, style, label, colour)

    white = style.get("logo_colour") == "white"
    path = os.path.join(logos_dir, logo_key + ".png")
    other = os.path.join(logos_dir, f"{logo_key}--{style.get('logo', 'standard')}.png")
    if style.get("logo", "standard") != "standard" and os.path.exists(other):
        path = other  # another version of the logo, when the service has one and it has been downloaded
    if os.path.exists(path):
        logo = _logo_image(path, logo_key, white)
        max_w, max_h = W - 2 * PAD - 20, 360
        r = min(max_w / logo.width, max_h / logo.height)
        logo = logo.resize((int(logo.width * r), int(logo.height * r)), Image.LANCZOS)
        shadow = logo.split()[3].filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.6))
        x, y = (W - logo.width) // 2, int(H * 0.42) - logo.height // 2
        img.paste((0, 0, 0), (x + 4, y + 10), shadow)
        img.paste(logo, (x, y), logo)
    else:
        name = (fallback_title or logo_key).replace("\n", " ")
        f = _fit(face, [name], round(170 * scale), W - 2 * PAD)
        draw.text(((W - f.getbbox(name)[2]) // 2, int(H * 0.42) - f.size // 2), name, font=f,
                  fill=(255, 255, 255) if white else colour)

    f = _font(face, round(150 * scale))
    subtitle = subtitle.upper() if style["case"] == "upper" else subtitle
    line_h = int(f.size * leading)
    x, y = _x(style, f, subtitle), H - PAD - 30 - line_h
    draw.text((x, y), subtitle, font=f, fill=_text_colour(style["subtitle_colour"], colour))
    return img, {"label": _fraction(label_box), "title": _fraction((x, y, x + f.getbbox(subtitle)[2], y + line_h))}
