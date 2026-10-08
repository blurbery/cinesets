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
SLUG = re.compile(r"^[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,120}\Z")


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


def fetch_list(slug, data_dir, patient=True):
    """A list's rows. patient=False (the dashboard) tries once instead of waiting out mdblist's rate limit."""
    if not SLUG.match(slug) or ".." in slug:
        raise RuntimeError(f"{slug!r} is not an mdblist list (it should look like user/list-name)")
    path = os.path.join(data_dir, "lists", slug.replace("/", "__") + ".json")
    cached = load_json(path, None)
    if cached and time.time() - cached["at"] < LIST_TTL:
        return cached["rows"]
    problem = None
    try:
        for attempt in range(4 if patient else 1):
            r = requests.get(f"https://mdblist.com/lists/{slug}/json", timeout=40 if patient else 20,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; CineSets; +https://github.com/blurbery/cinesets)"})
            if r.status_code != 429 or not patient:
                break
            time.sleep(20 * (attempt + 1))
        if r.status_code == 200:
            rows = r.json()
            if not isinstance(rows, list):
                raise ValueError("unexpected response")
            if rows:
                save_json(path, {"at": time.time(), "rows": rows})
            return rows
        problem = f"HTTP {r.status_code}"
    except (requests.RequestException, ValueError) as e:
        problem = type(e).__name__
    if cached:
        print(f"   {slug}: mdblist {problem}, using the copy from {int((time.time() - cached['at']) / 3600)} h ago")
        return cached["rows"]
    raise RuntimeError(f"mdblist {slug}: {problem}")
