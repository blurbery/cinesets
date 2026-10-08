# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
import contextlib
import json
import os
import shutil
import tempfile

STATE = "state.json"  # the record of which collections CineSets owns: kept with a .bak copy, and never ignored


def load_json(path, default):
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return default
    except ValueError:
        if os.path.basename(path) == STATE:
            raise SystemExit(f"{path} is damaged. It records which collections CineSets owns; {_restore(path)}")
        print(f"   ignoring a damaged cache file: {path}")
        return default
    if os.path.basename(path) == STATE and not isinstance(data, dict):
        raise SystemExit(f"{path} doesn't hold CineSets' record of its collections (it holds "
                         f"{type(data).__name__ if data is not None else 'null'}); {_restore(path)}")
    return data


def _restore(path):
    """What to do about a damaged state.json."""
    bak = path + ".bak"
    if os.path.exists(bak):
        return (f"replace it with {os.path.basename(bak)} beside it (the copy from before its last change), or delete "
                "it and use `cinesets adopt` to take the collections back.")
    return "restore it from a backup, or delete it and use `cinesets adopt` to take the collections back."


def save_json(path, obj):
    """Write the file atomically and make sure it is on disk. state.json keeps the version before as state.json.bak."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
            f.flush()
            os.fsync(f.fileno())
        if os.path.basename(path) == STATE and os.path.exists(path):
            _keep_copy(path, path + ".bak")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp)
        raise


def _keep_copy(path, bak):
    """Copy the file as it is now to `bak`, atomically. The file itself never moves, so a crash part way through still
    leaves it where it was."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".bak")
    try:
        with os.fdopen(fd, "wb") as out, open(path, "rb") as f:
            shutil.copyfileobj(f, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, bak)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp)
        raise
