# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""The dashboard: a local web page to pick collections, style the posters, move their text and choose artwork.

  cinesets web [--host 127.0.0.1] [--port 8095] [--demo]
  cinesets web --link | --new-key | --set-password

Who can use it: whoever signs in with the access key (made on first run and kept in data/web.json, readable by its
owner only) or the password set with --set-password. Signing in sets a session cookie: HttpOnly, SameSite=Strict,
scoped to the API, signed with a secret from the same file, and marked Secure behind an HTTPS proxy. Every API request
must also carry an X-CineSets header, which other web sites can't add, and failed sign-ins are rate limited. --new-key
signs everyone out. The API key for the media server never reaches the browser: artwork is fetched here and passed
on. It listens on this machine only unless --host says otherwise; for other computers, put it behind Tailscale or a
reverse proxy with HTTPS (see the README). Every URL in the page is relative, so a proxy can serve it under a path.

Settings are saved to config.yml (the old one is kept as config.yml.bak, and a save made over changes from elsewhere
is refused); artwork choices go in data/state.json with the rest of CineSets' record, and the posters change on the
next apply. --demo needs no server, no sign-in and saves nothing.
"""
import base64
import collections
import contextlib
import getpass
import hashlib
import hmac
import http.server
import io
import json
import os
import random
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import zlib
from urllib.parse import parse_qs, urlparse

import yaml
from PIL import Image

from . import __version__, catalog, config, posters, scenes
from .engine import SAFE_ID, Busy, Engine
from .lists import fetch_list, slug_of
from .servers import ServerError, connect
from .store import load_json, save_json

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
FILES = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
         "/app.css": ("app.css", "text/css; charset=utf-8"), "/icon.png": ("icon.png", "image/png")}
MAX_BODY = 1 << 20
PREVIEW = (600, 900)
CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
LOCAL = ("127.0.0.1", "localhost", "::1")
COOKIE = "cinesets"
SESSION_DAYS = 30
PASSWORD_MIN = 12
PBKDF2_ROUNDS = 600_000
BUSY_LIMIT = 16  # requests handled at once; more get "busy" rather than piling up threads


# ---------------------------------------------------------------- the access key, password and sessions
def access_file(cfg):
    return os.path.join(cfg.path("data_dir"), "web.json")


def _new_access():
    return {"key": secrets.token_urlsafe(24), "secret": secrets.token_hex(32), "password": None}


def read_access(path):
    """The access key, cookie secret and password hash, made on first use. The new file is written in full beside it
    and then linked into place, which fails if it's already there, so two processes starting together end up with
    the same key and neither reads it half written."""
    if not os.path.exists(path):
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        fd, part = tempfile.mkstemp(dir=folder, prefix=".web-", suffix=".json")  # only you can read it
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(_new_access(), f)
            try:
                os.link(part, path)
            except FileExistsError:
                pass  # another process made it first: use theirs
            except OSError:  # a filesystem without hard links: an exclusive create instead
                with contextlib.suppress(FileExistsError), open(path, "x") as f:
                    os.chmod(path, 0o600)
                    json.dump(_new_access(), f)
        finally:
            os.remove(part)
    access = load_json(path, None)
    if not isinstance(access, dict) or not access.get("key") or not access.get("secret"):
        raise SystemExit(f"{path} is damaged. Delete it and start the dashboard again to make a new access key.")
    return access


def new_key(path):
    """A new access key and cookie secret, which signs everyone out. A password set before is kept."""
    access = read_access(path)
    save_json(path, {**_new_access(), "password": access.get("password")})


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return {"salt": salt, "hash": digest, "rounds": PBKDF2_ROUNDS}


def set_password(path, password):
    """Set the dashboard password, or remove it with an empty one (the access key always works)."""
    if password and len(password) < PASSWORD_MIN:
        raise SystemExit(f"Use at least {PASSWORD_MIN} characters.")
    access = read_access(path)
    save_json(path, {**access, "password": hash_password(password) if password else None})


def check_password(stored, password):
    if not stored:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(stored["salt"]), int(stored["rounds"])).hex()
    return hmac.compare_digest(digest, stored["hash"])


class Gate:
    """Signs people in and checks their session cookie. Re-reads web.json when it changes, so --new-key and
    --set-password work without a restart. Wrong keys are rate limited per address and overall (behind a proxy every
    request comes from the proxy's address, so the overall limit is the one that counts)."""

    def __init__(self, path):
        self.path, self.stamp, self.access = path, None, None
        self.fails, self.lock = collections.defaultdict(list), threading.Lock()
        self.current()

    def current(self):
        stamp = os.stat(self.path).st_mtime_ns if os.path.exists(self.path) else None
        if stamp != self.stamp or self.access is None:
            self.access = read_access(self.path)
            self.stamp = os.stat(self.path).st_mtime_ns
        return self.access

    def _sign(self, expiry):
        return hmac.new(self.current()["secret"].encode(), str(expiry).encode(), hashlib.sha256).hexdigest()

    def cookie(self):
        expiry = int(time.time()) + SESSION_DAYS * 86400
        return f"{expiry}.{self._sign(expiry)}"

    def valid(self, value):
        expiry, _, signature = (value or "").partition(".")
        if not (expiry.isascii() and expiry.isdigit()) or int(expiry) < time.time():
            return False
        return hmac.compare_digest(signature.encode(), self._sign(int(expiry)).encode())

    def login(self, given, address):
        now = time.time()
        with self.lock:
            for who in (address, "*"):
                self.fails[who] = [t for t in self.fails[who] if now - t < 600]
            if len(self.fails[address]) >= 5 or len(self.fails["*"]) >= 20:
                raise Problem("Too many tries. Wait a few minutes, then try again.", 429)
        access = self.current()
        given = str(given or "")
        if hmac.compare_digest(given.encode(), access["key"].encode()) or check_password(access.get("password"), given):
            return True
        with self.lock:
            self.fails[address].append(now)
            self.fails["*"].append(now)
        time.sleep(0.4)
        raise Problem("That isn't the access key or password.", 401)


class Problem(Exception):
    """A request the dashboard turns down, with a message for the page."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _hex(colour):
    return "#%02x%02x%02x" % tuple(colour)


class Dashboard:
    """What the page talks to: config.yml, the catalogue, the poster code and (unless demo) the media server."""

    def __init__(self, cfg_path=None, demo=False, server=None):
        self.demo = demo
        self.lock = threading.Lock()          # one change to the files at a time
        self.render_lock = threading.Lock()   # drawing posters is heavy: one at a time
        self.fetch_lock = threading.Lock()    # one artwork download at a time
        self.loaded = (None, None)            # (file times, catalogue) so previews don't re-read the files each time
        self.ids, self.provisional, self.scene_files = {}, {}, {}
        self.rng = random.Random()
        self.run_state = {"running": False, "command": None, "lines": collections.deque(maxlen=500), "exit": None}
        self.work = tempfile.mkdtemp(prefix="cinesets-web-")
        if demo:
            self.cfg_path = None
            self.cfg = config.Config(config._merge(config.DEFAULTS, {}))
            self.cfg["base_dir"] = config.ROOT
            self.cfg["posters"] = posters.check_style({"artwork": "random"})
            self.cfg["collections"] = config.check_pick(None)
            self.cfg["custom_collections"] = os.path.join(self.work, "custom-collections.yml")  # gone when it stops
            self.state, self.engine, self.index = {}, None, None
            self.kind = "demo"
        else:
            self.cfg_path = config.config_path(cfg_path)
            self.cfg = config.load(self.cfg_path)
            self.engine = Engine(self.cfg, server or connect(self.cfg))
            self.index = self.engine.get_index()
            self.kind = self.cfg["server"]["type"]

    def close(self):
        shutil.rmtree(self.work, ignore_errors=True)

    # ------------------------------------------------------------ reading
    def settings_now(self):
        """The saved settings, read again when config.yml or the collections file has changed (including outside
        the dashboard)."""
        if self.demo:
            return self.cfg
        stamp = lambda p: os.stat(p).st_mtime_ns if os.path.exists(p) else None
        times = (stamp(self.cfg_path), stamp(self.cfg.path("collections_file")), stamp(self.cfg.path("custom_collections")))
        if times != self.loaded[0]:
            self.cfg = config.load(self.cfg_path)
            self.engine.cfg, self.engine.style = self.cfg, self.cfg["posters"]
            self.loaded = (times, {c["key"]: c for c in catalog.load(self.cfg)})
        return self.cfg

    def catalogue(self):
        if self.demo:
            stamp = os.stat(self.cfg["custom_collections"]).st_mtime_ns if os.path.exists(self.cfg["custom_collections"]) else 0
            if self.loaded[1] is None or self.loaded[0] != stamp:
                self.loaded = (stamp, {c["key"]: c for c in catalog.load(self.cfg)})
            return self.loaded[1]
        self.settings_now()
        return self.loaded[1]

    def coll(self, key):
        found = self.catalogue().get(str(key or ""))
        if not found:
            raise Problem(f"There is no collection called {key!r}", 404)
        return found

    def read_state(self):
        return self.state if self.demo else load_json(self.engine.state_file, {})

    def info(self):
        return {"version": __version__, "demo": self.demo, "server": self.kind,
                "config": os.path.basename(self.cfg_path) if self.cfg_path else None, "can_apply": not self.demo,
                "choices": {k: list(v) for k, v in posters.CHOICES.items()},
                "accents": {k: {"start": _hex(v[0]), "end": _hex(v[1])} for k, v in posters.ACCENTS.items()},
                "text_colours": list(posters.TEXT_COLOURS) + ["accent"], "gold": _hex(posters.LABEL_COLOUR),
                "defaults": posters.STYLE, "limits": {k: list(v) for k, v in posters.SIZES.items()},
                "custom_file": os.path.basename(self.cfg.path("custom_collections")),
                "logo_versions": self.logo_versions(),
                "limit_range": [1, config.LIMIT_MOST], "default_limit": self.cfg["defaults"]["limit"]}

    def logo_versions(self):
        """Each streaming service's logos: [{"key", "label", "downloaded"}], standard first."""
        from . import logos
        folder = self.logos_dir()
        have = lambda key, v: os.path.exists(os.path.join(folder, logos.file_name(key, v)))
        return {key: [{"key": "standard", "label": "Standard", "downloaded": have(key, "standard")}] +
                [{"key": v, "label": label, "downloaded": have(key, v)} for v, (label, _) in logos.VARIANTS.get(key, {}).items()]
                for key in logos.FILES}

    def settings(self):
        cfg = self.settings_now()
        version = config.file_version(self.cfg_path) if not self.demo else "demo"
        return {"posters": cfg["posters"], "collections": cfg["collections"], "limits": cfg["limits"], "version": version}

    def collections(self):
        cfg, state = self.settings_now(), self.read_state()
        out = []
        for group, members in catalog.sections(cfg, list(self.catalogue().values())):
            out.append({"key": group, "name": members[0]["section"], "collections": [{
                "key": c["key"], "name": c["name"], "title": c["title"], "subtitle": c.get("subtitle"), "label": c["label"],
                "kind": c["kind"], "accent": c["accent"], "streaming": bool(c.get("logo")), "service": c.get("logo"),
                "artwork": self.artwork_of(c, state), "lists": c.get("lists") or [], "added_lists": c.get("added_lists") or [],
                "fixed_titles": len(c["titles"]) if c.get("titles") else None, "custom": bool(c.get("custom")),
                "limit": c.get("limit"), "built_in_limit": c.get("built_in_limit"),
                "text": {"label": c["label"], "title": c["title"], "subtitle": c.get("subtitle")},
                "edited_text": c.get("edited_text") or ([] if not c.get("custom") else list(catalog.TEXT))}
                for c in members]})
        return {"sections": out}

    @staticmethod
    def artwork_of(coll, state):
        st = state.get(coll["key"]) or {}
        chosen = st.get("artwork") == "chosen" and not coll.get("logo")
        return {"mode": "chosen" if chosen else "auto", "item": st.get("backdrop_item") if chosen else None}

    # ------------------------------------------------------------ artwork
    def matched(self, coll):
        """The collection's titles in this library, in order (worked out once per session)."""
        if self.demo:
            return [f"scene-{name}" for name in scenes.SCENES]
        if coll["key"] not in self.ids:
            try:
                self.ids[coll["key"]] = self.engine.resolve(coll, self.index)[0]
            except (RuntimeError, ServerError, OSError) as e:
                raise Problem(f"Could not work out what is in {coll['name']}: {e}", 502)
        return self.ids[coll["key"]]

    def candidates(self, coll):
        if self.demo:
            ids = self.matched(coll)
            return [{"id": i, "name": i.split("-", 1)[1].capitalize(), "year": None} for i in ids]
        return [{"id": i, "name": self.index["items"][i]["n"], "year": self.index["items"][i]["y"]}
                for i in self.engine.candidates(self.matched(coll), self.index)]

    def artwork(self, q):
        coll = self.coll(q.get("key"))
        if coll.get("logo"):
            return {"streaming": True, "mode": "auto", "item": None, "candidates": []}
        return {"streaming": False, **self.artwork_of(coll, self.read_state()), "candidates": self.candidates(coll)}

    def known_item(self, item):
        item = str(item or "")
        if not SAFE_ID.match(item):
            raise Problem("That is not an item id")
        if self.demo:
            if item.split("-", 1)[-1] not in scenes.SCENES:
                raise Problem("That is not one of the demo pictures", 404)
        elif not self.index["items"].get(item, {}).get("b"):
            raise Problem("That title is not in your library, or has no artwork", 404)
        return item

    def pick_for(self, coll, state):
        """The artwork a preview shows: the dashboard's choice, then whatever the poster on the server uses now, then
        what the next run would pick (a random pick is held for this session so previews don't flicker)."""
        st = state.get(coll["key"]) or {}
        if st.get("artwork") == "chosen" and not coll.get("logo"):
            return st.get("backdrop_item")
        if self.demo:
            names = list(scenes.SCENES)
            return f"scene-{names[zlib.crc32(coll['key'].encode()) % len(names)]}"
        if st.get("backdrop_item") and self.index["items"].get(st["backdrop_item"], {}).get("b"):
            return st["backdrop_item"]
        if coll.get("backdrop_item"):
            return coll["backdrop_item"]
        if coll["key"] not in self.provisional:
            ids = self.matched(coll)
            top = self.engine.candidates(ids, self.index)
            items = self.index["items"]
            pick = next((i for i in ids if items[i]["n"] == coll.get("backdrop_title") and items[i]["b"]), None)
            if self.cfg["posters"]["artwork"] == "random" and not coll.get("logo"):
                pick = self.rng.choice(top) if top else None
            self.provisional[coll["key"]] = pick or (top[0] if top else None)
        return self.provisional[coll["key"]]

    def backdrop(self, item):
        """Artwork for a preview: what CineSets already downloaded, or a smaller copy kept only while the dashboard
        runs, so looking through candidates doesn't fill data/ with full-size artwork."""
        if not item:
            return None
        if self.demo:
            name = item.split("-", 1)[1]
            with self.fetch_lock:
                if name not in self.scene_files:
                    path = os.path.join(self.work, f"{name}.jpg")
                    scenes.make(name, 1600, 900).save(path, quality=90)
                    self.scene_files[name] = path
            return self.scene_files[name]
        kept = os.path.join(self.engine.backdrops, item + ".jpg")
        if os.path.exists(kept):
            return kept
        path = os.path.join(self.work, item + ".jpg")
        with self.fetch_lock:
            if not os.path.exists(path):
                try:
                    raw = self.engine.srv.backdrop_image(item, 1280, 85)
                    with Image.open(io.BytesIO(raw)) as im:
                        im.verify()
                except Exception as e:
                    print(f"   preview artwork {item}: {type(e).__name__}; using a plain background")
                    return None
                with open(path, "wb") as f:
                    f.write(raw)
        return path

    def thumb(self, q):
        item = self.known_item(q.get("id"))
        if self.demo:
            buf = io.BytesIO()
            scenes.make(item.split("-", 1)[1], 480, 270).save(buf, "JPEG", quality=80)
            return buf.getvalue()
        folder = os.path.join(self.engine.data, "thumbs")
        path = os.path.join(folder, item + ".jpg")
        if not os.path.exists(path):
            os.makedirs(folder, exist_ok=True)
            try:
                raw = self.engine.srv.backdrop_image(item, 480, 80)
                with Image.open(io.BytesIO(raw)) as im:
                    im.verify()
            except Exception as e:
                raise Problem(f"Could not fetch that picture from the server ({type(e).__name__})", 502)
            with open(path + ".part", "wb") as f:
                f.write(raw)
            os.replace(path + ".part", path)
        with open(path, "rb") as f:
            return f.read()

    def choose(self, body):
        coll = self.coll(body.get("key"))
        if coll.get("logo"):
            raise Problem("Streaming posters keep their own artwork")
        action = body.get("action")
        if action not in ("shuffle", "choose", "auto"):
            raise Problem("action must be shuffle, choose or auto")
        item = self.known_item(body.get("item")) if action == "choose" else None
        if action == "shuffle":
            now = self.pick_for(coll, self.read_state())
            pool = [c["id"] for c in self.candidates(coll)]
            pool = [i for i in pool if i != now] or pool
            if not pool:
                raise Problem("This collection has no titles with artwork to choose from")
            item = self.rng.choice(pool)
        with self.lock, self.changing_state() as state:
            st = state.setdefault(coll["key"], {})
            if action == "auto":
                if st.get("artwork") == "chosen":
                    st.pop("artwork")
                self.provisional.pop(coll["key"], None)
            else:
                st["backdrop_item"], st["artwork"] = item, "chosen"
        return self.artwork_of(coll, state)

    @contextlib.contextmanager
    def changing_state(self):
        if self.demo:
            yield self.state
            return
        try:
            with self.engine.lock(wait=False):
                state = load_json(self.engine.state_file, {})
                yield state
                save_json(self.engine.state_file, state)
        except Busy as e:
            raise Problem(str(e), 409)

    # ------------------------------------------------------------ previews and saving
    @staticmethod
    def checked(settings):
        """Settings from the page, checked like config.yml (a bad value comes back as a message, not a crash)."""
        try:
            return posters.check_style(settings if isinstance(settings, dict) else {})
        except SystemExit as e:
            raise Problem(str(e).replace("config.yml posters", "Poster settings"))

    @staticmethod
    def checked_text(text):
        """Label, title and subtitle from the page: the title up to 60 characters on at most two lines."""
        out = {}
        for field, most in (("label", 30), ("title", 60), ("subtitle", 40)):
            if field in text:
                value = str(text[field] if text[field] is not None else "").strip()
                if (field != "subtitle" and not value) or len(value.replace("\n", "")) > most or value.count("\n") > (
                        1 if field == "title" else 0):
                    raise Problem(f"The {field} needs to be {'1 to ' if field != 'subtitle' else 'up to '}{most} "
                                  f"characters{' on one or two lines' if field == 'title' else ''}")
                out[field] = value
        return out

    def set_text(self, body):
        """Change one collection's label, title or subtitle (saved straight away), or put back the usual words."""
        coll = self.coll(body.get("key"))
        text = {} if body.get("reset") else self.checked_text(body)
        if not text and not body.get("reset"):
            raise Problem("Give a label, title or subtitle")
        with self.lock:
            custom = catalog.read_custom(self.cfg)
            own = next((c for c in custom["collections"] if c.get("key") == coll["key"]), None)
            if coll.get("custom") and own and "group" in own:
                if body.get("reset"):
                    raise Problem("Your own collections have no usual words to go back to")
                for field, value in text.items():
                    if value or field != "subtitle":
                        own[field] = value
                    else:
                        own.pop(field, None)
            else:
                own = own or {"key": coll["key"]}
                for field in catalog.TEXT:
                    if body.get("reset"):
                        own.pop(field, None)
                    elif field in text:
                        own[field] = text[field]
                if own not in custom["collections"]:
                    custom["collections"].append(own)
                if set(own) == {"key"}:
                    custom["collections"].remove(own)
            self.write_custom(custom)
        fresh = self.coll(coll["key"])
        return {"key": coll["key"], "name": fresh["name"], "text": {f: fresh.get(f) for f in catalog.TEXT},
                "message": "Saved. If the collection is on your server already, it is renamed on the next apply."
                if fresh["name"] != coll["name"] else "Saved."}

    def preview(self, body):
        coll = self.coll(body.get("key"))
        if isinstance(body.get("text"), dict):  # words being typed, not saved yet
            draft = self.checked_text(body["text"])
            coll = {**coll, **{k: (v or None) if k == "subtitle" else v for k, v in draft.items()}}
        style = posters.style_for(self.checked(body.get("posters")), coll["key"], coll["group"])
        item = self.known_item(body["artwork"]) if body.get("artwork") else self.pick_for(coll, self.read_state())
        art = self.backdrop(item)
        with self.render_lock:
            if coll.get("logo"):
                img, layout = posters.logo_poster_image(coll["label"], coll["logo"], self.logos_dir(),
                                                        coll.get("subtitle") or "Popular", art, coll["title"], style)
            else:
                img, layout = posters.poster_image(coll["label"], coll["title"], coll.get("subtitle"), coll["accent"], art, style)
            buf = io.BytesIO()
            img.resize(PREVIEW, Image.LANCZOS).save(buf, "JPEG", quality=86)
        name = None
        if item and not self.demo:
            name = self.index["items"].get(item, {}).get("n")
        elif item:
            name = item.split("-", 1)[1].capitalize()
        return {"image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), "width": PREVIEW[0],
                "height": PREVIEW[1], "layout": layout, "draggable": not coll.get("logo"),
                "streaming": bool(coll.get("logo")), "artwork": {"item": item, "name": name}}

    def logos_dir(self):
        return os.path.join(self.work, "no-logos") if self.demo else self.engine.logos

    def save(self, body):
        style = self.checked(body.get("posters"))
        try:
            pick = config.check_pick(body.get("collections"))
            limits = config.check_limits(body.get("limits", self.settings_now()["limits"]))
        except SystemExit as e:
            raise Problem(str(e).replace("config.yml ", ""))
        if self.demo:
            self.cfg["posters"], self.cfg["collections"], self.cfg["limits"] = style, pick, limits
            self.loaded = (None, None)
            return {"saved": False, "message": "Demo mode: nothing is saved"}
        with self.lock:
            try:
                version = config.write_blocks(self.cfg_path, {"posters": config.posters_block(style),
                                                              "collections": config.collections_block(pick),
                                                              "limits": config.limits_block(limits)},
                                              version=body.get("version"), backup=True)
            except config.Changed as e:
                raise Problem(str(e), 409)
            self.settings_now()
        return {"saved": True, "version": version,
                "message": f"Saved to {os.path.basename(self.cfg_path)}. The posters change on the next apply."}

    # ------------------------------------------------------------ mdblist lists and your own collections
    def check_list(self, body):
        """What a list holds, before it becomes a collection: its size, films or shows, and how much is in the library."""
        slug = slug_of(body.get("list"))
        if not slug:
            raise Problem("That isn't an MDBList list. Paste its address, like https://mdblist.com/lists/user/list-name")
        try:
            rows = fetch_list(slug, self.work if self.demo else self.engine.data, patient=False)
        except RuntimeError as e:
            raise Problem(f"Couldn't read that list from MDBList ({str(e).split(': ', 1)[-1]}). Check it's public, "
                          "or try again in a minute.", 502)
        movies = [r for r in rows if r.get("mediatype") == "movie"]
        shows = [r for r in rows if r.get("mediatype") == "show"]
        kind = "show" if len(shows) > len(movies) else "movie"
        found = None
        if not self.demo:
            found = {k: sum(1 for r in group if Engine.match_row(r, k, self.index)) for k, group in (("movie", movies), ("show", shows))}
        return {"list": slug, "url": f"https://mdblist.com/lists/{slug}", "titles": len(rows), "movies": len(movies),
                "shows": len(shows), "type": kind, "in_library": found,
                "sample": [str(r.get("title")) for r in (shows if kind == "show" else movies)[:6]]}

    @staticmethod
    def _slugs(values):
        slugs = [slug_of(v) for v in (values if isinstance(values, list) else [values])]
        if not slugs or None in slugs or len(slugs) > 10:
            raise Problem("Give one to ten MDBList lists, like https://mdblist.com/lists/user/list-name")
        return list(dict.fromkeys(slugs))

    def write_custom(self, custom):
        """Save custom-collections.yml, but only if the catalogue still loads with it."""
        path = self.cfg.path("custom_collections")
        old = open(path).read() if os.path.exists(path) else None
        text = ("# Collections added in the CineSets dashboard, and lists added to the built-in ones. CineSets reads\n"
                "# this as well as collections.yml, and updates to CineSets never change it. The fields are the same\n"
                "# as in collections.yml; an entry with only key and add_lists adds lists to an existing collection.\n"
                + yaml.safe_dump({"sections": custom["sections"], "collections": custom["collections"]}, sort_keys=False,
                                 allow_unicode=True, width=110))
        config._replace(path, text)
        try:
            catalog.load(self.cfg)
        except SystemExit as e:
            if old is None:
                os.remove(path)
            else:
                config._replace(path, old)
            raise Problem(str(e))

    def add(self, body):
        """A new collection from mdblist lists, or more lists for an existing collection."""
        with self.lock:
            colls = self.catalogue()
            custom = catalog.read_custom(self.cfg)
            if body.get("key"):
                coll = colls.get(str(body["key"]))
                if not coll:
                    raise Problem(f"There is no collection called {body['key']!r}", 404)
                if coll.get("titles"):
                    raise Problem("That collection is a fixed list of titles, so lists can't be added to it")
                slugs = [s for s in self._slugs(body.get("lists")) if s not in coll["lists"]]
                if not slugs:
                    raise Problem("That collection already uses those lists")
                own = next((c for c in custom["collections"] if c.get("key") == coll["key"]), None)
                if own and "add_lists" in own:
                    own["add_lists"] += slugs
                elif own:
                    own["lists"] = list(own.get("lists") or []) + slugs
                else:
                    custom["collections"].append({"key": coll["key"], "add_lists": slugs})
                self.write_custom(custom)
                self.ids.pop(coll["key"], None)
                return {"key": coll["key"], "lists": coll["lists"] + slugs}
            new = body.get("collection") if isinstance(body.get("collection"), dict) else {}
            title = str(new.get("title") or "").strip()
            subtitle = str(new.get("subtitle") or "").strip() or None
            if not 1 <= len(title) <= 60 or title.count("\n") > 1 or (subtitle and len(subtitle) > 40):
                raise Problem("Give the collection a title of up to 60 characters (two lines at most) and a subtitle of "
                              "up to 40")
            if new.get("type") not in ("movie", "show"):
                raise Problem("type must be movie or show")
            try:
                accent = new.get("accent") or "blue"
                posters.check_accent(accent, "accent")
            except SystemExit as e:
                raise Problem(str(e))
            limit = new.get("limit", 150)
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
                raise Problem("limit must be a whole number from 1 to 500")
            words = lambda text: "-".join(re.findall(r"[a-z0-9]+", text.lower()))[:40].strip("-")
            group = str(new.get("section") or "")
            if group not in {c["group"] for c in colls.values()}:
                name = str(new.get("section_name") or "").strip()
                if not 1 <= len(name) <= 40 or not words(name):
                    raise Problem("Pick a section, or name a new one (up to 40 characters)")
                group = words(name)
                custom["sections"][group] = name
            stem = ("m-" if new["type"] == "movie" else "s-") + (words(f"{title} {subtitle or ''}") or "list")
            key, n = stem, 2
            while key in colls:
                key, n = f"{stem}-{n}", n + 1
            entry = {"key": key, "group": group, "type": new["type"], "title": title}
            if subtitle:
                entry["subtitle"] = subtitle
            entry.update({"accent": accent, "lists": self._slugs(new.get("lists")), "limit": limit})
            custom["collections"].append(entry)
            self.write_custom(custom)
            return {"key": key, "collection": entry}

    def remove_custom(self, body):
        """Take out a collection you added, or a list you added; the built-in ones stay as they are."""
        key, slug = str(body.get("key") or ""), body.get("list")
        with self.lock:
            custom = catalog.read_custom(self.cfg)
            own = next((c for c in custom["collections"] if c.get("key") == key), None)
            if not own:
                raise Problem("Only collections and lists you added can be removed here", 400)
            if slug is None and "add_lists" not in own:
                custom["collections"].remove(own)
                note = ("Removed. If CineSets already made it on your server, it stays there until you delete it "
                        "(./run.sh remove --unpicked).")
            else:
                field = "add_lists" if "add_lists" in own else "lists"
                if slug not in (own.get(field) or []):
                    raise Problem("That list was not added by you, so it stays", 400)
                own[field] = [x for x in own[field] if x != slug]
                if field == "lists" and not own[field]:
                    raise Problem("A collection needs at least one list; remove the collection instead")
                if field == "add_lists" and not own[field]:
                    custom["collections"].remove(own)
                note = "Removed the list."
            self.write_custom(custom)
            self.ids.pop(key, None)
        return {"removed": True, "message": note}

    # ------------------------------------------------------------ dry run and apply
    def run_command(self, command):
        return [sys.executable, "-m", "cinesets", command, "--config", self.cfg_path]

    def start_run(self, body):
        command = body.get("command")
        if command not in ("plan", "apply"):
            raise Problem("command must be plan or apply")
        if self.demo:
            raise Problem("Demo mode can't change a server")
        with self.lock:
            if self.run_state["running"]:
                raise Problem("A run is already going", 409)
            env = dict(os.environ, PYTHONUNBUFFERED="1")
            proc = subprocess.Popen(self.run_command(command), cwd=config.ROOT, env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
            self.run_state.update(running=True, command=command, exit=None)
            self.run_state["lines"].clear()
        threading.Thread(target=self._follow, args=(proc,), daemon=True).start()
        return {"started": True}

    def _follow(self, proc):
        for line in proc.stdout:
            self.run_state["lines"].append(line.rstrip("\n"))
        self.run_state.update(running=False, exit=proc.wait())

    def run_status(self, q=None):
        st = self.run_state
        return {"running": st["running"], "command": st["command"], "lines": list(st["lines"]), "exit": st["exit"]}


ROUTES = {
    ("GET", "/api/info"): lambda app, q, body: app.info(),
    ("GET", "/api/settings"): lambda app, q, body: app.settings(),
    ("GET", "/api/collections"): lambda app, q, body: app.collections(),
    ("GET", "/api/artwork"): lambda app, q, body: app.artwork(q),
    ("GET", "/api/thumb"): lambda app, q, body: ("image/jpeg", app.thumb(q)),
    ("GET", "/api/run"): lambda app, q, body: app.run_status(),
    ("POST", "/api/preview"): lambda app, q, body: app.preview(body),
    ("POST", "/api/artwork"): lambda app, q, body: app.choose(body),
    ("POST", "/api/save"): lambda app, q, body: app.save(body),
    ("POST", "/api/run"): lambda app, q, body: app.start_run(body),
    ("POST", "/api/lists/check"): lambda app, q, body: app.check_list(body),
    ("POST", "/api/lists/add"): lambda app, q, body: app.add(body),
    ("POST", "/api/lists/remove"): lambda app, q, body: app.remove_custom(body),
    ("POST", "/api/text"): lambda app, q, body: app.set_text(body),
}


OPEN = {("GET", "/api/session"), ("POST", "/api/login"), ("POST", "/api/logout")}
# a request carrying any of these was passed on by a proxy, Cloudflare or Tailscale, not sent straight from here
PROXIED = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "X-Real-IP", "Via",
           "Tailscale-User-Login", "CF-Connecting-IP", "True-Client-IP")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "CineSets"
    sys_version = ""
    timeout = 30  # a connection that sends nothing for this long is dropped

    def log_message(self, fmt, *args):  # quiet: the terminal shows only the link and problems
        pass

    def do_GET(self):
        self.guarded("GET")

    def do_POST(self):
        self.guarded("POST")

    def guarded(self, method):
        if not self.server.slots.acquire(blocking=False):
            return self.send(503, "application/json", json.dumps({"error": "The dashboard is busy. Try again."}).encode())
        try:
            self.route(method)
        finally:
            self.server.slots.release()

    def from_here(self):
        """A browser on this same machine, not something passed on by a proxy, and not a lookalike name."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0] if not (self.headers.get("Host") or "").startswith("[") \
            else (self.headers.get("Host") or "")[1:].split("]")[0]
        return host in LOCAL and not any(self.headers.get(h) for h in PROXIED)

    def https(self):
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def route(self, method):
        url = urlparse(self.path)
        self.cookie_out = None
        try:
            if self.server.local_only and not self.from_here():
                raise Problem("Sign-in is turned off, so this dashboard only answers a browser on the machine it runs on "
                              "(or an SSH tunnel to it).", 403)
            if method == "GET" and url.path in FILES:
                name, kind = FILES[url.path]
                with open(os.path.join(STATIC, name), "rb") as f:
                    return self.send(200, kind, f.read())
            if (method, url.path) not in ROUTES and (method, url.path) not in OPEN:
                raise Problem("Not found", 404)
            if self.headers.get("X-CineSets") != "1":  # other web sites can't add this header to a request
                raise Problem("Requests must come from the CineSets dashboard page", 403)
            body = self.read_json() if method == "POST" else {}
            if (method, url.path) in OPEN:
                return self.send_json(self.session(url.path, body))
            if not self.signed_in():
                raise Problem("Sign in first", 401)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            result = ROUTES[(method, url.path)](self.server.app, q, body)
            if isinstance(result, tuple):
                return self.send(200, result[0], result[1])
            self.send_json(result)
        except Problem as e:
            self.send(e.status, "application/json", json.dumps({"error": str(e)}).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            self.send(500, "application/json", json.dumps({"error": "Something went wrong: see the terminal"}).encode())

    def signed_in(self):
        if self.server.gate is None:  # demo mode
            return True
        value = None
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, v = part.strip().partition("=")
            if name == COOKIE:
                value = v
        return self.server.gate.valid(value)

    def session(self, path, body):
        gate = self.server.gate
        if path == "/api/login" and gate:
            if self.server.public and not self.https():
                raise Problem("This dashboard only takes sign-ins over HTTPS. Open it at its https:// address.", 403)
            gate.login(body.get("key"), self.client_address[0])
            self.cookie_out = (gate.cookie(), SESSION_DAYS * 86400)
            return {"signed_in": True}
        if path == "/api/logout" and gate:
            self.cookie_out = ("", 0)
            return {"signed_in": False}
        return {"signed_in": self.signed_in(), "demo": self.server.app.demo, "sign_in": gate is not None,
                "password": bool(gate and gate.current().get("password"))}

    def read_json(self):
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise Problem("Bad request")
        if size > MAX_BODY:
            raise Problem("That request is too big", 413)
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
        except ValueError:
            raise Problem("That request is not JSON")
        if not isinstance(body, dict):
            raise Problem("That request is not a JSON object")
        return body

    def send_json(self, result):
        self.send(200, "application/json", json.dumps(result).encode())

    def send(self, status, kind, data):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if self.server.public and self.https():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
        if getattr(self, "cookie_out", None):
            value, age = self.cookie_out
            # no Path: the browser scopes the cookie to the API folder, under whatever path a proxy serves the page
            secure = "; Secure" if self.https() else ""
            self.send_header("Set-Cookie", f"{COOKIE}={value}; Max-Age={age}; HttpOnly; SameSite=Strict{secure}")
        self.end_headers()
        self.wfile.write(data)


def make_server(app, host="127.0.0.1", port=8095, sign_in=True, public=False):
    """sign_in=False is allowed only on this machine's own address, and then only a browser on this machine is
    answered, or an SSH tunnel to it (which looks the same, and needs a login to the machine); nothing passed on by a
    proxy or Tailscale. public=True accepts sign-ins only over HTTPS."""
    if not sign_in and not app.demo and host not in LOCAL:
        raise SystemExit("Sign-in can only be turned off when the dashboard listens on this machine only "
                         "(host 127.0.0.1). For other computers, keep sign-in on.")
    if public and not sign_in:
        raise SystemExit("A public dashboard needs sign-in: set web: sign_in: true.")
    httpd = http.server.ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.app, httpd.slots, httpd.public = app, threading.BoundedSemaphore(BUSY_LIMIT), public
    httpd.gate = Gate(access_file(app.cfg)) if sign_in and not app.demo else None
    httpd.local_only = not sign_in and not app.demo
    return httpd


def link(cfg, host="127.0.0.1", port=8095):
    """The sign-in link. The key is in the part after #, which browsers never send to a server or proxy."""
    return f"http://{_address(host)}:{port}/#key={read_access(access_file(cfg))['key']}"


def _address(host):
    """The address to show in the link."""
    if host not in ("0.0.0.0", ""):
        return host
    if os.path.exists("/.dockerenv"):
        return "localhost"
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))  # picks the outgoing interface; nothing is sent
        return s.getsockname()[0]
    return "localhost"


def serve(cfg_path=None, host=None, port=None, demo=False, sign_in=None, public=None):
    """Run the dashboard. Anything not given comes from `web` in config.yml."""
    web = config.DEFAULTS["web"] if demo else config.load(cfg_path)["web"]
    host, port = host or web["host"], port or web["port"]
    sign_in = web["sign_in"] if sign_in is None else sign_in
    public = web["public"] if public is None else public
    print("Demo mode: made-up artwork, no server, no sign-in, nothing saved." if demo else
          "Reading your settings and library...")
    app = Dashboard(cfg_path, demo)
    try:
        httpd = make_server(app, host, port, sign_in, public)
    except OSError as e:
        app.close()
        raise SystemExit(f"Could not start the dashboard on {host}:{port} ({e.strerror or e}). Try another --port.")
    except SystemExit:
        app.close()
        raise
    address = f"http://{_address(host)}:{port}/"
    if demo or not sign_in:
        print(f"\nCineSets dashboard{' (demo)' if demo else ''}: {address}\n")
        if not sign_in and not demo:
            print("Sign-in is off: it answers only this machine (an SSH tunnel from your own computer counts), never a "
                  "proxy or Tailscale.")
    elif sys.stdout.isatty():
        print(f"\nCineSets dashboard: {link(app.cfg, host, port)}\n")
        print("That link signs you in. Keep it private: anyone with it can change your CineSets settings.")
    else:  # a service or container log, which people paste into bug reports: no key in it
        print(f"\nCineSets dashboard: {address}\nTo get the sign-in link, run: cinesets web --link "
              "(on Docker: docker compose run --rm cinesets web --link)\n")
    if public:
        print("Public mode: sign-ins are taken only over HTTPS, through your reverse proxy.")
    elif host not in LOCAL:
        print("It is open to other computers. Use it over Tailscale or a reverse proxy with HTTPS, not straight from "
              "the internet (see docs/dashboard.md).")
    print("Press Ctrl+C to stop it.")
    sys.stdout.flush()

    def stop(signum, frame):
        raise KeyboardInterrupt  # docker stop and systemctl stop: tidy up as Ctrl+C does
    signal.signal(signal.SIGTERM, stop)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        httpd.server_close()
        app.close()


def manage(cfg_path, what, host=None, port=None):
    """cinesets web --link | --new-key | --set-password"""
    cfg = config.load(cfg_path)
    host, port = host or cfg["web"]["host"], port or cfg["web"]["port"]
    path = access_file(cfg)
    if what == "new-key":
        new_key(path)
        print("Made a new access key; everyone is signed out. The new sign-in link:")
    elif what == "set-password":
        if not sys.stdin.isatty():
            raise SystemExit("Setting a password asks for it, so run this in a terminal.")
        first = getpass.getpass(f"New dashboard password (at least {PASSWORD_MIN} characters; leave it empty to remove "
                                "the password; typing is hidden): ")
        if getpass.getpass("Once more: ") != first:
            raise SystemExit("Those didn't match; nothing changed.")
        set_password(path, first)
        print("Password set. Sign in with it, or with the link below." if first else
              "Password removed. Sign in with the link below.")
    print(link(cfg, host, port))
    if host in LOCAL:
        print("If you reach the dashboard another way (Tailscale, a proxy, another computer), use that address with "
              "the same #key=... on the end.")
