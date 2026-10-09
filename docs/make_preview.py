# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Make the pictures in docs/preview.md and its tables of sections and keys.

  venv/bin/python docs/make_preview.py

Every poster is drawn by CineSets itself over made-up artwork from cinesets/scenes.py, so no film artwork or
streaming logo is ever committed. Streaming posters show the service name, as they do before `cinesets logos`.
The images/dashboard*.jpg pictures are screenshots of `cinesets web --demo` at 1440x900: this script doesn't make them.
"""
import os
import re
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

DOCS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DOCS)
sys.path.insert(0, ROOT)

from cinesets import catalog, config, mosaic, posters, scenes  # noqa: E402

OUT = os.path.join(DOCS, "images")
PAGE = os.path.join(DOCS, "preview.md")
BG, CAPTION, MUTED = (16, 16, 20), (235, 235, 240), (150, 150, 160)
UNIVERSE_SAMPLE = ["m-marvel", "m-starwars", "m-middleearth", "m-bond", "m-jurassic", "m-matrix", "m-indiana", "m-pixar",
                   "m-ghibli", "m-nolan", "m-backtothefuture", "m-ghostbusters", "m-alien", "m-madmax", "m-johnwick",
                   "m-toystory", "m-mission", "m-hungergames", "m-shrek", "m-knivesout", "s-startrek", "m-paddington",
                   "m-scream", "m-avatar"]
# made-up artwork that suits a collection, taken in turn when several share it; anything not listed takes the next
# scene in turn
SCENE_FOR = {
    "halloween": "moon", "horror": "moon", "conjuring": "moon", "scream": "moon", "insidious": "moon",
    "kids": "hills", "preschool": "hills", "family": "hills", "animation": "hills", "toystory": "hills", "shrek": "hills",
    "paddington": "hills", "ghibli": "hills", "pixar": "hills", "familytv": "hills", "familybest": "hills",
    "scifi": "nebula", "starwars": "nebula", "startrek": "nebula", "alien": "nebula", "avatar": "aurora",
    "trending": ["city", "aurora"], "action": ["storm", "desert"], "watched-week": "stage", "new": "road",
    "crime": "city", "thriller": "ocean",
    "war": "storm", "drama": "ocean", "comedy": "hills", "docs": "forest", "top250": "sunset", "oscars": "stage",
    "middleearth": "forest", "jurassic": "forest", "madmax": "desert", "indiana": "desert", "matrix": "city",
    "bond": "ocean", "mission": "city", "johnwick": "city", "backtothefuture": "road", "hungergames": "forest",
}


def font(weight, size):
    return ImageFont.truetype(os.path.join(ROOT, "assets", "fonts", "poppins", f"Poppins-{weight}.ttf"), size)


class Studio:
    """Draws posters into a temporary folder, each over a made-up scene, and hands back small copies."""

    def __init__(self, work):
        self.work = work
        self.logos = os.path.join(work, "no-logos")  # empty: streaming posters draw the service name
        os.makedirs(self.logos, exist_ok=True)
        self.art = {name: self._scene(name) for name in scenes.SCENES}
        self.turn = 0
        self.count = 0
        self.shared = {}

    def _scene(self, name):
        path = os.path.join(self.work, f"scene-{name}.jpg")
        scenes.make(name, 1600, 900).save(path, quality=92)
        return path

    def scene_for(self, coll):
        tail = coll["key"][2:]
        name = SCENE_FOR.get(tail) or next((v for k, v in SCENE_FOR.items() if tail.startswith(k)), None)
        if isinstance(name, list):
            self.shared[tail] = self.shared.get(tail, -1) + 1
            name = name[self.shared[tail] % len(name)]
        if name not in self.art:
            name = list(self.art)[self.turn % len(self.art)]
            self.turn += 1
        return self.art[name]

    def poster(self, coll, size, style=None, art=None):
        style = posters.check_style(style or {})
        self.count += 1
        out = os.path.join(self.work, f"poster-{self.count}.jpg")
        art = art or self.scene_for(coll)
        if coll.get("logo"):
            posters.make_logo_poster(out, coll["label"], coll["logo"], self.logos, coll.get("subtitle") or "Popular", art,
                                     coll["title"], style)
        else:
            posters.make_poster(out, coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], art, style)
        return Image.open(out).convert("RGB").resize(size, Image.LANCZOS)


def sheet(tiles, per_row, tile, gap=18, caption_h=34, heading=None, row_labels=None):
    """A grid of (image, caption) tiles on a dark background, with an optional heading and a label left of each row."""
    rows = (len(tiles) + per_row - 1) // per_row
    left = 200 if row_labels else 0
    top = 70 if heading else 0
    w = left + gap + per_row * (tile[0] + gap)
    h = top + gap + rows * (tile[1] + caption_h + gap)
    img = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(img)
    if heading:
        draw.text((gap + 6, 18), heading, font=font("SemiBold", 34), fill=CAPTION)
    small = font("Regular", 18 if tile[0] < 230 else 20)
    for i, (im, text) in enumerate(tiles):
        x = left + gap + (i % per_row) * (tile[0] + gap)
        y = top + gap + (i // per_row) * (tile[1] + caption_h + gap)
        img.paste(im, (x, y))
        while text and small.getbbox(text)[2] > tile[0]:
            text = text[:-2] + "…"
        draw.text((x + (tile[0] - small.getbbox(text)[2]) // 2, y + tile[1] + 6), text, font=small, fill=MUTED)
    for r, label in enumerate(row_labels or []):
        y = top + gap + r * (tile[1] + caption_h + gap) + tile[1] // 2 - 30
        for n, line in enumerate(label.split("\n")):
            draw.text((gap + 6, y + n * 34), line, font=font("SemiBold" if n == 0 else "Regular", 26 if n == 0 else 20),
                      fill=CAPTION if n == 0 else MUTED)
    return img


def save(img, name):
    path = os.path.join(OUT, name)
    img.save(path, "JPEG", quality=84, optimize=True, progressive=True)
    print(f"  {name}: {img.width}x{img.height}, {os.path.getsize(path) // 1024} KB")


def short(coll):
    return coll["name"].split(" - ", 1)[-1]


def collections_page(studio, by_key):
    keys = ["m-trending", "s-trending", "m-watched-week", "m-new", "m-action", "m-scifi",
            "m-horror", "s-comedy", "m-netflix", "s-disney", "m-top250", "m-80s",
            "m-kids", "m-halloween", "m-starwars", "m-backtothefuture", "m-jurassic", "m-ghibli"]
    keys = [k for k in keys if k in by_key]
    tile = (230, 345)
    img = sheet([(studio.poster(by_key[k], tile), by_key[k]["name"]) for k in keys], 6, tile, gap=24, heading="Collections")
    save(img, "collections-page.jpg")


def section_sheets(studio, cfg, colls):
    made = []
    for group, members in catalog.sections(cfg, colls):
        shown = members
        if group == "universes":
            sample = [c for k in UNIVERSE_SAMPLE for c in members if c["key"] == k]
            shown = sample or members[:24]
        tile = (190, 285)
        img = sheet([(studio.poster(c, tile), c["key"]) for c in shown], 8, tile)
        save(img, f"section-{group}.jpg")
        made.append((group, members, len(shown)))
    return made


def style_sheets(studio, by_key):
    tile = (240, 360)
    scifi, action, kids = by_key["m-scifi"], by_key["m-action"], by_key["m-kids"]
    accents = list(posters.ACCENTS)
    save(sheet([(studio.poster(scifi, tile, {"accent": a}), a) for a in accents], 5, tile), "style-accents.jpg")

    shades = [({"shade": s}, f"shade: {s}") for s in ("light", "medium", "dark")]
    tints = [({"tint": t}, f"tint: {t}") for t in ("strong", "normal", "subtle", "none")]
    tiles = [(studio.poster(action, tile, st), text) for st, text in shades + tints]
    save(sheet(tiles[:3] + [(Image.new("RGB", tile, BG), "")] + tiles[3:], 4, tile), "style-shade.jpg")

    text = [({}, "the defaults"), ({"title": "solid"}, "title: solid"), ({"title": "white"}, "title: white"),
            ({"align": "centre"}, "align: centre"),
            ({"case": "upper"}, "case: upper"), ({"label": False}, "label: false"),
            ({"label_colour": "white"}, "label_colour: white"), ({"label_colour": "accent"}, "label_colour: accent"),
            ({"subtitle_colour": "accent"}, "subtitle_colour: accent"), ({"subtitle_colour": "gold"}, "subtitle_colour: gold")]
    save(sheet([(studio.poster(kids if i % 2 else action, tile, st), t) for i, (st, t) in enumerate(text)], 5, tile),
         "style-text.jpg")

    looks = [("Default", {}),
             ("Clean", {"title": "white", "align": "centre", "case": "upper", "label_colour": "white", "tint": "subtle"}),
             ("Moody", {"shade": "dark", "tint": "strong", "subtitle_colour": "accent"}),
             ("Silver screen", {"accent": "silver", "tint": "none", "label_colour": "white", "case": "upper"})]
    picks = [by_key[k] for k in ("m-trending", "m-horror", "m-backtothefuture", "m-netflix")]
    tiles = [(studio.poster(c, tile, st), short(c)) for _, st in looks for c in picks]
    save(sheet(tiles, 4, tile, row_labels=[name for name, _ in looks]), "style-looks.jpg")


def random_artwork(studio, by_key):
    tile = (220, 330)
    names = [n for n in ("city", "road", "storm", "ocean") if n in studio.art] or list(studio.art)[:4]
    action, netflix = by_key["m-action"], by_key["m-netflix"]
    netflix_art = studio.art[names[0]]
    tiles = ([(studio.poster(action, tile, {}, studio.art[n]), f"Server {i + 1}") for i, n in enumerate(names)]
             + [(studio.poster(netflix, tile, {}, netflix_art), f"Server {i + 1}") for i in range(len(names))])
    save(sheet(tiles, len(names), tile, row_labels=["Popular Action\nrandom artwork", "Netflix\nleft alone"]),
         "random-artwork.jpg")


def mosaic_artwork(studio, by_key):
    """artwork: mosaic, over made-up film posters (mosaic.demo_poster), each with an invented title. Drawn after the
    fonts, with its own artwork, so the other pictures keep theirs."""
    tile = (240, 360)
    films = []
    for name in scenes.SCENES:
        films.append(os.path.join(studio.work, f"film-{name}.jpg"))
        mosaic.demo_poster(name).save(films[-1], quality=92)
    grid = lambda n, start: mosaic.compose(films[start:start + n * n], n,
                                           os.path.join(studio.work, f"grid-{n}-{start}.jpg"))
    scifi, action = by_key["m-scifi"], by_key["m-action"]
    tiles = [(studio.poster(scifi, tile, {}, studio.art["nebula"]), "artwork: fixed"),
             (studio.poster(scifi, tile, {"artwork": "mosaic", "mosaic": "2x2"}, grid(2, 0)), "mosaic: 2x2"),
             (studio.poster(scifi, tile, {"artwork": "mosaic"}, grid(3, 0)), "mosaic: 3x3"),
             (studio.poster(action, tile, {"artwork": "mosaic", "shade": "dark"}, grid(3, 3)), "3x3, shade: dark")]
    save(sheet(tiles, 4, tile), "style-mosaic.jpg")


# a collection each font suits, for the fonts picture
FONT_FOR = {"poppins": "m-action", "bebas-neue": "m-thriller", "abril-fatface": "m-drama", "cinzel-decorative": "m-middleearth",
            "limelight": "m-oscars", "bangers": "m-marvel", "creepster": "m-horror", "audiowide": "m-scifi", "rye": "m-indiana",
            "pacifico": "m-80s", "titan-one": "m-kids", "courier-prime": "m-docs"}


def font_sheet(studio, by_key):
    """Every font, each on a collection it suits. Drawn last, so the other pictures keep the artwork they had."""
    tile = (240, 360)
    tiles = [(studio.poster(by_key[FONT_FOR[face]], tile, {"font": face}), face) for face in posters.FONTS]
    save(sheet(tiles, 6, tile), "style-fonts.jpg")


# a few words under a section's heading, where the picture alone doesn't say it
SECTION_NOTES = {
    "seasonal": "Each one is only there around its holiday: Halloween from 1 October to 1 November, Christmas from 20 "
                "November\nto 6 January. Outside those dates CineSets takes down the copy it made, and makes it again "
                "next season.\n\n",
}


def section_tables(made):
    """Markdown for every section: its picture and a table of its keys, to paste between the markers in preview.md."""
    parts = []
    for group, members, shown in made:
        name = members[0]["section"]
        note = f" A sample of {shown} of its {len(members)} collections." if shown < len(members) else ""
        parts.append(f"### {name}\n\nSection key `{group}`, {len(members)} collections.{note}\n\n"
                     f"{SECTION_NOTES.get(group, '')}![{name}](images/section-{group}.jpg)\n\n<details>\n<summary>Every collection in "
                     f"{name.lower() if name[1:2].islower() else name}</summary>\n\n| Key | Collection |\n|---|---|\n"
                     + "".join(f"| `{c['key']}` | {c['name']} |\n" for c in members) + "\n</details>\n")
    return "\n".join(parts)


def main():
    os.makedirs(OUT, exist_ok=True)
    cfg = config.Config(config._merge(config.DEFAULTS, {}))
    cfg["base_dir"] = ROOT
    cfg["posters"] = posters.check_style({})
    cfg["collections"] = config.check_pick(None)
    colls = catalog.load(cfg)
    by_key = {c["key"]: c for c in colls}
    with tempfile.TemporaryDirectory() as work:
        studio = Studio(work)
        print("Making the preview pictures...")
        collections_page(studio, by_key)
        made = section_sheets(studio, cfg, colls)
        style_sheets(studio, by_key)
        random_artwork(studio, by_key)
        font_sheet(studio, by_key)
        mosaic_artwork(studio, by_key)
    with open(PAGE) as f:
        page = f.read()
    start, end = "<!-- sections:start -->", "<!-- sections:end -->"
    page = re.sub(f"{start}.*?{end}", lambda m: f"{start}\n\n{section_tables(made)}\n{end}", page, flags=re.S)
    with open(PAGE, "w") as f:
        f.write(page)
    print(f"Updated the section tables in {os.path.relpath(PAGE, ROOT)}")


if __name__ == "__main__":
    main()
