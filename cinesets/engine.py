# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Library index, list matching, posters and collection writes.

Safety rules: CineSets only ever changes collections it created (recorded in data/state.json), writes only
what changed, and backs off when the server is slow.
"""
import contextlib
import hashlib
import json
import os
import random
import re
import time

import requests

from . import posters
from .lists import fetch_list
from .servers import ServerError, chunks
from .store import load_json, save_json

SAFE_ID = re.compile(r"^[A-Za-z0-9-]+$")
RANDOM_FROM = 25  # random artwork comes from the top titles of a collection, so posters show ones people know

INDEX_MAX_AGE = 20 * 3600


class Busy(RuntimeError):
    """Another CineSets run holds the lock (raised only when asked not to wait)."""


class Engine:
    def __init__(self, cfg, server, rng=None):
        self.cfg, self.srv = cfg, server
        self.style = cfg["posters"]
        self.rng = rng or random.Random()
        self.reshuffle = False  # pick new random artwork this run (posters.artwork: random)
        self.data = cfg.path("data_dir")
        self.index_file = os.path.join(self.data, "index.json")
        self.state_file = os.path.join(self.data, "state.json")
        self.backdrops = os.path.join(self.data, "backdrops")
        self.logos = os.path.join(self.data, "logos")
        self.posters = os.path.join(self.data, "posters")

    # ------------------------------------------------------------ library index
    def build_index(self):
        """One item per title; libraries listed earlier in config.yml win when a title is in several."""
        if not self.cfg["libraries"]:
            raise SystemExit("No libraries in config.yml: list the movie and TV libraries CineSets should use")
        folders = self.srv.library_folders()
        index = {"built": time.time(), "movie": {"imdb": {}, "tmdb": {}}, "show": {"tvdb": {}, "imdb": {}, "tmdb": {}}, "items": {}}
        for lib in self.cfg["libraries"]:
            name, kind = lib["name"], lib["type"]
            if name not in folders:
                raise SystemExit(f"library {name!r} not found on the server (found: {', '.join(sorted(folders))})")
            items = self.srv.library_items(folders[name], kind, name)
            for it in items:
                for key in index[kind]:
                    if it["ids"].get(key):
                        index[kind][key].setdefault(it["ids"][key], it["id"])
                index["items"][it["id"]] = {"n": it["name"], "y": it["year"], "b": it["backdrop"], "k": kind}
                if "genres" in it:  # a server that lists genres with the titles (Silo) needs no more requests for them
                    index["items"][it["id"]]["g"] = [g.lower() for g in it["genres"]]
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
                eid = self.match_row(row, kind, index)
                if eid and eid not in seen:
                    seen.add(eid)
                    ids.append(eid)
        limit = coll.get("limit", self.cfg["defaults"]["limit"])
        skip = {g.lower() for g in coll.get("exclude_genres", [])}
        if skip:
            # drop titles carrying an excluded genre (for example talk shows), keeping list order
            kept, cand = [], ids[:limit * 4]
            for batch in chunks(cand, 100):
                known = {i: set(index["items"][i]["g"]) for i in batch if "g" in index["items"].get(i, {})}
                genres = known if len(known) == len(batch) else self.srv.genres(batch)
                kept += [i for i in batch if not genres.get(i, set()) & skip]
            ids = kept
        return ids[:limit], wanted, len(ids)

    @staticmethod
    def match_row(row, kind, index):
        """The library item a list row is, by TVDB (shows), IMDb or TMDB id, or None."""
        lookup = index[kind]
        eid = lookup["tvdb"].get(str(row["tvdbid"])) if kind == "show" and row.get("tvdbid") else None
        return eid or lookup["imdb"].get(str(row.get("imdb_id") or "")) or lookup["tmdb"].get(str(row.get("id") or ""))

    # ------------------------------------------------------------ posters
    def poster_for(self, coll, ids, index, state, used):
        """Build the poster once and keep it, so daily list churn does not re-upload artwork.

        With posters.artwork set to random, each install picks its own artwork from the top titles in the collection
        (ignoring backdrop_title, so no two servers look alike) and keeps it until --reshuffle. Streaming service
        posters, and collections pinned to one item with backdrop_item, are left as they are. Artwork chosen in the
        dashboard (state "artwork": "chosen") comes before all of that and stays until it is set back to automatic."""
        os.makedirs(self.posters, exist_ok=True)
        os.makedirs(self.backdrops, exist_ok=True)
        out = os.path.join(self.posters, coll["key"] + ".jpg")
        st = state.setdefault(coll["key"], {})
        logo = coll.get("logo")
        style = posters.style_for(self.style, coll["key"], coll["group"])
        chosen = st.get("backdrop_item") if st.get("artwork") == "chosen" and not logo else None
        if chosen and not index["items"].get(chosen, {}).get("b"):
            print(f"   {coll['key']}: the artwork chosen in the dashboard is no longer in your library, using the default")
            st.pop("artwork", None)
            chosen = None
        random_art = self.style["artwork"] == "random" and not logo and not coll.get("backdrop_item") and not chosen
        parts = [coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], coll.get("backdrop_item"), coll.get("backdrop_title")]
        if logo:
            parts.append("logo:" + logo)
        # only settings changed from the defaults go in, so posters made before these settings existed are kept
        changed = posters.style_changes(style, logo=bool(logo))
        if changed:
            parts.append("style:" + json.dumps(changed, sort_keys=True))
        if random_art:
            parts.append("artwork:random")
        if chosen:
            parts.append("artwork:chosen:" + chosen)
        design = json.dumps(parts)
        if os.path.exists(out) and st.get("design") == design and not (random_art and self.reshuffle):
            used.add(st.get("backdrop_item"))
            return out
        pick = chosen or coll.get("backdrop_item")
        if not pick and coll.get("backdrop_title") and not random_art:
            pick = next((i for i in ids if index["items"][i]["n"] == coll["backdrop_title"] and index["items"][i]["b"]), None)
            if not pick:
                print(f"   {coll['key']}: backdrop title {coll['backdrop_title']!r} not in this collection, using the default")
        if not pick:
            candidates = [i for i in ids if index["items"].get(i, {}).get("b")]
            if random_art:
                pick = self.random_pick(candidates, st, used)
            else:
                pick = next((i for i in candidates if i not in used), candidates[0] if candidates else None)
        bd = None
        if pick and SAFE_ID.match(str(pick)):
            used.add(pick)
            bd = self.backdrop(pick)
        if logo:
            posters.make_logo_poster(out, coll["label"], logo, self.logos, coll.get("subtitle") or "Popular", bd, coll["title"],
                                     style)
        else:
            posters.make_poster(out, coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], bd, style)
        if bd or not pick:
            st["design"], st["backdrop_item"] = design, pick
            if random_art:
                st["artwork"] = "random"
            elif not chosen:
                st.pop("artwork", None)
        else:
            st.pop("design", None)  # the artwork could not be fetched: build the poster again next run
        return out

    @staticmethod
    def candidates(ids, index):
        """The titles random artwork is picked from: the top ones in the collection that have artwork."""
        return [i for i in ids if index["items"].get(i, {}).get("b")][:RANDOM_FROM]

    def random_pick(self, candidates, st, used):
        """A random title from the top of the collection. A random pick from an earlier run is kept while it is still
        anywhere in the collection (so list churn or a colour change keeps the picture) unless this is a reshuffle;
        a pick made before random was switched on is not."""
        kept = st.get("backdrop_item")
        if st.get("artwork") == "random" and not self.reshuffle and kept in candidates and kept not in used:
            return kept
        top = candidates[:RANDOM_FROM]
        pool = [i for i in top if i not in used and i != kept] or [i for i in top if i != kept] or top
        return self.rng.choice(pool) if pool else None

    def backdrop(self, item_id):
        """Download an item's backdrop once. A failed or broken download is never left on disk."""
        path = os.path.join(self.backdrops, item_id + ".jpg")
        if os.path.exists(path):
            return path
        tmp = path + ".part"
        try:
            content = self.srv.backdrop_image(item_id, 1920, 90)
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
        return self.srv.list_collections()

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
                cid, slowest = self.srv.create_collection(create_as, coll, first)
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
            self.srv.wait_until_ready(cid, user_id)
        # read back what the collection holds, even a new one: Jellyfin 12 can drop the titles it was created with
        current = self.srv.members(cid, user_id)
        add = self.existing_ids([i for i in ids if i not in current])
        remove = current - set(ids)
        if add:
            slowest = max(slowest, self.srv.add_items(cid, add))
        if remove:
            slowest = max(slowest, self.srv.remove_items(cid, remove))

        with open(poster, "rb") as f:
            raw = f.read()
        digest = hashlib.sha1(raw).hexdigest()
        if created or st.get("poster") != digest:
            kept, took = self.srv.upload_poster(cid, raw, user_id)
            slowest = max(slowest, took)
            if kept:
                st["poster"] = digest
            else:  # the server took the upload but did not keep it: try again next run
                st.pop("poster", None)
                print(f"   {coll['key']}: the server did not keep the poster; it will be uploaded again next run")

        meta = json.dumps([name, coll["sort"], coll.get("overview", ""), coll.get("order", "PremiereDate")])
        if created or st.get("meta") != meta:
            slowest = max(slowest, self.srv.set_details(cid, user_id, coll, name))
            st["meta"] = meta
        st["name"] = name
        st["count"], st["updated"] = len(ids), int(time.time())
        save_json(self.state_file, state)
        return created, added + len(add), len(remove), slowest

    def existing_ids(self, ids):
        """Drop ids the server no longer has (the index can be up to a day old), keeping order."""
        alive = set()
        for batch in chunks(ids, 100):
            alive |= self.srv.alive(batch)
        return [i for i in ids if i in alive]

    @contextlib.contextmanager
    def lock(self, wait=True):
        """One run at a time per data folder (cron, Docker scheduler, manual runs and the dashboard). With wait=False,
        raise Busy instead of waiting for another run to finish."""
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
                if not wait:
                    raise Busy("A CineSets run is in progress. Try again when it has finished.")
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
                self.srv.delete_collection(cid)
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
            if not coll.get("titles"):
                need = min(need, coll["limit"])  # a collection capped at 5 titles is not skipped for having fewer than 8
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
        else:
            if hasattr(self.srv, "arrange"):  # a server that places collections by order, not sort name (Silo)
                try:
                    self.srv.arrange({k: v["id"] for k, v in state.items() if v.get("id")})
                except (requests.RequestException, ServerError) as e:
                    print(f"!! could not put the collections in order: {e}")
