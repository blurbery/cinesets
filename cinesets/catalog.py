# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Load collections.yml and work out each collection's name, sort title and display order.

The Collections page is ordered by sort title. `order` in config.yml lists the groups top to bottom; an entry
can be a list of groups that share one block (for example charts then genres). Collections with `pin` sit above
everything, and groups in `alphabetical_groups` are sorted A-Z ignoring a leading "The".
"""
import os
import re

import yaml

from .config import ROOT

NOUN = {"movie": "movies", "show": "TV shows"}
KINDS = {"movie": "movie", "movies": "movie", "show": "show", "shows": "show", "tv": "show", "tvshows": "show", "series": "show"}
KEY = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


def _blocks(order):
    out = {}
    for n, entry in enumerate(order, start=1):
        for sub, group in enumerate(entry if isinstance(entry, list) else [entry]):
            out[group] = (n, sub)
    return out


def load(cfg):
    path = cfg.path("collections_file")
    if not os.path.exists(path) and not os.path.isabs(cfg["collections_file"]):
        path = os.path.join(ROOT, cfg["collections_file"])  # fall back to the catalogue shipped with CineSets
    with open(path) as f:
        spec = yaml.safe_load(f)["collections"]
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
        c.setdefault("subtitle", None)
        c.setdefault("accent", "purple")
        c.setdefault("lists", [])
        if c.get("titles"):
            c["titles"] = [(t, y) for t, y in c["titles"]]
        label = cfg["labels"][c["kind"]]
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
        c.update({
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
    return out
