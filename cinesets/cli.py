# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Command line:

  cinesets index                          refresh the library index
  cinesets plan    [--only KEYS] [--group GROUPS]   dry run: what each collection would contain
  cinesets posters [--only KEYS] [--group GROUPS]   build posters and contact sheets, no server writes
  cinesets apply   [--only KEYS] [--group GROUPS]   create or update collections
  cinesets logos   [--force]              download streaming service logos from Wikimedia Commons
  cinesets list                           show every collection key, group and name
  cinesets schedule                       run forever on the schedule in config.yml (for Docker)
  cinesets setup                          ask for server details and write config.yml
  cinesets adopt   --only KEYS | --all    take over existing collections with CineSets' names (after a reinstall)
  cinesets remove  --only KEYS | --all    delete collections CineSets created (asks first; --yes to skip)
"""
import argparse
import getpass
import json
import os
import sys
import time
import traceback

import requests

from . import __version__, catalog, config, logos
from .engine import Engine
from .server import MediaServer


def select(colls, only=None, group=None):
    """Pick collections by key and/or group. Unknown names are reported and skipped (for example the
    Halloween entries after the season); it is an error only if nothing at all matches."""
    picked = colls
    if only:
        want = {k.strip() for k in only.split(",") if k.strip()}
        unknown = want - {c["key"] for c in colls}
        if unknown:
            print(f"Note: not in the collections file, skipped: {', '.join(sorted(unknown))}")
        picked = [c for c in picked if c["key"] in want]
    if group:
        groups = {g.strip() for g in group.split(",") if g.strip()}
        unknown = groups - {c["group"] for c in colls}
        if unknown:
            print(f"Note: no collections in group(s) {', '.join(sorted(unknown))}, skipped")
        picked = [c for c in picked if c["group"] in groups]
    if (only or group) and not picked:
        raise SystemExit("No collections match. See: cinesets list")
    return picked


DEFAULT_SCHEDULE = [
    {"every_hours": 6, "only": "m-trending,s-trending"},
    {"every_hours": 24, "group": "seasonal,charts"},
    {"every_hours": 168, "all": True},
]


def schedule(cfg, engine):
    jobs = cfg.get("schedule") or DEFAULT_SCHEDULE
    for job in jobs:
        if not isinstance(job, dict) or float(job.get("every_hours", 0)) <= 0:
            raise SystemExit(f"schedule: every job needs every_hours greater than 0: {job}")
    last = {i: 0.0 for i in range(len(jobs))}
    print(f"CineSets {__version__} scheduler: {len(jobs)} jobs")
    while True:
        for i, job in enumerate(jobs):
            if time.time() - last[i] >= float(job["every_hours"]) * 3600:
                print(f"--- {time.strftime('%Y-%m-%d %H:%M')} job {i + 1}")
                try:
                    colls = catalog.load(cfg)  # re-read each time, so edits apply without a restart
                    picked = colls if job.get("all") else select(colls, job.get("only"), job.get("group"))
                    engine.run("apply", picked, cfg["defaults"]["min_items"])
                except SystemExit as e:  # for example a renamed library: report it and try again next time
                    print(f"!! job {i + 1} stopped: {e}")
                except Exception:
                    traceback.print_exc()
                last[i] = time.time()
        sys.stdout.flush()
        time.sleep(300)


def setup(path):
    """Interactive first-run setup: test the server, detect libraries, write config.yml."""
    path = config.config_path(path)
    if os.path.exists(path) and input(f"{path} exists. Overwrite it? [y/N] ").strip().lower() != "y":
        return
    kind = input("Server type, emby or jellyfin [emby]: ").strip().lower() or "emby"
    config.check_type(kind)
    url = input("Server address [http://127.0.0.1:8096]: ").strip() or "http://127.0.0.1:8096"
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    url = url.split("/web/")[0].split("/web#")[0].rstrip("/")  # a pasted browser address works too
    for tail in ("/web", "/emby"):
        if url.endswith(tail):
            url = url[: -len(tail)]
    key = getpass.getpass("API key (Dashboard > API Keys, typing is hidden): ").strip()
    cfg = config.Config(config._merge(config.DEFAULTS, {"server": {"type": kind, "url": url, "api_key": key}}))
    cfg["base_dir"] = os.path.dirname(os.path.abspath(path))
    try:
        folders = MediaServer(cfg).get("/Library/VirtualFolders")
    except requests.RequestException as e:
        raise SystemExit(f"Could not reach the server at {url}: {type(e).__name__}. Check the address.")
    except RuntimeError as e:
        status = getattr(e, "status", None)
        if status in (401, 403):
            raise SystemExit("The server rejected the API key. Check it under Dashboard > API Keys.")
        raise SystemExit(f"The server at {url} answered unexpectedly ({e}). Check the address and the API key.")
    libs = [(f["Name"], {"movies": "movie", "tvshows": "show"}[f.get("CollectionType")])
            for f in folders if f.get("CollectionType") in ("movies", "tvshows")]
    if not libs:
        raise SystemExit("Connected, but found no Movies or TV Shows libraries. Add them to config.yml by hand "
                         "(see config.example.yml).")
    print("Connected. Movie and TV libraries found:")
    for name, t in libs:
        print(f"  {name} ({t})")
    with open(os.path.join(config.ROOT, "config.example.yml")) as f:
        text = f.read()
    text = text.replace("type: emby ", f"type: {kind} ", 1).replace("url: http://127.0.0.1:8096", f"url: {json.dumps(url)}", 1)
    text = text.replace('api_key: ""', f"api_key: {json.dumps(key)}", 1)
    lib_lines = "\n".join(f"  - {{name: {json.dumps(n)}, type: {t}}}" for n, t in libs)
    text = text.replace("  - {name: Movies, type: movie}\n  - {name: TV Shows, type: show}", lib_lines, 1)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # also when overwriting an older, more open file
    with os.fdopen(fd, "w") as f:
        f.write(text)
    print(f"Wrote {path}.")
    print("Check it: remove any library you don't want CineSets to use, and put your main one first.")


def main():
    ap = argparse.ArgumentParser(prog="cinesets", description="Automatic, beautiful collections for Emby and Jellyfin. By blurbery.")
    ap.add_argument("cmd", choices=["index", "plan", "posters", "apply", "logos", "list", "schedule", "setup", "adopt", "remove",
                                    "version"])
    ap.add_argument("--only", help="comma-separated collection keys")
    ap.add_argument("--group", help="comma-separated groups")
    ap.add_argument("--min", type=int, help="skip collections with fewer matches than this")
    ap.add_argument("--config", help="path to config.yml")
    ap.add_argument("--force", action="store_true", help="logos: download again even if present")
    ap.add_argument("--all", action="store_true", help="adopt/remove: every collection in the catalogue")
    ap.add_argument("--yes", action="store_true", help="remove: do not ask for confirmation")
    args = ap.parse_args()

    if args.cmd == "version":
        print(f"CineSets by blurbery (https://github.com/blurbery/cinesets)\n"
              f"Version {__version__}. Copyright (C) 2026 blurbery.\n"
              "This program comes with ABSOLUTELY NO WARRANTY. It is free software, and you are welcome to redistribute\n"
              "it under the GNU Affero General Public License v3.0 or later with the additional terms in NOTICE.")
        return
    if args.cmd == "setup":
        setup(args.config)
        return
    cfg = config.load(args.config)
    if args.cmd == "logos":
        try:
            logos.download(os.path.join(cfg.path("data_dir"), "logos"), force=args.force)
        except (requests.RequestException, KeyError, ValueError) as e:
            raise SystemExit(f"Could not download logos ({e}). Posters will show service names until you run this again.")
        return
    colls = catalog.load(cfg)
    if args.cmd == "list":
        for c in colls:
            print(f"{c['key']:<24} {c['group']:<10} {c['name']}")
        return
    engine = Engine(cfg, MediaServer(cfg))
    if args.cmd == "adopt":
        if not (args.only or args.group or args.all):
            raise SystemExit("adopt needs --only KEYS, --group GROUPS or --all")
        engine.adopt(colls if args.all else select(colls, args.only, args.group))
        return
    if args.cmd == "remove":
        if not (args.only or args.group or args.all):
            raise SystemExit("remove needs --only KEYS, --group GROUPS or --all")
        owned = engine.owned_keys()
        if args.all:
            keys = owned
        else:
            keys = [k.strip() for k in (args.only or "").split(",") if k.strip()]
            if args.group:
                keys += [c["key"] for c in colls if c["group"] in args.group.split(",")]
            keys = [k for k in dict.fromkeys(keys) if k in owned]
        if not keys:
            print("CineSets owns none of those collections; nothing to delete.")
            return
        if not args.yes and input(f"Delete {len(keys)} collections that CineSets created? Type yes: ").strip() != "yes":
            print("Nothing deleted.")
            return
        print(f"Deleted {engine.remove(keys, colls)} collections.")
        return
    if args.cmd == "index":
        engine.get_index(force=True)
    elif args.cmd == "schedule":
        schedule(cfg, engine)
    else:
        engine.run(args.cmd, select(colls, args.only, args.group), args.min if args.min is not None else cfg["defaults"]["min_items"])


if __name__ == "__main__":
    main()
