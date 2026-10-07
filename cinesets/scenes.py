# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Made-up cinematic backgrounds for the preview images in docs/ and the dashboard's demo mode.

Real posters sit on a film backdrop from the user's own library, but film artwork can't be committed to a
public repo, so the preview uses these original scenes instead. They are drawn with Pillow alone and seeded,
so every scene comes out the same on every run.

  venv/bin/python -m cinesets.scenes some/folder   # writes <name>.jpg for every scene
"""
import math
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

SCENES = {}


def _scene(fn):
    """Register a scene; each one finishes with the same light vignette and fine grain."""
    seed = 9000 + len(SCENES)

    def run(w=1920, h=1080):
        return _finish(fn(w, h).convert("RGB"), random.Random(seed))

    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    SCENES[fn.__name__] = run
    return run


# ---------------------------------------------------------------- helpers

def _mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _curve(mask, fn):
    """Remap an L image through fn, clamped to 0..255."""
    return mask.point([max(0, min(255, int(fn(v)))) for v in range(256)])


def _vgrad(w, h, stops):
    """Vertical gradient from [(position 0..1, colour or grey level), ...]; built one pixel wide, then stretched."""
    stops = sorted(stops, key=lambda s: s[0])
    grey = isinstance(stops[0][1], int)
    col = Image.new("L" if grey else "RGB", (1, h))
    px = col.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if t <= p1:
                break
        k = min(1.0, max(0.0, (t - p0) / ((p1 - p0) or 1)))
        px[0, y] = int(c0 + (c1 - c0) * k) if grey else _mix(c0, c1, k)
    return col.resize((w, h))


def _hgrad(w, h, stops):
    """Horizontal version of _vgrad."""
    return _vgrad(1, w, stops).transpose(Image.ROTATE_90).resize((w, h))


def _radial(size, cx, cy, rx, ry=None, power=1.0, peak=255):
    """L mask that is `peak` at (cx, cy) and fades to nothing at the radius; power > 1 tightens the core."""
    ry = ry or rx
    # Pillow's radial gradient reaches 255 at the corners, so the edge midpoints sit at about 181
    lut = [int(peak * max(0.0, 1 - v * 1.4142 / 255) ** power) for v in range(256)]
    blob = Image.radial_gradient("L").point(lut).resize((max(1, int(2 * rx)), max(1, int(2 * ry))), Image.BILINEAR)
    mask = Image.new("L", size, 0)
    mask.paste(blob, (int(cx - rx), int(cy - ry)))
    return mask


def _blur(im, r):
    """Gaussian blur; big radii run on a reduced copy, which is much quicker and looks the same."""
    if r <= 6:
        return im.filter(ImageFilter.GaussianBlur(r))
    f = min(8, int(r / 3))
    small = im.resize((max(1, im.width // f), max(1, im.height // f)), Image.BOX)
    return small.filter(ImageFilter.GaussianBlur(r / f)).resize(im.size, Image.BICUBIC)


def _light(img, mask, colour, amount=1.0):
    """Screen a colour onto img through an L mask (glows, beams, haze)."""
    if amount != 1:
        mask = _curve(mask, lambda v: v * amount)
    layer = Image.new("RGB", img.size)
    layer.paste(colour, (0, 0) + img.size, mask)
    return ImageChops.screen(img, layer)


def _paint(img, mask, fill, amount=1.0):
    """Paint a colour or a same-size image over img through an L mask, in place."""
    if amount != 1:
        mask = _curve(mask, lambda v: v * amount)
    img.paste(fill, (0, 0) + img.size, mask)
    return img


def _noise(rng, w, h, cells, octaves=5, keep=0.55, stretch=1.0):
    """Smooth fractal value noise (L, full range) for clouds, nebulae and haze. `cells` is how many blobs span
    the width at the coarsest level; stretch > 1 squashes it into horizontal streaks."""
    sw, sh = max(8, w // 4), max(8, h // 4)
    acc, total = None, 0.0
    for i in range(octaves):
        cw = min(sw, max(2, int(cells * 2 ** i)))
        ch = min(sh, max(2, int(cw * h / w * stretch)))
        layer = Image.frombytes("L", (cw, ch), rng.randbytes(cw * ch)).resize((sw, sh), Image.BICUBIC)
        total += keep ** i
        acc = layer if acc is None else Image.blend(acc, layer, keep ** i / total)
    acc = ImageOps.autocontrast(acc.filter(ImageFilter.GaussianBlur(1)), cutoff=1)
    return acc.resize((w, h), Image.BICUBIC)


def _ridge(rng, w, y, amp, rough=0.55, steps=8):
    """Jagged skyline across the full width by midpoint displacement."""
    ys = [y + rng.uniform(-amp, amp), y + rng.uniform(-amp, amp)]
    d = amp
    for _ in range(steps):
        out = []
        for a, b in zip(ys, ys[1:]):
            out += [a, (a + b) / 2 + rng.uniform(-d, d)]
        ys, d = out + [ys[-1]], d * rough
    n = len(ys) - 1
    return [(i * w / n, v) for i, v in enumerate(ys)]


def _waves(rng, w, y, parts, n=160):
    """Smooth rolling line: y plus random sine waves, parts = [(amplitude, wavelength), ...]."""
    phases = [rng.uniform(0, 2 * math.pi) for _ in parts]
    xs = [i * w / n for i in range(n + 1)]
    return [(x, y + sum(a * math.sin(2 * math.pi * x / lam + p) for (a, lam), p in zip(parts, phases))) for x in xs]


def _at(pts, x):
    """Height of a line of points at x."""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / ((x1 - x0) or 1)
    return pts[-1][1]


def _below(size, pts):
    """Soft-edged L mask of everything below a line of points running from x=0 to x=w."""
    w, h = size
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon(list(pts) + [(w, h + 1), (0, h + 1)], fill=255)
    return m.filter(ImageFilter.GaussianBlur(h / 1400))


def _disc(size, cx, cy, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    return m.filter(ImageFilter.GaussianBlur(size[1] / 1200))


def _stars(img, rng, n, y1=1.0, big=0.03):
    """Scatter n stars over the top y1 of the frame; a few big ones get a soft halo."""
    w, h = img.size
    u = h / 1080
    layer = Image.new("RGB", img.size)
    d = ImageDraw.Draw(layer)
    for _ in range(n):
        x, y = rng.uniform(0, w), h * y1 * rng.random()
        v = 40 + 215 * rng.random() ** 3
        tint = rng.choice(((1, 1, 1), (1, 1, 1), (0.8, 0.88, 1), (1, 0.88, 0.75)))
        c = tuple(int(v * t) for t in tint)
        if rng.random() < big:
            r = rng.uniform(1.0, 2.2) * u
            d.ellipse((x - r, y - r, x + r, y + r), fill=c)
        else:
            d.point((x, y), fill=c)
    halo = _blur(layer, 2.5 * u)
    return ImageChops.screen(ImageChops.screen(img, layer), ImageChops.add(halo, halo))


def _pine(d, rng, x, base, height, fill=255):
    """Jagged pine silhouette standing on (x, base)."""
    tiers = rng.randint(8, 12)
    top, step = base - height, height * 0.9 / tiers
    sides = []
    for sgn in (-1, 1):
        pts = []
        for i in range(1, tiers + 1):
            half = height * (0.17 * (i / tiers) ** 0.9 * rng.uniform(0.75, 1.2) + 0.01)
            y = top + step * i
            pts += [(x + sgn * half * 0.4, y - step * 0.55), (x + sgn * half, y)]
        trunk = x + sgn * height * 0.014
        sides.append(pts + [(trunk, top + step * tiers), (trunk, base)])
    d.polygon([(x, top)] + sides[0] + sides[1][::-1], fill=fill)


def _tree(d, rng, x, y, length, width, depth, angle=-90.0, spread=30.0):
    """Bare, twisted tree from recursive kinked branches (angles in degrees, -90 is straight up)."""
    stack = [(x, y, angle, length, width, depth)]
    while stack:
        x, y, a, ln, wd, dep = stack.pop()
        for _ in range(3):  # three kinked segments per branch
            a += rng.uniform(-13, 13)
            nx, ny = x + math.cos(math.radians(a)) * ln / 3, y + math.sin(math.radians(a)) * ln / 3
            d.line((x, y, nx, ny), fill=255, width=max(1, int(round(wd))))
            if wd > 2.5:
                d.ellipse((nx - wd / 2, ny - wd / 2, nx + wd / 2, ny + wd / 2), fill=255)
            x, y, wd = nx, ny, wd * 0.93
        if dep > 1:
            kids = 3 if rng.random() < 0.3 else 2
            for k in range(kids):
                off = (k - (kids - 1) / 2) * 2 * spread / (kids - 1) + rng.uniform(-10, 10)
                stack.append((x, y, a + off, ln * rng.uniform(0.62, 0.8), wd * 0.7, dep - 1))


def _zigzag(rng, x0, y0, x1, y1, disp, steps):
    """Lightning path between two points by perpendicular midpoint displacement."""
    pts = [(x0, y0), (x1, y1)]
    for _ in range(steps):
        out = [pts[0]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            dx, dy = bx - ax, by - ay
            ln = math.hypot(dx, dy) or 1
            off = rng.uniform(-disp, disp)
            out += [((ax + bx) / 2 - dy / ln * off, (ay + by) / 2 + dx / ln * off), (bx, by)]
        pts, disp = out, disp * 0.55
    return pts


def _finish(img, rng):
    """Light vignette towards the corners, then fine grain so the gradients don't band."""
    w, h = img.size
    vig = _curve(_radial(img.size, w / 2, h / 2, w * 0.78, h * 0.95, power=0.7), lambda v: 165 + v * 0.36)
    img = ImageChops.multiply(img, vig.convert("RGB"))
    grain = Image.frombytes("L", (w, h), rng.randbytes(w * h)).point(lambda v: v * 7 // 255)
    return ImageChops.add(img, grain.convert("RGB"), 1.0, -3)


# ---------------------------------------------------------------- scenes

@_scene
def city(w, h):
    """Night skyline with lit windows, searchlights and out-of-focus street lights."""
    rng = random.Random(101)
    u, size = h / 1080, (w, h)
    hz = 0.64 * h
    img = _vgrad(w, h, [(0, (8, 10, 30)), (0.35, (26, 26, 72)), (0.52, (78, 48, 100)), (0.64, (200, 106, 96)),
                        (1, (60, 34, 60))])
    haze = _curve(_noise(rng, w, h, 3, 5, 0.6, stretch=4), lambda v: (v - 110) * 2)
    img = _light(img, ImageChops.multiply(haze, _vgrad(w, h, [(0.15, 0), (0.45, 210), (0.62, 0)])), (150, 80, 110), 0.5)
    # two searchlights rising from behind the skyline
    beams = Image.new("L", size)
    d = ImageDraw.Draw(beams)
    for bx, lean in ((0.41 * w, 0.2), (0.6 * w, -0.16)):
        d.polygon([(bx - 3 * u, hz), (bx + 3 * u, hz), (bx + lean * h + 34 * u, 0), (bx + lean * h - 34 * u, 0)], fill=120)
    beams = ImageChops.multiply(_blur(beams, 9 * u), _vgrad(w, h, [(0, 40), (0.6, 255)]))
    img = _light(img, beams, (170, 190, 255), 0.8)

    env = lambda x: 0.3 + 0.7 * math.exp(-((x / w - 0.5) / 0.17) ** 2)  # downtown in the middle
    beacons = []
    layers = [((54, 42, 88), 0.06, 0.2, 30, 70, 0.0, 0), ((30, 26, 58), 0.1, 0.3, 40, 100, 0.13, 6),
              ((12, 11, 26), 0.12, 0.44, 50, 120, 0.3, 9)]
    for n, (colour, hmin, hmax, wmin, wmax, chance, pitch) in enumerate(layers):
        m = Image.new("L", size)
        d = ImageDraw.Draw(m)
        lights = Image.new("RGB", size)
        ld = ImageDraw.Draw(lights)
        x = -rng.uniform(0, wmax * u)
        while x < w:
            bw = rng.uniform(wmin, wmax) * u
            cx = x + bw / 2
            top = hz + n * 0.03 * h - h * rng.uniform(hmin, hmax) * env(cx)
            d.rectangle((x, top, x + bw, h), fill=255)
            kind = rng.random()
            if kind < 0.25:  # stepped crown
                inset, t2 = bw * rng.uniform(0.15, 0.3), top - h * rng.uniform(0.02, 0.05)
                d.rectangle((x + inset, t2, x + bw - inset, top), fill=255)
            elif kind < 0.4:  # spire
                tip = top - h * rng.uniform(0.04, 0.1) * env(cx)
                d.polygon([(cx - bw * 0.12, top), (cx, tip), (cx + bw * 0.12, top)], fill=255)
                if n == 2:
                    beacons.append((cx, tip))
            if chance:
                _windows(ld, rng, x, x + bw, top, 0.93 * h, pitch * u, chance * rng.uniform(0.4, 1.6))
            x += bw * rng.uniform(0.85, 1.2)
        img = _paint(img, m.filter(ImageFilter.GaussianBlur(0.6 * u)), colour)
        if chance:
            img = ImageChops.screen(img, lights)
            img = ImageChops.screen(img, _blur(lights, 5 * u))
            img = _light(img, _blur(lights.convert("L"), 28 * u), (255, 170, 110), 1.6)
    # red aircraft lights
    tips = Image.new("L", size)
    d = ImageDraw.Draw(tips)
    for bx, by in beacons:
        d.ellipse((bx - 3 * u, by - 3 * u, bx + 3 * u, by + 3 * u), fill=255)
    img = _light(img, tips, (255, 60, 50))
    img = _light(img, _blur(tips, 8 * u), (255, 40, 30), 3)
    # bokeh from street lights close to the camera
    for colour in ((255, 170, 80), (255, 90, 130), (120, 180, 255)):
        bokeh = Image.new("L", size)
        d = ImageDraw.Draw(bokeh)
        for _ in range(10):
            bx, by = w * (0.5 + rng.gauss(0, 0.17)), h * rng.uniform(0.52, 0.95)
            r, v = rng.uniform(14, 46) * u, rng.randint(50, 130)
            d.ellipse((bx - r, by - r, bx + r, by + r), fill=v, outline=min(255, v + 50), width=max(1, int(2 * u)))
        img = _light(img, _blur(bokeh, 3 * u), colour, 0.9)
    return img


def _windows(d, rng, x0, x1, top, bottom, pitch, chance):
    """Lit windows on one building, in a grid with whole dark floors here and there."""
    cw, rh = pitch, pitch * 1.45
    ww, wh = cw * 0.55, rh * 0.5
    cols = int((x1 - x0 - cw * 0.5) // cw)
    if cols < 1:
        return
    warm = rng.random() < 0.75
    left = x0 + (x1 - x0 - cols * cw) / 2 + (cw - ww) / 2
    y = top + rh
    while y < bottom:
        if rng.random() < 0.85:
            for c in range(cols):
                if rng.random() < chance:
                    v = rng.uniform(0.4, 1.0)
                    base = (255, 206, 140) if warm != (rng.random() < 0.15) else (180, 214, 255)
                    wx = left + c * cw
                    d.rectangle((wx, y, wx + ww, y + wh), fill=tuple(int(k * v) for k in base))
        y += rh


@_scene
def nebula(w, h):
    """Deep space: a magenta and teal nebula, a bright star with diffraction spikes and a ringed planet."""
    rng = random.Random(202)
    u, size = h / 1080, (w, h)
    img = _vgrad(w, h, [(0, (8, 6, 22)), (1, (14, 10, 30))])
    band = Image.new("L", size)
    ImageDraw.Draw(band).line((0.1 * w, 0.85 * h, 0.85 * w, 0.1 * h), fill=255, width=int(0.32 * h))
    band = _blur(band, 0.16 * h)
    pink = _curve(ImageChops.multiply(_noise(rng, w, h, 3, 6, 0.62), band), lambda v: 255 * (v / 255) ** 1.4 * 1.7)
    teal = _curve(ImageChops.multiply(_noise(rng, w, h, 4, 6, 0.62), band), lambda v: 255 * (v / 255) ** 1.8 * 1.9)
    img = _light(img, pink, (225, 50, 155))
    img = _light(img, teal, (40, 165, 235))
    img = _light(img, _curve(ImageChops.multiply(pink, teal), lambda v: v * 2.4), (255, 215, 235))
    dust = ImageChops.multiply(_curve(_noise(rng, w, h, 6, 5, 0.55), lambda v: (v - 140) * 3), band)
    img = ImageChops.multiply(img, ImageOps.invert(_curve(dust, lambda v: v * 0.75)).convert("RGB"))
    img = _stars(img, rng, int(2400 * w * h / 2073600), big=0.04)
    # the bright star that lights the cloud
    sx, sy = 0.4 * w, 0.36 * h
    img = _light(img, _radial(size, sx, sy, 0.26 * h, power=3), (190, 215, 255))
    spikes = Image.new("L", size)
    d = ImageDraw.Draw(spikes)
    sl = 0.17 * h
    d.line((sx - sl, sy, sx + sl, sy), fill=255, width=max(1, int(2 * u)))
    d.line((sx, sy - sl, sx, sy + sl), fill=255, width=max(1, int(2 * u)))
    spikes = ImageChops.multiply(_blur(spikes, 1.2 * u), _radial(size, sx, sy, sl, power=1.4))
    ImageDraw.Draw(spikes).ellipse((sx - 5 * u, sy - 5 * u, sx + 5 * u, sy + 5 * u), fill=255)
    img = _light(img, spikes, (240, 244, 255))
    img = _light(img, _blur(spikes, 6 * u), (160, 190, 255), 2)
    # ringed planet, lit from the star's side
    pr, px, py = 0.16 * h, 0.6 * w, 0.64 * h
    lx, ly = px - 0.55 * pr, py - 0.6 * pr
    ring = Image.new("L", size)
    d = ImageDraw.Draw(ring)
    for k in range(10, -1, -1):
        rx = pr * (1.32 + 0.075 * k)
        v = 22 if k == 6 else rng.randint(70, 200)  # a dark gap in the rings
        d.ellipse((px - rx, py - rx * 0.27, px + rx, py + rx * 0.27), fill=v)
    d.ellipse((px - pr * 1.3, py - pr * 1.3 * 0.27, px + pr * 1.3, py + pr * 1.3 * 0.27), fill=0)
    back, front = ring.copy(), ring
    ImageDraw.Draw(back).rectangle((0, py, w, h), fill=0)
    ImageDraw.Draw(front).rectangle((0, 0, w, py), fill=0)
    back, front = (r.rotate(14, Image.BICUBIC, center=(px, py)) for r in (back, front))
    img = _light(img, back, (225, 205, 180))
    bands = ImageOps.colorize(_noise(rng, w, h, 3, 5, 0.6, stretch=9), (60, 36, 70), (240, 196, 150), mid=(170, 100, 100))
    shade = _curve(_radial(size, lx, ly, 2.0 * pr, power=1.1), lambda v: 14 + v * 1.1)
    img = _paint(img, _disc(size, px, py, pr), ImageChops.multiply(bands, shade.convert("RGB")))
    rim = Image.new("L", size)
    ImageDraw.Draw(rim).ellipse((px - pr, py - pr, px + pr, py + pr), outline=255, width=max(2, int(5 * u)))
    rim = ImageChops.multiply(_blur(rim, 5 * u), _radial(size, lx, ly, 2.1 * pr, power=0.8))
    img = _light(img, rim, (120, 175, 255), 2.2)
    img = _light(img, front, (235, 215, 190))
    return img


@_scene
def sunset(w, h):
    """Layered mountain ridges at sunset with a big low sun, thin cloud and a few birds."""
    rng = random.Random(303)
    u, size = h / 1080, (w, h)
    sx, sy, sr = 0.5 * w, 0.49 * h, 0.085 * h
    img = _vgrad(w, h, [(0, (36, 26, 80)), (0.24, (112, 50, 112)), (0.4, (236, 110, 92)), (0.5, (255, 176, 96)),
                        (0.6, (255, 206, 132)), (1, (255, 206, 132))])
    img = _light(img, _radial(size, sx, sy, 0.75 * w, 0.62 * h, power=2.2), (255, 150, 70))
    img = _light(img, _radial(size, sx, sy, sr * 4, power=2.4), (255, 230, 170))
    img = _paint(img, _disc(size, sx, sy, sr), (255, 246, 220))
    # thin strands of cloud drifting across the sun
    strands = Image.new("L", size)
    d = ImageDraw.Draw(strands)
    for _ in range(14):
        cx, cy = w * (0.5 + rng.gauss(0, 0.16)), h * rng.uniform(0.33, 0.5)
        cw, ch = w * rng.uniform(0.08, 0.22), h * rng.uniform(0.004, 0.012)
        d.ellipse((cx - cw, cy - ch, cx + cw, cy + ch), fill=rng.randint(120, 220))
    strands = _blur(strands, 4 * u)
    img = _paint(img, strands, (130, 60, 100), 0.75)
    edge = ImageChops.subtract(strands, ImageChops.offset(strands, 0, -int(4 * u) - 1))
    img = _light(img, ImageChops.multiply(edge, _radial(size, sx, sy, 0.4 * w, 0.3 * h)), (255, 210, 150), 2)
    img = _light(img, _disc(size, sx, sy, sr), (255, 240, 205), 0.75)
    # ridges, hazy and warm at the back, near black at the front, opening into a valley around the sun
    haze, far, near = (244, 150, 116), (206, 104, 118), (26, 12, 36)
    for i in range(5):
        t = i / 4
        base, amp = h * (0.56 + 0.085 * i), h * (0.025 + 0.03 * i)
        pts = _ridge(rng, w, base, amp, rough=0.5 + 0.06 * t)
        dip = h * (0.02 + 0.1 * t)
        pts = [(x, y + dip * (math.exp(-((x - sx) / (0.22 * w)) ** 2) - 0.45)) for x, y in pts]
        colour = _mix(far, near, t ** 0.8)
        mist = _mix(colour, haze, 0.45 * (1 - t) + 0.12)
        top = min(y for _, y in pts) / h
        img = _paint(img, _below(size, pts), _vgrad(w, h, [(top, colour), (min(0.99, top + 0.12 + 0.05 * i), mist)]))
    # birds
    d = ImageDraw.Draw(img)
    for _ in range(6):
        bx, by, s = w * rng.uniform(0.53, 0.64), h * rng.uniform(0.3, 0.4), rng.uniform(6, 13) * u
        d.line((bx - s, by - s * 0.4, bx, by, bx + s, by - s * 0.5), fill=(40, 18, 40), width=max(1, int(2 * u)))
    return img


@_scene
def ocean(w, h):
    """Dusk over the sea: a low sun, cloud banks lit from below, a glittering path and a small sailboat."""
    rng = random.Random(404)
    u, size = h / 1080, (w, h)
    hz = int(0.57 * h)
    sx, sr = 0.5 * w, 0.055 * h
    sy = hz - 0.55 * sr
    img = _vgrad(w, h, [(0, (22, 28, 72)), (0.3, (72, 60, 122)), (0.48, (204, 110, 112)), (0.57, (255, 188, 122)),
                        (1, (255, 188, 122))])
    img = _light(img, _radial(size, sx, sy, 0.7 * w, 0.5 * h, power=2.0), (255, 140, 60))
    img = _light(img, _radial(size, sx, sy, 5 * sr, power=2.6), (255, 222, 165))
    clouds = _curve(_noise(rng, w, h, 2, 6, 0.6, stretch=5), lambda v: (v - 118) * 2.6)
    clouds = ImageChops.multiply(clouds, _vgrad(w, h, [(0.1, 0), (0.24, 255), (0.4, 255), (0.5, 0)]))
    img = _paint(img, clouds, (76, 46, 94), 0.9)
    under = ImageChops.subtract(clouds, ImageChops.offset(clouds, 0, -int(7 * u) - 1))
    lit = ImageChops.multiply(_blur(under, 2 * u), _radial(size, sx, sy, 0.6 * w, 0.45 * h, power=0.8))
    img = _light(img, lit, (255, 172, 112), 2.2)
    img = _paint(img, _disc(size, sx, sy, sr), (255, 242, 214))
    # the sea, with streaky swell
    sea_h = h - hz
    sea = _vgrad(w, sea_h, [(0, (176, 104, 112)), (0.25, (72, 52, 92)), (1, (12, 16, 40))])
    swell = _curve(_noise(rng, w, sea_h, 8, 5, 0.6, stretch=14), lambda v: (v - 128) * 2 + 128)
    sea = Image.composite(sea.point(lambda v: min(255, int(v * 1.3) + 6)), sea.point(lambda v: int(v * 0.8)), swell)
    img.paste(sea, (0, hz))
    img = _light(img, _radial(size, sx, hz + 0.16 * h, 0.06 * w, 0.22 * h, power=1.3), (255, 160, 100), 0.7)
    glitter = Image.new("L", size)
    d = ImageDraw.Draw(glitter)
    for _ in range(int(1500 * w / 1920)):
        t = rng.random() ** 1.5
        y = hz + 2 * u + t * sea_h
        spread = sr * 0.8 + t * 0.3 * w
        x = sx + rng.gauss(0, spread / 2.6)
        ln = (4 + 70 * t) * u * rng.uniform(0.4, 1.4)
        v = int(255 * max(0.0, 1 - abs(x - sx) / (spread * 1.1)) * rng.uniform(0.4, 1))
        d.line((x - ln / 2, y, x + ln / 2, y), fill=v, width=max(1, int((1 + 3 * t) * u)))
    img = _light(img, glitter, (255, 218, 165))
    img = _light(img, _blur(glitter, 6 * u), (255, 170, 110), 1.5)
    seam = Image.new("L", size)
    ImageDraw.Draw(seam).line((0, hz, w, hz), fill=255, width=max(1, int(2 * u)))
    seam = ImageChops.multiply(_blur(seam, 1.5 * u), _hgrad(w, h, [(0.1, 40), (0.5, 255), (0.9, 40)]))
    img = _light(img, seam, (255, 214, 165), 0.8)
    # sailboat
    bx, s = 0.41 * w, 0.06 * h
    d = ImageDraw.Draw(img)
    hull = (20, 12, 30)
    d.polygon([(bx - 0.5 * s, hz - 0.06 * s), (bx + 0.48 * s, hz - 0.06 * s), (bx + 0.36 * s, hz + 0.05 * s),
               (bx - 0.4 * s, hz + 0.05 * s)], fill=hull)
    d.polygon([(bx, hz - 0.1 * s), (bx, hz - 1.15 * s), (bx + 0.48 * s, hz - 0.12 * s)], fill=hull)
    d.polygon([(bx - 0.04 * s, hz - 1.0 * s), (bx - 0.42 * s, hz - 0.12 * s), (bx - 0.04 * s, hz - 0.12 * s)], fill=hull)
    return img


@_scene
def forest(w, h):
    """Misty pine forest in receding layers, with sun rays slanting through the fog."""
    rng = random.Random(505)
    u, size = h / 1080, (w, h)
    fog = (182, 202, 186)
    lx = 0.56 * w
    img = _vgrad(w, h, [(0, (216, 228, 206)), (0.5, (150, 176, 160)), (1, (70, 94, 84))])
    img = _light(img, _radial(size, lx, 0.08 * h, 0.42 * w, 0.6 * h, power=1.4), (255, 240, 200))
    layers = [(0.6, 0.1, 0.2, (142, 168, 154)), (0.66, 0.16, 0.3, (112, 140, 126)), (0.75, 0.26, 0.44, (72, 98, 88)),
              (0.87, 0.42, 0.66, (36, 56, 50)), (1.05, 0.7, 1.05, (12, 22, 20))]
    for i, (base, hmin, hmax, colour) in enumerate(layers):
        if i == 3:  # rays fall between the far trees and the two nearest rows
            rays = Image.new("L", size)
            d = ImageDraw.Draw(rays)
            ox, oy = lx + 0.12 * w, -0.3 * h
            for _ in range(12):
                a, wa = math.radians(rng.uniform(100, 122)), math.radians(rng.uniform(0.6, 2.2))
                reach = 2 * h
                d.polygon([(ox, oy), (ox + math.cos(a - wa) * reach, oy + math.sin(a - wa) * reach),
                           (ox + math.cos(a + wa) * reach, oy + math.sin(a + wa) * reach)], fill=rng.randint(60, 150))
            rays = ImageChops.multiply(_blur(rays, 12 * u), _vgrad(w, h, [(0, 255), (0.95, 50)]))
            img = _light(img, rays, (255, 244, 210), 1.4)
        m = Image.new("L", size)
        d = ImageDraw.Draw(m)
        ground = _waves(rng, w, base * h, [(0.012 * h, 0.6 * w), (0.006 * h, 0.21 * w)])
        d.polygon(ground + [(w, h + 1), (0, h + 1)], fill=255)
        x = -rng.uniform(0, 0.05 * w)
        while x < w * 1.03:
            th = rng.uniform(hmin, hmax) * h
            gap = th * rng.uniform(0.14, 0.32)
            if not (i >= 3 and abs(x - lx + 0.04 * w) < 0.1 * w * (i - 2)):  # leave a clearing for the light
                _pine(d, rng, x, _at(ground, x) + rng.uniform(0, 0.01) * h, th)
            x += gap
        img = _paint(img, m.filter(ImageFilter.GaussianBlur(0.7 * u)), colour)
        if i < 3:
            img = _paint(img, _vgrad(w, h, [(base - 0.16, 0), (base + 0.01, 150)]), fog)
    return img


@_scene
def desert(w, h):
    """Sharp-crested dunes under a pale dusk sky, a pale moon and a small camel train on a far ridge."""
    rng = random.Random(606)
    u, size = h / 1080, (w, h)
    img = _vgrad(w, h, [(0, (112, 128, 178)), (0.32, (170, 168, 204)), (0.52, (236, 204, 192)), (0.6, (250, 218, 190)),
                        (1, (250, 218, 190))])
    img = _light(img, _radial(size, 0.72 * w, 0.6 * h, 0.5 * w, 0.32 * h, power=1.5), (255, 196, 140), 0.6)
    mx, my, mr = 0.42 * w, 0.3 * h, 0.06 * h
    img = _light(img, _radial(size, mx, my, 3.5 * mr, power=2.5), (255, 250, 240), 0.5)
    disc = _disc(size, mx, my, mr)
    img = _paint(img, disc, (250, 247, 240), 0.92)
    maria = ImageChops.multiply(_curve(_noise(rng, w, h, 30, 3, 0.6), lambda v: (v - 120) * 1.6), disc)
    img = _paint(img, maria, (196, 194, 214), 0.45)
    xs = [i * w / 480 for i in range(481)]
    layers = [(0.6, 0.03, 0.22), (0.66, 0.055, 0.34), (0.745, 0.08, 0.5), (0.85, 0.11, 0.75), (0.98, 0.14, 1.1)]
    for i, (base, amp, lam) in enumerate(layers):
        t = i / (len(layers) - 1)
        ph, ph2, skew = rng.uniform(0, 6.3), rng.uniform(0, 6.3), rng.uniform(0.3, 0.6)
        def ridge(x, base=base * h, amp=amp * h, lam=lam * w):
            th = 2 * math.pi * x / lam + ph
            th += skew * math.sin(th)
            return base - amp * (1 - abs(math.sin(th / 2))) ** 1.6 + amp * 0.35 * math.sin(x / lam * 2.3 + ph2)
        ys = [ridge(x) for x in xs]
        pts = list(zip(xs, ys))
        lit = _mix((246, 210, 182), (234, 160, 104), t ** 0.7)
        dark = _mix((214, 172, 176), (122, 70, 86), t ** 0.7)
        body = _below(size, pts)
        top = min(ys) / h
        img = _paint(img, body, _vgrad(w, h, [(top, lit), (min(0.99, top + 0.16), _mix(lit, dark, 0.35))]))
        # shadowed slip faces: faces turned away from the light (on the right), deepest where steep
        low = [y + min(0.2 * h, max(0.0, (ys[max(0, j - 1)] - ys[min(len(ys) - 1, j + 1)]) / (2 * w / 480)) * 0.6 * h)
               for j, y in enumerate(ys)]
        sh = Image.new("L", size)
        ImageDraw.Draw(sh).polygon(pts + list(zip(xs, low))[::-1], fill=255)
        sh = ImageChops.multiply(ImageChops.lighter(sh, _blur(sh, 9 * u)), body)
        img = _paint(img, sh, _vgrad(w, h, [(top, dark), (min(0.99, top + 0.2), _mix(dark, (60, 30, 50), 0.4))]))
        if i == 1:  # camel train walking along this crest
            d = ImageDraw.Draw(img)
            for k in range(4):
                cx = w * 0.47 + k * 0.026 * w
                _camel(d, cx, _at(pts, cx) + 0.004 * h, 0.03 * h * (1 - 0.06 * k), (90, 56, 64))
    return img


def _camel(d, x, y, s, fill):
    """Tiny camel with rider walking right, feet at (x, y), about s tall."""
    lw = max(1, int(0.07 * s))
    for lx, dx in ((-0.3, -0.07), (-0.2, 0.06), (0.17, -0.06), (0.28, 0.07)):
        d.line((x + lx * s, y - 0.55 * s, x + (lx + dx) * s, y), fill=fill, width=lw)
    d.ellipse((x - 0.42 * s, y - 0.8 * s, x + 0.38 * s, y - 0.48 * s), fill=fill)
    d.ellipse((x - 0.22 * s, y - 0.98 * s, x + 0.14 * s, y - 0.62 * s), fill=fill)
    d.polygon([(x + 0.28 * s, y - 0.72 * s), (x + 0.48 * s, y - 1.0 * s), (x + 0.58 * s, y - 0.96 * s),
               (x + 0.4 * s, y - 0.6 * s)], fill=fill)
    d.ellipse((x + 0.47 * s, y - 1.07 * s, x + 0.72 * s, y - 0.93 * s), fill=fill)
    d.polygon([(x - 0.06 * s, y - 0.9 * s), (x - 0.02 * s, y - 1.32 * s), (x + 0.1 * s, y - 1.32 * s),
               (x + 0.12 * s, y - 0.9 * s)], fill=fill)
    d.ellipse((x - 0.02 * s, y - 1.48 * s, x + 0.12 * s, y - 1.3 * s), fill=fill)


@_scene
def aurora(w, h):
    """Green and violet aurora curtains over snowy hills, with a lit cabin."""
    rng = random.Random(707)
    u, size = h / 1080, (w, h)
    img = _vgrad(w, h, [(0, (4, 8, 24)), (0.45, (10, 26, 50)), (0.66, (28, 60, 82)), (1, (28, 60, 82))])
    img = _stars(img, rng, int(1500 * w * h / 2073600), y1=0.7)
    img = _curtain(img, rng, 0.38 * h, 0.04 * h, 0.22 * h, 0.55)
    img = _curtain(img, rng, 0.52 * h, 0.06 * h, 0.34 * h, 1.0)
    # far hill with a pine fringe
    far = _waves(rng, w, 0.67 * h, [(0.015 * h, 0.7 * w), (0.008 * h, 0.23 * w)])
    img = _paint(img, _below(size, far), _vgrad(w, h, [(0.64, (52, 74, 104)), (0.8, (30, 44, 66))]))
    m = Image.new("L", size)
    d = ImageDraw.Draw(m)
    x = 0.0
    while x < w:
        if rng.random() < 0.7:
            _pine(d, rng, x, _at(far, x) + 3 * u, rng.uniform(0.025, 0.06) * h)
        x += rng.uniform(6, 22) * u
    img = _paint(img, m.filter(ImageFilter.GaussianBlur(0.6 * u)), (12, 20, 34))
    near = _waves(rng, w, 0.79 * h, [(0.035 * h, 1.1 * w), (0.01 * h, 0.3 * w)])
    snow = _below(size, near)
    img = _paint(img, snow, _vgrad(w, h, [(0.72, (156, 182, 210)), (1, (64, 86, 118))]))
    img = _light(img, ImageChops.multiply(snow, _radial(size, 0.5 * w, 0.76 * h, 0.5 * w, 0.18 * h)), (60, 170, 120), 0.45)
    # cabin with a warm window
    cx, s = 0.6 * w, 0.06 * h
    cy = _at(near, cx) + 0.01 * h
    d = ImageDraw.Draw(img)
    wall = (16, 20, 30)
    d.rectangle((cx - 0.6 * s, cy - 0.7 * s, cx + 0.6 * s, cy), fill=wall)
    d.polygon([(cx - 0.78 * s, cy - 0.66 * s), (cx, cy - 1.25 * s), (cx + 0.78 * s, cy - 0.66 * s)], fill=wall)
    d.polygon([(cx - 0.8 * s, cy - 0.64 * s), (cx, cy - 1.27 * s), (cx + 0.8 * s, cy - 0.64 * s), (cx, cy - 1.12 * s)],
              fill=(176, 196, 220))
    d.rectangle((cx + 0.3 * s, cy - 1.2 * s, cx + 0.44 * s, cy - 0.9 * s), fill=wall)
    glow = Image.new("L", size)
    ImageDraw.Draw(glow).rectangle((cx - 0.38 * s, cy - 0.5 * s, cx - 0.08 * s, cy - 0.22 * s), fill=255)
    img = _light(img, glow, (255, 196, 120))
    img = _light(img, _blur(glow, 14 * u), (255, 150, 70), 4)
    return img


def _curtain(img, rng, base, amp, height, strength):
    """One aurora curtain: vertical rays, brightest along a wavy lower edge, bent into place with a mesh warp."""
    w, h = img.size
    u, hc = h / 1080, max(8, int(height))

    def row(cells):
        return Image.frombytes("L", (cells, 1), rng.randbytes(cells)).resize((w, 1), Image.BICUBIC)

    fine = _curve(row(max(4, w // 6)), lambda v: 255 * (v / 255) ** 1.5 * 1.5)
    folds = _curve(row(max(4, w // 110)), lambda v: (v - 50) * 1.6)
    rays = ImageChops.multiply(fine, folds)
    rays = ImageChops.multiply(rays, _hgrad(w, 1, [(0.05, 0), (0.3, 255), (0.75, 255), (0.97, 0)])).resize((w, hc))
    green = ImageChops.multiply(rays, _vgrad(w, hc, [(0, 0), (0.5, 60), (0.9, 255), (1, 0)]))
    violet = ImageChops.multiply(rays, _vgrad(w, hc, [(0, 0), (0.18, 150), (0.55, 0)]))
    p1, p2, p3 = (rng.uniform(0, 6.3) for _ in range(3))
    edge = lambda x: base + amp * math.sin(x / w * 7 + p1) + amp * 0.45 * math.sin(x / w * 17 + p2)
    tall = lambda x: hc * (0.75 + 0.25 * math.sin(x / w * 5 + p3))
    mesh, step = [], max(4, int(10 * u))
    for x0 in range(0, w, step):
        x1 = min(w, x0 + step)
        b0, b1, t0, t1 = edge(x0), edge(x1), tall(x0), tall(x1)
        top, bot = int(min(b0 - t0, b1 - t1)), int(max(b0, b1)) + 1
        src = lambda y, b, t: (y - b + t) * hc / t
        mesh.append(((x0, top, x1, bot), (x0, src(top, b0, t0), x0, src(bot, b0, t0),
                                         x1, src(bot, b1, t1), x1, src(top, b1, t1))))
    green, violet = (m.transform((w, h), Image.MESH, mesh, Image.BILINEAR) for m in (green, violet))
    img = _light(img, _blur(green, 22 * u), (40, 200, 130), 1.1 * strength)
    img = _light(img, _blur(green, 2.5 * u), (100, 255, 175), 1.15 * strength)
    return _light(img, _blur(violet, 3 * u), (170, 70, 215), 0.9 * strength)


@_scene
def storm(w, h):
    """Thunderstorm over a dark plain: a branching lightning strike, rain shafts, a lone tree and a fence."""
    rng = random.Random(808)
    u, size = h / 1080, (w, h)
    hz = int(0.7 * h)
    n = _noise(rng, w, h, 3, 6, 0.6)
    clouds = ImageOps.colorize(n, (12, 14, 24), (136, 144, 166), mid=(46, 52, 72))
    sky = _vgrad(w, h, [(0, (20, 22, 32)), (0.5, (52, 58, 76)), (0.7, (108, 112, 126)), (1, (108, 112, 126))])
    img = Image.composite(clouds, sky, _vgrad(w, h, [(0, 235), (0.6, 130), (0.7, 60)]))
    bx, by, ex = 0.47 * w, 0.2 * h, 0.535 * w
    lit = ImageChops.multiply(_radial(size, bx + 0.02 * w, by + 0.06 * h, 0.4 * w, 0.32 * h, power=1.3), n)
    img = _light(img, lit, (170, 182, 255), 1.1)
    # rain shafts falling either side of the strike
    rain = Image.new("L", size)
    d = ImageDraw.Draw(rain)
    for _ in range(int(1100 * w / 1920)):
        x, y, ln = rng.uniform(0, w), rng.uniform(0.25, 0.7) * h, rng.uniform(30, 90) * u
        d.line((x, y, x - 0.22 * ln, y + ln), fill=rng.randint(30, 90))
    shafts = _hgrad(w, h, [(0, 255), (0.25, 200), (0.38, 0), (0.62, 0), (0.75, 220), (1, 255)])
    shafts = ImageChops.multiply(shafts, _vgrad(w, h, [(0.25, 0), (0.4, 255)]))
    img = _light(img, ImageChops.multiply(rain.filter(ImageFilter.GaussianBlur(0.7 * u)), shafts), (180, 190, 210))
    img = _light(img, ImageChops.multiply(_blur(shafts, 30 * u), _vgrad(w, h, [(0.3, 0), (0.7, 255)])), (80, 86, 104), 0.35)
    # the plain, with a low treeline and the flash on the ground
    land = _ridge(rng, w, hz, 0.006 * h, rough=0.6)
    ground = _below(size, land)
    img = _paint(img, ground, _vgrad(w, h, [(0.69, (42, 44, 54)), (1, (10, 10, 14))]))
    img = _light(img, ImageChops.multiply(ground, _radial(size, ex, hz, 0.32 * w, 0.07 * h)), (150, 160, 230), 0.9)
    # lightning
    bolt = Image.new("L", size)
    d = ImageDraw.Draw(bolt)
    main = _zigzag(rng, bx, by, ex, hz + 0.004 * h, 0.05 * w, 7)
    d.line(main, fill=255, width=max(2, int(4 * u)), joint="curve")
    for _ in range(7):
        x0, y0 = main[rng.randrange(len(main) // 8, int(len(main) * 0.7))]
        a, ln = math.radians(90 + rng.choice((-1, 1)) * rng.uniform(20, 55)), rng.uniform(0.07, 0.2) * h
        br = _zigzag(rng, x0, y0, x0 + math.cos(a) * ln, y0 + math.sin(a) * ln, ln * 0.25, 5)
        d.line(br, fill=210, width=max(1, int(2 * u)), joint="curve")
        for _ in range(2):
            x1, y1 = br[rng.randrange(len(br) // 3, len(br))]
            a2, l2 = a + math.radians(rng.uniform(-35, 35)), ln * rng.uniform(0.25, 0.5)
            d.line(_zigzag(rng, x1, y1, x1 + math.cos(a2) * l2, y1 + math.sin(a2) * l2, l2 * 0.25, 4), fill=150)
    img = _light(img, _blur(bolt, 45 * u), (110, 120, 255), 9)
    img = _light(img, _blur(bolt, 10 * u), (150, 160, 255), 4)
    img = _light(img, _blur(bolt, 2.5 * u), (200, 210, 255), 1.6)
    img = _light(img, bolt, (255, 255, 255))
    # lone tree and a fence running off towards the horizon
    sil = Image.new("L", size)
    d = ImageDraw.Draw(sil)
    tx, ty = 0.35 * w, hz + 0.008 * h
    d.polygon([(tx - 0.008 * h, ty), (tx - 0.003 * h, ty - 0.1 * h), (tx + 0.004 * h, ty - 0.1 * h), (tx + 0.009 * h, ty)],
              fill=255)
    for _ in range(14):
        cx, cy, r = tx + rng.gauss(0, 0.028 * h), ty - 0.13 * h + rng.gauss(0, 0.02 * h), rng.uniform(0.02, 0.04) * h
        d.ellipse((cx - r * 1.2, cy - r, cx + r * 1.2, cy + r), fill=255)
    posts = []
    for k in range(14):
        z = 1 + k * 0.8
        px, py = 0.5 * w + (0.02 * w - 0.5 * w) / z, hz + (0.99 * h - hz) / z
        ph, pw = 0.14 * h / z, max(1, 9 * u / z)
        d.rectangle((px - pw, py - ph, px + pw, py), fill=255)
        posts.append((px, py, ph))
    for f in (0.85, 0.45):
        d.line([(px, py - ph * f) for px, py, ph in posts], fill=255, width=max(1, int(2 * u)))
    return _paint(img, sil.filter(ImageFilter.GaussianBlur(0.7 * u)), (8, 8, 12))


@_scene
def stage(w, h):
    """Concert stage: coloured spotlight beams through haze, a backlit singer and a crowd with phones up."""
    rng = random.Random(909)
    u, size = h / 1080, (w, h)
    img = _vgrad(w, h, [(0, (8, 4, 16)), (0.55, (28, 12, 42)), (0.75, (14, 6, 22)), (1, (6, 3, 10))])
    haze = _noise(rng, w, h, 3, 5, 0.6)
    img = _light(img, ImageChops.multiply(_radial(size, 0.5 * w, 0.5 * h, 0.45 * w, 0.42 * h, power=1.2), haze),
                 (120, 40, 180), 0.8)
    floor, fy = 0.7 * h, 0.18 * h
    colours = [(255, 50, 180), (60, 190, 255), (150, 80, 255), (255, 160, 60)]
    beams = [Image.new("L", size) for _ in colours]
    lamps = Image.new("L", size)
    for k in range(8):
        fx = w * (0.22 + 0.56 * k / 7)
        ci = (0, 1, 2, 3, 3, 2, 1, 0)[k]
        tx = fx + (0.5 * w - fx) * rng.uniform(0.3, 1.6) + rng.uniform(-0.12, 0.12) * w
        sp = rng.uniform(0.04, 0.08) * w
        ImageDraw.Draw(beams[ci]).polygon([(fx - 4 * u, fy), (fx + 4 * u, fy), (tx + sp, h), (tx - sp, h)],
                                          fill=rng.randint(120, 210))
        ImageDraw.Draw(lamps).ellipse((fx - 7 * u, fy - 7 * u, fx + 7 * u, fy + 7 * u), fill=255)
    fade = _vgrad(w, h, [(0.15, 255), (0.75, 80), (1, 40)])
    smoke = _curve(haze, lambda v: 80 + v * 0.7)
    for m, colour in zip(beams, colours):
        img = _light(img, ImageChops.multiply(ImageChops.multiply(_blur(m, 7 * u), fade), smoke), colour, 0.95)
    img = _light(img, _blur(lamps, 14 * u), (255, 220, 255), 3)
    img = _light(img, lamps, (255, 255, 255))
    # backlight behind the singer, with a horizontal lens streak
    img = _light(img, _radial(size, 0.5 * w, 0.5 * h, 0.3 * w, 0.32 * h, power=2.2), (225, 215, 255))
    img = _light(img, _radial(size, 0.5 * w, 0.5 * h, 0.07 * h, power=1.5), (255, 255, 255))
    streak = Image.new("L", size)
    ImageDraw.Draw(streak).line((0.12 * w, 0.5 * h, 0.88 * w, 0.5 * h), fill=255, width=max(1, int(3 * u)))
    streak = ImageChops.multiply(_blur(streak, 2 * u), _hgrad(w, h, [(0.12, 0), (0.5, 255), (0.88, 0)]))
    img = _light(img, streak, (110, 150, 255))
    # stage floor
    img = _paint(img, _vgrad(w, h, [(0.7 - 0.001, 0), (0.7, 255)]), (18, 10, 28))
    img = _light(img, _radial(size, 0.5 * w, floor + 0.03 * h, 0.34 * w, 0.06 * h), (190, 170, 255), 0.6)
    edge = Image.new("L", size)
    ImageDraw.Draw(edge).line((0.1 * w, floor, 0.9 * w, floor), fill=255, width=max(1, int(2 * u)))
    img = _light(img, ImageChops.multiply(_blur(edge, 1.5 * u), _hgrad(w, h, [(0.1, 0), (0.5, 255), (0.9, 0)])),
                 (210, 180, 255))
    sil = Image.new("L", size)
    d = ImageDraw.Draw(sil)
    _singer(d, 0.5 * w, floor + 0.005 * h, 0.25 * h)
    # crowd, some with arms or phones up
    phones = Image.new("L", size)
    pd = ImageDraw.Draw(phones)
    x = -20 * u
    while x < w + 20 * u:
        r, top = rng.uniform(0.026, 0.036) * h, rng.uniform(0.84, 0.89) * h
        d.ellipse((x - r, top - r, x + r, top + r), fill=255)
        d.ellipse((x - 2.6 * r, top + 0.8 * r, x + 2.6 * r, top + 6 * r), fill=255)
        if rng.random() < 0.3:
            sgn = rng.choice((-1, 1))
            hx, hy = x + sgn * rng.uniform(1.6, 2.6) * r, top - rng.uniform(2.5, 5.5) * r
            d.line((x + sgn * 1.6 * r, top + 1.6 * r, hx, hy), fill=255, width=max(2, int(0.55 * r)))
            d.ellipse((hx - 0.4 * r, hy - 0.4 * r, hx + 0.4 * r, hy + 0.4 * r), fill=255)
            if rng.random() < 0.4:
                pd.rectangle((hx - 0.28 * r, hy - 1.1 * r, hx + 0.28 * r, hy - 0.3 * r), fill=255)
        x += r * rng.uniform(2.2, 3.2)
    img = _paint(img, sil.filter(ImageFilter.GaussianBlur(0.7 * u)), (4, 2, 8))
    img = _light(img, phones, (220, 230, 255))
    return _light(img, _blur(phones, 6 * u), (140, 170, 255), 2)


def _singer(d, x, y, s):
    """Singer silhouette, feet at (x, y), about s tall, one arm raised and a mic stand."""
    lw = max(2, int(0.07 * s))
    d.line((x - 0.08 * s, y, x - 0.03 * s, y - 0.48 * s), fill=255, width=lw)
    d.line((x + 0.1 * s, y, x + 0.03 * s, y - 0.48 * s), fill=255, width=lw)
    d.polygon([(x - 0.08 * s, y - 0.5 * s), (x + 0.08 * s, y - 0.5 * s), (x + 0.12 * s, y - 0.8 * s),
               (x - 0.12 * s, y - 0.8 * s)], fill=255)
    d.ellipse((x - 0.055 * s, y - 0.94 * s, x + 0.055 * s, y - 0.8 * s), fill=255)
    d.line((x + 0.1 * s, y - 0.78 * s, x + 0.2 * s, y - 0.92 * s, x + 0.24 * s, y - 1.08 * s), fill=255,
           width=int(lw * 0.8), joint="curve")
    d.ellipse((x + 0.215 * s, y - 1.12 * s, x + 0.27 * s, y - 1.06 * s), fill=255)
    d.line((x - 0.1 * s, y - 0.78 * s, x - 0.13 * s, y - 0.64 * s, x - 0.07 * s, y - 0.84 * s), fill=255,
           width=int(lw * 0.8), joint="curve")
    d.line((x - 0.2 * s, y, x - 0.08 * s, y - 0.86 * s), fill=255, width=max(1, lw // 3))
    d.line((x - 0.26 * s, y, x - 0.14 * s, y, x - 0.2 * s, y - 0.02 * s), fill=255, width=max(1, lw // 3))


@_scene
def moon(w, h):
    """Spooky full moon behind a bare twisted tree, with bats, gravestones and ground mist."""
    rng = random.Random(1010)
    u, size = h / 1080, (w, h)
    mx, my, mr = 0.53 * w, 0.4 * h, 0.17 * h
    img = _vgrad(w, h, [(0, (6, 10, 20)), (0.45, (16, 30, 42)), (1, (10, 16, 22))])
    img = _stars(img, rng, int(600 * w * h / 2073600), y1=0.6, big=0.02)
    img = _light(img, _radial(size, mx, my, 0.6 * w, 0.7 * h, power=1.8), (90, 132, 130), 0.9)
    img = _light(img, _radial(size, mx, my, 2.1 * mr, power=2.4), (200, 226, 212))
    tex = ImageOps.colorize(_noise(rng, w, h, 14, 5, 0.6), (150, 156, 150), (250, 248, 230), mid=(222, 222, 206))
    limb = _curve(_radial(size, mx, my, mr * 1.1, power=0.35), lambda v: 150 + v * 0.42)
    img = _paint(img, _disc(size, mx, my, mr), ImageChops.multiply(tex, limb.convert("RGB")))
    craters = Image.new("L", size)
    d = ImageDraw.Draw(craters)
    for _ in range(10):
        a, dist, r = rng.uniform(0, 6.3), mr * rng.uniform(0, 0.8), mr * rng.uniform(0.04, 0.12)
        cx, cy = mx + math.cos(a) * dist, my + math.sin(a) * dist
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=70, outline=20, width=max(1, int(r / 5)))
    img = _paint(img, _blur(craters, 1.2 * u), (150, 152, 140))
    wisp = _curve(_noise(rng, w, h, 2, 6, 0.6, stretch=6), lambda v: (v - 125) * 2.2)
    wisp = ImageChops.multiply(wisp, _vgrad(w, h, [(0.3, 0), (0.43, 255), (0.5, 255), (0.62, 0)]))
    img = _paint(img, wisp, (28, 40, 48), 0.72)
    img = _light(img, ImageChops.multiply(wisp, _radial(size, mx, my, 1.7 * mr, power=1.5)), (150, 172, 170), 0.5)
    # hill, trees, gravestones
    hill = [(x, y - 0.1 * h * math.exp(-((x - 0.32 * w) / (0.24 * w)) ** 2))
            for x, y in _waves(rng, w, 0.83 * h, [(0.01 * h, 0.5 * w), (0.004 * h, 0.13 * w)])]
    sil = _below(size, hill)
    d = ImageDraw.Draw(sil)
    _tree(d, rng, 0.33 * w, _at(hill, 0.33 * w) + 0.01 * h, 0.14 * h, 0.03 * h, 9, angle=-82, spread=32)
    _tree(d, rng, 0.78 * w, _at(hill, 0.78 * w) + 0.01 * h, 0.07 * h, 0.014 * h, 8, angle=-95, spread=30)
    for k in range(6):
        gx = w * (0.45 + 0.045 * k + rng.uniform(-0.01, 0.01))
        gy, gh = _at(hill, gx) + 0.012 * h, rng.uniform(0.035, 0.06) * h
        gw = gh * rng.uniform(0.45, 0.6)
        if rng.random() < 0.3:  # a cross
            d.rectangle((gx - gw * 0.14, gy - gh * 1.2, gx + gw * 0.14, gy), fill=255)
            d.rectangle((gx - gw * 0.5, gy - gh * 0.95, gx + gw * 0.5, gy - gh * 0.75), fill=255)
        else:
            d.rectangle((gx - gw / 2, gy - gh + gw / 2, gx + gw / 2, gy), fill=255)
            d.ellipse((gx - gw / 2, gy - gh, gx + gw / 2, gy - gh + gw), fill=255)
    # bats
    wing = [(0.05, -0.28), (0.1, -0.12), (0.3, -0.18), (0.6, -0.3), (1.0, -0.36), (0.86, -0.12), (0.72, 0.02),
            (0.6, -0.04), (0.47, 0.08), (0.35, 0.0), (0.22, 0.12), (0.1, 0.1), (0.0, 0.25)]
    shape = [(0, -0.15)] + wing + [(-x, y) for x, y in reversed(wing[:-1])]
    for _ in range(7):
        a, dist = rng.uniform(0, 6.3), mr * rng.uniform(0.6, 2.4)
        bx, by, s = mx + math.cos(a) * dist * 1.4, my + math.sin(a) * dist * 0.7, rng.uniform(12, 26) * u
        flap = rng.uniform(0.6, 1.3)
        d.polygon([(bx + x * s, by + y * s * flap) for x, y in shape], fill=255)
    img = _paint(img, sil.filter(ImageFilter.GaussianBlur(0.6 * u)), (5, 8, 11))
    mist = ImageChops.multiply(_noise(rng, w, h, 3, 5, 0.6, stretch=4), _vgrad(w, h, [(0.7, 0), (0.82, 200), (0.95, 120)]))
    return _light(img, mist, (96, 128, 128), 0.55)


@_scene
def hills(w, h):
    """Bright cartoon day: a soft sun, puffy clouds and rolling green hills with round trees and flowers."""
    rng = random.Random(1111)
    u, size = h / 1080, (w, h)
    img = _vgrad(w, h, [(0, (66, 146, 232)), (0.55, (150, 208, 250)), (0.68, (206, 236, 255)), (1, (206, 236, 255))])
    sx, sy, sr = 0.62 * w, 0.27 * h, 0.07 * h
    img = _light(img, _radial(size, sx, sy, 0.4 * w, 0.4 * h, power=1.6), (255, 246, 200), 0.9)
    img = _paint(img, _disc(size, sx, sy, sr * 1.25), (255, 244, 176), 0.6)
    img = _paint(img, _disc(size, sx, sy, sr), (255, 232, 110))
    for cx, cy, s in ((0.38, 0.3, 0.26), (0.66, 0.44, 0.2), (0.17, 0.44, 0.15), (0.86, 0.22, 0.17), (0.52, 0.16, 0.12)):
        m = Image.new("L", size)
        _cloud(ImageDraw.Draw(m), rng, cx * w, cy * h, s * w)
        m = m.filter(ImageFilter.GaussianBlur(1.5 * u))
        img = _paint(img, m, (198, 218, 242))
        img = _paint(img, ImageChops.multiply(m, ImageChops.offset(m, 0, -int(0.016 * h))), (255, 255, 255))
    layers = [(0.6, 0.025, (164, 222, 170), (130, 196, 150)), (0.67, 0.035, (146, 222, 118), (98, 186, 92)),
              (0.77, 0.045, (118, 206, 84), (72, 164, 60)), (0.9, 0.055, (96, 186, 62), (48, 132, 40))]
    for i, (base, amp, top_c, low_c) in enumerate(layers):
        pts = _waves(rng, w, base * h, [(amp * h, 0.95 * w), (amp * 0.5 * h, 0.37 * w)])
        top = min(y for _, y in pts) / h
        img = _paint(img, _below(size, pts), _vgrad(w, h, [(top, top_c), (min(0.99, top + 0.14), low_c)]))
        d = ImageDraw.Draw(img)
        if i == 2:  # round trees along the crest
            for k in range(6):
                tx = w * (0.3 + 0.08 * k + rng.uniform(-0.02, 0.02))
                ty, r = _at(pts, tx) + 0.012 * h, rng.uniform(0.024, 0.036) * h
                d.rectangle((tx - 0.15 * r, ty - 1.6 * r, tx + 0.15 * r, ty), fill=(116, 80, 52))
                d.ellipse((tx - r, ty - 2.9 * r, tx + r, ty - 0.9 * r), fill=(46, 140, 58))
                d.ellipse((tx - 0.65 * r, ty - 2.75 * r, tx + 0.25 * r, ty - 1.85 * r), fill=(96, 184, 82))
        if i == 3:  # flowers
            for _ in range(140):
                fx = rng.uniform(0, w)
                fy, r = rng.uniform(_at(pts, fx) + 0.01 * h, h), rng.uniform(2.5, 4.5) * u
                c = rng.choice(((255, 255, 255), (255, 226, 80), (255, 140, 180)))
                d.ellipse((fx - r, fy - r, fx + r, fy + r), fill=c)
    return img


def _cloud(d, rng, cx, cy, s):
    """Puffy cartoon cloud of width s: a flat pill with round bumps on top."""
    ph = s * 0.2
    d.ellipse((cx - s / 2, cy - ph / 2, cx - s / 2 + ph, cy + ph / 2), fill=255)
    d.ellipse((cx + s / 2 - ph, cy - ph / 2, cx + s / 2, cy + ph / 2), fill=255)
    d.rectangle((cx - s / 2 + ph / 2, cy - ph / 2, cx + s / 2 - ph / 2, cy + ph / 2), fill=255)
    n = rng.randint(3, 5)
    for i in range(n):
        f = i / (n - 1)
        bx = cx - s * 0.3 + s * 0.6 * f + rng.uniform(-0.03, 0.03) * s
        r = s * rng.uniform(0.13, 0.19) * (1.15 - 0.6 * abs(f - 0.5))
        d.ellipse((bx - r, cy - ph * 0.2 - r, bx + r, cy - ph * 0.2 + r), fill=255)


@_scene
def road(w, h):
    """An empty road running straight to a low golden sun, with telephone poles and wires."""
    rng = random.Random(1212)
    u, size = h / 1080, (w, h)
    hz, vx = 0.58 * h, 0.5 * w
    img = _vgrad(w, h, [(0, (50, 66, 126)), (0.28, (140, 116, 152)), (0.48, (244, 160, 100)), (0.58, (255, 208, 142)),
                        (1, (255, 208, 142))])
    sx, sy, sr = vx, hz - 0.03 * h, 0.045 * h
    img = _light(img, _radial(size, sx, sy, 0.7 * w, 0.38 * h, power=2.0), (255, 170, 80))
    img = _light(img, _radial(size, sx, sy, 5 * sr, power=2.5), (255, 236, 190))
    img = _paint(img, _disc(size, sx, sy, sr), (255, 246, 222))
    mountains = _ridge(rng, w, hz - 0.012 * h, 0.022 * h, rough=0.55)
    img = _paint(img, _below(size, mountains), (204, 134, 124), 0.85)
    low_hills = _ridge(rng, w, hz - 0.002 * h, 0.008 * h, rough=0.6)
    img = _paint(img, _below(size, low_hills), (150, 98, 92))
    # fields
    land = _vgrad(w, h, [(0.58, (198, 142, 92)), (1, (84, 58, 36))])
    grass = _curve(_noise(rng, w, h, 20, 4, 0.6, stretch=4), lambda v: 205 + v * 0.2)
    land = ImageChops.multiply(land, grass.convert("RGB"))
    img = _paint(img, _vgrad(w, h, [(0.58 - 0.001, 0), (0.58, 255)]), land)
    # the road, in perspective from the vanishing point
    kw = 0.42 * w / (h - hz)
    road_m = Image.new("L", size)
    ImageDraw.Draw(road_m).polygon([(vx - u, hz), (vx + u, hz), (vx + kw * (h - hz), h), (vx - kw * (h - hz), h)], fill=255)
    road_m = road_m.filter(ImageFilter.GaussianBlur(0.7 * u))
    img = _paint(img, road_m, _vgrad(w, h, [(0.58, (156, 116, 102)), (1, (42, 36, 40))]))
    img = _light(img, ImageChops.multiply(road_m, _radial(size, vx, hz, 0.16 * w, 0.3 * h)), (255, 190, 120), 0.7)
    marks = Image.new("L", size)
    d = ImageDraw.Draw(marks)
    for sgn in (-1, 1):
        d.polygon([(vx, hz), (vx + sgn * kw * (h - hz) * 0.92, h), (vx + sgn * kw * (h - hz) * 0.95, h)], fill=200)
    for k in range(40):
        z0 = 1 + k * 1.3
        ya, yb = hz + (h - hz) / z0, hz + (h - hz) / (z0 + 0.6)
        wa, wb = kw * (ya - hz) * 0.018, kw * (yb - hz) * 0.018
        d.polygon([(vx - wa, ya), (vx + wa, ya), (vx + wb, yb), (vx - wb, yb)], fill=255)
    marks = ImageChops.multiply(marks.filter(ImageFilter.GaussianBlur(0.6 * u)), _vgrad(w, h, [(0.58, 60), (0.8, 255)]))
    img = _paint(img, marks, (238, 206, 130))
    # telephone poles down the right side, wires sagging between them
    poles = Image.new("L", size)
    d = ImageDraw.Draw(poles)
    tops = []
    for k in range(14):
        z = 0.75 + k * 1.1
        yb = hz + (h - hz) / z
        x = vx + kw * (yb - hz) * 1.45
        ph, pw = (yb - hz) * 4.4, max(1, (yb - hz) * kw * 0.035)
        d.rectangle((x - pw, yb - ph, x + pw, yb), fill=255)
        d.rectangle((x - pw * 7, yb - ph * 0.95, x + pw * 7, yb - ph * 0.95 + pw * 1.6), fill=255)
        tops.append((x, yb - ph * 0.95, pw))
    for off in (-6, 0, 6):
        for (x0, y0, p0), (x1, y1, p1) in zip(tops, tops[1:]):
            sag = (x0 - x1) * 0.06
            seg = [(x0 + off * p0 + (x1 + off * p1 - x0 - off * p0) * t, y0 + (y1 - y0) * t + sag * 4 * t * (1 - t))
                   for t in (i / 8 for i in range(9))]
            d.line(seg, fill=255, width=max(1, int(1.5 * u)))
    return _paint(img, poles.filter(ImageFilter.GaussianBlur(0.6 * u)), (40, 24, 26))


def make(name, w=1920, h=1080):
    """Render one scene as an RGB image."""
    return SCENES[name](w, h)


def save_all(folder, w=1920, h=1080):
    """Write <name>.jpg for every scene into folder and return the paths."""
    os.makedirs(folder, exist_ok=True)
    paths = []
    for name in SCENES:
        path = os.path.join(folder, f"{name}.jpg")
        make(name, w, h).save(path, quality=90)
        paths.append(path)
    return paths


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python -m cinesets.scenes <output folder>")
    for p in save_all(sys.argv[1]):
        print(p)
