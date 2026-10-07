# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Silo: a client for the parts of Silo's own API (/api/v2) CineSets uses.

Silo's Jellyfin-compatible port can show collections but not make them, so CineSets talks to Silo's main address.
Its collections are manual Silo library collections, each in one library: the one most of its titles are in (a Silo
collection can only hold titles from its libraries, and in any other library it would show up empty). Titles are
Silo content ids such as movie-tmdb-105, which carry one provider id; a TV show's others are looked up once and kept
in data/silo-ids.json, so lists match the same shows they match on Emby."""
import os
import re
import sys
import time
from collections import Counter
from urllib.parse import quote, urljoin, urlparse

import requests

from .. import __version__
from ..store import load_json, save_json
from . import ServerError, warn_plain_http
from .base import Server

PAGE = 200            # the most Silo sends in one page
ID_LOOKUP_PAUSE = 0.05
SORTS = {"PremiereDate": {"field": "release_date", "order": "asc"}, "SortName": {"field": "title", "order": "asc"}}
CONTENT_ID = re.compile(r"^(movie|series)-(tmdb|imdb|tvdb)-(.+)$")


def content_ids(content_id):
    """The provider id a Silo content id is built from: movie-tmdb-105 -> {"tmdb": "105"}. Local ids have none."""
    m = CONTENT_ID.match(content_id or "")
    return {m.group(2): m.group(3)} if m else {}


def provider_id(value):
    """tmdb ids can come back as 1931-some-slug; keep the number."""
    m = re.match(r"^(tt)?\d+", str(value or "").strip())
    return m.group(0) if m else ""


COMPAT_NOTE = "That is Silo's Jellyfin-compatible port. CineSets needs Silo's own address, the one its web app opens on."


def _answers(url, path):
    try:
        r = requests.get(url + path, timeout=10, allow_redirects=False, headers={"accept": "application/json"})
        info = r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None
    return info if isinstance(info, dict) else None


def _own_api(url):
    info = _answers(url, "/api/v2/system/info")
    return bool(info and info.get("api_major") and "contract_digest" in info)


class SiloServer(Server):
    TYPE = "silo"
    KEY_PAGE = "Admin > API keys"
    SETUP_NOTE = ("CineSets needs a Silo API key that belongs to an administrator and has no scopes. Make one under "
                  "Admin > API keys (name it CineSets).")

    @staticmethod
    def trim(url):
        return url

    @staticmethod
    def detect(url):
        """("silo", url, None) if Silo's own API answers at `url`. Given Silo's Jellyfin-compatible port (it says who it
        is on its sign-in page), Silo's own address on port 8080 with a note, or None for the address if Silo's
        isn't there, so setup asks for it."""
        if _own_api(url):
            return "silo", url, None
        info = _answers(url, "/Branding/Configuration")
        if info and "Silo" in str(info.get("LoginDisclaimer") or ""):
            guess = urlparse(url)._replace(netloc=f"{urlparse(url).hostname}:8080", path="").geturl()
            return "silo", (guess if _own_api(guess) else None), COMPAT_NOTE
        return None

    def __init__(self, cfg):
        srv = cfg["server"]
        if not srv["api_key"]:
            raise SystemExit("No API key: set server.api_key in config.yml or CINESETS_API_KEY")
        self.cfg = cfg
        self.root = srv["url"]
        self.base = self.root + "/api/v2"
        warn_plain_http(self.root)
        self.pause = float(cfg["write_pause"])
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json", "Authorization": f"Bearer {srv['api_key']}",
                                     "User-Agent": f"CineSets/{__version__} (+https://github.com/blurbery/cinesets)"})
        self.ids_file = os.path.join(cfg.path("data_dir"), "silo-ids.json")
        self.where_file = os.path.join(cfg.path("data_dir"), "silo-libraries.json")
        self._profile = None
        self._folders = None
        self._where = None      # content id -> the libraries it is in, kept with the index
        self._home = {}         # collection key -> the library it lives in
        self._attached = {}     # collection id -> its libraries, as Silo has them
        self._next = {}         # collection id -> the position the next added title gets

    # ------------------------------------------------------------ requests
    def call(self, method, path, timeout=120, **kw):
        # never follow redirects: the API key travels in headers and must not reach another host
        for attempt in range(6):
            r = self.session.request(method, self.base + path, timeout=timeout, allow_redirects=False, **kw)
            if r.status_code != 429 or attempt == 5:
                break
            wait = r.headers.get("Retry-After", "")
            time.sleep(min(float(wait), 60) if wait.replace(".", "", 1).isdigit() else 2 ** attempt)
        if 300 <= r.status_code < 400:
            raise ServerError(f"{method} {path.split('?')[0]} was redirected to {r.headers.get('Location', '?')}: "
                              f"set server.url to the address Silo answers on directly", r.status_code)
        if r.status_code not in (200, 201, 204):
            raise ServerError(f"{method} {path.split('?')[0]} -> {r.status_code} {self.problem(r)}", r.status_code)
        return r

    @staticmethod
    def problem(r):
        try:
            body = r.json()
        except ValueError:
            return r.text[:200]
        detail = str(body.get("detail") or body.get("title") or "") if isinstance(body, dict) else ""
        if r.status_code == 401:
            detail += " (Silo did not accept the API key)"
        elif r.status_code == 403:
            detail += (" (CineSets needs an API key that belongs to an administrator and has no scopes: "
                       "Admin > API keys in Silo)")
        return detail[:300]

    def get(self, path, **kw):
        return self.call("GET", path, **kw).json()

    def timed(self, method, path, pause=None, **kw):
        """A write that backs off when the server is slow to take it."""
        t = time.time()
        r = self.call(method, path, **kw)
        took = time.time() - t
        time.sleep((self.pause if pause is None else pause) + min(took, 10))
        return r, took

    def pages(self, path, **kw):
        """Every item of a paged list. If Silo ever hands back a cursor it gave before, reading stops there rather than
        going round forever."""
        out, cursor, used = [], None, set()
        while True:
            sep = "&" if "?" in path else "?"
            page = self.get(path + (f"{sep}cursor={quote(cursor, safe='')}" if cursor else ""), **kw)
            out += page.get("items") or []
            cursor = (page.get("page") or {}).get("next_cursor")
            if not (page.get("page") or {}).get("has_more") or not cursor:
                return out
            if cursor in used:
                print(f"   Silo sent the same page of {path.split('?')[0]} twice; anything after it was not read")
                return out
            used.add(cursor)

    def profile(self):
        """The profile header the catalogue needs: the household's main profile."""
        if self._profile is None:
            profiles = self.get("/profiles").get("items") or []
            main = next((p for p in profiles if p.get("is_primary")), profiles[0] if profiles else None)
            if not main:
                raise SystemExit("The API key's account has no profile in Silo; sign in to Silo once to create one.")
            if main.get("library_restrictions_enabled") or main.get("max_content_rating") or main.get("max_advisory_age"):
                print(f"Note: the Silo profile {main.get('name')!r} has library or rating limits, so titles it can't "
                      "see are left out of collections.", file=sys.stderr)
            self._profile = {"X-Profile-Id": str(main["id"])}
        return self._profile

    def admin_user(self):
        self.get("/admin/collections/capabilities")  # a clear refusal now if the key isn't an administrator's
        return None

    # ------------------------------------------------------------ libraries and titles
    def libraries(self):
        return self.pages("/libraries")

    def media_libraries(self):
        """Movie then TV libraries for setup, the biggest of each type first. The first one of a type is where
        collections live unless they're clearly anime, international or the like (see narrow), so it should be the
        main library, whatever order the libraries were added to Silo in."""
        kinds = {"movies": "movie", "series": "show"}
        libs = [(lib, kinds[lib["type"]]) for lib in self.libraries() if lib.get("type") in kinds]
        size = {str(lib["id"]): self.get(f"/catalog?library_id={quote(str(lib['id']))}&type={'movie' if kind == 'movie' else 'series'}"
                                         f"&limit=1", headers=self.profile()).get("total") or 0 for lib, kind in libs}
        libs.sort(key=lambda x: (x[1] != "movie", -size[str(x[0]["id"])]))  # stable: equal sizes keep Silo's order
        return [(lib["name"], kind) for lib, kind in libs]

    def library_folders(self):
        if self._folders is None:
            self._folders = {lib["name"]: str(lib["id"]) for lib in self.libraries()}
        return self._folders

    def library_items(self, folder, kind, name):
        typ = "movie" if kind == "movie" else "series"
        cards = self.pages(f"/catalog?library_id={quote(folder)}&type={typ}&sort=title&skip_total=true"
                           f"&image_size=small&limit={PAGE}", headers=self.profile())
        out, seen = [], set()
        for c in cards:
            cid = c.get("content_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append({"id": cid, "name": c.get("title"), "year": c.get("year"), "ids": content_ids(cid),
                        "backdrop": bool(c.get("backdrop_url") or c.get("backdrop_thumbhash")),
                        "genres": c.get("genres") or []})
        if self._where is None or name == self.cfg["libraries"][0]["name"]:  # a new index starts the record afresh
            self._where = {}
        for it in out:
            self._where.setdefault(it["id"], []).append(folder)
        save_json(self.where_file, self._where)
        if kind == "show":
            self.add_show_ids(out, name)
        return out

    def where(self):
        """content id -> the libraries it is in. Written with the index; made here if an older install has none."""
        if self._where is None:
            self._where = load_json(self.where_file, None)
        if self._where is None:
            self._where = {}
            for lib in self.cfg["libraries"]:
                folder = self.library_folders().get(lib["name"])
                typ = "movie" if lib["type"] == "movie" else "series"
                if folder:
                    for c in self.pages(f"/catalog?library_id={quote(folder)}&type={typ}&sort=title&skip_total=true"
                                        f"&image_size=small&limit={PAGE}", headers=self.profile()):
                        self._where.setdefault(c["content_id"], []).append(folder)
            save_json(self.where_file, self._where)
        return self._where

    def narrow(self, coll, ids):
        """A collection lives in one library, picked from where its titles are, so it works whatever the libraries are
        called: the library that holds at least two thirds of them (an anime or an international collection, say),
        or else the first library of its type in config.yml that has any (a title in several counts for the first
        listed). Only titles in that library go in it."""
        folders = self.library_folders()
        libs = [folders[x["name"]] for x in self.cfg["libraries"] if x["type"] == coll["kind"] and x["name"] in folders]
        where = self.where()
        votes = Counter(next((lib for lib in libs if lib in where.get(i, ())), None) for i in ids)
        votes.pop(None, None)
        if not votes:
            return ids
        best = max(libs, key=lambda lib: (votes[lib], -libs.index(lib)))
        home = best if votes[best] * 3 >= sum(votes.values()) * 2 else next(lib for lib in libs if votes[lib])
        self._home[coll["key"]] = home
        return [i for i in ids if home in where.get(i, ())]

    def add_show_ids(self, items, name):
        """A show's content id carries one provider id (TVDB when it has one); lists also match by IMDb and TMDB, so
        look the others up once per show and keep them."""
        known = load_json(self.ids_file, {})
        todo = [it for it in items if it["id"] not in known and it["ids"]]
        if todo:
            print(f"  looking up the ids of {len(todo)} shows in {name} (once; later runs reuse them)")
        for n, it in enumerate(todo, start=1):
            try:
                d = self.get(f"/catalog/items/{quote(it['id'], safe='')}", headers=self.profile())
            except ServerError as e:
                if e.status == 404:
                    known[it["id"]] = {}
                    continue
                raise
            known[it["id"]] = {k: v for k, v in (("tmdb", provider_id(d.get("tmdb_id"))),
                                                 ("imdb", provider_id(d.get("imdb_id"))),
                                                 ("tvdb", provider_id(d.get("tvdb_id")))) if v}
            if n % 250 == 0:
                save_json(self.ids_file, known)
                print(f"    {n} of {len(todo)}")
            time.sleep(ID_LOOKUP_PAUSE)
        if todo:
            save_json(self.ids_file, known)
        for it in items:
            it["ids"] = {**known.get(it["id"], {}), **it["ids"]}

    def genres(self, ids):
        out = {}
        for i in ids:
            try:
                d = self.get(f"/catalog/items/{quote(i, safe='')}", headers=self.profile())
            except ServerError as e:
                if e.status == 404:
                    continue
                raise
            out[i] = {g.lower() for g in d.get("genres") or []}
        return out

    def alive(self, ids):
        # Silo answers 404 when a title that has gone is added, and add_items skips those
        return set(ids)

    def backdrop_image(self, item_id, width=1920, quality=90):
        size = "medium" if width > 800 else "small"
        d = self.get(f"/catalog/items/{quote(item_id, safe='')}?image_size={size}", headers=self.profile())
        if not d.get("backdrop_url"):
            raise ServerError(f"{item_id} has no backdrop", 404)
        url = urljoin(self.root + "/", d["backdrop_url"])
        if urlparse(url).netloc == urlparse(self.root).netloc:
            r = self.session.get(url, timeout=60, allow_redirects=False)
            if 300 <= r.status_code < 400 and r.headers.get("Location"):
                url = urljoin(url, r.headers["Location"])
                r = requests.get(url, timeout=60)  # a signed link to storage: no API key goes with it
        else:
            r = requests.get(url, timeout=60)  # artwork storage, with a signed link: no API key goes with it
        if r.status_code != 200:
            raise ServerError(f"backdrop for {item_id} -> {r.status_code}", r.status_code)
        return r.content

    # ------------------------------------------------------------ collections
    def list_collections(self):
        found = self.pages("/admin/collections")
        self._attached = {str(c["id"]): [str(x) for x in c.get("library_ids") or []] for c in found}
        return {str(c["id"]): c.get("title") for c in found}

    def library_ids(self, kind):
        folders = self.library_folders()
        ids = [folders[lib["name"]] for lib in self.cfg["libraries"] if lib["type"] == kind and lib["name"] in folders]
        if not ids:
            raise RuntimeError(f"none of the {kind} libraries in config.yml are on the server")
        return ids

    def create_collection(self, name, coll, ids):
        home = self._home.get(coll["key"])
        libs = [home] if home else self.library_ids(coll["kind"])
        body = {"title": name, "slug": f"cinesets-{coll['key']}", "library_ids": libs,
                "description": coll.get("overview", ""), "collection_type": "manual", "visibility": "visible"}
        r, took = self.timed("POST", "/admin/collections", json=body)
        cid = str(r.json()["id"])
        self._next[cid], self._attached[cid] = 0, libs
        return cid, max(took, self.add_items(cid, ids))

    def wait_until_ready(self, cid, user_id):
        pass  # usable as soon as it is made

    def prepare(self, cid, coll):
        """Move a collection to its library (see narrow) when that changed, before its titles are brought up to date."""
        home = self._home.get(coll["key"])
        if home and self._attached.get(cid) != [home]:
            self.timed("PATCH", f"/admin/collections/{cid}", json={"library_ids": [home]}, headers={"If-Match": "*"})
            self._attached[cid] = [home]

    def members(self, cid, user_id):
        rows = self.pages(f"/admin/collections/{cid}/items?limit={PAGE}")
        self._next[cid] = max((r.get("position") or 0 for r in rows), default=-1) + 1
        return {r["media_item_id"] for r in rows}

    def add_items(self, cid, ids):
        """One write per title, with a short pause between them. Titles Silo no longer has are skipped."""
        slowest, gone = 0.0, 0
        for i in ids:
            pos = self._next.get(cid, 0)
            try:
                took = self.timed("PUT", f"/admin/collections/{cid}/items/{quote(i, safe='')}", json={"position": pos},
                                  pause=self.pause / 10)[1]
            except ServerError as e:
                if e.status != 404:
                    raise
                gone += 1
                continue
            self._next[cid] = pos + 1
            slowest = max(slowest, took)
        if gone:
            print(f"   {gone} titles were not in Silo any more and were left out")
        return slowest

    def remove_items(self, cid, ids):
        slowest = 0.0
        for i in ids:
            try:
                took = self.timed("DELETE", f"/admin/collections/{cid}/items/{quote(i, safe='')}", pause=self.pause / 10)[1]
            except ServerError as e:
                if e.status != 404:
                    raise
                continue
            slowest = max(slowest, took)
        return slowest

    def poster_tag(self, cid):
        try:
            return self.get(f"/admin/collections/{cid}").get("poster_thumbhash")
        except ServerError:
            return None

    def upload_poster(self, cid, raw, user_id):
        r, took = self.timed("PUT", f"/admin/collections/{cid}/poster", files={"image": ("poster.jpg", raw, "image/jpeg")})
        try:
            body = r.json()
        except ValueError:
            body = {}
        return bool(body.get("poster_url") or body.get("poster_thumbhash") or self.poster_tag(cid)), took

    def set_details(self, cid, user_id, coll, name):
        """Name, description and the order titles show in (Silo has no sort name; arrange places collections)."""
        body = {"title": name, "description": coll.get("overview", ""),
                "sort_config": SORTS.get(coll.get("order", "PremiereDate"), {})}
        return self.timed("PATCH", f"/admin/collections/{cid}", json=body, headers={"If-Match": "*"})[1]

    def delete_collection(self, cid):
        self.timed("DELETE", f"/admin/collections/{cid}", headers={"If-Match": "*"})

    def arrange(self, owned):
        """Put CineSets' collections in Collections page order in each library, in the places they already hold among
        any other collections (which stay where they are). owned: collection key -> id."""
        from .. import catalog
        rank = {c["key"]: n for n, c in enumerate(sorted(catalog.load(self.cfg), key=lambda c: c["sort"]))}
        ours = {cid: (rank.get(key, len(rank)), key) for key, cid in owned.items()}
        moved = 0
        for lib in dict.fromkeys(self.library_folders()[x["name"]] for x in self.cfg["libraries"]
                                 if x["name"] in self.library_folders()):
            r = self.call("GET", f"/admin/collections/order?library_id={quote(lib)}")
            now = [str(i) for i in r.json().get("ordered_ids") or []]
            mine = sorted((i for i in now if i in ours), key=lambda i: ours[i])
            it = iter(mine)
            want = [next(it) if i in ours else i for i in now]
            if want != now:
                self.timed("PUT", "/admin/collections/order", json={"library_id": lib, "ordered_ids": want},
                           headers={"If-Match": r.headers.get("ETag") or "*"})
                moved += 1
        if moved:
            print(f"Put the collections in order in {moved} libraries.")


SERVER = SiloServer
