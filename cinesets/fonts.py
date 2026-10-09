# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Download the Japanese, Chinese and Korean font onto this server, the first time a poster needs it.

The font is Noto Sans CJK, under the SIL Open Font License. Its two weights come to about 38 MB, too big to ship
with CineSets for the few servers that need them, so each server downloads its own copy from the Noto project on
GitHub, once, into data/fonts: when a poster first has Japanese, Chinese or Korean text, or ahead of time with
`cinesets fonts`. Both files are pinned to one commit and checked against their SHA-256 before they're used.
"""
import hashlib
import os
import re
import threading
import time

import requests

from . import __version__

COMMIT = "f8d157532fbfaeda587e826d4cd5b21a49186f7c"  # in github.com/notofonts/noto-cjk
SOURCE = f"https://raw.githubusercontent.com/notofonts/noto-cjk/{COMMIT}/Sans/OTC/"
# Bold draws the label and title (where Poppins uses SemiBold), Regular the subtitle. Each file holds a face for each
# place that writes these letters (see posters.CJK). file -> (SHA-256, size in bytes)
BOLD, REGULAR = "NotoSansCJK-Bold.ttc", "NotoSansCJK-Regular.ttc"
FILES = {
    BOLD: ("faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb", 20050760),
    REGULAR: ("b76b0433203017ca80401b2ee0dd69350349871c4b19d504c34dbdd80541690a", 19484784),
}
NAME = "the Japanese, Chinese and Korean font"
SIZE = "about 38 MB"
MOST_SECONDS = 900  # a download (both files) still going after this long is given up, so a run never waits for ever
RETRY_AFTER = 3600  # the dashboard tries a download that failed again after this long, not on every preview

# the letters it's for: kana (Japanese), hangul (Korean) and Han characters (all three). Punctuation and full-width
# forms alone don't ask for it, but once a poster has these letters the font draws all of its text
KANA = re.compile("[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
HANGUL = re.compile("[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff\uffa0-\uffdc]")
HAN = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003134f]")


class FontError(RuntimeError):
    """The font couldn't be downloaded, or what came wasn't the file it should be."""


def wanted(*texts):
    """Whether any of the texts has Japanese, Chinese or Korean letters, which only this font draws."""
    return any(t and (KANA.search(t) or HANGUL.search(t) or HAN.search(t)) for t in texts)


# the folder this process draws the font from (data/fonts), set by the engine. None until then, so nothing else (a
# test, the dashboard's demo) picks up a font downloaded somewhere
_where = {"folder": None}
_lock = threading.Lock()  # one download at a time in this process
_failed = {}  # folder -> (when its download last failed, why)
_busy = set()  # folders the dashboard is downloading into in the background
_busy_lock = threading.Lock()


def use(folder):
    """Draw with the font in this folder once it's there."""
    _where["folder"] = folder


def path(name):
    """Where one of FILES is, in the folder in use."""
    return os.path.join(_where["folder"] or "", name)


def _have(folder, name):
    """Whether one of FILES is downloaded. It was checked before it was swapped in, so its size is enough to tell."""
    try:
        return os.path.getsize(os.path.join(folder, name)) == FILES[name][1]
    except OSError:
        return False


def ready(folder=None):
    """Whether both files are downloaded, in `folder` or the folder in use."""
    folder = folder or _where["folder"]
    return bool(folder) and all(_have(folder, name) for name in FILES)


def _fetch(session, name, target, deadline):
    """One file, to a .part file beside where it goes, hashed as it comes. It's swapped in only when it's whole and its
    SHA-256 matches, so a download that's cut off, or isn't the file it should be, never leaves a broken font."""
    sha, size = FILES[name]
    part = f"{target}.{os.getpid()}-{threading.get_ident()}.part"
    digest, got = hashlib.sha256(), 0
    try:
        with session.get(SOURCE + name, stream=True, timeout=(15, 60)) as r:
            if not r.ok:
                raise FontError(f"GitHub answered {r.status_code} for {name}")
            with open(part, "wb") as f:
                for piece in r.iter_content(1 << 20):
                    got += len(piece)
                    if got > size:
                        raise FontError(f"{name} is bigger than it should be")
                    if time.monotonic() > deadline:
                        raise FontError(f"it took more than {MOST_SECONDS // 60} minutes")
                    digest.update(piece)
                    f.write(piece)
        if digest.hexdigest() != sha:
            raise FontError(f"{name} isn't the file it should be (its SHA-256 doesn't match)")
        os.replace(part, target)
    except requests.RequestException as e:
        raise FontError(f"{name}: {type(e).__name__}")
    finally:
        if os.path.exists(part):
            os.remove(part)


def download(folder, force=False, say=print):
    """Download the font's files into `folder`: those not there yet, or both with force. Raises FontError saying what
    went wrong; a file downloaded before it is kept."""
    want = [name for name in FILES if force or not _have(folder, name)]
    if not want:
        say(f"Noto Sans CJK, {NAME}, is already downloaded.")
        return
    os.makedirs(folder, exist_ok=True)
    say(f"Downloading {NAME} (Noto Sans CJK, {SIZE}, just this once) into {folder}")
    s = requests.Session()
    # CineSets names itself, its version and where to find it, as it does for the logos
    s.headers["User-Agent"] = (f"CineSets/{__version__} (+https://github.com/blurbery/cinesets; self-hosted media server "
                               f"posters) python-requests/{requests.__version__}")
    deadline = time.monotonic() + MOST_SECONDS
    for name in want:
        _fetch(s, name, os.path.join(folder, name), deadline)
        say(f"  {name}: {FILES[name][1] // (1 << 20)} MB")


def ensure(folder, say=print, again=False):
    """Whether the font is in `folder`, downloading it first when it isn't: the first time a poster needs it. A download
    that fails says so, and the text is drawn as it was without the font. One that failed in the last hour isn't tried
    again unless `again` (a run, which tries once each time it needs the font)."""
    use(folder)
    if ready(folder):
        return True
    with _lock:
        if ready(folder):  # another thread downloaded it while this one waited
            return True
        if not again and time.time() - _failed.get(folder, (-RETRY_AFTER, None))[0] < RETRY_AFTER:
            return False
        try:
            download(folder, say=say)
        except (FontError, OSError) as e:
            _failed[folder] = (time.time(), str(e))
            say(f"!! Couldn't download {NAME}: {e}. Japanese, Chinese and Korean letters are drawn as boxes until it "
                "can be: later runs try again, or run `cinesets fonts`")
            return False
        return True


def state(folder):
    """The font, for the dashboard: ("ready", "downloading", "failed" or "missing", and why it failed or None)."""
    if ready(folder):
        return "ready", None
    if folder in _busy:
        return "downloading", None
    when, why = _failed.get(folder, (-RETRY_AFTER, None))
    if time.time() - when < RETRY_AFTER:
        return "failed", f"Couldn't download {NAME} ({why}), so its letters are drawn as boxes for now. Later runs " \
                         "try again, or run `cinesets fonts`."
    return "missing", None


def start(folder):
    """For the dashboard: the font's state, once its download is started in the background if it's needed and isn't
    there (or failed over an hour ago), so a preview never waits for it."""
    use(folder)
    with _busy_lock:
        now = state(folder)[0]
        if now != "missing":
            return now
        _busy.add(folder)

    def fetch():
        try:
            ensure(folder)
        finally:
            _busy.discard(folder)
    threading.Thread(target=fetch, daemon=True).start()
    return "downloading"
