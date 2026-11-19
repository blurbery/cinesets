# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""TMDB collections behind the fixed franchise lists, for people who set a TMDB API key (it's optional).

With a key in config.yml (tmdb: api_key) or CINESETS_TMDB_API_KEY, a franchise that names its `tmdb_collections` in
collections.yml follows TMDB: a film comes in once it is out, and one TMDB has taken out of the collection goes (see
plan). What TMDB answers is kept in data/tmdb for a day, and for longer while TMDB can't be reached, so an outage
never empties a collection. Without a key, or before TMDB has ever answered, the list that comes with CineSets is
used as it is. The weekly franchise check (tests/e2e/check_franchises.py) keeps that list current with the same rules.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""
import datetime
import os
import time

import requests

from .store import load_json, save_json

API = "https://api.themoviedb.org/3"
AGENT = "CineSets (+https://github.com/blurbery/cinesets)"
CREDIT = "This product uses the TMDB API but is not endorsed or certified by TMDB."
COLLECTION_TTL = 24 * 3600   # a collection is asked for again after a day
MOVIE_TTL = 7 * 24 * 3600    # a tmdb_add film's title and date change rarely


class Problem(Exception):
    """An entry or TMDB answer that can't be worked with."""


class Unreadable(Problem):
    """TMDB can't be read at all (no answer, or busy every time): asking again for the next film won't help."""


class Refused(Unreadable):
    """TMDB refused the key."""


def retry_after(value):
    """Seconds to wait from a Retry-After header: a number of seconds (an HTTP date or nothing means 10), at most 60."""
    try:
        return min(max(int(str(value).strip()), 1), 60)
    except (TypeError, ValueError):
        return 10


def plan(titles, parts, adds, skip, today):
    """A franchise's list as TMDB has it now, plus the films added and taken out.

    titles: its [title, year, id] entries; parts: {id: (title, release date)} for every film in its TMDB collections;
    adds: the same for its tmdb_add films; skip: ids to leave out; today: an ISO date. A film comes in once it is out
    (a release date of today or earlier), unless it is skipped; a listed film goes when it is in none of the
    collections and not added by hand. Listed films keep their place, title and year (one added by hand before its
    release stays); new ones go at the end with TMDB's title and year."""
    wanted = {**parts, **adds}
    keep, out = [], []
    for entry in titles:
        tmdb = entry[2] if len(entry) > 2 else None
        (keep if tmdb in wanted and tmdb not in skip else out).append(list(entry))
    have = {e[2] for e in keep}
    new = []
    for tmdb, (title, date) in sorted(wanted.items(), key=lambda kv: (kv[1][1] or "9999", kv[0])):
        if tmdb not in have and tmdb not in skip and date and date <= today:
            new.append([title, int(date[:4]), tmdb])
    return keep + new, new, out


class Client:
    """TMDB's API, a request at a time. A read access token (the long one) goes in a header, an API key as api_key.
    patient=False (the dashboard) asks once with a short wait instead of riding out a slow-down."""

    def __init__(self, key, patient=True):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = AGENT
        self.params = {"language": "en-US"}
        self.tries, self.timeout = (3, 30) if patient else (1, 10)
        if key.startswith("eyJ"):
            self.session.headers["Authorization"] = f"Bearer {key}"
        else:
            self.params["api_key"] = key

    def get(self, path):
        for attempt in range(self.tries):
            last = attempt == self.tries - 1
            try:
                r = self.session.get(API + path, params=self.params, timeout=self.timeout)
            except requests.RequestException as e:
                if last:
                    raise Unreadable(f"TMDB didn't answer ({type(e).__name__})")
                time.sleep(5)
                continue
            if r.status_code == 401:
                raise Refused("TMDB refused the key")
            if r.status_code == 404:
                raise Problem(f"TMDB has nothing at {path}")
            if r.status_code == 429 or r.status_code >= 500:
                if last:  # every film after this one would hit it too
                    raise Unreadable(f"TMDB answered {r.status_code} for {path}"
                                     + (f" {self.tries} times" if self.tries > 1 else ""))
                time.sleep(retry_after(r.headers.get("Retry-After")) if r.status_code == 429 else 5)
                continue
            if r.status_code != 200:
                raise Problem(f"TMDB answered {r.status_code} for {path}")
            try:
                body = r.json()
            except ValueError:
                raise Problem(f"TMDB answered {path} with something that isn't JSON")
            if not isinstance(body, dict):
                raise Problem(f"TMDB answered {path} with something unexpected")
            if self.tries > 1:
                time.sleep(0.1)
            return body
        raise Unreadable(f"TMDB kept failing for {path}")

    def collection(self, cid):
        """{id: (title, release date)} for every film in the collection."""
        body = self.get(f"/collection/{cid}")
        return {p["id"]: (str(p.get("title") or ""), str(p.get("release_date") or "")) for p in body.get("parts") or []
                if isinstance(p, dict) and isinstance(p.get("id"), int) and not isinstance(p.get("id"), bool)}

    def movie(self, mid):
        body = self.get(f"/movie/{mid}")
        return {mid: (str(body.get("title") or ""), str(body.get("release_date") or ""))}

    def check(self):
        """Raises Refused when TMDB turns the key down, Unreadable when TMDB can't be reached."""
        self.get("/configuration")


def key_of(cfg):
    return str((cfg.get("tmdb") or {}).get("api_key") or "").strip()


PAUSE = 300  # the dashboard leaves TMDB alone this long after it couldn't be read or refused the key
_refused = False  # TMDB turned the key down this run: the rest of the run uses the shipped lists without asking
_down_until = 0.0  # TMDB couldn't be read: until then, saved copies and the shipped lists are used without asking


def new_run():
    """Called at the start of each run (and when the dashboard saves a key), so TMDB is asked again."""
    global _refused, _down_until
    _refused, _down_until = False, 0.0


def _give_up(patient, e):
    """TMDB couldn't be read: a run stops asking until its end (each franchise would wait out its own tries), the
    dashboard for a few minutes. Said once."""
    global _down_until
    if time.time() < _down_until:
        return
    _down_until = float("inf") if patient else time.time() + PAUSE
    print(f"TMDB couldn't be read ({e}), so " + ("the rest of this run uses" if patient else
          f"for the next {PAUSE // 60} minutes the dashboard uses") +
          " the copies CineSets saved, or the lists that come with CineSets")


def _films(fetch, tmdb_id, path, ttl, patient=True):
    """{id: (title, date)} from the saved copy while it is fresh, else from TMDB (saved), else the stale copy with a
    note. Raises Problem when there is neither an answer nor a copy, and Refused whatever is saved. While TMDB is
    down (see _give_up) the saved copy is used however old it is, without asking."""
    saved = load_json(path, None)
    ok = (isinstance(saved, dict) and isinstance(saved.get("at"), (int, float)) and isinstance(saved.get("films"), list)
          and all(isinstance(f, list) and len(f) == 3 for f in saved["films"]))
    films = {f[0]: (f[1], f[2]) for f in saved["films"]} if ok else None
    if films is not None and time.time() - saved["at"] < ttl:
        return films
    if time.time() < _down_until:
        if films is None:
            raise Problem("TMDB couldn't be read")
        return films
    try:
        fresh = fetch(tmdb_id)
    except Refused:
        raise
    except Problem as e:
        if isinstance(e, Unreadable):
            _give_up(patient, e)
        if films is None:
            raise
        hours = int((time.time() - saved["at"]) / 3600)
        print(f"   TMDB: {e}, so CineSets is using the copy it saved {hours // 24 if hours >= 48 else hours}"
              f"{' days' if hours >= 48 else ' h'} ago")
        return films
    save_json(path, {"at": time.time(), "films": [[i, t, d] for i, (t, d) in fresh.items()]})
    return fresh


def live_titles(coll, cfg, data_dir, patient=True, today=None):
    """A fixed list's (title, year, id) entries as TMDB has its collections now, or the list in collections.yml when
    there is no key, the entry names no TMDB collection, or TMDB has never answered for it."""
    global _refused, _down_until
    titles = coll["titles"]
    key = key_of(cfg)
    if not key or not coll.get("tmdb_collections") or _refused:
        return titles
    client, folder = Client(key, patient), os.path.join(data_dir, "tmdb")
    try:
        parts, adds = {}, {}
        for cid in coll["tmdb_collections"]:
            parts.update(_films(client.collection, cid, os.path.join(folder, f"collection-{cid}.json"), COLLECTION_TTL,
                                patient))
        for mid in coll.get("tmdb_add") or []:
            adds.update(_films(client.movie, mid, os.path.join(folder, f"movie-{mid}.json"), MOVIE_TTL, patient))
    except Refused:
        if patient:
            _refused = True
        else:  # the dashboard keeps running: it tries again after a pause, or as soon as a new key is saved
            _down_until = time.time() + PAUSE
        print("TMDB refused the API key in config.yml (tmdb: api_key, or CINESETS_TMDB_API_KEY), so franchises use "
              "the lists that come with CineSets. Check the key on themoviedb.org, Settings, API.")
        return titles
    except Problem as e:
        print(f"   {coll['key']}: {e}, so it uses the list that comes with CineSets")
        return titles
    new, added, out = plan(titles, parts, adds, set(coll.get("tmdb_skip") or []), today or datetime.date.today().isoformat())
    if added:
        print(f"   {coll['key']}: new from TMDB: " + ", ".join(f"{t} ({y})" for t, y, _ in added))
    if out:
        print(f"   {coll['key']}: no longer in its TMDB collection: " + ", ".join(f"{t} ({y})" for t, y, _ in out))
    return [tuple(e) for e in new]
