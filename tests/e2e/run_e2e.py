# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""End-to-end test against a real, throwaway Emby or Jellyfin server (used by CI).

  python tests/e2e/run_e2e.py --kind jellyfin --url http://127.0.0.1:8096 --media /media/movies

Runs the first-run wizard, makes an API key, adds a Movies library, then checks that CineSets creates a
franchise collection with the right films, sort title and poster, shrinks it, changes nothing on a repeat
run, and refuses to touch a collection it did not create.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
USER, PASSWORD = "ci", "ci-password"
CLIENT = 'MediaBrowser Client="cinesets-ci", Device="ci", DeviceId="cinesets-ci", Version="1.0"'


def log(msg):
    print(f"[e2e] {msg}", flush=True)


class Api:
    def __init__(self, kind, url):
        self.kind, self.base = kind, url.rstrip("/") + ("/emby" if kind == "emby" else "")
        self.s = requests.Session()
        self.s.headers.update({"X-Emby-Authorization": CLIENT, "Authorization": CLIENT, "accept": "application/json"})

    def req(self, method, path, ok=(200, 204), **kw):
        for _ in range(60):  # a starting server answers 503 for a while
            r = self.s.request(method, self.base + path, timeout=60, **kw)
            if r.status_code != 503:
                break
            time.sleep(3)
        if r.status_code not in ok:
            raise SystemExit(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r

    def token(self, token):
        auth = CLIENT + f', Token="{token}"'
        self.s.headers.update({"X-Emby-Token": token, "X-Emby-Authorization": auth, "Authorization": auth})


def wait_up(api):
    for _ in range(150):
        try:
            r = api.s.get(api.base + "/System/Info/Public", timeout=5)
            if r.ok and r.headers.get("content-type", "").startswith("application/json") and r.json().get("Version"):
                return
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2)
    raise SystemExit("server did not start")


def numbers(text):
    """Jellyfin pads every number in a sort name to ten digits; compare the numbers, not their padding."""
    return re.sub(r"\d+", lambda m: str(int(m.group())), str(text))


def collection_item(api, cid, user_id):
    path = f"/Items/{cid}?userId={user_id}" if api.kind == "jellyfin" else f"/Users/{user_id}/Items/{cid}"
    return api.req("GET", path).json()


def has_poster(api, cid, user_id):
    for _ in range(15):
        item = collection_item(api, cid, user_id)
        if "Primary" in (item.get("ImageTags") or {}):
            return True
        time.sleep(2)
    r = api.s.get(api.base + f"/Items/{cid}/Images/Primary", timeout=30)
    log(f"poster diagnostics: ImageTags={item.get('ImageTags')} ImageInfos?={'Primary' in str(item)} "
        f"GET image -> {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes; path={item.get('Path')}")
    return False


def first_run(api):
    culture = {"UICulture": "en-US", "MetadataCountryCode": "US", "PreferredMetadataLanguage": "en"}
    api.req("POST", "/Startup/Configuration", json=culture)
    api.req("GET", "/Startup/User")
    api.req("POST", "/Startup/User", json={"Name": USER, "Password": PASSWORD})
    if api.kind == "jellyfin":
        api.req("POST", "/Startup/RemoteAccess", json={"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False})
    api.req("POST", "/Startup/Complete")
    auth = api.req("POST", "/Users/AuthenticateByName", json={"Username": USER, "Pw": PASSWORD}).json()
    api.token(auth["AccessToken"])
    api.req("POST", "/Auth/Keys", params={"app" if api.kind == "jellyfin" else "App": "cinesets-ci"})
    keys = api.req("GET", "/Auth/Keys").json()["Items"]
    key = keys[-1]["AccessToken"]
    user_id = next(u["Id"] for u in api.req("GET", "/Users").json() if u.get("Policy", {}).get("IsAdministrator"))
    return key, user_id


def add_library(api, media, expect):
    api.req("POST", "/Library/VirtualFolders", params={"name": "Movies", "collectionType": "movies", "refreshLibrary": "false",
                                                       "paths": media}, json={"LibraryOptions": {}})
    folder = next(f for f in api.req("GET", "/Library/VirtualFolders").json() if f["Name"] == "Movies")
    if media not in (folder.get("Locations") or []):
        log(f"library has no path yet ({folder.get('Locations')}); adding it")
        api.req("POST", "/Library/VirtualFolders/Paths", params={"refreshLibrary": "false"},
                json={"Name": "Movies", "Path": media, "PathInfo": {"Path": media}})
        folder = next(f for f in api.req("GET", "/Library/VirtualFolders").json() if f["Name"] == "Movies")
    log(f"library locations: {folder.get('Locations')}")
    api.req("POST", "/Library/Refresh")
    for _ in range(90):
        items = api.req("GET", "/Items", params={"Recursive": "true", "IncludeItemTypes": "Movie",
                                                 "Fields": "ProductionYear"}).json()["Items"]
        if len(items) >= expect:
            # wait for online metadata to settle: names can change while the scan fetches details
            seen = sorted((i["Name"], i.get("ProductionYear")) for i in items)
            stable = 0
            for _ in range(30):
                time.sleep(5)
                items = api.req("GET", "/Items", params={"Recursive": "true", "IncludeItemTypes": "Movie",
                                                         "Fields": "ProductionYear"}).json()["Items"]
                now = sorted((i["Name"], i.get("ProductionYear")) for i in items)
                stable = stable + 1 if now == seen else 0
                seen = now
                if stable >= 3:
                    break
            log("library: " + ", ".join(f"{i['Name']} ({i.get('ProductionYear')})" for i in items))
            return {i["Name"]: i for i in items}
        time.sleep(4)
    raise SystemExit(f"library scan found {len(items)} of {expect} films")


def cinesets(cfg, *args):
    out = subprocess.run([sys.executable, "-m", "cinesets", *args, "--config", cfg], cwd=ROOT,
                         capture_output=True, text=True, timeout=600)
    text = out.stdout + out.stderr
    log("cinesets " + " ".join(args) + "\n" + text.strip())
    if out.returncode:
        raise SystemExit(f"cinesets {' '.join(args)} exited {out.returncode}")
    return text


def boxsets(api):
    return {i["Name"]: i["Id"] for i in api.req("GET", "/Items", params={"Recursive": "true", "IncludeItemTypes": "BoxSet",
                                                                         "Fields": "SortName"}).json()["Items"]}


def members(api, cid, user_id):
    return sorted(i["Name"] for i in api.req("GET", "/Items", params={"ParentId": cid, "UserId": user_id}).json()["Items"])


def check(cond, msg):
    if not cond:
        raise SystemExit("FAILED: " + msg)
    log("ok: " + msg)


def franchise(titles, key="m-bttf", title="Back to\\nthe Future"):
    lines = [f"  - key: {key}", "    group: universes", "    type: movie", f'    title: "{title}"', "    accent: blue",
             "    min: 1", "    titles:"]
    lines += [f'      - ["{t}", {y}]' for t, y in titles]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["emby", "jellyfin"], required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8096")
    ap.add_argument("--media", default="/media/movies")
    args = ap.parse_args()
    api = Api(args.kind, args.url)
    wait_up(api)
    info = api.req("GET", "/System/Info/Public").json()
    log(f"{args.kind} {info.get('Version')} is up")
    key, user_id = first_run(api)
    films = add_library(api, args.media, 4)

    def film(title, year):
        """The server's own name for a test film (a server without online metadata may keep the folder name)."""
        for name, item in films.items():
            if name.startswith(title) and item.get("ProductionYear") == year and (title != "Back to the Future" or "Part" not in name):
                return name, year
        raise SystemExit(f"FAILED: the server does not list {title} ({year}): {sorted(films)}")
    bttf = [film("Back to the Future", 1985), film("Back to the Future Part II", 1989), film("Back to the Future Part III", 1990)]
    matrix = film("The Matrix", 1999)
    log(f"test films as the server names them: {bttf + [matrix]}")

    work = tempfile.mkdtemp(prefix="cinesets-e2e-")
    cfg, coll = os.path.join(work, "config.yml"), os.path.join(work, "collections.yml")
    with open(cfg, "w") as f:
        f.write(f'server: {{type: {args.kind}, url: "{args.url}", api_key: "{key}"}}\n'
                "libraries: [{name: Movies, type: movie}]\ncollections_file: collections.yml\nwrite_pause: 0.2\n")

    # 1) create
    with open(coll, "w") as f:
        f.write("collections:\n" + franchise(bttf))
    out = cinesets(cfg, "apply")
    check("created 'Movies - Back to the Future'" in out and "!!" not in out, "CineSets created the collection")
    sets = boxsets(api)
    check("Movies - Back to the Future" in sets, "collection exists on the server with the right name")
    cid = sets["Movies - Back to the Future"]
    got = members(api, cid, user_id)
    check(got == sorted(t for t, _ in bttf), f"collection holds exactly the three films ({got})")
    item = api.req("GET", "/Items", params={"Ids": cid, "Fields": "SortName"}).json()["Items"][0]
    # servers normalise sort names differently (Jellyfin pads numbers; Jellyfin 12 also drops "+" and "the"),
    # but the block number and the title always lead, which is what keeps the page order
    check(numbers(item.get("SortName", "")).lstrip("+ ").startswith("70_back to"), f"sort title set ({item.get('SortName')})")
    check(has_poster(api, cid, user_id), "poster uploaded")

    # 2) shrink
    with open(coll, "w") as f:
        f.write("collections:\n" + franchise(bttf[:2]))
    out = cinesets(cfg, "apply")
    check("+0 -1" in out, "CineSets removed the film that left the list")
    check(members(api, cid, user_id) == sorted(t for t, _ in bttf[:2]), "collection shrank to two films")

    # 3) nothing to do
    out = cinesets(cfg, "apply")
    check("+0 -0" in out and "!!" not in out, "a repeat run changes nothing")

    # 4) someone else's collection is left alone
    api.req("POST", "/Collections", params={"Name": "Movies - The Matrix", "Ids": films[matrix[0]]["Id"]})
    theirs = boxsets(api)["Movies - The Matrix"]
    with open(coll, "a") as f:
        f.write(franchise([matrix], key="m-matrix", title="The Matrix"))
    out = cinesets(cfg, "apply")
    check("not created by CineSets" in out, "CineSets refused a collection it did not create")
    check("Primary" not in (collection_item(api, theirs, user_id).get("ImageTags") or {}),
          "the other collection's poster was not touched")

    # 5) plan and posters write nothing
    before = boxsets(api)
    cinesets(cfg, "plan")
    cinesets(cfg, "posters")
    check(boxsets(api) == before, "plan and posters made no changes")

    # 6) remove deletes only CineSets' own collection
    out = cinesets(cfg, "remove", "--all", "--yes")
    after = boxsets(api)
    check("Movies - Back to the Future" not in after, "remove deleted CineSets' collection")
    check(after.get("Movies - The Matrix") == theirs, "remove left the other collection alone")
    log(f"ALL CHECKS PASSED on {args.kind} {info.get('Version')}")


if __name__ == "__main__":
    main()
