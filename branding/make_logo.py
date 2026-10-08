# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""CineSets logo: fanned stack of gold poster cards, front card with film sprockets and a play mark.

Usage: python branding/make_logo.py [fonts_dir] [out_dir]   (defaults: assets/fonts/poppins, branding)
"""
import os, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "assets", "fonts", "poppins")
OUT = sys.argv[2] if len(sys.argv) > 2 else HERE
os.makedirs(OUT, exist_ok=True)
SS = 4  # supersampling

GOLD = [(255, 243, 196), (248, 212, 118), (222, 166, 58), (176, 116, 26), (232, 184, 82)]
STOPS = [0.0, 0.34, 0.58, 0.82, 1.0]
INK = (16, 13, 22)


def gradient(size, colours=GOLD, stops=STOPS, diagonal=True):
    w, h = size
    line = Image.new("RGB", (256, 1))
    for i in range(256):
        t = i / 255
        for k in range(len(stops) - 1):
            if stops[k] <= t <= stops[k + 1]:
                f = (t - stops[k]) / (stops[k + 1] - stops[k])
                line.putpixel((i, 0), tuple(int(colours[k][j] + (colours[k + 1][j] - colours[k][j]) * f) for j in range(3)))
                break
    if not diagonal:
        return line.resize((h, 1)).rotate(-90, expand=True).resize((w, h))
    big = line.resize((int((w + h) * 1.5), int((w + h) * 1.5)))
    big = big.rotate(-35, resample=Image.BICUBIC)
    x, y = (big.width - w) // 2, (big.height - h) // 2
    return big.crop((x, y, x + w, y + h))


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return m


def card(w, h, r, front=False):
    """One poster card as RGBA."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    outer = rounded_mask((w, h), r)
    gold = gradient((w, h)).convert("RGBA")
    img.paste(gold, (0, 0), outer)
    if front:
        b = int(w * 0.075)
        inner = rounded_mask((w - 2 * b, h - 2 * b), int(r * 0.62))
        img.paste(Image.new("RGBA", inner.size, INK + (255,)), (b, b), inner)
        # film sprockets down both sides
        sw, sh = int(w * 0.075), int(h * 0.055)
        n = 6
        gap = (h - 2 * b - n * sh) / (n + 1)
        d = ImageDraw.Draw(img)
        for i in range(n):
            y = int(b + gap * (i + 1) + sh * i)
            for x in (int(b + w * 0.06), int(w - b - w * 0.06 - sw)):
                d.rounded_rectangle((x, y, x + sw, y + sh), int(sw * 0.3), fill=None)
                hole = rounded_mask((sw, sh), int(sw * 0.3))
                img.paste(gradient((sw, sh)).convert("RGBA"), (x, y), hole)
        # play mark in the centre
        cx, cy, s = w * 0.53, h * 0.5, w * 0.22
        tri = Image.new("L", (w, h), 0)
        ImageDraw.Draw(tri).polygon([(cx - s * 0.62, cy - s), (cx - s * 0.62, cy + s), (cx + s * 0.95, cy)], fill=255)
        tri = tri.filter(ImageFilter.GaussianBlur(w * 0.004))
        img.paste(gradient((w, h)).convert("RGBA"), (0, 0), tri)
    else:
        # back cards: gold rim around a dark poster face, dimmed so the stack reads as depth
        b = int(w * 0.075)
        inner = rounded_mask((w - 2 * b, h - 2 * b), int(r * 0.62))
        img.paste(Image.new("RGBA", inner.size, (30, 24, 34, 255)), (b, b), inner)
        dim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dim.putalpha(outer.point(lambda v: int(v * 0.38)))
        img = Image.alpha_composite(img, Image.new("RGBA", (w, h), (8, 6, 12, 0)))
        blk = Image.new("RGBA", (w, h), (8, 6, 12, 255)); blk.putalpha(dim.split()[3])
        img = Image.alpha_composite(img, blk)
    return img


def icon(size):
    S = size * SS
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cw, ch = int(S * 0.46), int(S * 0.66)
    r = int(cw * 0.12)
    layers = [(14, -0.13, 0.02, False), (6, -0.05, 0.005, False), (-3, 0.07, -0.01, True)]
    for angle, dx, dy, front in layers:
        c = card(cw, ch, r, front)
        # soft shadow under each card
        sh = Image.new("RGBA", c.size, (0, 0, 0, 0))
        sh.putalpha(c.split()[3].point(lambda v: int(v * 0.55)))
        sh = sh.rotate(angle, resample=Image.BICUBIC, expand=True)
        pad = int(S * 0.06)
        padded = Image.new("RGBA", (sh.width + 2 * pad, sh.height + 2 * pad), (0, 0, 0, 0))
        padded.alpha_composite(sh, (pad, pad))
        sh = padded.filter(ImageFilter.GaussianBlur(S * 0.018))
        c = c.rotate(angle, resample=Image.BICUBIC, expand=True)
        x = int(S / 2 - c.width / 2 + dx * S)
        y = int(S / 2 - c.height / 2 + dy * S)
        blk = Image.new("RGBA", sh.size, (0, 0, 0, 255)); blk.putalpha(sh.split()[3])
        canvas.alpha_composite(blk, (x - pad + int(S * 0.012), y - pad + int(S * 0.025)))
        canvas.alpha_composite(c, (x, y))
    return canvas.resize((size, size), Image.LANCZOS)


def wordmark(height, light=True):
    H = height * SS
    f = ImageFont.truetype(os.path.join(FONTS, "Poppins-SemiBold.ttf"), int(H * 0.82))
    a, b = "Cine", "Sets"
    wa, wb = f.getlength(a), f.getlength(b)
    W = int(wa + wb + H * 0.1)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    top = f.getbbox("Cine")[1]
    y = int((H - (f.getbbox("CineSets")[3] - top)) / 2 - top)
    ImageDraw.Draw(img).text((0, y), a, font=f, fill=(255, 255, 255, 255) if light else INK + (255,))
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).text((int(wa), y), b, font=f, fill=255)
    img.paste(gradient((W, H), diagonal=False).convert("RGBA"), (0, 0), m)
    return img.resize((W // SS, height), Image.LANCZOS)


def lockup(height, light=True):
    ic = icon(height)
    wm = wordmark(int(height * 0.5), light)
    gap = int(height * 0.12)
    img = Image.new("RGBA", (ic.width + gap + wm.width, height), (0, 0, 0, 0))
    img.alpha_composite(ic, (0, 0))
    img.alpha_composite(wm, (ic.width + gap, (height - wm.height) // 2))
    return img


TAGLINE = "Automatic, beautiful collections for Emby, Jellyfin and Silo"


def backdrop(w, h):
    """Near-black background with a warm gold glow from the top left."""
    bg = Image.new("RGB", (w, h), (10, 8, 14))
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse((-w * 0.1, -h * 0.6, w * 0.7, h * 1.4), fill=255)
    bg.paste((60, 40, 12), (0, 0), glow.filter(ImageFilter.GaussianBlur(180)).point(lambda v: int(v * 0.55)))
    return bg.convert("RGBA")


def banner(w=1600, h=520):
    img = backdrop(w, h)
    lk = lockup(300)
    x, y = (w - lk.width) // 2, int(h * 0.12)
    img.alpha_composite(lk, (x, y))
    f = ImageFont.truetype(os.path.join(FONTS, "Poppins-Regular.ttf"), 34)
    ImageDraw.Draw(img).text(((w - f.getlength(TAGLINE)) / 2, y + lk.height + 34), TAGLINE, font=f, fill=(222, 214, 196))
    return img.convert("RGB")


def social(w=1280, h=640):
    """Link preview image (GitHub social preview, Discord and so on): 2:1, logo and tagline centred."""
    img = backdrop(w, h)
    lk = lockup(260)
    f = ImageFont.truetype(os.path.join(FONTS, "Poppins-Regular.ttf"), 32)
    top, bottom = lk.getbbox()[1], lk.getbbox()[3]  # centre what is drawn, not the lockup's empty margins
    _, text_top, _, text_bottom = f.getbbox(TAGLINE)
    gap = 44
    y = (h - (bottom - top) - gap - (text_bottom - text_top)) // 2 - top
    img.alpha_composite(lk, ((w - lk.width) // 2, y))
    ImageDraw.Draw(img).text(((w - f.getlength(TAGLINE)) / 2, y + bottom + gap - text_top), TAGLINE, font=f, fill=(222, 214, 196))
    return img.convert("RGB")


icon(1024).save(os.path.join(OUT, "cinesets-icon.png"))
icon(256).save(os.path.join(OUT, "cinesets-icon-256.png"))
lockup(240, light=True).save(os.path.join(OUT, "cinesets-logo-dark-bg.png"))
lockup(240, light=False).save(os.path.join(OUT, "cinesets-logo-light-bg.png"))
banner().save(os.path.join(OUT, "cinesets-banner.png"))
social().save(os.path.join(OUT, "cinesets-social.png"))
# preview: icon on dark and light, lockups on both
pv = Image.new("RGB", (1600, 1160), (24, 22, 28))
pv.paste(banner(), (0, 0))
pv.paste((236, 234, 230), (800, 540, 1600, 1160))
ic = icon(320)
pv.paste(ic, (240, 560), ic); pv.paste(ic, (1040, 560), ic)
for lk_img, x0 in ((lockup(150, True), 40), (lockup(150, False), 840)):
    pv.paste(lk_img, (x0 + (720 - lk_img.width) // 2, 960), lk_img)
print("ok")
