# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Keep the fixed franchise lists in collections.yml in step with TMDB's collections.

  TMDB_API_KEY=... python tests/e2e/check_franchises.py            (say what would change)
  TMDB_API_KEY=... python tests/e2e/check_franchises.py --write    (change collections.yml to match)

TMDB_API_KEY is a TMDB API key or API read access token (themoviedb.org, Settings, API). Only this check uses it:
CineSets itself reads the `titles` it writes and never asks TMDB.

An entry with `tmdb_collections` gets its films from those TMDB collections, its `tmdb_add` films (spin-offs TMDB
keeps apart, like Ballerina from John Wick) and none of its `tmdb_skip` ones:
- a film comes in once it is out, so announced films (Zootopia 3, Avatar 5) wait for their release date;
- a film goes when TMDB has taken it out of all of the entry's collections and it isn't in `tmdb_add`;
- films already in the list keep their place, title and year, so a film added by hand before its release stays.
New films go at the end with TMDB's title and year. The order in the file doesn't matter much: franchises show in
release order on every server.

Exits 0 when every list matches TMDB, 1 when a list would change (with --write: when collections.yml is not what
it should be after writing), and 2 when TMDB couldn't be read or an entry is wrong.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API = "https://api.themoviedb.org/3"
AGENT = "CineSets franchise check (+https://github.com/blurbery/cinesets)"
FIELDS = ("tmdb_collections", "tmdb_add", "tmdb_skip")


class Problem(Exception):
    """An entry or TMDB answer this check can't work with."""


class Unreadable(Problem):
    """TMDB can't be read at all (a refused key, or no answer): the run stops rather than repeat it for each entry."""


def ids_of(entry, field):
    """The entry's TMDB ids under `field`, checked: a list of positive whole numbers (empty if it has none)."""
    value = entry.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in value):
        raise Problem(f"{entry.get('key')}: {field} must be a list of TMDB ids, like [404609], not {value!r}")
    return value


def plan(titles, parts, adds, skip, today):
    """The list after the rules in this file's docstring, plus the films added and taken out.

    titles: the entry's [title, year, id] entries; parts: {id: (title, release date)} for every film in its TMDB
    collections; adds: the same for its tmdb_add films; skip: ids to leave out; today: an ISO date."""
    wanted = {**parts, **adds}
    keep, out = [], []
    for entry in titles:
        tmdb = entry[2] if len(entry) > 2 else None
        if tmdb in wanted and tmdb not in skip:
            keep.append(list(entry))
        else:
            out.append(list(entry))
    have = {e[2] for e in keep}
    new = []
    for tmdb, (title, date) in sorted(wanted.items(), key=lambda kv: (kv[1][1] or "9999", kv[0])):
        if tmdb not in have and tmdb not in skip and date and date <= today:
            new.append([title, int(date[:4]), tmdb])
    return keep + new, new, out


def retry_after(value):
    """Seconds to wait from a Retry-After header: a number of seconds (an HTTP date or nothing means 10), at most 60."""
    try:
        return min(max(int(str(value).strip()), 1), 60)
    except (TypeError, ValueError):
        return 10


class TMDB:
    """TMDB's API, a request at a time. A token (the long read access token) goes in a header, a key as api_key."""

    def __init__(self, key):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = AGENT
        self.params = {"language": "en-US"}
        if key.startswith("eyJ"):
            self.session.headers["Authorization"] = f"Bearer {key}"
        else:
            self.params["api_key"] = key

    def get(self, path):
        for attempt in range(3):
            try:
                r = self.session.get(API + path, params=self.params, timeout=30)
            except requests.RequestException as e:
                if attempt == 2:
                    raise Unreadable(f"TMDB didn't answer for {path}: {type(e).__name__}")
                time.sleep(5)
                continue
            if r.status_code == 401:
                raise Unreadable("TMDB refused the key: set TMDB_API_KEY to a TMDB API key or read access token")
            if r.status_code == 404:
                raise Problem(f"TMDB has nothing at {path}")
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == 2:   # every entry after this one would hit it too
                    raise Unreadable(f"TMDB answered {r.status_code} for {path} three times")
                time.sleep(retry_after(r.headers.get("Retry-After")) if r.status_code == 429 else 5)
                continue
            if r.status_code != 200:
                raise Problem(f"TMDB answered {r.status_code} for {path}")
            time.sleep(0.1)
            return r.json()
        raise Unreadable(f"TMDB kept failing for {path}")

    def collection(self, cid):
        """{id: (title, release date)} for every film in the collection."""
        body = self.get(f"/collection/{cid}")
        return {p["id"]: (p.get("title") or "", p.get("release_date") or "") for p in body.get("parts") or []
                if isinstance(p, dict) and isinstance(p.get("id"), int)}

    def movie(self, mid):
        body = self.get(f"/movie/{mid}")
        return {mid: (body.get("title") or "", body.get("release_date") or "")}


def check(doc, tmdb, today):
    """[(key, new titles, added, taken out)] for every entry with tmdb_collections, and the problems found."""
    results, problems = [], []
    for entry in doc.get("collections") or []:
        if not isinstance(entry, dict) or not any(f in entry for f in FIELDS):
            continue
        key = entry.get("key")
        try:
            cols, adds, skip = (ids_of(entry, f) for f in FIELDS)
            if not cols:
                raise Problem(f"{key}: tmdb_add and tmdb_skip need tmdb_collections")
            if not entry.get("titles"):
                raise Problem(f"{key}: tmdb_collections is for fixed lists, so it needs titles")
            missing = [e for e in entry["titles"] if len(e) < 3]
            if missing:
                raise Problem(f"{key}: give every title its TMDB id, like {missing[0][0]!r}")
            if set(adds) & set(skip):
                raise Problem(f"{key}: a film can't be in both tmdb_add and tmdb_skip")
            parts = {}
            for cid in cols:
                parts.update(tmdb.collection(cid))
            extra = {}
            for mid in adds:
                extra.update(tmdb.movie(mid))
            titles, added, out = plan(entry["titles"], parts, extra, set(skip), today)
            results.append((key, titles, added, out))
        except Unreadable:
            raise
        except Problem as e:
            problems.append(str(e))
    return results, problems


def title_line(entry, indent):
    title, year, tmdb = entry
    return f"{indent}- [{json.dumps(title, ensure_ascii=False)}, {year}, {tmdb}]"


def rewrite(text, changes):
    """collections.yml with the `titles` of each changed entry replaced, the rest of the file as it was.
    changes: {key: new titles}. Lines of titles that stay are kept exactly as written."""
    lines = text.split("\n")
    out, n = [], 0
    while n < len(lines):
        line = lines[n]
        m = re.match(r"^(\s*)- key: *([\w-]+)\s*$", line)
        if not m or m.group(2) not in changes:
            out.append(line)
            n += 1
            continue
        start = n
        n += 1
        while n < len(lines) and not re.match(r"^\s*- key:", lines[n]) and not re.match(r"^ {0,2}\S", lines[n]):
            n += 1
        block = lines[start:n]
        at = next((i for i, x in enumerate(block) if re.match(r"^\s+titles:\s*$", x)), None)
        if at is None:
            raise Problem(f"{m.group(2)}: its titles aren't written one to a line under `titles:`, so --write "
                          f"can't change them")
        end = at + 1
        while end < len(block) and re.match(r"^\s+- \[", block[end]):
            end += 1
        old = {}
        for x in block[at + 1:end]:
            parsed = yaml.safe_load(x.strip()[2:])
            if isinstance(parsed, list) and len(parsed) == 3:
                old[parsed[2]] = x
        indent = re.match(r"^(\s+)", block[at + 1]).group(1) if end > at + 1 else " " * (len(m.group(1)) + 4)
        new = [old.get(e[2]) or title_line(e, indent) for e in changes[m.group(2)]]
        out.extend(block[:at + 1] + new + block[end:])
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", nargs="?", default=os.path.join(ROOT, "collections.yml"))
    ap.add_argument("--write", action="store_true", help="change the file to match TMDB")
    args = ap.parse_args(argv)
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        print("Set TMDB_API_KEY to a TMDB API key or read access token (on GitHub: the repository secret of that "
              "name).")
        return 2
    with open(args.file, encoding="utf-8") as f:
        text = f.read()
    doc = yaml.safe_load(text) or {}
    today = datetime.date.today().isoformat()
    try:
        results, problems = check(doc, TMDB(key), today)
    except Unreadable as e:
        print(f"Problem: {e}")
        return 2
    changed = {k: titles for k, titles, added, out in results if added or out}
    for k, titles, added, out in results:
        if added or out:
            print(f"{k}:")
            for e in added:
                print(f"  + {title_line(e, '')[2:]}")
            for e in out:
                print(f"  - {json.dumps(e, ensure_ascii=False)} (in none of its TMDB collections or tmdb_add)")
    for p in problems:
        print(f"Problem: {p}")
    print(f"{len(results)} franchise lists checked against TMDB, {len(changed)} would change.")
    if args.write and changed:
        try:
            text = rewrite(text, changed)
        except Problem as e:
            print(f"Problem: {e}")
            return 2
        with open(args.file, "w", encoding="utf-8") as f:
            f.write(text)
        after = {c.get("key"): c.get("titles") for c in (yaml.safe_load(text) or {}).get("collections") or []}
        wrong = [k for k, titles in changed.items() if after.get(k) != titles]
        if wrong:
            print(f"Problem: after writing, the titles of {', '.join(wrong)} aren't what they should be")
            return 1
        print(f"Wrote {args.file}.")
    if problems:
        return 2
    return 1 if changed and not args.write else 0


if __name__ == "__main__":
    sys.exit(main())
