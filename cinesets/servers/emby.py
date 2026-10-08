# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Emby: a thin client for the parts of its API CineSets uses, served under /emby.

Jellyfin began as a fork of Emby and the two APIs are still close, but each server has its own module, so a change
for one can't change what the other gets."""
import base64
import time
from functools import partial
from urllib.parse import urlparse

import requests

from .. import __version__
from . import ServerError, chunks, public_info, send, verify_setting, warn_plain_http
from .base import Server

PAGE = 5000
# a fixed order to page through, so no title slips between pages: by name, then year, then when it was added
ORDER = "SortBy=SortName,ProductionYear,DateCreated&SortOrder=Ascending"
# paths every Emby server answers, so a 404 on one means server.url isn't Emby's address
BASE_PATHS = ("/Library/VirtualFolders", "/Users", "/Items", "/Collections", "/System/Info")


class EmbyCalls(Server):
    """What CineSets reads and writes on Emby, on top of get, call, timed and item. The tests' fake Emby shares
    these, so it answers exactly the requests a real Emby server gets."""

    def all_items(self, query, what, pause=0.0, keep=None):
        """Every item an /Items query returns, a page at a time, in a fixed order. A short page is not taken as the
        end, since a server or a proxy in front of it may send fewer items than asked for: reading stops at an empty
        page. The first page also asks how many there are, to say so if fewer came back. With `keep`, each item is
        cut down to keep(item) as its page arrives, so a big library is never held in memory whole."""
        out, seen, start, total = [], set(), 0, None
        while True:
            page = self.get(f"/Items?{query}&StartIndex={start}&Limit={PAGE}&{ORDER}"
                            f"&EnableTotalRecordCount={'true' if start == 0 else 'false'}")
            if start == 0:
                total = page.get("TotalRecordCount")
            new = [i for i in page["Items"] if i["Id"] not in seen]
            if not new:
                if page["Items"]:  # the same items again: the server ignored StartIndex, so stop, not loop forever
                    print(f"   the server sent the same page of {what} twice; anything after it was not read")
                break
            seen.update(i["Id"] for i in new)
            out += [keep(i) for i in new] if keep else new
            start += len(page["Items"])
            time.sleep(pause)
        if isinstance(total, int) and len(seen) < total:
            print(f"   {what}: the server counted {total} but sent {len(seen)}; the others were not read")
        return out

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
        # CollapseBoxSetItems=false: titles that are in a collection are listed as themselves
        def title(it):
            ids = {k.lower(): str(v) for k, v in (it.get("ProviderIds") or {}).items() if v}
            return {"id": it["Id"], "name": it.get("Name"), "year": it.get("ProductionYear"), "ids": ids,
                    "backdrop": bool(it.get("BackdropImageTags"))}
        return self.all_items(f"Recursive=true&IncludeItemTypes={item_type}&Fields=ProviderIds,ProductionYear"
                              f"&CollapseBoxSetItems=false&ParentId={folder}", f"library {name!r}", pause=0.5, keep=title)

    def genres(self, ids):
        return {i["Id"]: {g.lower() for g in (i.get("Genres") or [])}
                for i in self.get(f"/Items?Ids={','.join(ids)}&Fields=Genres")["Items"]}

    def alive(self, ids):
        """The ones of these item ids the server still has."""
        return {i["Id"] for i in self.get(f"/Items?Ids={','.join(ids)}")["Items"]}

    def backdrop_image(self, item_id, width=1920, quality=90):
        """A poster is cut from the middle of a wide backdrop, so for posters and their previews it's the backdrop's
        height that counts: 1920 wide is only 1080 tall, stretched to fill a 1500 tall poster. So those are asked for
        by height (1600 for 1920), and thumbnails, which are shown wide, by width."""
        size = f"maxHeight={width * 5 // 6}" if width > 800 else f"maxWidth={width}"
        return self.call("GET", f"/Items/{item_id}/Images/Backdrop?{size}&quality={quality}").content

    # ------------------------------------------------------------ collections
    def list_collections(self):
        """Every collection on the server, id -> name."""
        return {i["Id"]: i.get("Name") for i in self.all_items("IncludeItemTypes=BoxSet&Recursive=true", "collections")}

    def narrow(self, coll, ids):
        """Emby collections are server-wide, so every matched title can go in."""
        return ids

    def create_collection(self, name, coll, ids):
        """Make a collection holding `ids`. Returns its id and how long the write took. Never sent twice: a try that
        failed may still have made it."""
        r, took = self.timed("POST", f"/Collections?Name={requests.utils.quote(name)}&Ids={','.join(ids)}", retry=False)
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

    def prepare(self, cid, coll):
        """Nothing to do: Emby collections aren't tied to a library."""

    def members(self, cid, user_id):
        # Emby lists a collection's titles without a user
        return {i["Id"] for i in self.all_items(f"ParentId={cid}", f"collection {cid}")}

    def add_items(self, cid, ids):
        """Returns the slowest write. Adding a title twice changes nothing, so a failed write is tried again."""
        slowest = 0.0
        for batch in chunks(ids):
            slowest = max(slowest, self.timed("POST", f"/Collections/{cid}/Items?Ids={','.join(batch)}", retry=True)[1])
        return slowest

    def remove_items(self, cid, ids):
        slowest = 0.0
        for batch in chunks(ids):
            slowest = max(slowest, self.timed("DELETE", f"/Collections/{cid}/Items?Ids={','.join(batch)}",
                                              retry=True)[1])
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
                          headers={"Content-Type": "image/jpeg"}, retry=True)[1]
        return self.has_poster(cid, user_id, changed_from=before), took

    def set_details(self, cid, user_id, coll, name):
        """Name, sort name, overview and the order titles show in, locked so metadata refreshes leave them alone.
        Returns how long the write took."""
        item = self.item(user_id, cid)
        item["Name"], item["ForcedSortName"], item["SortName"] = name, coll["sort"], coll["sort"]
        item["Overview"] = coll.get("overview", "")
        item["DisplayOrder"] = coll.get("order", "PremiereDate")
        lock = {"Name", "Overview", "SortName"}
        item["LockedFields"] = sorted(set(item.get("LockedFields") or []) | lock)
        return self.timed("POST", f"/Items/{cid}", json=item, retry=True)[1]

    def delete_collection(self, cid):
        """Only once Emby confirms it's a collection: DELETE /Items/{id} deletes any item, a film and its files too."""
        found = self.get(f"/Items?Ids={cid}&IncludeItemTypes=BoxSet&Recursive=true")["Items"]
        if not any(str(i.get("Id")) == str(cid) and i.get("Type") == "BoxSet" for i in found):
            raise ServerError(f"Emby's item {cid} is not a collection, so CineSets did not delete it")
        try:
            self.timed("DELETE", f"/Items/{cid}", retry=True)
        except ServerError as e:
            if e.status != 404:  # gone already, by a try whose answer was lost on the way back
                raise

    def arrange(self, owned):
        """Nothing to do: the sort names set_details writes keep Emby's Collections page in order."""


class EmbyServer(EmbyCalls):
    TYPE = "emby"
    KEY_PAGE = "Dashboard > API Keys"
    SETUP_NOTE = None

    @staticmethod
    def trim(url):
        """A pasted web app address works too: drop /web/index.html#... and a trailing /web or /emby from the path.
        Only the path, so a server called web or emby keeps its name."""
        parts = urlparse(url)
        path = parts.path.split("/web/")[0].rstrip("/")
        for tail in ("/web", "/emby"):
            if path.endswith(tail):
                path = path[: -len(tail)]
        return parts._replace(path=path, params="", query="", fragment="").geturl()

    @staticmethod
    def detect(url, verify=True):
        """("emby", url, None) from the server's public information (no API key needed), or None."""
        # the first of these that says which server it is decides
        for path in ("/System/Info/Public", "/emby/System/Info/Public"):
            info = public_info(url, path, verify)
            if info is None:
                continue
            product = str(info.get("ProductName") or "").lower()
            if "jellyfin" in product:
                return None  # Jellyfin's, not Emby's
            if "emby" in product or info.get("ServerName") or info.get("Id"):  # Emby's public information has no product name
                return "emby", url, None
        return None

    def __init__(self, cfg):
        srv = cfg["server"]
        if not srv["api_key"]:
            raise SystemExit("No API key: set server.api_key in config.yml or CINESETS_API_KEY")
        self.base = srv["url"] + "/emby"
        warn_plain_http(srv["url"])
        self.verify = verify_setting(cfg)
        self.pause = float(cfg["write_pause"])
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json", "X-Emby-Token": srv["api_key"],
                                     "User-Agent": f"CineSets/{__version__} (+https://github.com/blurbery/cinesets)"})

    def request(self, method, path, timeout=120, retry=None, **kw):
        """One request, and how long the try that got its answer took. Reads are sent again after a dropped connection
        or a busy answer, and so are writes whose caller says retry=True: ones that do the same thing however often
        they arrive."""
        # never follow redirects: the API key travels in headers and must not reach another host
        again = method == "GET" if retry is None else retry
        r, took = send(partial(self.session.request, method), self.base + path, again, timeout=timeout,
                       allow_redirects=False, verify=self.verify, **kw)
        if 300 <= r.status_code < 400:
            raise ServerError(f"{method} {path.split('?')[0]} was redirected to {r.headers.get('Location', '?')}: "
                              f"set server.url to the address the server answers on directly", r.status_code)
        if r.status_code not in (200, 201, 204):
            raise ServerError(self.refused(method, path, r), r.status_code)
        return r, took

    def refused(self, method, path, r):
        """What a refused request means, and what to do about it."""
        where = path.split("?")[0]
        said = f"{method} {where} -> {r.status_code}"
        if r.status_code in (401, 403):
            return (f"{said}: Emby did not accept the API key. CineSets needs one from {self.KEY_PAGE} on Emby "
                    "(only an administrator can make them) in server.api_key")
        if r.status_code == 404 and where in BASE_PATHS:
            return (f"{said}: nothing answered there, so server.url is probably not Emby's address. Use the address "
                    "Emby's web app opens on")
        if r.status_code == 413:
            return (f"{said}: a proxy in front of Emby turned the upload away as too big. Raise its limit (nginx's "
                    "client_max_body_size, to 10m say)")
        if r.status_code == 429:
            return (f"{said}: Emby, or a proxy in front of it, is limiting how often CineSets can ask, and still was "
                    "after waiting. Try again later, or raise write_pause in config.yml")
        return f"{said} {r.text[:200]}"

    def call(self, method, path, timeout=120, retry=None, **kw):
        return self.request(method, path, timeout, retry, **kw)[0]

    def get(self, path, **kw):
        return self.call("GET", path, **kw).json()

    def timed(self, method, path, retry=None, **kw):
        """A write that backs off when the server is slow to take it."""
        r, took = self.request(method, path, retry=retry, **kw)
        time.sleep(self.pause + min(took, 10))
        return r, took

    def admin_user(self):
        """Collections are made as an administrator: the first one Emby lists."""
        admin = next((u["Id"] for u in self.get("/Users") if (u.get("Policy") or {}).get("IsAdministrator")), None)
        if admin is None:
            raise ServerError(f"Emby lists no administrator for this API key, and CineSets makes collections as one. "
                              f"Use a key from {self.KEY_PAGE} on Emby in server.api_key")
        return admin

    def item(self, user_id, item_id):
        """One item with full metadata, as the edit endpoint expects it back."""
        return self.get(f"/Users/{user_id}/Items/{item_id}")


SERVER = EmbyServer
