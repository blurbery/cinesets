# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Settings: config.yml plus environment overrides (CINESETS_URL, CINESETS_API_KEY, CINESETS_SERVER)."""
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "server": {"type": "emby", "url": "http://127.0.0.1:8096", "api_key": ""},
    "libraries": [],
    "collections_file": "collections.yml",
    "data_dir": "data",
    "labels": {"movie": "Movies", "show": "TV Shows"},
    "defaults": {"limit": 150, "min_items": 8},
    # Collections page order, top to bottom. Entries with `pin` always sit above every group.
    "order": [["charts", "genres"], "streaming", "bestof", "kids", "seasonal", "regional", "universes"],
    "alphabetical_groups": ["universes"],
    "write_pause": 1.0,
    "slow_write_limit": 30,
    # poster colours, text and artwork: see posters.STYLE
    "posters": {},
}


def _merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Config(dict):
    def path(self, key):
        p = self[key]
        return p if os.path.isabs(p) else os.path.join(self["base_dir"], p)


def load(path=None):
    path = config_path(path)
    raw = {}
    if os.path.exists(path):
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    cfg = Config(_merge(DEFAULTS, raw))
    cfg["base_dir"] = os.path.dirname(os.path.abspath(path))
    srv = cfg["server"]
    # an empty environment variable must not wipe out a value from config.yml
    srv["url"] = (os.environ.get("CINESETS_URL") or srv["url"]).rstrip("/")
    srv["api_key"] = os.environ.get("CINESETS_API_KEY") or srv["api_key"]
    srv["type"] = (os.environ.get("CINESETS_SERVER") or srv["type"]).lower()
    check_type(srv["type"])
    if not srv["url"].startswith(("http://", "https://")):
        raise SystemExit(f"server.url must start with http:// or https:// (got {srv['url']!r})")
    cfg["libraries"] = cfg["libraries"] or []
    for lib in cfg["libraries"]:
        t = str(lib.get("type", "")).lower()
        if t not in LIBRARY_TYPES:
            raise SystemExit(f"library {lib.get('name')!r}: type must be movie or show, not {lib.get('type')!r}")
        lib["type"] = LIBRARY_TYPES[t]
    from . import posters  # here, not at the top: posters reads ROOT from this module
    if not isinstance(cfg["posters"], dict):
        raise SystemExit("config.yml: posters must be a list of settings (see config.example.yml)")
    cfg["posters"] = posters.check_style(cfg["posters"])
    return cfg


LIBRARY_TYPES = {"movies": "movie", "movie": "movie", "shows": "show", "show": "show", "tv": "show", "tvshows": "show", "series": "show"}


def check_type(kind):
    if kind == "silo":
        raise SystemExit("Silo support is coming soon. For now server.type must be emby or jellyfin.")
    if kind not in ("emby", "jellyfin"):
        raise SystemExit(f"server.type must be emby or jellyfin, not {kind!r}")


def config_path(path=None):
    return path or os.environ.get("CINESETS_CONFIG") or os.path.join(ROOT, "config.yml")
