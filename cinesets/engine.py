# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Library index, list matching, posters and collection writes.

Safety rules: CineSets only ever changes collections it created (recorded in data/state.json), writes only
what changed, and backs off when the server is slow.
"""
import base64
import contextlib
import hashlib
import json
import os
import re
import time

import requests

from . import posters
from .lists import fetch_list
from .server import ServerError
from .store import load_json, save_json

SAFE_ID = re.compile(r"^[A-Za-z0-9-]+$")

INDEX_MAX_AGE = 20 * 3600
PAGE = 5000


def chunks(seq, n=40):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class Engine:
    def __init__(self, cfg, server):
        self.cfg, self.srv = cfg, server
        self.data = cfg.path("data_dir")
        self.index_file = os.path.join(self.data, "index.json")
        self.state_file = os.path.join(self.data, "state.json")
        self.backdrops = os.path.join(self.data, "backdrops")
        self.logos = os.path.join(self.data, "logos")
        self.posters = os.path.join(self.data, "posters")

    # ------------------------------------------------------------ reads
    def all_items(self, query, what, pause=0.0):
        """Every item an /Items query returns, a page at a time. A short page is not taken as the end, since a server
        or a proxy in front of it may send fewer items than asked for: reading stops at an empty page."""
        out, seen, start = [], set(), 0
        while True:
            page = self.srv.get(f"/Items?{query}&StartIndex={start}&Limit={PAGE}&EnableTotalRecordCount=false")["Items"]
            new = [i for i in page if i["Id"] not in seen]
            if not new:
                if page:  # the same items again: the server ignored StartIndex, so stop rather than loop forever
                    print(f"   the server sent the same page of {what} twice; anything after it was not read")
                return out
            seen.update(i["Id"] for i in new)
            out += new
            start += len(page)
            time.sleep(pause)

    # ------------------------------------------------------------ library index
    def build_index(self):
        """One item per title; libraries listed earlier in config.yml win when a title is in several."""
        if not self.cfg["libraries"]:
            raise SystemExit("No libraries in config.yml: list the movie and TV libraries CineSets should use")
        folders = {f["Name"]: f["ItemId"] for f in self.srv.get("/Library/VirtualFolders")}
        index = {"built": time.time(), "movie": {"imdb": {}, "tmdb": {}}, "show": {"tvdb": {}, "imdb": {}, "tmdb": {}}, "items": {}}
        for lib in self.cfg["libraries"]:
            name, kind = lib["name"], lib["type"]
            if name not in folders:
                raise SystemExit(f"library {name!r} not found on the server (found: {', '.join(sorted(folders))})")
            item_type = "Movie" if kind == "movie" else "Series"
            # without CollapseBoxSetItems=false, Jellyfin 12 lists a collection in place of the titles in it
            items = self.all_items(f"Recursive=true&IncludeItemTypes={item_type}&Fields=ProviderIds,ProductionYear"
                                   f"&CollapseBoxSetItems=false&ParentId={folders[name]}", f"library {name!r}", pause=0.5)
            for it in items:
                prov = {k.lower(): str(v) for k, v in (it.get("ProviderIds") or {}).items() if v}
                for key in index[kind]:
                    if prov.get(key):
                        index[kind][key].setdefault(prov[key], it["Id"])
                index["items"][it["Id"]] = {"n": it.get("Name"), "y": it.get("ProductionYear"), "b": bool(it.get("BackdropImageTags")), "k": kind}
            print(f"  indexed {name}: {len(items)}")
        save_json(self.index_file, index)
        return index

    def get_index(self, force=False):
        index = load_json(self.index_file, None)
        if force or not index or time.time() - index["built"] > INDEX_MAX_AGE:
            print("Refreshing library index...")
            index = self.build_index()
        return index

    # ------------------------------------------------------------ matching
    def resolve(self, coll, index):
        """Matched item ids in list order, plus (titles wanted, titles matched)."""
        kind = coll["kind"]
        if coll.get("titles"):
            # fixed franchise list: exact title and year; prefer the copy the index treats as canonical
            canon = set(index[kind]["imdb"].values()) | set(index[kind]["tmdb"].values())
            want = {(t.lower(), y) for t, y in coll["titles"]}
            found = {}
            for iid, it in index["items"].items():
                if it.get("k", kind) != kind:
                    continue
                k = ((it.get("n") or "").lower(), it.get("y"))
                if k in want and (k not in found or (iid in canon and found[k] not in canon)):
                    found[k] = iid
            ids = [found[(t.lower(), y)] for t, y in coll["titles"] if (t.lower(), y) in found]
            return ids, len(coll["titles"]), len(ids)
        ids, seen, wanted = [], set(), 0
        for slug in coll["lists"]:
            rows = [x for x in fetch_list(slug, self.data) if x.get("mediatype") == kind]
            if coll.get("ranked", True):
                rows.sort(key=lambda x: x.get("rank") if x.get("rank") is not None else 10 ** 9)
            for row in rows:
                wanted += 1
                lookup = index[kind]
                eid = None
                if kind == "show" and row.get("tvdbid"):
                    eid = lookup["tvdb"].get(str(row["tvdbid"]))
                eid = eid or lookup["imdb"].get(str(row.get("imdb_id") or "")) or lookup["tmdb"].get(str(row.get("id") or ""))
                if eid and eid not in seen:
                    seen.add(eid)
                    ids.append(eid)
        limit = coll.get("limit", self.cfg["defaults"]["limit"])
        skip = {g.lower() for g in coll.get("exclude_genres", [])}
        if skip:
            # drop titles carrying an excluded genre (for example talk shows), keeping list order
            kept, cand = [], ids[:limit * 4]
            for batch in chunks(cand, 100):
                genres = {i["Id"]: {g.lower() for g in (i.get("Genres") or [])}
                          for i in self.srv.get(f"/Items?Ids={','.join(batch)}&Fields=Genres")["Items"]}
                kept += [i for i in batch if not genres.get(i, set()) & skip]
            ids = kept
        return ids[:limit], wanted, len(ids)

    # ------------------------------------------------------------ posters
    def poster_for(self, coll, ids, index, state, used):
        """Build the poster once and keep it, so daily list churn does not re-upload artwork."""
        os.makedirs(self.posters, exist_ok=True)
        os.makedirs(self.backdrops, exist_ok=True)
        out = os.path.join(self.posters, coll["key"] + ".jpg")
        st = state.setdefault(coll["key"], {})
        parts = [coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], coll.get("backdrop_item"), coll.get("backdrop_title")]
        if coll.get("logo"):
            parts.append("logo:" + coll["logo"])
        design = json.dumps(parts)
        if os.path.exists(out) and st.get("design") == design:
            used.add(st.get("backdrop_item"))
            return out
        pick = coll.get("backdrop_item")
        if not pick and coll.get("backdrop_title"):
            pick = next((i for i in ids if index["items"][i]["n"] == coll["backdrop_title"] and index["items"][i]["b"]), None)
            if not pick:
                print(f"   {coll['key']}: backdrop title {coll['backdrop_title']!r} not in this collection, using the default")
        if not pick:
            candidates = [i for i in ids if index["items"].get(i, {}).get("b")]
            pick = next((i for i in candidates if i not in used), candidates[0] if candidates else None)
        bd = None
        if pick and SAFE_ID.match(str(pick)):
            used.add(pick)
            bd = self.backdrop(pick)
        if coll.get("logo"):
            posters.make_logo_poster(out, coll["label"], coll["logo"], self.logos, coll.get("subtitle") or "Popular", bd, coll["title"])
        else:
            posters.make_poster(out, coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], bd)
        if bd or not pick:
            st["design"], st["backdrop_item"] = design, pick
        else:
            st.pop("design", None)  # the artwork could not be fetched: build the poster again next run
        return out

    def backdrop(self, item_id):
        """Download an item's backdrop once. A failed or broken download is never left on disk."""
        path = os.path.join(self.backdrops, item_id + ".jpg")
        if os.path.exists(path):
            return path
        tmp = path + ".part"
        try:
            content = self.srv.call("GET", f"/Items/{item_id}/Images/Backdrop?maxWidth=1920&quality=90").content
            with open(tmp, "wb") as f:
                f.write(content)
            from PIL import Image
            with Image.open(tmp) as im:
                im.verify()
            os.replace(tmp, path)
            return path
        except Exception as e:
            print(f"   backdrop {item_id}: {e}; using a plain background")
            with contextlib.suppress(FileNotFoundError):
                os.remove(tmp)
            return None

    def contact_sheets(self, keys):
        from PIL import Image
        files = [os.path.join(self.posters, k + ".jpg") for k in keys if os.path.exists(os.path.join(self.posters, k + ".jpg"))]
        sheets, per_row, per_sheet, tw, th, gap = [], 8, 24, 300, 450, 16
        for n in range(0, len(files), per_sheet):
            chunk = files[n:n + per_sheet]
            rows = (len(chunk) + per_row - 1) // per_row
            sheet = Image.new("RGB", (per_row * (tw + gap) + gap, rows * (th + gap) + gap), (24, 24, 24))
            for i, f in enumerate(chunk):
                sheet.paste(Image.open(f).resize((tw, th), Image.LANCZOS), (gap + (i % per_row) * (tw + gap), gap + (i // per_row) * (th + gap)))
            path = os.path.join(self.data, "samples", f"review-{n // per_sheet + 1}.png")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            sheet.save(path)
            sheets.append(path)
        return sheets

    # ------------------------------------------------------------ writes
    def collections_by_id(self):
        """Every collection on the server, id -> name."""
        return {i["Id"]: i.get("Name") for i in self.all_items("IncludeItemTypes=BoxSet&Recursive=true", "collections")}

    def existing_collections(self):
        return {name: cid for cid, name in self.collections_by_id().items()}

    @staticmethod
    def owned_name_ok(st, live_name, coll=None):
        """A stored id is only trusted while the collection still carries a name CineSets gave it."""
        names = {st.get("name")} | ({coll["name"], coll.get("create_name")} if coll else set())
        names.discard(None)
        return not st.get("name") and not coll or live_name in names

    def apply_collection(self, coll, ids, poster, state, live, user_id):
        name, st, slowest = coll["name"], state.setdefault(coll["key"], {}), 0.0
        create_as = coll.get("create_name", name)
        by_id = {v: k for k, v in live.items()}
        if st.get("id") and st["id"] not in by_id:
            st.pop("id")  # deleted on the server since the last run
        if st.get("id") and not self.owned_name_ok(st, by_id[st["id"]], coll):
            raise RuntimeError(f"collection {st['id']} is now called {by_id[st['id']]!r}, not a name CineSets gave it; "
                               "not touching it (rename it back, or remove its entry)")
        pending = st.get("pending")
        if not st.get("id") and pending:
            # an earlier create may have finished on the server after CineSets gave up waiting
            found = live.get(pending["name"])
            if found and found != pending.get("not"):
                st["id"] = found
                print(f"   claimed {pending['name']!r}, created by an earlier run")
            st.pop("pending", None)
            save_json(self.state_file, state)
        cid = st.get("id") or live.get(name)
        created, added = False, 0
        if cid and st.get("id") != cid:
            raise RuntimeError(f"a collection named {name!r} already exists and was not created by CineSets "
                               f"(if it is from an earlier install, run: cinesets adopt --only {coll['key']})")
        if not cid:
            if create_as in live:
                raise RuntimeError(f"a collection named {create_as!r} already exists and was not created by CineSets; "
                                   "not creating another with that name")
            first = self.existing_ids(ids[:40])
            if not first:
                raise RuntimeError("none of its titles are on the server any more")
            st["pending"] = {"name": create_as, "not": None}
            save_json(self.state_file, state)
            try:
                r, took = self.srv.timed("POST", f"/Collections?Name={requests.utils.quote(create_as)}&Ids={','.join(first)}")
                cid, slowest = r.json()["Id"], took
            except (requests.RequestException, ServerError):
                # the server may have made the collection before failing; claim it if it is new since this run started
                cid = self.existing_collections().get(create_as)
                if cid and cid not in live.values():
                    st["id"], st["name"] = cid, create_as
                    st.pop("pending", None)
                    save_json(self.state_file, state)
                    print(f"   recovered {create_as!r} after a failed create; finishing it next run")
                raise
            created, added = True, len(first)
            owner = next((k for k, v in state.items() if k != coll["key"] and v.get("id") == cid), None)
            if owner or cid in live.values():
                st.pop("pending", None)
                save_json(self.state_file, state)
                raise RuntimeError(f"the server returned collection {cid}, which CineSets does not own "
                                   f"({'it belongs to ' + owner if owner else 'it already existed'}); not touching it")
            st["id"], st["name"] = cid, create_as
            st.pop("pending", None)
            save_json(self.state_file, state)
            self.wait_until_ready(cid, user_id)
        # read back what the collection holds, even a new one: Jellyfin 12 can drop the titles it was created with
        current = self.members(cid, user_id)
        add = self.existing_ids([i for i in ids if i not in current])
        remove = current - set(ids)
        for batch in chunks(add):
            slowest = max(slowest, self.srv.timed("POST", f"/Collections/{cid}/Items?Ids={','.join(batch)}")[1])
        for batch in chunks(remove):
            slowest = max(slowest, self.srv.timed("DELETE", f"/Collections/{cid}/Items?Ids={','.join(batch)}")[1])

        with open(poster, "rb") as f:
            raw = f.read()
        digest = hashlib.sha1(raw).hexdigest()
        if created or st.get("poster") != digest:
            before = self.poster_tag(cid, user_id)
            slowest = max(slowest, self.srv.timed("POST", f"/Items/{cid}/Images/Primary", data=base64.b64encode(raw),
                                                  headers={"Content-Type": "image/jpeg"})[1])
            if self.has_poster(cid, user_id, changed_from=before):
                st["poster"] = digest
            else:  # the server took the upload but did not keep it: try again next run
                st.pop("poster", None)
                print(f"   {coll['key']}: the server did not keep the poster; it will be uploaded again next run")

        meta = json.dumps([name, coll["sort"], coll.get("overview", ""), coll.get("order", "PremiereDate")])
        if created or st.get("meta") != meta:
            item = self.srv.item(user_id, cid)
            item["Name"], item["ForcedSortName"], item["SortName"] = name, coll["sort"], coll["sort"]
            item["Overview"] = coll.get("overview", "")
            item["DisplayOrder"] = coll.get("order", "PremiereDate")
            # Jellyfin has no SortName lock field; Emby does
            lock = {"Name", "Overview"} | ({"SortName"} if self.srv.kind == "emby" else set())
            item["LockedFields"] = sorted(set(item.get("LockedFields") or []) | lock)
            slowest = max(slowest, self.srv.timed("POST", f"/Items/{cid}", json=item)[1])
            st["meta"] = meta
        st["name"] = name
        st["count"], st["updated"] = len(ids), int(time.time())
        save_json(self.state_file, state)
        return created, added + len(add), len(remove), slowest

    def wait_until_ready(self, cid, user_id, seconds=20):
        """A new collection is usable once the server has given it a folder (Emby finishes this just after replying)."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                if self.srv.item(user_id, cid).get("Path"):
                    return
            except ServerError:
                pass
            time.sleep(1)

    def poster_tag(self, cid, user_id):
        try:
            return (self.srv.item(user_id, cid).get("ImageTags") or {}).get("Primary")
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

    def members(self, cid, user_id):
        # Jellyfin only lists box set children for a user; Emby lists them either way
        user = f"&UserId={user_id}" if self.srv.kind == "jellyfin" else ""
        return {i["Id"] for i in self.all_items(f"ParentId={cid}{user}", f"collection {cid}")}

    def existing_ids(self, ids):
        """Drop ids the server no longer has (the index can be up to a day old), keeping order."""
        alive = set()
        for batch in chunks(ids, 100):
            alive |= {i["Id"] for i in self.srv.get(f"/Items?Ids={','.join(batch)}")["Items"]}
        return [i for i in ids if i in alive]

    @contextlib.contextmanager
    def lock(self):
        """One run at a time per data folder (cron, Docker scheduler and manual runs)."""
        os.makedirs(self.data, exist_ok=True)
        try:
            import fcntl
        except ImportError:  # Windows: no advisory locks; run without one
            yield
            return
        with open(os.path.join(self.data, "cinesets.lock"), "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Another CineSets run is in progress; waiting for it to finish...")
                fcntl.flock(f, fcntl.LOCK_EX)
            except OSError as e:  # for example a network filesystem without lock support
                print(f"Could not lock the data folder ({e}); continuing without a lock.")
            yield

    # ------------------------------------------------------------ one run
    def run(self, cmd, colls, min_items):
        with self.lock():
            return self._run(cmd, colls, min_items)

    # ------------------------------------------------------------ ownership tools
    def adopt(self, colls):
        """Take ownership of existing collections with CineSets' names, for example after a reinstall."""
        with self.lock():
            state = load_json(self.state_file, {})
            live = self.existing_collections()
            owned = {v.get("id") for v in state.values()}
            for coll in colls:
                st = state.setdefault(coll["key"], {})
                cid = live.get(coll["name"]) or live.get(coll.get("create_name", ""))
                if st.get("id") in live.values():
                    print(f"{coll['key']}: already managed by CineSets")
                elif not cid:
                    print(f"{coll['key']}: no collection named {coll['name']!r} on the server")
                elif cid in owned:
                    print(f"{coll['key']}: {coll['name']!r} already belongs to another entry")
                else:
                    st.clear()
                    st.update({"id": cid, "name": coll["name"] if live.get(coll["name"]) == cid else coll.get("create_name")})
                    owned.add(cid)
                    print(f"{coll['key']}: adopted {coll['name']!r}; the next apply updates its titles, poster and name")
            save_json(self.state_file, state)

    def remove(self, keys, catalogue):
        """Delete collections CineSets created, by key (from its own record, not the collections file).
        A collection is only deleted while it still carries a name CineSets gave it. Returns how many were deleted."""
        by_key = {c["key"]: c for c in catalogue}
        with self.lock():
            state = load_json(self.state_file, {})
            live = self.collections_by_id()
            n = 0
            for key in keys:
                st = state.get(key) or {}
                cid = st.get("id")
                if not cid or cid not in live:
                    state.pop(key, None)
                    continue
                if not self.owned_name_ok(st, live[cid], by_key.get(key)):
                    print(f"{key}: collection {cid} is now called {live[cid]!r}; not deleting it")
                    continue
                self.srv.timed("DELETE", f"/Items/{cid}")
                print(f"deleted {live[cid]!r}")
                n += 1
                state.pop(key, None)
                save_json(self.state_file, state)
            save_json(self.state_file, state)
            return n

    def owned_keys(self):
        return [k for k, v in load_json(self.state_file, {}).items() if v.get("id")]

    def _run(self, cmd, colls, min_items):
        index = self.get_index()
        state = load_json(self.state_file, {})
        used, ready = set(), []
        for coll in colls:
            try:
                ids, wanted, matched = self.resolve(coll, index)
            except Exception as e:  # a dead list must not take the whole run down
                print(f"!! {coll['key']}: {e}")
                continue
            top = ", ".join(index["items"][i]["n"] for i in ids[:4])
            print(f"{coll['key']:<28} list {wanted:>4}  in library {matched:>4}  using {len(ids):>4}  | {top}")
            need = coll.get("min", min_items)
            if len(ids) < need:
                print(f"   skipped {coll['key']}: fewer than {need} matches")
                continue
            ready.append((coll, ids))
        if cmd == "plan":
            return

        made = []
        for coll, ids in ready:
            try:
                self.poster_for(coll, ids, index, state, used)
                made.append((coll, ids))
            except Exception as e:  # one bad poster must not stop the rest
                print(f"!! {coll['key']}: poster failed: {e}")
        ready = made
        save_json(self.state_file, state)
        if cmd == "posters":
            for s in self.contact_sheets([c["key"] for c, _ in ready]):
                print("sheet:", s)
            return

        live = self.existing_collections()
        user_id = self.srv.admin_user()
        for coll, ids in ready:
            poster = os.path.join(self.posters, coll["key"] + ".jpg")
            try:
                created, added, removed, slowest = self.apply_collection(coll, ids, poster, state, live, user_id)
            except requests.RequestException as e:
                print(f"!! {coll['key']}: the server did not answer ({type(e).__name__}); stopping this run to spare it.")
                break
            except Exception as e:
                print(f"!! {coll['key']}: {e}")
                if isinstance(e, ServerError) and (e.status or 0) >= 500:
                    print("Server error; stopping this run to spare it.")
                    break
                continue
            print(f"{'created' if created else 'updated'} {coll['name']!r}: +{added} -{removed}, slowest write {slowest:.1f}s")
            if slowest > self.cfg["slow_write_limit"]:
                print("Server is taking writes very slowly; stopping this run.")
                break
