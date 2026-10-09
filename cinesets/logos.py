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

from . import __version__

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
    "binge": "File:Binge logo.svg",
    "iplayer": "File:BBC iPlayer 2021 (Alt).svg",
    "channel4": "File:Channel 4 2022.svg",
    "crunchyroll": "File:Crunchyroll 2024.svg",
    "shudder": "File:Shudder 2017.svg",
}
# other logos a streaming poster can use instead: "alt" (another version of the logo) and "icon" (the mark alone)
VARIANTS = {
    "netflix": {"icon": ("Netflix N", "File:Netflix 2015 N logo.svg")},
    "prime": {"alt": ("Prime Video 2024", "File:Prime Video logo (2024).svg"),
              "icon": ("Prime Video icon", "File:Amazon Prime Video logo (2024).svg")},
    "disney": {"alt": ("Disney+ alternative", "File:Disney Plus logo.svg")},
    "hbomax": {"alt": ("Max 2023", "File:Max logo.svg")},
    "apple": {"alt": ("Apple TV", "File:Apple TV logo.svg")},
    "hulu": {"alt": ("Hulu 2018", "File:Hulu logo (2018).svg")},
    "paramount": {"alt": ("Paramount+ stacked", "File:Paramount Plus.svg")},
    "iplayer": {"alt": ("iPlayer symbol and wordmark", "File:BBC iPlayer (2021).svg"),
                "icon": ("iPlayer symbol", "File:BBC iPlayer 2021 (symbol).svg")},
    "crunchyroll": {"alt": ("Crunchyroll stacked", "File:Crunchyroll 2024 stacked.svg"),
                    "icon": ("Crunchyroll symbol", "File:Cib-crunchyroll (CoreUI Icons v1.0.0) orange.svg")},
}


def file_name(key, variant="standard"):
    """The downloaded file for a service's logo: netflix.png, or netflix--icon.png for another version."""
    return f"{key}.png" if variant == "standard" else f"{key}--{variant}.png"


def _save(path, data):
    """Write the file next to where it goes, then swap it in, so a download that's cut off never leaves half a logo.
    It's opened plainly, so the logo gets the usual permissions and anyone who could read it before still can."""
    part = f"{path}.{os.getpid()}.part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def download(logos_dir, force=False):
    os.makedirs(logos_dir, exist_ok=True)
    s = requests.Session()
    # Wikimedia asks every tool to name itself, its version and where to find it
    s.headers["User-Agent"] = (f"CineSets/{__version__} (+https://github.com/blurbery/cinesets; self-hosted media server "
                               f"posters) python-requests/{requests.__version__}")
    every = {file_name(k): t for k, t in FILES.items()}
    every.update({file_name(k, v): t for k, versions in VARIANTS.items() for v, (_, t) in versions.items()})
    want = {name: t for name, t in every.items() if force or not os.path.exists(os.path.join(logos_dir, name))}
    if not want:
        print("All logos already downloaded.")
        return
    q = s.get("https://commons.wikimedia.org/w/api.php", params={
        "action": "query", "format": "json", "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 1280, "redirects": 1,
        "titles": "|".join(want.values())}, timeout=30).json()["query"]
    # a title can be tidied (normalized) and then lead on to a file that has been renamed (redirects)
    norm = {n["from"]: n["to"] for n in q.get("normalized", [])}
    moved = {r["from"]: r["to"] for r in q.get("redirects", [])}
    urls = {p["title"]: p["imageinfo"][0].get("thumburl") for p in q.get("pages", {}).values() if p.get("imageinfo")}
    for name, title in want.items():
        key = name[:-4]
        title = norm.get(title, title)
        url = urls.get(moved.get(title, title))
        if not url:
            print(f"  {key}: not found on Wikimedia Commons, posters will show the service name instead")
            continue
        try:
            r = s.get(url, timeout=60)
        except requests.RequestException as e:
            print(f"  {key}: download failed ({type(e).__name__})")
            continue
        if r.ok and r.headers.get("Content-Type", "").startswith("image/png"):
            _save(os.path.join(logos_dir, name), r.content)
            print(f"  {key}: {len(r.content) // 1024} KB")
        else:
            print(f"  {key}: download failed ({r.status_code})")
