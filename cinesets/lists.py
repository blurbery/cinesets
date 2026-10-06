# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Public mdblist lists, cached on disk so rate limits and outages never empty a collection."""
import os
import time

import requests

from .store import load_json, save_json

LIST_TTL = 3 * 3600


def fetch_list(slug, data_dir):
    path = os.path.join(data_dir, "lists", slug.replace("/", "__") + ".json")
    cached = load_json(path, None)
    if cached and time.time() - cached["at"] < LIST_TTL:
        return cached["rows"]
    problem = None
    try:
        for attempt in range(4):
            r = requests.get(f"https://mdblist.com/lists/{slug}/json", timeout=40,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; CineSets; +https://github.com/blurbery/cinesets)"})
            if r.status_code != 429:
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
