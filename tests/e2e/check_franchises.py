# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Keep the fixed franchise lists in collections.yml in step with TMDB's collections.

  TMDB_API_KEY=... python tests/e2e/check_franchises.py            (say what would change)
  TMDB_API_KEY=... python tests/e2e/check_franchises.py --write    (change collections.yml to match)

TMDB_API_KEY is a TMDB API key or API read access token (themoviedb.org, Settings, API). This keeps the `titles`
that come with CineSets current for everyone; people who set their own key get the same changes straight away
(cinesets/tmdb.py).

An entry with `tmdb_collections` gets its films from those TMDB collections, its `tmdb_add` films (spin-offs TMDB
keeps apart, like Ballerina from John Wick) and none of its `tmdb_skip` ones, by the rules in cinesets.tmdb.plan:
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

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cinesets.tmdb import Client as TMDB, Problem, Refused, Unreadable, plan  # noqa: E402

FIELDS = ("tmdb_collections", "tmdb_add", "tmdb_skip")


def ids_of(entry, field):
    """The entry's TMDB ids under `field`, checked: a list of positive whole numbers (empty if it has none)."""
    value = entry.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in value):
        raise Problem(f"{entry.get('key')}: {field} must be a list of TMDB ids, like [404609], not {value!r}")
    return value


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
        hint = ": set TMDB_API_KEY to a TMDB API key or read access token" if isinstance(e, Refused) else ""
        print(f"Problem: {e}{hint}")
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
