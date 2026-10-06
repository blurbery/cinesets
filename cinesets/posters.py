# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Collection posters: a gold section label, a big two-tone title bottom-left over the collection's own
artwork, or a streaming service logo for service collections."""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .config import ROOT

FONTS = os.path.join(ROOT, "assets", "fonts")
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
}


def _font(weight, size):
    return ImageFont.truetype(os.path.join(FONTS, f"Poppins-{weight}.ttf"), size)


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
    tw, th = box[2], box[3]
    mask = Image.new("L", (tw + 8, th + 8), 0)
    ImageDraw.Draw(mask).text((0, 0), text, font=font, fill=255)
    grad = Image.new("RGB", mask.size)
    px = grad.load()
    for i in range(mask.width):
        t = i / max(1, mask.width - 1)
        col = tuple(round(c1[k] + (c2[k] - c1[k]) * t) for k in range(3))
        for j in range(mask.height):
            px[i, j] = col
    base.paste(grad, (x, y), mask)


def _background(backdrop, tint):
    if backdrop:
        bg = _cover(Image.open(backdrop).convert("RGB"), W, H)
        bg = Image.blend(bg, bg.convert("L").convert("RGB"), 0.35)
        bg = Image.blend(bg, Image.new("RGB", (W, H), tint), 0.38)
        bg = bg.point(lambda v: int(v * 0.78))
    else:
        bg = Image.new("RGB", (W, H), (8, 4, 20))
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse((W * 0.15, H * 0.18, W * 1.5, H * 1.05), fill=255)
        glow = glow.filter(ImageFilter.GaussianBlur(170))
        bright = tuple(min(255, int(c * 1.9) + 30) for c in tint)
        bg = Image.composite(Image.new("RGB", (W, H), bright), bg, glow.point(lambda v: int(v * 0.8)))
    # darken the top (label) and bottom (title) so text always reads
    shade = Image.new("L", (1, H))
    for y in range(H):
        t = y / H
        top = max(0.0, 1 - t / 0.30) * 0.78
        bot = max(0.0, (t - 0.42) / 0.58) ** 1.25 * 0.95
        shade.putpixel((0, y), int(255 * min(1.0, max(top, bot))))
    return Image.composite(Image.new("RGB", (W, H), (4, 2, 10)), bg, shade.resize((W, H)))


def _fit(weight, lines, start, max_w):
    size = start
    while size > 60:
        f = _font(weight, size)
        if all(f.getbbox(t)[2] <= max_w for t in lines):
            return f
        size -= 4
    return _font(weight, 60)


def make_poster(out_path, label, title, subtitle=None, accent="purple", backdrop=None):
    """label: 'Movies' / 'TV Shows'. title: coloured big text (may contain a newline). subtitle: white line(s)."""
    c1, c2, tint = ACCENTS.get(accent, ACCENTS["purple"])
    img = _background(backdrop, tint)
    draw = ImageDraw.Draw(img)
    draw.text((PAD, PAD), label, font=_font("SemiBold", 66), fill=LABEL_COLOUR)

    title_lines = title.split("\n")
    sub_lines = subtitle.split("\n") if subtitle else []
    max_w = W - 2 * PAD
    tf = _fit("SemiBold", title_lines, 150, max_w)
    sf = _fit("Regular", sub_lines, min(tf.size, 132), max_w) if sub_lines else None
    line_h = lambda f: int(f.size * 1.12)
    total = len(title_lines) * line_h(tf) + (len(sub_lines) * line_h(sf) if sf else 0)
    y = H - PAD - 30 - total
    for t in title_lines:
        _gradient_text(img, (PAD, y), t, tf, c1, c2)
        y += line_h(tf)
    for t in sub_lines:
        draw.text((PAD, y), t, font=sf, fill=(255, 255, 255))
        y += line_h(sf)
    img.save(out_path, "JPEG", quality=88, optimize=True)
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


def _logo_image(path, key):
    """Load a service logo; grey or black parts become white so the logo reads on a dark poster."""
    logo = Image.open(path).convert("RGBA")
    px = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = px[x, y]
            if a and max(r, g, b) - min(r, g, b) < 40 and (r + g + b) / 3 < 140:
                px[x, y] = (255, 255, 255, a)
    box = logo.getbbox()
    logo = logo.crop(box) if box else logo
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


def make_logo_poster(out_path, label, logo_key, logos_dir, subtitle="Popular", backdrop=None, fallback_title=None):
    """Service poster. If the logo file has not been downloaded (`cinesets logos`), the service name is drawn instead."""
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
    draw.text((PAD, PAD), label, font=_font("SemiBold", 66), fill=LABEL_COLOUR)

    path = os.path.join(logos_dir, logo_key + ".png")
    if os.path.exists(path):
        logo = _logo_image(path, logo_key)
        max_w, max_h = W - 2 * PAD - 20, 360
        r = min(max_w / logo.width, max_h / logo.height)
        logo = logo.resize((int(logo.width * r), int(logo.height * r)), Image.LANCZOS)
        shadow = logo.split()[3].filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * 0.6))
        x, y = (W - logo.width) // 2, int(H * 0.42) - logo.height // 2
        img.paste((0, 0, 0), (x + 4, y + 10), shadow)
        img.paste(logo, (x, y), logo)
    else:
        name = (fallback_title or logo_key).replace("\n", " ")
        f = _fit("SemiBold", [name], 170, W - 2 * PAD)
        draw.text(((W - f.getbbox(name)[2]) // 2, int(H * 0.42) - f.size // 2), name, font=f, fill=colour)

    f = _font("SemiBold", 150)
    draw.text((PAD, H - PAD - 30 - int(f.size * 1.12)), subtitle, font=f, fill=(255, 255, 255))
    img.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path
