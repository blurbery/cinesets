# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Emby and Jellyfin: a thin client for the parts of their APIs CineSets uses. The two share these endpoints;
Emby serves them under /emby and Jellyfin at the root."""
import base64
import time

import requests

from .. import __version__
from . import ServerError, chunks, warn_plain_http

PAGE = 5000


class EmbyCalls:
    """What CineSets reads and writes on an Emby or Jellyfin server, on top of get, call, timed and item. The tests'
    fake server shares these, so it answers exactly the requests a real server gets."""

    def all_items(self, query, what, pause=0.0):
        """Every item an /Items query returns, a page at a time. A short page is not taken as the end, since a server
        or a proxy in front of it may send fewer items than asked for: reading stops at an empty page."""
        out, seen, start = [], set(), 0
        while True:
            page = self.get(f"/Items?{query}&StartIndex={start}&Limit={PAGE}&EnableTotalRecordCount=false")["Items"]
            new = [i for i in page if i["Id"] not in seen]
            if not new:
                if page:  # the same items again: the server ignored StartIndex, so stop rather than loop forever
                    print(f"   the server sent the same page of {what} twice; anything after it was not read")
                return out
            seen.update(i["Id"] for i in new)
            out += new
            start += len(page)
            time.sleep(pause)

    # ------------------------------------------------------------ libraries
    def media_libraries(self):
        """(name, movie or show) for every movie and TV library, for setup."""
        return [(f["Name"], {"movies": "movie", "tvshows": "show"}[f.get("CollectionType")])
                for f in self.get("/Library/VirtualFolders") if f.get("CollectionType") in ("movies", "tvshows")]

    def library_folders(self):
        return {f["Name"]: f["ItemId"] for f in self.get("/Library/VirtualFolders")}

    def library_items(self, folder, kind, name):
        """Every movie or show in a library: id, name, year, provider ids and whether it has a backdrop."""
        item_type = "Movie" if kind == "movie" else "Series"
        # without CollapseBoxSetItems=false, Jellyfin 12 lists a collection in place of the titles in it
        items = self.all_items(f"Recursive=true&IncludeItemTypes={item_type}&Fields=ProviderIds,ProductionYear"
                               f"&CollapseBoxSetItems=false&ParentId={folder}", f"library {name!r}", pause=0.5)
        return [{"id": it["Id"], "name": it.get("Name"), "year": it.get("ProductionYear"),
                 "ids": {k.lower(): str(v) for k, v in (it.get("ProviderIds") or {}).items() if v},
                 "backdrop": bool(it.get("BackdropImageTags"))} for it in items]

    def genres(self, ids):
        return {i["Id"]: {g.lower() for g in (i.get("Genres") or [])}
                for i in self.get(f"/Items?Ids={','.join(ids)}&Fields=Genres")["Items"]}

    def alive(self, ids):
        """The ones of these item ids the server still has."""
        return {i["Id"] for i in self.get(f"/Items?Ids={','.join(ids)}")["Items"]}

    def backdrop_image(self, item_id, width=1920, quality=90):
        return self.call("GET", f"/Items/{item_id}/Images/Backdrop?maxWidth={width}&quality={quality}").content

    # ------------------------------------------------------------ collections
    def list_collections(self):
        """Every collection on the server, id -> name."""
        return {i["Id"]: i.get("Name") for i in self.all_items("IncludeItemTypes=BoxSet&Recursive=true", "collections")}

    def create_collection(self, name, coll, ids):
        """Make a collection holding `ids`. Returns its id and how long the write took."""
        r, took = self.timed("POST", f"/Collections?Name={requests.utils.quote(name)}&Ids={','.join(ids)}")
        return r.json()["Id"], took

    def wait_until_ready(self, cid, user_id, seconds=20):
        """A new collection is usable once the server has given it a folder (Emby finishes this just after replying)."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                if self.item(user_id, cid).get("Path"):
                    return
            except ServerError:
                pass
            time.sleep(1)

    def members(self, cid, user_id):
        # Jellyfin only lists box set children for a user; Emby lists them either way
        user = f"&UserId={user_id}" if self.kind == "jellyfin" else ""
        return {i["Id"] for i in self.all_items(f"ParentId={cid}{user}", f"collection {cid}")}

    def add_items(self, cid, ids):
        """Returns the slowest write."""
        slowest = 0.0
        for batch in chunks(ids):
            slowest = max(slowest, self.timed("POST", f"/Collections/{cid}/Items?Ids={','.join(batch)}")[1])
        return slowest

    def remove_items(self, cid, ids):
        slowest = 0.0
        for batch in chunks(ids):
            slowest = max(slowest, self.timed("DELETE", f"/Collections/{cid}/Items?Ids={','.join(batch)}")[1])
        return slowest

    def poster_tag(self, cid, user_id):
        try:
            return (self.item(user_id, cid).get("ImageTags") or {}).get("Primary")
        except ServerError:
            return None

    def has_poster(self, cid, user_id, changed_from=None, tries=5):
        """True once the collection has a poster that differs from `changed_from` (the one before an upload)."""
        for _ in range(tries):
            tag = self.poster_tag(cid, user_id)
            if tag and tag != changed_from:
                return True
            time.sleep(1)
        return False

    def upload_poster(self, cid, raw, user_id):
        """Upload a JPEG poster. Returns whether the server kept it, and how long the write took."""
        before = self.poster_tag(cid, user_id)
        took = self.timed("POST", f"/Items/{cid}/Images/Primary", data=base64.b64encode(raw),
                          headers={"Content-Type": "image/jpeg"})[1]
        return self.has_poster(cid, user_id, changed_from=before), took

    def set_details(self, cid, user_id, coll, name):
        """Name, sort name, overview and the order titles show in, locked so metadata refreshes leave them alone.
        Returns how long the write took."""
        item = self.item(user_id, cid)
        item["Name"], item["ForcedSortName"], item["SortName"] = name, coll["sort"], coll["sort"]
        item["Overview"] = coll.get("overview", "")
        item["DisplayOrder"] = coll.get("order", "PremiereDate")
        # Jellyfin has no SortName lock field; Emby does
        lock = {"Name", "Overview"} | ({"SortName"} if self.kind == "emby" else set())
        item["LockedFields"] = sorted(set(item.get("LockedFields") or []) | lock)
        return self.timed("POST", f"/Items/{cid}", json=item)[1]

    def delete_collection(self, cid):
        self.timed("DELETE", f"/Items/{cid}")


class MediaServer(EmbyCalls):
    @staticmethod
    def detect(url):
        """emby or jellyfin, from the server's public information (no API key needed), or None if it can't tell."""
        for path in ("/System/Info/Public", "/emby/System/Info/Public"):
            try:
                r = requests.get(url + path, timeout=10, allow_redirects=False, headers={"accept": "application/json"})
                info = r.json() if r.status_code == 200 else None
            except (requests.RequestException, ValueError):
                continue
            if not isinstance(info, dict):
                continue
            product = str(info.get("ProductName") or "").lower()
            if "jellyfin" in product:
                return "jellyfin"
            if "emby" in product or info.get("ServerName") or info.get("Id"):  # Emby's public information has no product name
                return "emby"
        return None

    def __init__(self, cfg):
        srv = cfg["server"]
        if not srv["api_key"]:
            raise SystemExit("No API key: set server.api_key in config.yml or CINESETS_API_KEY")
        self.kind = srv["type"]
        self.base = srv["url"] + ("/emby" if self.kind == "emby" else "")
        warn_plain_http(srv["url"])
        self.pause = float(cfg["write_pause"])
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json", "X-Emby-Token": srv["api_key"],
                                     "User-Agent": f"CineSets/{__version__} (+https://github.com/blurbery/cinesets)"})
        if self.kind == "jellyfin":
            self.session.headers["Authorization"] = (
                f'MediaBrowser Client="CineSets", Device="CineSets", DeviceId="cinesets", '
                f'Version="{__version__}", Token="{srv["api_key"]}"')

    def call(self, method, path, timeout=120, **kw):
        # never follow redirects: the API key travels in headers and must not reach another host
        r = self.session.request(method, self.base + path, timeout=timeout, allow_redirects=False, **kw)
        if 300 <= r.status_code < 400:
            raise ServerError(f"{method} {path.split('?')[0]} was redirected to {r.headers.get('Location', '?')}: "
                              f"set server.url to the address the server answers on directly", r.status_code)
        if r.status_code not in (200, 201, 204):
            raise ServerError(f"{method} {path.split('?')[0]} -> {r.status_code} {r.text[:200]}", r.status_code)
        return r

    def get(self, path, **kw):
        return self.call("GET", path, **kw).json()

    def timed(self, method, path, **kw):
        """A write that backs off when the server is slow to take it."""
        t = time.time()
        r = self.call(method, path, **kw)
        took = time.time() - t
        time.sleep(self.pause + min(took, 10))
        return r, took

    def admin_user(self):
        return next(u["Id"] for u in self.get("/Users") if u.get("Policy", {}).get("IsAdministrator"))

    def item(self, user_id, item_id):
        """One item with full metadata, as the edit endpoint expects it back."""
        if self.kind == "jellyfin":
            return self.get(f"/Items/{item_id}?userId={user_id}")
        return self.get(f"/Users/{user_id}/Items/{item_id}")
