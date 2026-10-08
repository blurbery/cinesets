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

from . import lists, posters
from .lists import fetch_list
from .servers import ServerError, chunks
from .store import load_json, save_json

SAFE_ID = re.compile(r"^[A-Za-z0-9-]+$")
RANDOM_FROM = 25  # random artwork comes from the top titles of a collection, so posters show ones people know

INDEX_MAX_AGE = 20 * 3600


class Busy(RuntimeError):
    """Another CineSets run holds the lock (raised only when asked not to wait)."""


class Result:
    """What one run did: the counts for the line it ends with, and why it stopped early if it did."""

    def __init__(self, cmd):
        self.cmd, self.stopped, self.listed = cmd, None, True
        self.created = self.updated = self.matched = self.below = self.failed = 0

    @property
    def ok(self):
        """False when something failed or the run stopped early. Collections below their minimum are not failures."""
        return not self.failed and not self.stopped

    def summary(self):
        """`Summary: 3 created, 40 updated, 2 left as they are (below the minimum), 1 failed`, leaving out the parts that
        are nothing. A plan says what apply would do, or only what matched if it couldn't list the server's collections."""
        if self.cmd == "plan":
            done = [(self.created, "would create"), (self.updated, "would update")] if self.listed else [
                (self.matched, "matched")]
        elif self.cmd == "posters":
            done = [(self.created, "posters made")]
        else:
            done = [(self.created, "created"), (self.updated, "updated")]
        parts = [f"{n} {what}" for n, what in done + [(self.below, "left as they are (below the minimum)"),
                                                      (self.failed, "failed")] if n]
        return "Summary: " + (", ".join(parts) or "nothing to do")


def in_season(active, today=None):
    """Whether today is inside a seasonal collection's `active: [MM-DD, MM-DD]` window. Both days count, and a window
    can run past new year (["12-01", "01-06"]). A collection without one is always in season."""
    if not isinstance(active, (list, tuple)) or len(active) != 2:
        return True
    start, end = (str(d) for d in active)
    today = today or time.strftime("%m-%d")
    return start <= today <= end if start <= end else (today >= start or today <= end)


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
        self._titles = None  # (index, {kind: titles_in table}) for the index a run or the dashboard is using
        self.halt = lambda: False  # the scheduler swaps this for one that says when it has been asked to stop

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
            # fixed franchise list: exact title and year
            found = self.titles_in(index, kind)
            ids = self.srv.narrow(coll, [found[(t.lower(), y)] for t, y in coll["titles"] if (t.lower(), y) in found])
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
        ids = self.srv.narrow(coll, ids)  # the titles this collection can hold on this server
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

    def titles_in(self, index, kind):
        """(lower-case title, year) -> item id for every title of one kind, worked out once per index rather than once
        per franchise, so a big library is read through once. A title in the library more than once is the copy the
        index treats as canonical (it holds the title's IMDb or TMDB id), or else the first one."""
        if self._titles is None or self._titles[0] is not index:
            self._titles = (index, {})
        tables = self._titles[1]
        if kind not in tables:
            canon = set(index[kind]["imdb"].values()) | set(index[kind]["tmdb"].values())
            found = {}
            for iid, it in index["items"].items():
                if it.get("k", kind) != kind:  # an index from before "k" counts every title as either kind
                    continue
                k = ((it.get("n") or "").lower(), it.get("y"))
                if k not in found or (iid in canon and found[k] not in canon):
                    found[k] = iid
            tables[kind] = found  # only once it is whole: the dashboard answers several requests at a time
        return tables[kind]

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

        def draw(art):
            if logo:
                posters.make_logo_poster(out, coll["label"], logo, self.logos, coll.get("subtitle") or "Popular", art,
                                         coll["title"], style)
            else:
                posters.make_poster(out, coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], art, style)
        try:
            draw(bd)
        except Exception as e:
            if not bd:
                raise
            # a saved backdrop that can't be drawn (cut off, say): delete it so the next run downloads it again
            print(f"   {coll['key']}: the saved artwork could not be drawn ({e}); using a plain background, and it is "
                  "downloaded again next run")
            with contextlib.suppress(FileNotFoundError):
                os.remove(bd)
            bd = None
            draw(None)
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
            with Image.open(tmp) as im:
                im.load()  # every pixel too: a download cut off part way passes verify() but can't be drawn
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
        """Every collection on the server, id -> name. Ownership is always checked by id: several collections can share
        a name."""
        return self.srv.list_collections()

    def existing_collections(self):
        """name -> id; a name several collections share keeps only one of them, so this is never used to decide what
        CineSets owns."""
        return {name: cid for cid, name in self.collections_by_id().items()}

    @staticmethod
    def owned_name_ok(st, live_name, coll=None):
        """A stored id is only trusted while the collection still carries a name CineSets gave it: the one it saved,
        or for an entry still in the collections file, its name or create_name. With neither to go on (a record from
        an old version, for a collection no longer in the file) it isn't trusted."""
        names = {st.get("name")} | ({coll["name"], coll.get("create_name")} if coll else set())
        names.discard(None)
        return live_name in names

    @staticmethod
    def renamed(key, cid, live_name):
        return (f"collection {cid} is now called {live_name!r}, not a name CineSets gave it; not touching it (rename it "
                f"back, or run: cinesets forget {key})")

    @staticmethod
    def check_name_free(coll, live):
        """Before making a collection: stop if its name, or the name it is made under, is on the server already. A
        name several collections share is never made again, so CineSets can always tell its own apart."""
        for name in dict.fromkeys([coll["name"], coll.get("create_name", coll["name"])]):
            held = sum(1 for n in live.values() if n == name)
            if held > 1:
                raise RuntimeError(f"{held} collections on the server are called {name!r}, so CineSets can't tell them "
                                   "apart; not making another (rename or delete the extra ones)")
            if held and name == coll["name"]:
                raise RuntimeError(f"a collection named {name!r} already exists and was not created by CineSets "
                                   f"(if it is from an earlier install, run: cinesets adopt --only {coll['key']})")
            if held:
                raise RuntimeError(f"a collection named {name!r} already exists and was not created by CineSets; "
                                   "not creating another with that name")

    @staticmethod
    def claimable(key, st, state, live):
        """Collections an earlier run's create may have made after CineSets gave up waiting: those with the name it
        asked for that weren't there before it asked, and aren't another entry's."""
        pending = st.get("pending") or {}
        before = set(pending.get("not") or ())  # None in older records: the name was free then, or it wasn't made
        others = {v.get("id") for k, v in state.items() if k != key}
        return [c for c, n in live.items() if n == pending.get("name") and c not in before and c not in others]

    def claim(self, coll, st, state, live):
        """Take on a collection an earlier run asked for, if exactly one could be it."""
        found, name = self.claimable(coll["key"], st, state, live), st["pending"].get("name")
        if len(found) == 1:
            st["id"], st["name"] = found[0], name
            print(f"   claimed {name!r}, created by an earlier run")
        elif found:
            print(f"   {coll['key']}: {len(found)} collections are called {name!r}, so CineSets can't tell which one an "
                  "earlier run made; claiming none of them")
        st.pop("pending", None)
        save_json(self.state_file, state)

    def after_failed_create(self, st, state, live, e):
        """A create that raised: forget it if the server clearly turned it down, claim the collection if the server
        made it anyway, and otherwise leave it pending so the next run can claim one that turns up late."""
        name = st["pending"]["name"]
        if isinstance(e, ServerError) and e.status and 400 <= e.status < 500 and e.status != 408:
            st.pop("pending", None)  # refused, so nothing was made
            save_json(self.state_file, state)
            return
        try:
            fresh = self.collections_by_id()
        except (requests.RequestException, ServerError):
            return
        new = [c for c, n in fresh.items() if n == name and c not in live]
        if len(new) == 1:
            st["id"], st["name"] = new[0], name
            st.pop("pending", None)
            live[new[0]] = name
            save_json(self.state_file, state)
            print(f"   recovered {name!r} after a failed create; finishing it next run")

    def apply_collection(self, coll, ids, poster, state, live, user_id):
        """Make or update one collection. `live` is every collection on the server (id -> name), kept up to date as the
        run makes and renames them. `poster` is None when it couldn't be drawn: the titles are still updated."""
        name, key, st, slowest = coll["name"], coll["key"], state.setdefault(coll["key"], {}), 0.0
        create_as = coll.get("create_name", name)
        if st.get("id") and st["id"] not in live:
            print(f"   {key}: the collection CineSets made was deleted on the server, so it is being made again "
                  "(unpick it to stop that)")
            st.pop("id")
        if st.get("id") and not self.owned_name_ok(st, live[st["id"]], coll):
            raise RuntimeError(self.renamed(key, st["id"], live[st["id"]]))
        if not st.get("id") and st.get("pending"):
            self.claim(coll, st, state, live)
        cid, created, added = st.get("id"), False, 0
        if not cid:
            self.check_name_free(coll, live)
            first = self.existing_ids(ids[:40])
            if not first:
                raise RuntimeError("none of its titles are on the server any more")
            st["pending"] = {"name": create_as, "not": sorted(c for c, n in live.items() if n == create_as)}
            save_json(self.state_file, state)
            try:
                cid, slowest = self.srv.create_collection(create_as, coll, first)
            except (requests.RequestException, ServerError) as e:
                self.after_failed_create(st, state, live, e)
                raise
            created, added = True, len(first)
            owner = next((k for k, v in state.items() if k != key and v.get("id") == cid), None)
            if owner or cid in live:
                st.pop("pending", None)
                save_json(self.state_file, state)
                raise RuntimeError(f"the server returned collection {cid}, which CineSets does not own "
                                   f"({'it belongs to ' + owner if owner else 'it already existed'}); not touching it")
            st["id"], st["name"] = cid, create_as
            st.pop("pending", None)
            live[cid] = create_as
            save_json(self.state_file, state)
            self.srv.wait_until_ready(cid, user_id)
        # read back what the collection holds, even a new one: Jellyfin 12 can drop the titles it was created with
        self.srv.prepare(cid, coll)
        current = self.srv.members(cid, user_id)
        add = self.existing_ids([i for i in ids if i not in current])
        remove = current - set(ids)
        if add:
            slowest = max(slowest, self.srv.add_items(cid, add))
        if remove:
            slowest = max(slowest, self.srv.remove_items(cid, remove))

        problem = None
        if poster:
            with open(poster, "rb") as f:
                raw = f.read()
            digest = hashlib.sha1(raw).hexdigest()
            if created or st.get("poster") != digest:
                try:
                    kept, took = self.srv.upload_poster(cid, raw, user_id)
                except Exception as e:  # the details below still go on, so a poster problem never holds them up
                    problem, kept, took = e, False, 0.0
                slowest = max(slowest, took)
                if kept:
                    st["poster"] = digest
                else:  # the server did not keep it, or the upload failed: try again next run
                    st.pop("poster", None)
                    if not problem:
                        print(f"   {key}: the server did not keep the poster; it will be uploaded again next run")
                if problem:
                    save_json(self.state_file, state)

        meta = json.dumps([name, coll["sort"], coll.get("overview", ""), coll.get("order", "PremiereDate")])
        if created or st.get("meta") != meta:
            slowest = max(slowest, self.srv.set_details(cid, user_id, coll, name))
            st["meta"] = meta
            live[cid] = name
        st["name"] = name
        st["count"], st["updated"] = len(ids), int(time.time())
        save_json(self.state_file, state)
        if problem:
            print(f"   {key}: its titles and details are up to date, but the poster upload failed; it is tried again "
                  "next run")
            raise problem
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
        """Run plan, posters or apply for these collections. Returns a Result, whose `ok` is False when something
        failed or the run stopped early."""
        with self.lock():
            try:
                return self._run(cmd, colls, min_items)
            finally:
                self._titles = None  # let this run's index go once the run is over (the scheduler sleeps for hours)

    # ------------------------------------------------------------ ownership tools
    def adopt(self, colls):
        """Take ownership of existing collections with CineSets' names, for example after a reinstall. A name several
        collections share is never adopted: CineSets can't tell which one is its own."""
        with self.lock():
            state = load_json(self.state_file, {})
            live = self.collections_by_id()
            owned = {v.get("id") for v in state.values()}
            for coll in colls:
                st = state.setdefault(coll["key"], {})
                if st.get("id") in live:
                    print(f"{coll['key']}: already managed by CineSets")
                    continue
                found = None
                for name in dict.fromkeys(n for n in (coll["name"], coll.get("create_name")) if n):
                    held = [c for c, n in live.items() if n == name]
                    if len(held) > 1:
                        print(f"{coll['key']}: {len(held)} collections are called {name!r}, so CineSets can't tell "
                              "which one is its own; not adopting any of them (rename or delete the others, then adopt "
                              "again)")
                        found = False
                        break
                    if held:
                        found = (held[0], name)
                        break
                if found is False:
                    continue
                if not found:
                    print(f"{coll['key']}: no collection named {coll['name']!r} on the server")
                elif found[0] in owned:
                    print(f"{coll['key']}: {found[1]!r} already belongs to another entry")
                else:
                    st.clear()
                    st.update({"id": found[0], "name": found[1]})
                    owned.add(found[0])
                    print(f"{coll['key']}: adopted {found[1]!r}; the next apply updates its titles, poster and name")
            save_json(self.state_file, state)

    def remove(self, keys, catalogue):
        """Delete collections CineSets created, by key (from its own record, not the collections file).
        A collection is only deleted while it still carries a name CineSets gave it. Returns how many were deleted."""
        by_key = {c["key"]: c for c in catalogue}
        with self.lock():
            state = load_json(self.state_file, {})
            n = self._delete(keys, by_key, state, self.collections_by_id())
            save_json(self.state_file, state)
            return n

    def _delete(self, keys, by_key, state, live, why=""):
        """remove() without the lock, for a run that already holds it (seasonal collections out of season)."""
        n = 0
        for key in keys:
            st = state.get(key) or {}
            cid = st.get("id")
            if not cid or cid not in live:
                state.pop(key, None)
                continue
            if not self.owned_name_ok(st, live[cid], by_key.get(key)):
                if st.get("name") or key in by_key:
                    print(f"{key}: collection {cid} is now called {live[cid]!r}; not deleting it")
                else:
                    print(f"{key}: CineSets' record doesn't say what it named collection {cid} (now {live[cid]!r}), "
                          f"and {key} isn't in the collections file any more, so it can't be sure the collection is "
                          f"still its own; not deleting it (delete it on the server yourself if it is, then run: "
                          f"cinesets forget {key})")
                continue
            self.srv.delete_collection(cid)
            print(f"deleted {live.pop(cid)!r}{why}")
            n += 1
            state.pop(key, None)
            save_json(self.state_file, state)
        return n

    def forget(self, keys):
        """Drop CineSets' record of these collections without touching the server: they stay as they are, and from
        then on CineSets treats them like anyone else's. Returns the keys it had a record of."""
        with self.lock():
            state = load_json(self.state_file, {})
            known = [k for k in keys if k in state]
            for key in keys:
                st = state.pop(key, None)
                if st is None:
                    print(f"{key}: CineSets has no record of it, so there is nothing to forget")
                elif st.get("id"):
                    called = f" ({st['name']!r})" if st.get("name") else ""
                    print(f"{key}: forgot collection {st['id']}{called}. It stays on your server as it is, and CineSets "
                          "won't change or delete it")
                else:
                    print(f"{key}: forgot it (CineSets hadn't made it on the server)")
            save_json(self.state_file, state)
            return known

    def owned_keys(self):
        return [k for k, v in load_json(self.state_file, {}).items() if v.get("id")]

    @staticmethod
    def stop_reason(e):
        """Why a run stops after this error, or None to carry on with the next collection: the server not answering,
        turning the key down, still asking CineSets to slow down after its retries, or failing itself."""
        if isinstance(e, requests.RequestException):
            return f"the server did not answer ({type(e).__name__})"
        status = e.status if isinstance(e, ServerError) else None
        if status in (401, 403):
            return f"the server turned down CineSets' API key (HTTP {status})"
        if status == 429:
            return "the server kept asking CineSets to slow down (HTTP 429)"
        if (status or 0) >= 500:
            return f"the server had a problem (HTTP {status})"
        return None

    def _run(self, cmd, colls, min_items):
        result = Result(cmd)
        try:
            self._steps(cmd, colls, min_items, result)
        except (requests.RequestException, ServerError) as e:  # outside a collection: listing them, say
            print(f"!! {e}")
            result.failed += 1
            result.stopped = self.stop_reason(e) or "the server answered with an error"
        if result.stopped:
            print(f"Stopped early: {result.stopped}")
        print(result.summary())
        return result

    def _steps(self, cmd, colls, min_items, result):
        lists.new_run()
        index = self.get_index()
        state = load_json(self.state_file, {})
        used, todo = set(), []  # (collection, its titles), or (collection, None) for one out of season
        for coll in colls:
            if self.halt():
                result.stopped = "asked to stop"
                return
            if not in_season(coll.get("active")):
                print(f"{coll['key']:<28} out of season (it runs from {coll['active'][0]} to {coll['active'][1]})")
                todo.append((coll, None))
                continue
            try:
                ids, wanted, matched = self.resolve(coll, index)
            except Exception as e:  # a dead list must not take the whole run down, but a struggling server does
                print(f"!! {coll['key']}: {e}")
                result.failed += 1
                result.stopped = self.stop_reason(e)
                if result.stopped:
                    return
                continue
            top = ", ".join(index["items"][i]["n"] or "?" for i in ids[:4])  # a title can come without a name
            print(f"{coll['key']:<28} list {wanted:>4}  in library {matched:>4}  using {len(ids):>4}  | {top}")
            need = coll.get("min", min_items)
            if not coll.get("titles"):
                need = min(need, coll["limit"])  # a collection capped at 5 titles is not skipped for having fewer than 8
            # even with --min 0: an empty collection is never made, and one CineSets made is never emptied
            if len(ids) < need or not ids:
                why = f"below its minimum ({len(ids)} of {need} matches)" if len(ids) < need else "no matches"
                where = "left as it is on the server" if (state.get(coll["key"]) or {}).get("id") else "not made"
                print(f"   {coll['key']}: {why}, so it is {where}")
                result.below += 1
                continue
            todo.append((coll, ids))
        if cmd == "plan":
            self._plan(todo, state, result)
            return

        drawn, undrawn = {}, set()
        for coll, ids in todo:
            if ids is None:
                continue
            try:
                drawn[coll["key"]] = self.poster_for(coll, ids, index, state, used)
            except Exception as e:  # one bad poster must not stop the rest, nor keep its collection's titles back
                print(f"!! {coll['key']}: poster failed: {e}" + ("" if cmd == "posters" else
                                                                 "; its titles are still updated"))
                (state.get(coll["key"]) or {}).pop("design", None)  # draw it again next run
                undrawn.add(coll["key"])
        save_json(self.state_file, state)
        if cmd == "posters":
            result.created, result.failed = len(drawn), result.failed + len(undrawn)
            for s in self.contact_sheets(list(drawn)):
                print("sheet:", s)
            return

        live = self.collections_by_id()
        user_id = self.srv.admin_user()
        for coll, ids in todo:
            if self.halt():
                result.stopped = "asked to stop"
                break
            key = coll["key"]
            try:
                if ids is None:
                    if (state.get(key) or {}).get("id") in live:
                        self._delete([key], {key: coll}, state, live, ", as it is out of season")
                    continue
                created, added, removed, slowest = self.apply_collection(coll, ids, drawn.get(key), state, live, user_id)
            except Exception as e:
                gone = isinstance(e, requests.RequestException)
                print(f"!! {key}: {'the server did not answer (' + type(e).__name__ + ')' if gone else e}")
                result.failed += 1
                result.stopped = self.stop_reason(e)
                if result.stopped:
                    break
                continue
            print(f"{'created' if created else 'updated'} {coll['name']!r}: +{added} -{removed}, slowest write {slowest:.1f}s"
                  + (", without a new poster" if key in undrawn else ""))
            if key in undrawn:
                result.failed += 1
            elif created:
                result.created += 1
            else:
                result.updated += 1
            if slowest > self.cfg["slow_write_limit"]:
                result.stopped = f"the server is taking writes very slowly (one took {slowest:.0f} s)"
                break
        else:  # every collection was dealt with: put them in page order, if the server needs telling
            by_key = {c["key"]: c for c in colls}
            # only the ones still carrying a name CineSets gave them: never one this run turned down as renamed
            mine = {k: v["id"] for k, v in state.items()
                    if v.get("id") in live and self.owned_name_ok(v, live[v["id"]], by_key.get(k))}
            try:
                self.srv.arrange(mine)
            except (requests.RequestException, ServerError) as e:
                print(f"!! could not put the collections in order: {e}")
                result.failed += 1

    def _plan(self, todo, state, result):
        """What apply would do, from one read-only listing of the server's collections."""
        try:
            live = self.collections_by_id()
        except (requests.RequestException, ServerError) as e:
            print(f"   (could not list the collections on the server, so this only shows what matched: {e})")
            result.listed = False
            result.matched = sum(1 for _, ids in todo if ids is not None)
            return
        for coll, ids in todo:
            key = coll["key"]
            st = state.get(key) or {}
            cid = st.get("id") if st.get("id") in live else None
            if ids is None:
                if cid and self.owned_name_ok(st, live[cid], coll):
                    print(f"   {key}: apply would delete {live[cid]!r}, as it is out of season")
                continue
            if st.get("id") and not cid:
                print(f"   {key}: the collection CineSets made was deleted on the server, so apply would make it again "
                      "(unpick it to stop that)")
            try:
                if cid and not self.owned_name_ok(st, live[cid], coll):
                    raise RuntimeError(self.renamed(key, cid, live[cid]))
                if cid or (st.get("pending") and len(self.claimable(key, st, state, live)) == 1):
                    result.updated += 1
                else:
                    self.check_name_free(coll, live)
                    result.created += 1
            except RuntimeError as e:
                print(f"!! {key}: {e}")
                result.failed += 1
