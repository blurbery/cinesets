# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Mosaic posters (`posters: artwork: mosaic`): instead of one artwork, the poster's background is a grid of the
collection's own titles' posters, 2x2 or 3x3, with thin dark gutters between them. The grid is drawn as one picture
the size of the poster and handed to the poster code as its artwork, so the shade, tint and text go on top exactly as
they do on any other poster.

The tiles are picked once, at random from the collection's top titles that have a poster, and kept in
data/state.json (`tiles`), so a list that changes order doesn't redraw the poster and upload it again: only a tile
whose title has left the collection is replaced, in its own place. `--reshuffle` picks a whole new grid, unless its
tiles were picked in the dashboard (`tiles_chosen`). Each title's poster is downloaded once, small, into data/tiles.
When too few of a collection's titles have posters, its poster has one artwork instead, as with `artwork: fixed`."""
import contextlib
import os
import re
import tempfile
import threading
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import posters, scenes

GRIDS = {"2x2": 2, "3x3": 3}  # posters.CHOICES["mosaic"] -> tiles across and down
GAP = 8                       # the dark gutter between tiles, in pixels of the 1000x1500 poster
GUTTER = (8, 8, 12)
TILE_WIDTH = 400              # how wide tiles are kept in data/tiles (drawn about 330 wide in a 3x3 grid, 500 in a 2x2)
PICK_FROM = 25                # new tiles come from the top titles with posters, as random artwork does
TRIES = 3                     # failed downloads before a poster gives up on its mosaic for this run
SAFE_NAME = re.compile(r"^[A-Za-z0-9-]+\Z")  # an item id that is safe as a file name (engine.SAFE_ID)

# made-up films for the tiles in demo mode and the docs, one for each scene in scenes.py. Every title is invented.
DEMO_FILMS = {
    "city": "Glass Avenue", "nebula": "Orbit of Ash", "sunset": "Marigold Hour", "ocean": "Saltglass",
    "forest": "The Fernwood Pact", "desert": "Red Mesa Express", "aurora": "Northlight Static",
    "storm": "The Gale Archive", "stage": "Encore at Halfmoon", "moon": "Lantern Moon Hotel",
    "hills": "Clover and the Kite", "road": "Route Juniper",
}
DEMO_FONT = os.path.join(posters.FONT_DIR, "bebas-neue", "BebasNeue-Regular.ttf")


def size(style):
    """How many tiles across (and down) a style's mosaic has."""
    return GRIDS[style.get("mosaic") or posters.STYLE["mosaic"]]


def cells(n):
    """The boxes (left, top, right, bottom) of an n x n grid's tiles on the poster, row by row. Gutters go only between
    tiles, and the edges are rounded so the grid fills the poster to the last pixel."""
    edge = lambda length, k: round(k * (length + GAP) / n)
    return [(edge(posters.W, c), edge(posters.H, r), edge(posters.W, c + 1) - GAP, edge(posters.H, r + 1) - GAP)
            for r in range(n) for c in range(n)]


def compose(paths, n, out):
    """Lay out the grid: each tile's poster scaled to fill its box (trimmed a touch at the sides, as a 2:3 poster is a
    little taller than its box) on a dark background, saved as a JPEG at `out`. A tile that can't be read is deleted,
    so it's downloaded again next time, and the error is raised."""
    sheet = Image.new("RGB", (posters.W, posters.H), GUTTER)
    for path, box in zip(paths, cells(n)):
        try:
            with Image.open(path) as im:
                tile = ImageOps.fit(im.convert("RGB"), (box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
        except OSError:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
            raise
        sheet.paste(tile, box[:2])
    sheet.save(out, "JPEG", quality=95)
    return out


def has_poster(index, item):
    """Whether a title can be a tile: in the library index with a poster, and with an id that is safe as a file name.
    An index from before posters were noted has no "p", so its titles are tried, and skipped if they have none."""
    it = index["items"].get(item)
    return bool(it) and bool(it.get("p", True)) and bool(SAFE_NAME.match(str(item)))


def pick(ids, has, kept, need, rng, fresh=False):
    """The tiles for a grid of `need` (in grid order), and spare titles to stand in for any that can't be downloaded:
    (tiles, spares), or ([], []) when fewer than `need` of the collection's titles have a poster. `has` says whether a
    title has one.

    Kept tiles (from state.json) keep their places while their titles are anywhere in the collection, and only the
    ones that left are replaced, so a list that changes order changes nothing. Going from 3x3 to 2x2 keeps the first
    four. New tiles come at random from the top PICK_FROM titles with posters, and from further down only when those
    run out; a whole new grid is laid out in the collection's order. fresh: a whole new grid (a reshuffle), away from
    the kept tiles where there are other titles to use."""
    found = list(dict.fromkeys(i for i in ids if has(i)))
    if len(found) < need:
        return [], []
    here = set(found)
    kept = [i for i in kept if isinstance(i, str)] if isinstance(kept, list) else []
    slots = [None] * need
    if not fresh:
        for n, i in enumerate(kept[:need]):
            if i in here and i not in slots:
                slots[n] = i
    taken = set(slots)
    top = [i for i in found[:PICK_FROM] if i not in taken]
    rng.shuffle(top)
    if fresh:
        top.sort(key=lambda i: i in kept)  # titles that weren't tiles before come first, still in random order
    spares = top + [i for i in found[PICK_FROM:] if i not in taken]
    if not any(slots):
        place = {i: n for n, i in enumerate(found)}
        return sorted(spares[:need], key=place.get), spares[need:]
    for n, i in enumerate(slots):
        if i is None:
            slots[n] = spares.pop(0)
    return slots, spares


def fetch(tiles, spares, get):
    """[(title, its poster file)] for the grid, in order, with get(title) giving the file or None. A tile whose poster
    can't be had gives its place to the next spare title. None when there aren't enough, or after TRIES failed
    downloads, since the server may be struggling."""
    spares, out, failed = list(spares), [], 0
    for item in tiles:
        path = get(item)
        while not path:
            failed += 1
            if failed >= TRIES or not spares:
                return None
            item = spares.pop(0)
            path = get(item)
        out.append((item, path))
    return out


def tile_file(srv, folder, item, pause=0.0):
    """A title's own poster, downloaded once into `folder` about TILE_WIDTH wide, or None when it can't be had. Every
    pixel is read before it's kept, so a download cut off part way is never left on disk. `pause` follows each
    download, to spare the server."""
    if not SAFE_NAME.match(str(item)):
        return None
    path = os.path.join(folder, f"{item}.jpg")
    if os.path.exists(path):
        return path
    os.makedirs(folder, exist_ok=True)
    part = f"{path}.{os.getpid()}-{threading.get_ident()}.part"  # a run and the dashboard can fetch at the same time
    try:
        raw = srv.poster_image(item, TILE_WIDTH, 90)
        with open(part, "wb") as f:
            f.write(raw)
        with Image.open(part) as im:
            im.verify()
        with Image.open(part) as im:
            im.load()
        os.replace(part, path)
        return path
    except Exception as e:
        print(f"   poster {item}: {e}; trying another title")
        return None
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(part)
        time.sleep(pause)


class Grid:
    """One poster's mosaic in a run: its tiles, picked from the library index (nothing is downloaded until it's drawn),
    and its entry in the poster's design record."""

    def __init__(self, engine, ids, index, st, style):
        self.engine, self.style, self.n = engine, style, size(style)
        fresh = engine.reshuffle and not st.get("tiles_chosen")  # tiles picked in the dashboard stay, like chosen artwork
        self.tiles, self.spares = pick(ids, lambda i: has_poster(index, i), st.get("tiles"), self.n ** 2, engine.rng,
                                       fresh)
        self.missing = None if self.tiles else "too few"

    def part(self):
        """The entry in the design record: the grid and its tiles, or why the poster has one artwork instead."""
        return f"artwork:mosaic:{self.style['mosaic']}:" + (self.missing or ",".join(self.tiles))

    def draw(self, out, coll):
        """Fetch the tiles (any that can't be had swapped for others), lay out the grid and draw the poster on it. False,
        saying why in the run log, when the poster makes do with one artwork instead."""
        key = coll["key"]
        if not self.tiles:
            print(f"   {key}: too few of its titles have posters for a {self.style['mosaic']} mosaic, so its poster has "
                  "one artwork")
            return False
        folder = os.path.join(self.engine.data, "tiles")
        pause = float(self.engine.cfg["write_pause"]) / 10
        got = fetch(self.tiles, self.spares, lambda i: tile_file(self.engine.srv, folder, i, pause))
        if not got:
            self.missing = "not fetched"
            print(f"   {key}: not enough of its posters could be fetched for a mosaic, so its poster has one artwork "
                  "this time; the mosaic is tried again next run")
            return False
        handle, grid = tempfile.mkstemp(prefix="mosaic-", suffix=".jpg", dir=self.engine.data)
        os.close(handle)
        try:
            compose([path for _, path in got], self.n, grid)
            posters.make_poster(out, coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], grid,
                                self.style)
        except OSError as e:  # a kept tile that can't be read any more: compose deleted it, to download again
            self.missing = "not drawn"
            print(f"   {key}: the mosaic could not be drawn ({e}), so its poster has one artwork this time; the mosaic "
                  "is tried again next run")
            return False
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.remove(grid)
        self.tiles = [i for i, _ in got]
        return True


# ---------------------------------------------------------------- demo mode and the docs
def demo_poster(name, w=TILE_WIDTH, h=None):
    """A made-up film poster: one of the scenes in scenes.py, portrait, with an invented title along the bottom (see
    DEMO_FILMS), so no real film's artwork ever turns up in demo mode or the docs."""
    h = h or w * 3 // 2
    img = scenes.make(name, w, h)
    fade = Image.new("L", (1, h))
    for y in range(h):  # darker towards the bottom, where the title goes
        fade.putpixel((0, y), int(255 * max(0.0, (y / h - 0.6) / 0.4) ** 1.4 * 0.85))
    img = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), img, fade.resize((w, h)))
    title = DEMO_FILMS.get(name, name).upper()
    words = title.split()
    # one line if it fits, or else two lines as even as the words allow
    splits = [[title]] + [[" ".join(words[:k]), " ".join(words[k:])] for k in range(1, len(words))]
    probe = ImageFont.truetype(DEMO_FONT, 100)
    width = lambda lines: max(probe.getbbox(t)[2] for t in lines)
    lines = splits[0] if width(splits[0]) * h * 0.11 / 100 <= w * 0.86 else min(splits[1:] or splits, key=width)
    font = ImageFont.truetype(DEMO_FONT, max(10, min(int(h * 0.11), int(100 * w * 0.86 / width(lines)))))
    draw = ImageDraw.Draw(img)
    step = int(font.size * 0.95)
    y = h - int(h * 0.05) - step * len(lines)
    for line in lines:
        draw.text(((w - font.getbbox(line)[2]) // 2, y), line, font=font, fill=(245, 240, 230))
        y += step
    return img
