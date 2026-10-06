# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Download streaming service logos from Wikimedia Commons onto this server.

Logos are trademarks of their owners, so CineSets does not ship them. Each server downloads its own copy
for its own posters.
"""
import os

import requests

FILES = {
    "netflix": "File:Netflix 2015 logo.svg",
    "prime": "File:Amazon Prime Video logo.svg",
    "disney": "File:Disney+ logo.svg",
    "hbomax": "File:HBO Max May 2025 (Horizontal).svg",
    "apple": "File:Apple TV Plus Logo.svg",
    "hulu": "File:Hulu Logo.svg",
    "paramount": "File:Paramount+ logo.svg",
    "peacock": "File:NBCUniversal Peacock Logo.svg",
    "stan": "File:Stan logo.svg",
}


def download(logos_dir, force=False):
    os.makedirs(logos_dir, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "CineSets/1.0 (+https://github.com/blurbery/cinesets; self-hosted media server posters)"
    want = {k: t for k, t in FILES.items() if force or not os.path.exists(os.path.join(logos_dir, k + ".png"))}
    if not want:
        print("All logos already downloaded.")
        return
    q = s.get("https://commons.wikimedia.org/w/api.php", params={
        "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1280,
        "titles": "|".join(want.values())}, timeout=30).json()["query"]
    norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
    urls = {p["title"]: p["imageinfo"][0]["thumburl"] for p in q["pages"].values() if p.get("imageinfo")}
    for key, title in want.items():
        url = urls.get(norm.get(title, title))
        if not url:
            print(f"  {key}: not found on Wikimedia Commons, posters will show the service name instead")
            continue
        r = s.get(url, timeout=60)
        if r.ok and r.headers.get("Content-Type", "").startswith("image/png"):
            with open(os.path.join(logos_dir, key + ".png"), "wb") as f:
                f.write(r.content)
            print(f"  {key}: {len(r.content) // 1024} KB")
        else:
            print(f"  {key}: download failed ({r.status_code})")
