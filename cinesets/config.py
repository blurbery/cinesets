# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Settings: config.yml plus environment overrides (CINESETS_URL, CINESETS_API_KEY, CINESETS_SERVER)."""
import contextlib
import errno
import hashlib
import json
import os
import re
import tempfile

import yaml

from .servers import SERVERS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "server": {"type": next(iter(SERVERS)), "url": "http://127.0.0.1:8096", "api_key": ""},  # the first server listed
    "libraries": [],
    "collections_file": "collections.yml",
    # collections added in the dashboard, and lists added to existing ones; read as well as collections_file
    "custom_collections": "custom-collections.yml",
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
    # which collections to make: whole sections (the `group` in collections.yml), then single collections by key
    "collections": {"sections": "all", "include": [], "exclude": []},
    # how many titles collections hold: `most` caps every list-based collection; a section's or a collection's own
    # number replaces its built-in size (up or down). Franchises always keep every title in their list.
    "limits": {"most": None, "sections": {}, "collections": {}},
    # the dashboard (cinesets web): see web.py and docs/dashboard.md
    "web": {"host": "127.0.0.1", "port": 8095, "sign_in": True, "public": False, "hosts": []},
}


def _merge(base, extra):
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


OTHER_KEYS = {"schedule"}  # settings that are read but have no default (schedule: the Docker scheduler's jobs)
_warned = set()


def check_keys(raw, where="config.yml"):
    """Warn (never stop) about settings CineSets doesn't know, at the top level and inside each block, so a typo like
    `colections:` doesn't quietly fall back to the default. The known names come from DEFAULTS; `posters` checks its
    own, and blocks whose entries are names of your choosing (limits: sections, say) aren't looked inside."""
    import difflib
    found = []
    for key in raw:
        if key not in DEFAULTS and key not in OTHER_KEYS:
            found.append((str(key), sorted(set(DEFAULTS) | OTHER_KEYS)))
        elif isinstance(DEFAULTS.get(key), dict) and DEFAULTS[key] and isinstance(raw[key], dict):
            found += [(f"{key}.{k}", [f"{key}.{n}" for n in DEFAULTS[key]]) for k in raw[key] if k not in DEFAULTS[key]]
    for name, known in found:
        if (where, name) in _warned:
            continue
        _warned.add((where, name))
        close = difflib.get_close_matches(name, known, n=1)
        print(f"Note: {where}: CineSets doesn't know the setting `{name}`, so it is ignored"
              + (f" (did you mean `{close[0]}`?)" if close else ""))


def read_yaml(f, where="config.yml"):
    """config.yml's settings, with a clear message when it isn't valid YAML or isn't a list of settings."""
    try:
        raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise SystemExit(f"{where} isn't valid YAML, so it can't be read. Fix the line it points to:\n{e}")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SystemExit(f"{where} should hold settings like `server:` and `libraries:` (see config.example.yml), "
                         f"not a {type(raw).__name__}")
    check_keys(raw, where)
    return raw


class Config(dict):
    def path(self, key):
        p = self[key]
        return p if os.path.isabs(p) else os.path.join(self["base_dir"], p)


def load(path=None):
    path = config_path(path)
    raw = {}
    if os.path.exists(path):
        with open(path) as f:
            raw = read_yaml(f, os.path.basename(path))
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
    cfg["collections"] = check_pick(cfg["collections"])
    cfg["web"] = check_web(cfg["web"])
    cfg["limits"] = check_limits(cfg["limits"])
    return cfg


LIMIT_MOST = 1000


def check_limits(raw):
    """`limits` in config.yml: {most: n or null, sections: {group: n}, collections: {key: n}}."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit("config.yml: limits must have most, sections and collections (see config.example.yml)")
    count = lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= LIMIT_MOST
    most = raw.get("most")
    if most is not None and not count(most):
        raise SystemExit(f"config.yml limits: most must be a number from 1 to {LIMIT_MOST}, or null, not {most!r}")
    out = {"most": most}
    for field in ("sections", "collections"):
        entries = raw.get(field) or {}
        if not isinstance(entries, dict) or not all(count(v) for v in entries.values()):
            raise SystemExit(f"config.yml limits: {field} must list keys with a number from 1 to {LIMIT_MOST} each")
        out[field] = {str(k): v for k, v in entries.items()}
    return out


def limits_block(limits):
    """The `limits` block for config.yml."""
    return yaml.safe_dump({"limits": limits}, sort_keys=False, default_flow_style=None, width=110)


def check_web(raw):
    """`web` in config.yml: where the dashboard listens and how people sign in."""
    if not isinstance(raw, dict):
        raise SystemExit("config.yml: web must have host, port, sign_in and public (see config.example.yml)")
    web = {**DEFAULTS["web"], **raw}
    if not isinstance(web["host"], str) or not web["host"]:
        raise SystemExit(f"config.yml web: host must be an address like 127.0.0.1, not {web['host']!r}")
    if not isinstance(web["port"], int) or isinstance(web["port"], bool) or not 1 <= web["port"] <= 65535:
        raise SystemExit(f"config.yml web: port must be a number from 1 to 65535, not {web['port']!r}")
    for key in ("sign_in", "public"):
        if not isinstance(web[key], bool):
            raise SystemExit(f"config.yml web: {key} must be true or false, not {web[key]!r}")
    return web


def _names(value, what):
    """A list of names from YAML: a list, one name, or a comma-separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        raise SystemExit(f"config.yml collections: {what} must be a list, not {value!r}")
    return [str(v).strip() for v in value if str(v).strip()]


def check_pick(raw):
    """`collections` in config.yml: `all`, or {sections: all | [names], include: [keys], exclude: [keys]}."""
    if raw is None or raw == "all":
        raw = {}
    if not isinstance(raw, dict):
        raise SystemExit("config.yml: collections must be `all` or have sections, include and exclude "
                         "(see config.example.yml)")
    sections = raw.get("sections", "all")
    return {"sections": "all" if sections in ("all", None) else _names(sections, "sections"),
            "include": _names(raw.get("include"), "include"), "exclude": _names(raw.get("exclude"), "exclude")}


LIBRARY_TYPES = {"movies": "movie", "movie": "movie", "shows": "show", "show": "show", "tv": "show", "tvshows": "show", "series": "show"}


def check_type(kind):
    known = list(SERVERS)
    if kind not in known:
        raise SystemExit(f"server.type must be {', '.join(known[:-1])} or {known[-1]}, not {kind!r}")


def config_path(path=None):
    return path or os.environ.get("CINESETS_CONFIG") or os.path.join(ROOT, "config.yml")


class Changed(RuntimeError):
    """config.yml changed since it was read (another dashboard tab, another person or a hand edit)."""


def file_version(path):
    """A short fingerprint of config.yml as it is now, to notice changes made elsewhere."""
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:16]


def _replace(path, text):
    """Write the whole file atomically, readable by its owner only. A config.yml mounted on its own into a container
    can't be replaced, so that one is rewritten in place."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".tmp-", suffix=".yml")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        try:
            os.replace(tmp, path)
        except OSError as e:
            if e.errno not in (errno.EBUSY, errno.EXDEV, errno.EPERM):
                raise
            with open(path, "r+", encoding="utf-8", newline="") as f:
                f.write(text)
                f.truncate()
            os.chmod(path, 0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp)


def write_blocks(path, blocks, version=None, backup=False):
    """Put top-level blocks ({"posters": text, ...}, each `key:` and its indented lines) into config.yml in place of
    the old ones, keeping every other line and comment, or add them at the end. With `version`, stop with Changed if
    the file is no longer the one that was read; with `backup`, keep the old file as config.yml.bak. Returns the new
    version. The file holds the API key, so it stays readable by its owner only."""
    with open(path, "rb") as f:
        raw = f.read()
    old = text = raw.decode("utf-8")
    if version is not None and hashlib.sha1(raw).hexdigest()[:16] != version:
        raise Changed(f"{os.path.basename(path)} has changed since it was loaded (in another tab, by someone else or "
                      "by hand). Reload to see the changes, then make yours again.")
    for key, block in blocks.items():
        m = re.search(rf"^{re.escape(key)}:.*?(?=^\S|\Z)", text, flags=re.M | re.S)
        if m:
            gap = m.group(0)[len(m.group(0).rstrip("\n")) + 1:]  # keep the blank lines that followed the old block
            text = text[:m.start()] + block + gap + text[m.end():]
        else:
            text = text.rstrip("\n") + "\n\n" + block
    if backup:
        _replace(path + ".bak", old)
    _replace(path, text)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def write_block(path, key, block):
    """write_blocks for one block."""
    return write_blocks(path, {key: block})


def collections_block(pick):
    """The `collections` block for config.yml from checked settings (check_pick): sections in one line, the keys
    one per line."""
    plain = lambda g: re.fullmatch(r"[a-z][a-z0-9_-]*", g) and g not in ("yes", "no", "on", "off", "true", "false", "null")
    name = lambda g: g if plain(g) else json.dumps(g)  # quoted when YAML would read it as something else
    sections = pick["sections"]
    lines = ["collections:", "  sections: " + ("all" if sections == "all" else "[" + ", ".join(map(name, sections)) + "]")]
    for field in ("include", "exclude"):
        items = pick[field]
        lines.append(f"  {field}:" + ("".join(f"\n    - {name(k)}" for k in items) if items else " []"))
    return "\n".join(lines) + "\n"


def posters_block(style):
    """The `posters` block for config.yml: every main setting, plus positions, size and overrides once they are set."""
    from . import posters
    out = {k: v for k, v in style.items() if k in posters.STYLE and (k not in posters.LAYOUT or v != posters.STYLE[k])}
    for layer in posters.LAYERS:
        if style.get(layer):
            out[layer] = style[layer]
    return yaml.safe_dump({"posters": out}, sort_keys=False, default_flow_style=None, allow_unicode=True, width=110)
