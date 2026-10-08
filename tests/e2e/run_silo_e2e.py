# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""End-to-end test against a real, throwaway Silo server (used by CI), set up the way a new user would.

  python tests/e2e/run_silo_e2e.py --make-media media      (needs ffmpeg; then mount ./media as /mnt/media)
  python tests/e2e/run_silo_e2e.py --url http://127.0.0.1:8080 --media /mnt/media

Makes the first administrator and an API key, adds a Movies and a TV Shows library (titles carry their ids in their
folder names, and .nfo files give them genres, their other ids and artwork, so nothing depends on online lookups),
then runs `cinesets setup` as a new user would, given Silo's Jellyfin-compatible port. Then it checks that CineSets
creates manual library collections matched by IMDb, TMDb and TVDB ids (one with a genre left out, one matched by a
show's IMDb id, which only Silo's item details have), with the right titles, libraries, description, display order,
page order and poster. It shrinks and renames them, changes nothing on a repeat run, takes them back with adopt
after losing its record, refuses to touch a collection it did not create and removes only its own.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_e2e import FILMS, ROOT, SHOWS, check, cinesets, clean, entry, log, nfo, results, seed_list, video  # noqa: E402

ADMIN = {"username": "ci", "email": "ci@example.com", "password": "ci-password-123", "create_default_profile": True}


# ------------------------------------------------------------ test media
def tag(ids):
    """The folder-name tag Silo takes a title's id from: {tmdb-105}, {imdb-tt0133093}, {tvdb-305288}."""
    k, v = ids
    return "{%s-%s}" % (k, v)


def picture(path, colour):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c={colour}:s=1280x720",
                    "-frames:v", "1", path], check=True)


def make_media(root):
    for n, (title, year, imdb, tmdb, genres) in enumerate(FILMS):
        # The Matrix is known to Silo by its IMDb id (movie-imdb-...), the others by their TMDb id
        main = ("imdb", imdb) if title == "The Matrix" else ("tmdb", tmdb)
        name = f"{title} ({year}) {tag(main)}"
        folder = os.path.join(root, "movies", name)
        video(os.path.join(folder, name + ".mkv"))
        others = [x for x in (("imdb", imdb), ("tmdb", tmdb)) if x != main]
        nfo(os.path.join(folder, "movie.nfo"), "movie", title, year, [main] + others, genres)
        picture(os.path.join(folder, "fanart.jpg"), ["navy", "darkred", "darkgreen", "purple"][n % 4])
    for n, (title, year, imdb, tmdb, tvdb, genres) in enumerate(SHOWS):
        folder = os.path.join(root, "tv", f"{title} ({year}) {tag(('tvdb', tvdb))}")
        video(os.path.join(folder, "Season 01", f"{title} - S01E01.mkv"))
        nfo(os.path.join(folder, "tvshow.nfo"), "tvshow", title, year, [("tvdb", tvdb), ("imdb", imdb), ("tmdb", tmdb)], genres)
        picture(os.path.join(folder, "fanart.jpg"), ["teal", "olive"][n % 2])
    log(f"made {len(FILMS)} films and {len(SHOWS)} shows in {root}")


# ------------------------------------------------------------ server setup
class Silo:
    def __init__(self, url):
        self.base = url.rstrip("/") + "/api/v2"
        self.s = requests.Session()
        self.s.headers.update({"accept": "application/json"})

    def req(self, method, path, ok=(200, 201, 202, 204), **kw):
        for _ in range(60):  # a starting server can answer 503 for a while
            r = self.s.request(method, self.base + path, timeout=60, **kw)
            if r.status_code not in (502, 503):
                break
            time.sleep(3)
        if r.status_code not in ok:
            raise SystemExit(f"{method} {path} -> {r.status_code} {r.text[:400]}")
        return r

    def json(self, method, path, **kw):
        r = self.req(method, path, **kw)
        return r.json() if r.content else None


def wait_up(silo):
    for _ in range(150):
        try:
            r = silo.s.get(silo.base + "/system/setup", timeout=5)
            if r.status_code == 200 and "needs_setup" in r.json():
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(3)
    raise SystemExit("Silo did not start")


def first_run(silo):
    """The first administrator (as the setup page makes it) and an API key for CineSets, as Admin > API keys does."""
    tokens = silo.json("POST", "/auth/setup", json=ADMIN)
    silo.s.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    created = silo.json("POST", "/admin/api-keys", json={"label": "cinesets"})
    check(created["key"].startswith("sa_") and not created["scopes"], "made an unscoped API key for the administrator")
    profile = next(p for p in silo.json("GET", "/profiles")["items"] if p.get("is_primary"))
    silo.s.headers["X-Profile-Id"] = str(profile["id"])
    return created["key"]


def add_library(silo, name, kind, path):
    lib = silo.json("POST", "/libraries", json={"name": name, "type": kind, "paths": [path]})
    log(f"library {name} ({kind}) at {path}: id {lib['id']}")
    return str(lib["id"])


def enable_nfo(silo, lib):
    """Turn on Silo's local .nfo reader for a library (Admin > Libraries > metadata providers)."""
    chain = silo.json("GET", f"/libraries/{lib}/providers")
    found = False
    levels = []
    for level in chain["levels"]:
        entries = []
        for e in level["entries"]:
            on = e.get("enabled") or e.get("provider_slug") == "nfo"
            found |= e.get("provider_slug") == "nfo"
            entries.append({k: e[k] for k in ("capability_id", "plugin_installation_id", "priority") if e.get(k) is not None}
                           | {"enabled": bool(on)})
        levels.append({"content_level": level["content_level"], "entries": entries})
    check(found, f"library {lib} offers the .nfo provider ({[e.get('provider_slug') for l in chain['levels'] for e in l['entries']]})")
    silo.req("PUT", f"/libraries/{lib}/providers", json={"levels": levels})


def wait_scanned(silo, libs):
    for _ in range(100):
        state = {str(lib["id"]): lib.get("last_scanned_at") for lib in silo.json("GET", "/libraries")["items"]}
        if all(state.get(lib) for lib in libs):
            return
        time.sleep(3)
    raise SystemExit(f"libraries were not scanned: {state}")


def refresh(silo, lib):
    job = silo.json("POST", f"/libraries/{lib}/refresh-metadata", json={"mode": "full"})
    for _ in range(100):
        job = silo.json("GET", f"/library-jobs/{job['id']}")
        if job.get("terminal"):
            check(not job.get("failure"), f"metadata refresh of library {lib} finished ({job.get('state')}, {job.get('failure')})")
            return
        time.sleep(3)
    raise SystemExit(f"metadata refresh of library {lib} did not finish: {job}")


def catalogue(silo, lib, typ):
    return silo.json("GET", "/catalog", params={"library_id": lib, "type": typ, "limit": 200})["items"]


def wait_titles(silo, libs):
    """Wait until every test title is listed with its genres and its artwork (Silo fetches artwork after the
    details, shows last). Returns {title: content id}."""
    want = len(FILMS) + len(SHOWS)
    for _ in range(90):
        cards = catalogue(silo, libs["Movies"], "movie") + catalogue(silo, libs["TV Shows"], "series")
        ready = [c for c in cards if c.get("genres") and (c.get("backdrop_url") or c.get("backdrop_thumbhash"))]
        if len(ready) >= want:
            break
        time.sleep(4)
    for c in cards:
        log(f"{c['type']}: {c['title']} ({c.get('year')}) {c['content_id']} genres={c.get('genres')} "
            f"backdrop={bool(c.get('backdrop_url') or c.get('backdrop_thumbhash'))}")
    check(len(ready) == want, f"every title has its genres and the artwork from its fanart.jpg ({len(ready)} of {want})")
    return {c["title"]: c["content_id"] for c in cards}


# ------------------------------------------------------------ CineSets
def run_setup(key, url, compat):
    """`cinesets setup` as a new user runs it, answering its questions. The address given is Silo's
    Jellyfin-compatible port when it is on, which setup has to turn into Silo's own address."""
    work = tempfile.mkdtemp(prefix="cinesets-silo-e2e-")
    cfg = os.path.join(work, "config.yml")
    typed = "127.0.0.1:8096" if compat else url
    out = subprocess.run([sys.executable, "-m", "cinesets", "setup", "--config", cfg], cwd=ROOT, input=f"{typed}\n{key}\n",
                         capture_output=True, text=True, timeout=300, start_new_session=True)  # no terminal: the key comes from stdin
    log("cinesets setup\n" + (out.stdout + out.stderr).strip())
    if out.returncode:
        raise SystemExit(f"cinesets setup exited {out.returncode}")
    check("Found Silo at " + url in out.stdout, f"setup found Silo at {url} (typed {typed})")
    with open(cfg) as f:
        text = f.read()
    check("type: silo" in text and f'url: "{url}"' in text, "setup wrote a Silo config")
    check("{name: \"Movies\", type: movie}" in text and "{name: \"TV Shows\", type: show}" in text, "setup found both libraries")
    text = re.sub(r"(?m)^write_pause: .*$", "write_pause: 0.2", text)
    with open(cfg, "w") as f:
        f.write(text)
    return work, cfg


def collections(silo):
    return {c["title"]: c for c in silo.json("GET", "/admin/collections")["items"]}


def members(silo, cid):
    out, cursor = [], None
    while True:
        page = silo.json("GET", f"/admin/collections/{cid}/items", params={"limit": 200, **({"cursor": cursor} if cursor else {})})
        out += [r["media_item_id"] for r in page["items"]]
        cursor = (page.get("page") or {}).get("next_cursor")
        if not cursor:
            return sorted(out)


def page_order(silo, lib):
    return silo.json("GET", "/admin/collections/order", params={"library_id": lib})["ordered_ids"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make-media", metavar="DIR", help="write the test films and shows to DIR and stop")
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--media", default="/mnt/media", help="the media folder as Silo sees it")
    args = ap.parse_args()
    if args.make_media:
        make_media(args.make_media)
        return
    silo = Silo(args.url)
    status = wait_up(silo)
    info = silo.json("GET", "/system/info")
    log(f"Silo {info.get('server_version')} is up ({status})")
    key = first_run(silo)
    libs = {"Movies": add_library(silo, "Movies", "movies", args.media + "/movies"),
            "TV Shows": add_library(silo, "TV Shows", "series", args.media + "/tv")}
    wait_scanned(silo, libs.values())
    for lib in libs.values():
        enable_nfo(silo, lib)
        refresh(silo, lib)
    ids = wait_titles(silo, libs)

    def cid(title):
        return next(v for k, v in ids.items() if k.startswith(title) and (title != "Back to the Future" or "Part" not in k))
    bttf = [cid("Back to the Future"), cid("Back to the Future Part II"), cid("Back to the Future Part III")]
    matrix, stranger, late = cid("The Matrix"), cid("Stranger Things"), cid("The Late Show")
    # The Matrix's folder carries its IMDb id; Silo may move it to its TMDb id once it looks it up, either is fine
    check(bttf[0] == "movie-tmdb-105" and stranger == "series-tvdb-305288" and matrix in ("movie-imdb-tt0133093", "movie-tmdb-603"),
          f"Silo took the ids from the folder names ({bttf[0]}, {matrix}, {stranger})")

    try:
        compat = "Silo" in requests.get("http://127.0.0.1:8096/Branding/Configuration", timeout=5).json().get("LoginDisclaimer", "")
    except (requests.RequestException, ValueError):
        compat = False
    log(f"Jellyfin-compatible port {'answers' if compat else 'is off'}")
    work, cfg = run_setup(key, args.url, compat)
    data = os.path.join(work, "data")
    coll = os.path.join(work, "collections.yml")
    # list rows as mdblist sends them; each id kind has to match on its own
    seed_list(data, "ci/movies", [
        # mdblist gives every film its TMDb id, which Silo keys films by; IMDb-only matching is tested with a show below
        {"mediatype": "movie", "rank": 1, "title": "The Matrix", "imdb_id": "tt0133093", "id": 603},
        {"mediatype": "movie", "rank": 2, "title": "Back to the Future", "imdb_id": None, "id": 105},   # TMDb only
        {"mediatype": "movie", "rank": 3, "title": "Not on the server", "imdb_id": "tt0000001", "id": 1},
        {"mediatype": "show", "rank": 4, "title": "Stranger Things", "imdb_id": "tt4574334", "id": 66732},
    ])
    seed_list(data, "ci/shows", [
        {"mediatype": "show", "rank": 1, "title": "The Late Show", "tvdbid": 289574, "imdb_id": "tt3697842", "id": 63770},
        {"mediatype": "show", "rank": 2, "title": "Stranger Things", "tvdbid": 305288, "imdb_id": None, "id": None},  # TVDB only
    ])
    seed_list(data, "ci/imdb-shows", [  # IMDb only: Silo knows the show by its TVDB id, so this needs the id lookup
        {"mediatype": "show", "rank": 1, "title": "Stranger Things", "tvdbid": None, "imdb_id": "tt4574334", "id": None},
    ])

    def write(*entries):
        with open(coll, "w") as f:
            f.write("collections:\n" + "".join(entries))

    def franchise(titles):
        return entry("m-bttf", "movie", "Back to\nthe Future", "universes", titles=[list(t) for t in titles])
    films = [(t, y) for t, y, *_ in FILMS[:3]]
    picks = entry("m-ci-picks", "movie", "CI Picks", "charts", lists=["ci/movies"])
    all_shows = entry("s-ci-shows", "show", "CI Shows", "charts", lists=["ci/shows"])
    no_talk = entry("s-ci-notalk", "show", "No Talk", "charts", lists=["ci/shows"], exclude_genres=["Talk", "Talk Show"])
    by_imdb = entry("s-ci-imdb", "show", "By IMDb", "charts", lists=["ci/imdb-shows"])
    ours = {"Movies - Back to the Future": sorted(bttf), "Movies - CI Picks": sorted([matrix, bttf[0]]),
            "TV Shows - CI Shows": sorted([stranger, late]), "TV Shows - No Talk": [stranger], "TV Shows - By IMDb": [stranger]}
    in_library = {"Movies - Back to the Future": libs["Movies"], "Movies - CI Picks": libs["Movies"],
                  "TV Shows - CI Shows": libs["TV Shows"], "TV Shows - No Talk": libs["TV Shows"], "TV Shows - By IMDb": libs["TV Shows"]}

    # 1) create
    write(franchise(films), picks, all_shows, no_talk, by_imdb)
    out = cinesets(cfg, "apply")
    done = results(out)
    check(sorted(done) == sorted(ours) and all(d[0] == "created" for d in done.values()) and clean(out),
          f"CineSets created all five collections ({done})")
    sets = collections(silo)
    made = {name: sets.get(name) for name in ours}
    check(all(made.values()), "the collections exist in Silo with the right names")
    for name, want in ours.items():
        c = made[name]
        check(c["collection_type"] == "manual" and [str(x) for x in c["library_ids"]] == [in_library[name]],
              f"{name}: a manual collection in its library ({c['collection_type']}, {c['library_ids']})")
        check(members(silo, c["id"]) == want, f"{name} holds exactly {want} ({members(silo, c['id'])})")
        check(bool(c.get("poster_thumbhash") or c.get("poster_url")), f"{name}: poster uploaded")
    order = {"Movies - Back to the Future": "release_date", "Movies - CI Picks": "title"}
    for name, field in order.items():
        check((made[name].get("sort_config") or {}).get("field") == field, f"{name}: titles ordered by {field} ({made[name].get('sort_config')})")
    check(made["Movies - Back to the Future"]["description"] == "Back to the Future movies. Updated automatically.",
          "description set")
    movies_order = page_order(silo, libs["Movies"])
    check(movies_order.index(made["Movies - CI Picks"]["id"]) < movies_order.index(made["Movies - Back to the Future"]["id"]),
          f"charts come before franchises on the page ({movies_order})")
    if compat:  # people using Jellyfin apps see them too
        r = requests.get("http://127.0.0.1:8096/Items", params={"IncludeItemTypes": "BoxSet", "Recursive": "true"},
                         headers={"X-Emby-Token": key}, timeout=30)
        names = {i["Name"] for i in r.json().get("Items", [])}
        check(set(ours) <= names, f"Jellyfin apps see the collections ({sorted(names)})")

    # 2) shrink
    write(franchise(films[:2]), picks, all_shows, no_talk, by_imdb)
    out = cinesets(cfg, "apply")
    check(results(out).get("Movies - Back to the Future") == ("updated", 0, 1), "CineSets removed the film that left the list")
    check(members(silo, made["Movies - Back to the Future"]["id"]) == sorted(bttf[:2]), "collection shrank to two films")

    # 3) nothing to do
    out = cinesets(cfg, "apply")
    done = results(out)
    check(len(done) == 5 and all(d == ("updated", 0, 0) for d in done.values()) and clean(out),
          f"a repeat run changes nothing ({done})")
    check("looking up the ids" not in out, "the show ids were looked up only once")

    # 4) a new title renames the collection in place
    picks = entry("m-ci-picks", "movie", "CI Favourites", "charts", lists=["ci/movies"])
    write(franchise(films[:2]), picks, all_shows, no_talk, by_imdb)
    out = cinesets(cfg, "apply")
    sets = collections(silo)
    check(results(out).get("Movies - CI Favourites") == ("updated", 0, 0) and clean(out)
          and sets["Movies - CI Favourites"]["id"] == made["Movies - CI Picks"]["id"] and "Movies - CI Picks" not in sets,
          "a new title renamed the collection in place")
    ours["Movies - CI Favourites"] = ours.pop("Movies - CI Picks")

    # 5) after losing its record, CineSets leaves the collections alone until adopt takes them back
    os.remove(os.path.join(data, "state.json"))
    before = {k: v["id"] for k, v in collections(silo).items()}
    out = cinesets(cfg, "apply", fails=True)
    check(out.count("not created by CineSets") == 5 and {k: v["id"] for k, v in collections(silo).items()} == before,
          "without its record CineSets refused all five collections")
    out = cinesets(cfg, "adopt", "--all")
    check(out.count("adopted") == 5, "adopt took all five back")
    out = cinesets(cfg, "apply")
    done = results(out)
    check(len(done) == 5 and all(d == ("updated", 0, 0) for d in done.values()) and clean(out)
          and {k: v["id"] for k, v in collections(silo).items()} == before,
          f"after adopt, apply updated the same collections and made no new ones ({done})")

    # 6) someone else's collection is left alone
    theirs = silo.json("POST", "/admin/collections", json={"title": "Movies - The Matrix", "library_ids": [libs["Movies"]],
                                                           "collection_type": "manual"})["id"]
    silo.req("PUT", f"/admin/collections/{theirs}/items/{matrix}", json={"position": 0})
    write(franchise(films[:2]), picks, all_shows, no_talk, by_imdb,
          entry("m-matrix", "movie", "The Matrix", "universes", titles=[["The Matrix", 1999]]))
    out = cinesets(cfg, "apply", fails=True)
    check("not created by CineSets" in out, "CineSets refused a collection it did not create")
    mine = collections(silo)["Movies - The Matrix"]
    check(not mine.get("poster_thumbhash") and members(silo, theirs) == [matrix], "the other collection was not touched")

    # 7) plan and posters write nothing (plan says it would turn down The Matrix, so it exits with 1 too)
    before = {k: (v["id"], v.get("item_count")) for k, v in collections(silo).items()}
    cinesets(cfg, "plan", fails=True)
    cinesets(cfg, "posters")
    check({k: (v["id"], v.get("item_count")) for k, v in collections(silo).items()} == before, "plan and posters made no changes")

    # 8) remove deletes only CineSets' own collections
    cinesets(cfg, "remove", "--all", "--yes")
    after = collections(silo)
    check(not set(ours) & set(after), "remove deleted all of CineSets' collections")
    check(str(after.get("Movies - The Matrix", {}).get("id")) == str(theirs), "remove left the other collection alone")
    log(f"ALL CHECKS PASSED on Silo {info.get('server_version')}")


if __name__ == "__main__":
    main()
