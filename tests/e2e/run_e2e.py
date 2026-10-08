# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""End-to-end test against a real, throwaway Emby or Jellyfin server (used by CI).

  python tests/e2e/run_e2e.py --make-media media      (needs ffmpeg; then mount ./media as /media)
  python tests/e2e/run_e2e.py --kind jellyfin --url http://127.0.0.1:8096 --media /media

Runs the first-run wizard, makes an API key and adds a Movies and a TV Shows library. Then it checks that
CineSets creates a franchise collection and list collections matched by IMDb, TMDb and TVDB ids (one with a
genre left out), with the right titles, name, overview, display order, locked fields, sort title and poster. It
shrinks and renames them, changes nothing on a repeat run (also when reading one item per page), takes them back
with adopt after losing its record, refuses to touch a collection it did not create and removes only its own.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from xml.sax.saxutils import escape

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
USER, PASSWORD = "ci", "ci-password"
CLIENT = 'MediaBrowser Client="cinesets-ci", Device="ci", DeviceId="cinesets-ci", Version="1.0"'

# Test titles with their real ids, so the servers' own online lookups agree with the .nfo files
FILMS = [  # title, year, imdb, tmdb, genres
    ("Back to the Future", 1985, "tt0088763", 105, ["Adventure", "Comedy", "Science Fiction"]),
    ("Back to the Future Part II", 1989, "tt0096874", 165, ["Adventure", "Comedy", "Science Fiction"]),
    ("Back to the Future Part III", 1990, "tt0099088", 196, ["Adventure", "Comedy", "Western"]),
    ("The Matrix", 1999, "tt0133093", 603, ["Action", "Science Fiction"]),
]
SHOWS = [  # title, year, imdb, tmdb, tvdb, genres
    ("Stranger Things", 2016, "tt4574334", 66732, 305288, ["Drama", "Mystery", "Science Fiction"]),
    ("The Late Show with Stephen Colbert", 2015, "tt3697842", 63770, 289574, ["Talk", "Comedy"]),
]


def log(msg):
    print(f"[e2e] {msg}", flush=True)


# ------------------------------------------------------------ test media
def video(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=navy:s=320x180:d=3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)


def nfo(path, root, title, year, ids, genres):
    """Kodi-style metadata that Emby and Jellyfin both read, so the ids do not depend on online lookups."""
    lines = [f"<{root}>", f"  <title>{escape(title)}</title>", f"  <year>{year}</year>"]
    lines += [f'  <uniqueid type="{k}"{default}>{v}</uniqueid>' for (k, v), default in zip(ids, [' default="true"'] + [""] * len(ids))]
    lines += [f"  <{k}id>{v}</{k}id>" for k, v in ids]
    lines += [f"  <genre>{escape(g)}</genre>" for g in genres]
    with open(path, "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + "\n".join(lines + [f"</{root}>"]) + "\n")


def make_media(root):
    for title, year, imdb, tmdb, genres in FILMS:
        folder = os.path.join(root, "movies", f"{title} ({year})")
        video(os.path.join(folder, f"{title} ({year}).mkv"))
        nfo(os.path.join(folder, f"{title} ({year}).nfo"), "movie", title, year, [("imdb", imdb), ("tmdb", tmdb)], genres)
    for title, year, imdb, tmdb, tvdb, genres in SHOWS:
        folder = os.path.join(root, "tv", f"{title} ({year})")
        video(os.path.join(folder, "Season 01", f"{title} S01E01.mkv"))
        nfo(os.path.join(folder, "tvshow.nfo"), "tvshow", title, year, [("tvdb", tvdb), ("imdb", imdb), ("tmdb", tmdb)], genres)
    log(f"made {len(FILMS)} films and {len(SHOWS)} shows in {root}")


# ------------------------------------------------------------ server setup
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


def add_library(api, name, collection_type, path):
    api.req("POST", "/Library/VirtualFolders", params={"name": name, "collectionType": collection_type,
                                                       "refreshLibrary": "false", "paths": path}, json={"LibraryOptions": {}})
    folder = next(f for f in api.req("GET", "/Library/VirtualFolders").json() if f["Name"] == name)
    if path not in (folder.get("Locations") or []):
        log(f"library {name} has no path yet ({folder.get('Locations')}); adding it")
        api.req("POST", "/Library/VirtualFolders/Paths", params={"refreshLibrary": "false"},
                json={"Name": name, "Path": path, "PathInfo": {"Path": path}})
        folder = next(f for f in api.req("GET", "/Library/VirtualFolders").json() if f["Name"] == name)
    log(f"library {name} locations: {folder.get('Locations')}")


def scan(api, expect):
    """Scan the libraries and wait for `expect` ({item type: count}) with settled metadata. Returns
    {item type: {name: item}}."""
    def read():
        return {t: api.req("GET", "/Items", params={"Recursive": "true", "IncludeItemTypes": t,
                                                    "Fields": "ProductionYear,ProviderIds,Genres"}).json()["Items"] for t in expect}

    def summary(found):
        return sorted((t, i["Name"], i.get("ProductionYear"), sorted((i.get("ProviderIds") or {}).items()),
                       sorted(i.get("Genres") or [])) for t, items in found.items() for i in items)
    api.req("POST", "/Library/Refresh")
    for _ in range(90):
        found = read()
        if all(len(found[t]) >= n for t, n in expect.items()):
            # wait for metadata to settle: names and ids can change while the scan fetches details
            seen, stable = summary(found), 0
            for _ in range(30):
                time.sleep(5)
                found = read()
                now = summary(found)
                stable = stable + 1 if now == seen else 0
                seen = now
                if stable >= 3:
                    break
            lacking = [i for items in found.values() for i in items if not i.get("ProviderIds")]
            if lacking:
                # a server can leave a new title's details for later (Emby 4.11 did for shows): ask for them now,
                # as you would by hand
                for i in lacking:
                    log(f"{i['Name']} has no ids yet; asking the server to refresh it")
                    api.req("POST", f"/Items/{i['Id']}/Refresh", params={
                        "Recursive": "true", "MetadataRefreshMode": "FullRefresh", "ImageRefreshMode": "Default",
                        "ReplaceAllMetadata": "false", "ReplaceAllImages": "false"})
                for _ in range(30):
                    time.sleep(5)
                    found = read()
                    if all(i.get("ProviderIds") for items in found.values() for i in items):
                        break
            for t, items in found.items():
                for i in items:
                    log(f"{t}: {i['Name']} ({i.get('ProductionYear')}) ids={i.get('ProviderIds')} genres={i.get('Genres')}")
            return {t: {i["Name"]: i for i in items} for t, items in found.items()}
        time.sleep(4)
    raise SystemExit(f"library scan found {({t: len(v) for t, v in found.items()})} of {expect}")


# ------------------------------------------------------------ CineSets
def cinesets(cfg, *args, page=None, fails=False):
    """Run CineSets. `page` sets how many items it asks for per page, so a small library still spans many pages.
    `fails` is for a run where CineSets should turn a collection down, which it reports by exiting with 1."""
    cmd = [sys.executable, "-m", "cinesets", *args, "--config", cfg]
    if page:
        # each server module has its own page size; set both so whichever server this is reads one item at a time
        cmd[1:3] = ["-c", f"import sys, cinesets.cli, cinesets.servers.emby as e, cinesets.servers.jellyfin as j; "
                          f"e.PAGE = j.PAGE = {int(page)}; "
                          "sys.argv[0] = 'cinesets'; cinesets.cli.main()"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    text = out.stdout + out.stderr
    log("cinesets " + " ".join(args) + "\n" + text.strip())
    if out.returncode != (1 if fails else 0):
        raise SystemExit(f"cinesets {' '.join(args)} exited {out.returncode}" + (", not 1" if fails else ""))
    return text


def results(out):
    """What an apply did: {collection name: (created or updated, added, removed)}."""
    return {name: (what, int(a), int(r))
            for what, name, a, r in re.findall(r"^(created|updated) '(.+)': \+(\d+) -(\d+)", out, flags=re.M)}


def paged(api, params):
    """A query's ids read one per page, moving on by what each page held and stopping at an empty page."""
    out, start = [], 0
    while True:
        page = api.req("GET", "/Items", params={**params, "StartIndex": start, "Limit": 1,
                                                 "EnableTotalRecordCount": "false"}).json()["Items"]
        if not page:
            return out
        out += [i["Id"] for i in page]
        start += len(page)
        if start > 100:
            raise SystemExit(f"FAILED: paging {params} never reached an empty page")


def boxsets(api):
    return {i["Name"]: i["Id"] for i in api.req("GET", "/Items", params={"Recursive": "true", "IncludeItemTypes": "BoxSet",
                                                                         "Fields": "SortName"}).json()["Items"]}


def members(api, cid, user_id):
    return sorted(i["Name"] for i in api.req("GET", "/Items", params={"ParentId": cid, "UserId": user_id}).json()["Items"])


def clean(out):
    """No collection failed and every poster upload was kept."""
    return "!!" not in out and "did not keep the poster" not in out


def check(cond, msg):
    if not cond:
        raise SystemExit("FAILED: " + msg)
    log("ok: " + msg)


def check_meta(api, cid, user_id, name, overview, order):
    """The details CineSets writes back to the collection item, as the server kept them."""
    item = collection_item(api, cid, user_id)
    locks = set(item.get("LockedFields") or [])
    want = {"Name", "Overview"} | ({"SortName"} if api.kind == "emby" else set())
    check(item.get("Name") == name, f"{name}: name kept ({item.get('Name')!r})")
    check(item.get("Overview") == overview, f"{name}: overview set ({item.get('Overview')!r})")
    check(item.get("DisplayOrder") == order, f"{name}: display order {order} ({item.get('DisplayOrder')!r})")
    check(want <= locks, f"{name}: {', '.join(sorted(want))} locked ({sorted(locks)})")


def entry(key, kind, title, group, **fields):
    lines = [f"  - key: {key}", f"    group: {group}", f"    type: {kind}", f"    title: {json.dumps(title)}",
             "    accent: blue", "    min: 1"]
    lines += [f"    {k}: {json.dumps(v)}" for k, v in fields.items()]  # JSON is valid YAML
    return "\n".join(lines) + "\n"


def seed_list(data_dir, slug, rows):
    """A fresh cached copy of an mdblist list, so the test needs no outside service."""
    path = os.path.join(data_dir, "lists", slug.replace("/", "__") + ".json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"at": time.time(), "rows": rows}, f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-media", metavar="DIR", help="write the test films and shows to DIR and stop")
    ap.add_argument("--kind", choices=["emby", "jellyfin"])
    ap.add_argument("--url", default="http://127.0.0.1:8096")
    ap.add_argument("--media", default="/media", help="the media folder as the server sees it")
    args = ap.parse_args()
    if args.make_media:
        make_media(args.make_media)
        return
    if not args.kind:
        ap.error("--kind is required")
    api = Api(args.kind, args.url)
    wait_up(api)
    info = api.req("GET", "/System/Info/Public").json()
    log(f"{args.kind} {info.get('Version')} is up")
    key, user_id = first_run(api)
    add_library(api, "Movies", "movies", args.media + "/movies")
    add_library(api, "TV Shows", "tvshows", args.media + "/tv")
    found = scan(api, {"Movie": len(FILMS), "Series": len(SHOWS)})

    def named(item_type, title, year, ids):
        """The server's own name for a test title (a server without online metadata may keep the folder name),
        after checking it carries the ids the test lists use."""
        for name, item in found[item_type].items():
            if name.startswith(title) and item.get("ProductionYear") == year and (title != "Back to the Future" or "Part" not in name):
                prov = {k.lower(): str(v) for k, v in (item.get("ProviderIds") or {}).items()}
                check(all(prov.get(k) == str(v) for k, v in ids.items()), f"the server has the ids of {name} ({prov})")
                return name, year
        raise SystemExit(f"FAILED: the server does not list {title} ({year}): {sorted(found[item_type])}")
    films = {t: named("Movie", t, y, {"imdb": i, "tmdb": m}) for t, y, i, m, _ in FILMS}
    shows = {t: named("Series", t, y, {"tvdb": v, "imdb": i, "tmdb": m}) for t, y, i, m, v, _ in SHOWS}
    bttf = [films["Back to the Future"], films["Back to the Future Part II"], films["Back to the Future Part III"]]
    matrix, stranger, late = films["The Matrix"], shows["Stranger Things"], shows["The Late Show with Stephen Colbert"]
    log(f"test titles as the server names them: {list(films.values()) + list(shows.values())}")

    work = tempfile.mkdtemp(prefix="cinesets-e2e-")
    cfg, coll, data = (os.path.join(work, f) for f in ("config.yml", "collections.yml", "data"))
    with open(cfg, "w") as f:
        f.write(f'server: {{type: {args.kind}, url: "{args.url}", api_key: "{key}"}}\n'
                "libraries: [{name: Movies, type: movie}, {name: TV Shows, type: show}]\n"
                "collections_file: collections.yml\nwrite_pause: 0.2\n")
    # list rows as mdblist sends them; each id kind has to match on its own
    seed_list(data, "ci/movies", [
        {"mediatype": "movie", "rank": 1, "title": "The Matrix", "imdb_id": "tt0133093", "id": None},    # IMDb only
        {"mediatype": "movie", "rank": 2, "title": "Back to the Future", "imdb_id": None, "id": 105},   # TMDb only
        {"mediatype": "movie", "rank": 3, "title": "Not on the server", "imdb_id": "tt0000001", "id": 1},
        {"mediatype": "show", "rank": 4, "title": "Stranger Things", "imdb_id": "tt4574334", "id": 66732},
    ])
    seed_list(data, "ci/shows", [
        {"mediatype": "show", "rank": 1, "title": "The Late Show", "tvdbid": 289574, "imdb_id": "tt3697842", "id": 63770},
        {"mediatype": "show", "rank": 2, "title": "Stranger Things", "tvdbid": 305288, "imdb_id": None, "id": None},  # TVDB only
    ])

    def write(*entries):
        with open(coll, "w") as f:
            f.write("collections:\n" + "".join(entries))

    def franchise(titles):
        return entry("m-bttf", "movie", "Back to\nthe Future", "universes", titles=[list(t) for t in titles])
    picks = entry("m-ci-picks", "movie", "CI Picks", "charts", lists=["ci/movies"])
    all_shows = entry("s-ci-shows", "show", "CI Shows", "charts", lists=["ci/shows"])
    no_talk = entry("s-ci-notalk", "show", "No Talk", "charts", lists=["ci/shows"], exclude_genres=["Talk", "Talk Show"])
    ours = {"Movies - Back to the Future": sorted(t for t, _ in bttf),
            "Movies - CI Picks": sorted([matrix[0], films["Back to the Future"][0]]),
            "TV Shows - CI Shows": sorted([stranger[0], late[0]]),
            "TV Shows - No Talk": [stranger[0]]}

    # 1) create: a franchise by title and year, and list collections by IMDb, TMDb and TVDB id
    write(franchise(bttf), picks, all_shows, no_talk)
    out = cinesets(cfg, "apply")
    done = results(out)
    check(sorted(done) == sorted(ours) and all(d[0] == "created" for d in done.values()) and clean(out),
          f"CineSets created all four collections ({done})")
    sets = boxsets(api)
    ids = {name: sets.get(name) for name in ours}
    check(all(ids.values()), "the collections exist on the server with the right names")
    for name, want in ours.items():
        got = members(api, ids[name], user_id)
        check(got == want, f"{name} holds exactly {want} ({got})")
    item = api.req("GET", "/Items", params={"Ids": ids["Movies - Back to the Future"], "Fields": "SortName"}).json()["Items"][0]
    # servers normalise sort names differently (Jellyfin pads numbers; Jellyfin 12 also drops "+" and "the"),
    # but the block number and the title always lead, which is what keeps the page order
    check(numbers(item.get("SortName", "")).lstrip("+ ").startswith("70_back to"), f"sort title set ({item.get('SortName')})")
    check_meta(api, ids["Movies - Back to the Future"], user_id, "Movies - Back to the Future",
               "Back to the Future movies. Updated automatically.", "PremiereDate")
    check_meta(api, ids["Movies - CI Picks"], user_id, "Movies - CI Picks", "CI Picks movies. Updated automatically.", "SortName")
    check_meta(api, ids["TV Shows - No Talk"], user_id, "TV Shows - No Talk", "No Talk TV shows. Updated automatically.", "SortName")
    for name in ours:
        check(has_poster(api, ids[name], user_id), f"{name}: poster uploaded")

    # 2) shrink
    write(franchise(bttf[:2]), picks, all_shows, no_talk)
    out = cinesets(cfg, "apply")
    check(results(out).get("Movies - Back to the Future") == ("updated", 0, 1), "CineSets removed the film that left the list")
    check(members(api, ids["Movies - Back to the Future"], user_id) == sorted(t for t, _ in bttf[:2]), "collection shrank to two films")
    ours["Movies - Back to the Future"] = sorted(t for t, _ in bttf[:2])

    # 3) nothing to do
    out = cinesets(cfg, "apply")
    done = results(out)
    check(len(done) == 4 and all(d == ("updated", 0, 0) for d in done.values()) and clean(out),
          f"a repeat run changes nothing ({done})")

    # 4) the index, rebuilt now that the collections exist (Jellyfin 12 can list a collection in place of its
    # titles), and paging: the server pages each list the way CineSets asks for it, and CineSets sees everything
    # with one item per page
    folders = {f["Name"]: f["ItemId"] for f in api.req("GET", "/Library/VirtualFolders").json()}
    keyed = Api(args.kind, args.url)  # CineSets reads with the API key, which some servers answer differently
    keyed.token(key)
    library = {"Recursive": "true", "Fields": "ProviderIds,ProductionYear", "CollapseBoxSetItems": "false"}
    titles = {"ParentId": ids["TV Shows - CI Shows"]}
    if api.kind == "jellyfin":
        titles["UserId"] = user_id  # as CineSets asks: Jellyfin lists box set children only for a user
    for what, params in [
            ("the Movies library", {**library, "IncludeItemTypes": "Movie", "ParentId": folders["Movies"]}),
            ("the TV Shows library", {**library, "IncludeItemTypes": "Series", "ParentId": folders["TV Shows"]}),
            ("the collections", {"Recursive": "true", "IncludeItemTypes": "BoxSet"}),
            ("a collection's titles", titles)]:
        full = sorted(i["Id"] for i in keyed.req("GET", "/Items", params=params).json()["Items"])
        got = paged(keyed, params)
        check(len(full) > 1 and sorted(got) == full, f"one item per page reads all of {what} ({len(got)} of {len(full)})")
    with open(os.path.join(data, "index.json")) as f:
        indexed = json.load(f)["items"]  # built before any collection existed
    for how, page in [("now that the collections exist", None), ("with one item per page", 1)]:
        cinesets(cfg, "index", page=page)
        with open(os.path.join(data, "index.json")) as f:
            now = json.load(f)["items"]
        missing = sorted(v["n"] for k, v in indexed.items() if k not in now)
        extra = sorted(v["n"] for k, v in now.items() if k not in indexed)
        check(not missing and not extra and len(now) == len(FILMS) + len(SHOWS),
              f"{how}, CineSets indexed the same titles (missing {missing}, extra {extra})")
    out = cinesets(cfg, "apply", page=1)
    done = results(out)
    check(len(done) == 4 and all(d == ("updated", 0, 0) for d in done.values()) and clean(out),
          f"with one item per page a repeat run still changes nothing ({done})")

    # 5) a new title renames the collection in place
    picks = entry("m-ci-picks", "movie", "CI Favourites", "charts", lists=["ci/movies"])
    write(franchise(bttf[:2]), picks, all_shows, no_talk)
    out = cinesets(cfg, "apply")
    sets = boxsets(api)
    check(results(out).get("Movies - CI Favourites") == ("updated", 0, 0) and clean(out)
          and sets.get("Movies - CI Favourites") == ids["Movies - CI Picks"] and "Movies - CI Picks" not in sets,
          "a new title renamed the collection in place")
    check_meta(api, ids["Movies - CI Picks"], user_id, "Movies - CI Favourites",
               "CI Favourites movies. Updated automatically.", "SortName")
    ids["Movies - CI Favourites"] = ids.pop("Movies - CI Picks")
    ours["Movies - CI Favourites"] = ours.pop("Movies - CI Picks")

    # 6) after losing its record, CineSets leaves the collections alone until adopt takes them back
    os.remove(os.path.join(data, "state.json"))
    before = boxsets(api)
    out = cinesets(cfg, "apply", fails=True)
    check(out.count("not created by CineSets") == 4 and boxsets(api) == before,
          "without its record CineSets refused all four collections")
    out = cinesets(cfg, "adopt", "--all")
    check(out.count("adopted") == 4, "adopt took all four back")
    out = cinesets(cfg, "apply")
    done = results(out)
    check(len(done) == 4 and all(d == ("updated", 0, 0) for d in done.values()) and clean(out) and boxsets(api) == before,
          f"after adopt, apply updated the same collections and made no new ones ({done})")

    # 7) someone else's collection is left alone
    api.req("POST", "/Collections", params={"Name": "Movies - The Matrix", "Ids": found["Movie"][matrix[0]]["Id"]})
    theirs = boxsets(api)["Movies - The Matrix"]
    write(franchise(bttf[:2]), picks, all_shows, no_talk, entry("m-matrix", "movie", "The Matrix", "universes", titles=[list(matrix)]))
    out = cinesets(cfg, "apply", fails=True)
    check("not created by CineSets" in out, "CineSets refused a collection it did not create")
    check("Primary" not in (collection_item(api, theirs, user_id).get("ImageTags") or {}),
          "the other collection's poster was not touched")
    check(members(api, theirs, user_id) == [matrix[0]], "the other collection's titles were not touched")

    # 8) plan and posters write nothing (plan says it would turn down The Matrix, so it exits with 1 too)
    before = boxsets(api)
    cinesets(cfg, "plan", fails=True)
    cinesets(cfg, "posters")
    check(boxsets(api) == before, "plan and posters made no changes")

    # 9) remove deletes only CineSets' own collections
    out = cinesets(cfg, "remove", "--all", "--yes")
    after = boxsets(api)
    check(not set(ours) & set(after), "remove deleted all of CineSets' collections")
    check(after.get("Movies - The Matrix") == theirs, "remove left the other collection alone")
    log(f"ALL CHECKS PASSED on {args.kind} {info.get('Version')}")


if __name__ == "__main__":
    main()
