# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Load collections.yml and work out each collection's name, sort title and display order.

The Collections page is ordered by sort title. `order` in config.yml lists the groups top to bottom; an entry
can be a list of groups that share one block (for example charts then genres). Collections with `pin` sit above
everything, and groups in `alphabetical_groups` are sorted A-Z ignoring a leading "The".

Each group is a section people can pick as a whole, or collection by collection, under `collections` in config.yml.

custom-collections.yml (made by the dashboard, next to config.yml) is read as well: new collections in the same
format, and `{key, add_lists}` entries that add lists to an existing collection. Updates to CineSets never touch it.

A collection with `active: ["MM-DD", "MM-DD"]` belongs to part of the year only (see in_season), for example a
seasonal one.
"""
import datetime
import os
import re
import unicodedata

import yaml

from .config import ROOT
from .lists import SLUG

NOUN = {"movie": "movies", "show": "TV shows"}
KINDS = {"movie": "movie", "movies": "movie", "show": "show", "shows": "show", "tv": "show", "tvshows": "show", "series": "show"}
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
# what each group is called in `list`, `pick` and the docs; a collections file can add or change names under `sections`
SECTIONS = {
    "charts": "Trending and charts",
    "genres": "Popular genres",
    "streaming": "Streaming services",
    "bestof": "Best of",
    "kids": "Kids and family",
    "seasonal": "Seasonal",
    "regional": "Regional",
    "universes": "Franchises and studios",
}


MONTH_DAY = re.compile(r"^(\d{2})-(\d{2})$")


def _month_day(text):
    """(month, day) from "MM-DD", or None if it is not a real day of the year (29 February counts)."""
    m = MONTH_DAY.match(text) if isinstance(text, str) else None
    if not m:
        return None
    try:
        datetime.date(2000, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    return int(m.group(1)), int(m.group(2))


def _active(value, key):
    """`active` checked: two "MM-DD" days, from and to."""
    if not (isinstance(value, (list, tuple)) and len(value) == 2 and all(_month_day(x) for x in value)):
        raise SystemExit(f"collections.yml: {key}: active must be two days of the year in quotes, from and to, like "
                         f"[\"10-01\", \"11-01\"] or [\"11-20\", \"01-06\"] (month-day), not {value!r}")
    return [str(x) for x in value]


def in_season(coll, today=None):
    """True when today (a datetime.date, by default the real one) is inside the collection's `active` window, or the
    collection has none. Both ends count, and a window can run past new year, like ["11-20", "01-06"]."""
    window = coll.get("active")
    if not window:
        return True
    today = today or datetime.date.today()
    now, start, end = (today.month, today.day), _month_day(window[0]), _month_day(window[1])
    return start <= now <= end if start <= end else (now >= start or now <= end)


def fixed_title(entry):
    """One place in a fixed list as (title, year, TMDB id or None), from [title, year] or [title, year, TMDB id]."""
    title, year, *tmdb = entry
    return title, year, (tmdb[0] if tmdb else None)


def _fixed_titles(value, key):
    """`titles` checked: each one [title, year], or [title, year, TMDB id] with the id a positive whole number."""
    out = []
    for entry in value if isinstance(value, list) else [value]:
        if not (isinstance(entry, (list, tuple)) and len(entry) in (2, 3)):
            raise SystemExit(f"collections.yml: {key}: each of its titles must be [title, year] or [title, year, TMDB "
                             f"id], like [\"Zootopia\", 2016, 269149], not {entry!r}")
        title, year, tmdb = fixed_title(entry)
        if len(entry) == 3 and (isinstance(tmdb, bool) or not isinstance(tmdb, int) or tmdb < 1):
            raise SystemExit(f"collections.yml: {key}: the TMDB id of {title!r} must be a positive whole number, the "
                             f"one in its themoviedb.org address (like 269149 for Zootopia), not {tmdb!r}")
        out.append((title, year, tmdb))
    return out


def loose_title(name):
    """A title reduced to its letters and digits for a second try at matching a fixed list: no case, accents,
    punctuation, spaces or leading "The", "&" read as "and" and "³" as "3", so "Alien³" and "Alien 3" are the same."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower().replace("&", " and ")
    text = re.sub(r"^\W*the\b", "", text)
    return re.sub(r"[\W_]+", "", text)


def _blocks(order):
    out = {}
    for n, entry in enumerate(order, start=1):
        for sub, group in enumerate(entry if isinstance(entry, list) else [entry]):
            out[group] = (n, sub)
    return out


def read_custom(cfg):
    """custom-collections.yml as {"sections": {...}, "collections": [...]}, empty if there is none yet."""
    path = cfg.path("custom_collections")
    if not os.path.exists(path):
        return {"sections": {}, "collections": []}
    with open(path) as f:
        doc = yaml.safe_load(f) or {}
    if not isinstance(doc, dict) or not isinstance(doc.get("collections") or [], list):
        raise SystemExit(f"{path}: expected `collections:` with a list of entries")
    return {"sections": dict(doc.get("sections") or {}), "collections": list(doc.get("collections") or [])}


TEXT = ("label", "title", "subtitle")  # words on a poster that can be changed for one collection


def _merge_custom(spec, custom, where):
    """The main catalogue plus custom collections, and changes to existing ones: lists added to them, and their
    label, title or subtitle."""
    out, at = list(spec), {raw.get("key"): n for n, raw in enumerate(spec)}
    for raw in custom["collections"]:
        if not isinstance(raw, dict):
            raise SystemExit(f"{where}: every entry must be a collection, or a key with changes to one")
        key = raw.get("key")
        if set(raw) > {"key"} and set(raw) <= {"key", "add_lists", *TEXT}:
            if key not in at:
                print(f"Note: {where}: {key!r} is not a collection any more, so the changes to it are skipped")
                continue
            base = dict(out[at[key]])
            if raw.get("add_lists") and base.get("titles"):
                # a collection that has become a fixed list of titles since: the rest of the file still loads
                print(f"Note: {where}: {key} is a fixed list of titles, so the lists added to it are skipped")
            elif raw.get("add_lists"):
                added = [x for x in raw["add_lists"] if x not in (base.get("lists") or [])]
                base["lists"], base["added_lists"] = list(base.get("lists") or []) + added, added
            base["built_in_text"] = {f: base.get(f) for f in TEXT}
            for field in TEXT:
                if field in raw:
                    base[field] = raw[field]
            base["edited_text"] = [f for f in TEXT if f in raw]
            out[at[key]] = base
        elif key in at:
            print(f"Note: {where}: there is already a collection called {key!r}, so this one is skipped")
        else:
            at[key] = len(out)
            out.append({**raw, "custom": True})
    return out


def load(cfg):
    path = cfg.path("collections_file")
    if not os.path.exists(path) and not os.path.isabs(cfg["collections_file"]):
        path = os.path.join(ROOT, cfg["collections_file"])  # fall back to the catalogue shipped with CineSets
    with open(path) as f:
        doc = yaml.safe_load(f)
    custom = read_custom(cfg)
    spec = _merge_custom(doc["collections"], custom, os.path.basename(cfg.path("custom_collections")))
    names = {**SECTIONS, **(doc.get("sections") or {}), **custom["sections"]}
    blocks = _blocks(cfg["order"])
    alpha_groups = set(cfg["alphabetical_groups"])
    out, pos = [], {}
    for raw in spec:
        c = dict(raw)
        for field in ("key", "group", "type", "title"):
            if not c.get(field):
                raise SystemExit(f"collections.yml: an entry is missing {field!r}: {raw}")
        if not KEY.match(str(c["key"])):
            raise SystemExit(f"collections.yml: key {c['key']!r} must be lower-case letters, digits and dashes")
        if str(c["type"]).lower() not in KINDS:
            raise SystemExit(f"collections.yml: {c['key']}: type must be movie or show")
        c["kind"] = KINDS[str(c.pop("type")).lower()]
        bad = [x for x in c.get("lists") or [] if not (isinstance(x, str) and SLUG.match(x) and ".." not in x)]
        if bad:
            raise SystemExit(f"collections.yml: {c['key']}: {bad[0]!r} is not an mdblist list (like user/list-name)")
        if c.get("active") is not None:
            c["active"] = _active(c["active"], c["key"])
        c["subtitle"] = c.get("subtitle") or None
        c.setdefault("accent", "purple")
        c.setdefault("lists", [])
        if c.get("titles"):
            c["titles"] = _fixed_titles(c["titles"], c["key"])
        label = str(c.get("label") or cfg["labels"][c["kind"]])
        words = " ".join(x for x in [c["title"].replace("-\n", "-").replace("\n", " "), c["subtitle"]] if x)
        twin = 0 if c["kind"] == "movie" else 1
        group = c["group"]
        # a movie collection and its TV twin (same key after the m-/s- prefix) sit next to each other
        pair = pos.setdefault(group, {}).setdefault(c["key"][2:], len(pos[group]) + 1)
        block, sub = blocks.get(group, (len(blocks) + 1, 0))
        if c.get("pin"):
            sort = f"+000_{int(c['pin']):02d}{twin} {label} - {words}"
        elif group in alpha_groups:
            alpha = words.lower()
            alpha = alpha[4:] if alpha.startswith("the ") else alpha
            sort = f"+{block:02d}{sub}_{alpha} {twin}"
        else:
            sort = f"+{block:02d}{sub}_{pair:02d}{twin} {label} - {words}"
        if not c.get("titles"):  # how many titles: the collection's own number, then its section's, then the cap
            limits = cfg.get("limits") or {}
            built_in = c.get("limit", cfg["defaults"]["limit"])
            own = (limits.get("collections") or {}).get(c["key"]) or (limits.get("sections") or {}).get(group)
            c["limit"] = own or (min(built_in, limits["most"]) if limits.get("most") else built_in)
            c["built_in_limit"] = built_in
        c.update({
            "section": str(names.get(group) or group.replace("-", " ").replace("_", " ").capitalize()),
            "label": label,
            "name": f"{label} - {words}",
            "sort": sort,
            # timeline-like groups read best in release order; the rest by title
            "order": c.get("display_order") or ("PremiereDate" if group in ("bestof", "universes") else "SortName"),
            "overview": c.get("overview") or f"{words} {NOUN[c['kind']]}. Updated automatically.",
        })
        out.append(c)
    keys = [c["key"] for c in out]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise SystemExit(f"collections.yml has duplicate keys: {sorted(dupes)}")
    # two collections with one name would be mixed up on the server; a note rather than an error, so a custom
    # collections file that does this still loads
    named = {}
    for c in out:
        named.setdefault(c["name"], []).append(c["key"])
    for name, same in named.items():
        if len(same) > 1:
            print(f"Note: collections.yml: {', '.join(same[:-1])} and {same[-1]} are "
                  f"{'both' if len(same) == 2 else 'all'} called {name!r}; give each its own title or "
                  f"subtitle so they are not mixed up on the server")
    return out


def sections(cfg, colls):
    """[(group, [collections])] in Collections page order, each group's collections in page order too."""
    blocks = _blocks(cfg["order"])
    groups = {}
    for c in sorted(colls, key=lambda c: c["sort"]):
        groups.setdefault(c["group"], []).append(c)
    return sorted(groups.items(), key=lambda g: blocks.get(g[0], (len(blocks) + 1, 0)))


def picked(cfg, colls, quiet=False):
    """The collections config.yml picks: its whole sections and its included keys, less its excluded keys.
    Names that are not in the collections file (for example seasonal ones after the season) are noted, not errors."""
    pick = cfg["collections"]
    groups, keys = {c["group"] for c in colls}, {c["key"] for c in colls}
    chosen = groups if pick["sections"] == "all" else set(pick["sections"])
    include, exclude = set(pick["include"]), set(pick["exclude"])
    if not quiet:
        if chosen - groups:
            print(f"Note: config.yml collections: no such sections, ignored: {', '.join(sorted(chosen - groups))}")
        if (include | exclude) - keys:
            print(f"Note: config.yml collections: not in the collections file, ignored: "
                  f"{', '.join(sorted((include | exclude) - keys))}")
    return [c for c in colls if (c["group"] in chosen or c["key"] in include) and c["key"] not in exclude]
