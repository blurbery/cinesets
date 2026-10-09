# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Check every mdblist list a collections file uses, and report the ones that need replacing.

  python tests/e2e/check_lists.py                      (the shipped collections.yml)
  python tests/e2e/check_lists.py my-collections.yml custom-collections.yml

Each list is read once, from the same address CineSets reads (cinesets/lists.py), one request at a time with a
pause between them, and the run stops if mdblist asks it to slow down. A list fails when it is gone or private
(mdblist answers 404 for both), answers with an error or something that isn't a list, is empty, or has none of the
movies or shows its collection needs. Lists for charts and streaming services should follow what's new, so they
also fail when nothing in them is recent. Lists such as "Best of the 70s" are never stale.

Exits 0 when every list is fine, 1 when any list fails, and 2 when mdblist rate limited the run before the end.
"""
import argparse
import datetime
import os
import sys
import time

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cinesets.lists import SLUG  # noqa: E402

AGENT = "Mozilla/5.0 (compatible; CineSets; +https://github.com/blurbery/cinesets)"
NOUN = {"movie": "movies", "show": "shows"}
KINDS = {"movie": "movie", "movies": "movie", "show": "show", "shows": "show", "tv": "show", "tvshows": "show",
         "series": "show"}
# how recent the newest title has to be for groups that follow what's new: days back from today
RECENT = {"charts": 183, "streaming": 2 * 365}


def lists_in(paths):
    """{slug: [(key, group, kind)]} in the order the files use them."""
    found = {}
    for path in paths:
        with open(path) as f:
            doc = yaml.safe_load(f) or {}
        for c in doc.get("collections") or []:
            if not isinstance(c, dict):
                continue
            kind = KINDS.get(str(c.get("type", "")).lower())
            for slug in list(c.get("lists") or []) + list(c.get("add_lists") or []):
                found.setdefault(str(slug), []).append((c.get("key"), c.get("group"), kind))
    return found


def verdict(slug, rows, users, today):
    """None if the list is fine, else what is wrong with it. rows is what mdblist answered."""
    if not isinstance(rows, list):
        return "mdblist did not answer with a list"
    if not rows:
        return "empty"
    for key, group, kind in users:
        mine = [r for r in rows if isinstance(r, dict) and (kind is None or r.get("mediatype") == kind)]
        if not mine:
            return f"no {NOUN.get(kind, 'titles')} for {key}"
        if group in RECENT:
            years = [r.get("release_year") for r in mine if isinstance(r.get("release_year"), int)]
            since = (today - datetime.timedelta(days=RECENT[group])).year
            if not years or max(years) < since:
                return f"stale for {key}: the newest of its {NOUN.get(kind, 'titles')} is from " \
                       f"{max(years) if years else 'no known year'}, nothing from {since} on"
    return None


def fetch(session, slug):
    """(rows or None, problem or None, rate limited). Waits out one slow-down request before giving up."""
    for attempt in range(2):
        try:
            r = session.get(f"https://mdblist.com/lists/{slug}/json", timeout=40)
        except requests.RequestException as e:
            return None, f"no answer ({type(e).__name__})", False
        if r.status_code == 429:
            if attempt == 0:
                wait = r.headers.get("Retry-After", "")
                time.sleep(min(int(wait), 300) if wait.isdigit() else 60)
                continue
            return None, "rate limited", True
        if r.status_code == 404:
            return None, "gone or private (HTTP 404)", False
        if r.status_code in (401, 403):
            return None, f"private (HTTP {r.status_code})", False
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}", False
        try:
            return r.json(), None, False
        except ValueError:
            return None, "not JSON", False
    return None, "rate limited", True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", default=[os.path.join(ROOT, "collections.yml")])
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between requests (at least 1)")
    args = ap.parse_args(argv)
    pause = max(args.pause, 1.0)
    found = lists_in(args.files)
    today = datetime.date.today()
    session = requests.Session()
    session.headers["User-Agent"] = AGENT
    failed, limited = [], False
    print(f"Checking {len(found)} lists, {pause:g} s apart...")
    for n, (slug, users) in enumerate(found.items(), start=1):
        keys = ", ".join(str(k) for k, _, _ in users)
        if not SLUG.match(slug) or ".." in slug:
            problem, rows = "not an mdblist list (like user/list-name)", None
        else:
            if n > 1:
                time.sleep(pause)
            rows, problem, limited = fetch(session, slug)
            if limited:
                print(f"Rate limited by mdblist after {n - 1} lists; stopping. Not checked: "
                      f"{', '.join(list(found)[n - 1:])}")
                break
        problem = problem or verdict(slug, rows, users, today)
        if problem:
            failed.append(slug)
            print(f"FAIL  {slug} ({keys}): {problem}")
        else:
            kinds = {}
            for r in rows:
                kinds[r.get("mediatype")] = kinds.get(r.get("mediatype"), 0) + 1
            years = [r.get("release_year") for r in rows if isinstance(r.get("release_year"), int)]
            parts = ", ".join(f"{v} {NOUN.get(k, k)}" for k, v in sorted(kinds.items(), key=lambda x: str(x[0])))
            print(f"ok    {slug} ({keys}): {parts}, newest {max(years) if years else '?'}")
    print(f"\n{len(failed)} of {len(found)} lists need looking at" + (": " + ", ".join(failed) if failed else "."))
    return 2 if limited else 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
