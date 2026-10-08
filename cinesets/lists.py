# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Public mdblist lists, cached on disk so rate limits and outages never empty a collection."""
import os
import re
import time
from urllib.parse import urlparse

import requests

from .store import load_json, save_json

LIST_TTL = 3 * 3600
SLUG = re.compile(r"^[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,120}$")


def slug_of(text):
    """'user/list' from what people paste: the slug itself, or a list's address on mdblist.com. None if it is neither."""
    text = str(text or "").strip()
    if "://" in text or text.startswith(("mdblist.com/", "www.mdblist.com/")):
        url = urlparse(text if "://" in text else "https://" + text)
        if url.hostname not in ("mdblist.com", "www.mdblist.com"):
            return None
        parts = [p for p in url.path.split("/") if p]
        text = "/".join(parts[1:3]) if len(parts) >= 3 and parts[0] == "lists" else ""
    return text if SLUG.match(text) and ".." not in text else None


RETRY_AFTER_MOST = 120  # the longest CineSets waits when mdblist asks it to slow down
_impatient = False  # set once a list has used up its tries on a 429, until the next run


def new_run():
    """Called at the start of each run, so it is patient with mdblist again (see fetch_list)."""
    global _impatient
    _impatient = False


def _wait(r, attempt):
    """Seconds to wait before asking again after a 429: mdblist's Retry-After when it sends one, within reason."""
    asked = str(r.headers.get("Retry-After") or "").strip()
    if asked.replace(".", "", 1).isdigit():
        return min(float(asked), RETRY_AFTER_MOST)
    return 20 * (attempt + 1)


def _rows(r):
    """The rows of a list from mdblist's answer, or ValueError if it isn't a list of rows."""
    rows = r.json()
    if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
        raise ValueError("unexpected response")
    return rows


def fetch_list(slug, data_dir, patient=True):
    """A list's rows. patient=False (the dashboard) tries once instead of waiting out mdblist's rate limit, and so does
    the rest of a run once one list has used up its tries."""
    global _impatient
    if not SLUG.match(slug) or ".." in slug:
        raise RuntimeError(f"{slug!r} is not an mdblist list (it should look like user/list-name)")
    path = os.path.join(data_dir, "lists", slug.replace("/", "__") + ".json")
    cached = load_json(path, None)
    if not (isinstance(cached, dict) and isinstance(cached.get("rows"), list) and isinstance(cached.get("at"), (int, float))):
        cached = None  # a copy that can't be read is the same as none
    if cached and time.time() - cached["at"] < LIST_TTL:
        return cached["rows"]
    patient = patient and not _impatient
    tries = 4 if patient else 1
    problem = status = None
    try:
        for attempt in range(tries):
            r = requests.get(f"https://mdblist.com/lists/{slug}/json", timeout=40 if patient else 20,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; CineSets; +https://github.com/blurbery/cinesets)"})
            if r.status_code != 429 or attempt == tries - 1:
                break
            time.sleep(_wait(r, attempt))  # never after the last try
        status = r.status_code
        if status == 429 and patient:
            _impatient = True
            print("   mdblist is still asking CineSets to slow down, so the rest of this run tries each list once")
        if status == 200:
            rows = _rows(r)
            if rows:
                save_json(path, {"at": time.time(), "rows": rows})
            return rows
        problem = f"HTTP {status}"
    except (requests.RequestException, ValueError) as e:
        problem = type(e).__name__
    if cached:
        print(f"Warning: {slug}: {_stale(cached, path, problem, status)}")
        return cached["rows"]
    raise RuntimeError(f"mdblist {slug}: {problem}")


def _stale(cached, path, problem, status):
    """The warning for a list that can't be fetched, printed every run until it can be. When it started failing is
    kept in the saved copy, so a list deleted upstream doesn't quietly live on."""
    now = time.time()
    if not isinstance(cached.get("failing"), (int, float)):
        cached["failing"] = now
        save_json(path, cached)
    days = int((now - cached["failing"]) / 86400)
    since = f"for {days} days" if days >= 2 else "since yesterday" if days == 1 else "today"
    hours = int((now - cached["at"]) / 3600)
    saved = f"{hours // 24} days ago" if hours >= 48 else f"{hours} h ago"
    why = (" The list may have been deleted or made private: check it, or take it out of the collection."
           if status in (403, 404, 410) else "")
    return f"mdblist has answered {problem} {since}, so CineSets is using the copy it saved {saved}.{why}"
