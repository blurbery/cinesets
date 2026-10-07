# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Command line:

  cinesets index                          refresh the library index
  cinesets plan    [--only KEYS] [--group GROUPS]   dry run: what each collection would contain
  cinesets posters [--only KEYS] [--group GROUPS] [--reshuffle]   build posters and contact sheets, no server writes
  cinesets apply   [--only KEYS] [--group GROUPS] [--reshuffle]   create or update collections
  cinesets logos   [--force]              download streaming service logos from Wikimedia Commons
  cinesets list                           show every section and collection, and which are picked
  cinesets pick                           choose sections or single collections to make (writes config.yml)
  cinesets web     [--host H] [--port P] [--demo]   the dashboard: pick, style and preview in a web page
  cinesets web     --link | --new-key | --set-password   its sign-in link, a new access key, or a password
  cinesets schedule                       run forever on the schedule in config.yml (for Docker)
  cinesets setup                          ask for server details and write config.yml
  cinesets adopt   --only KEYS | --all    take over existing collections with CineSets' names (after a reinstall)
  cinesets remove  --only KEYS | --all | --unpicked   delete collections CineSets created (asks first; --yes to skip)
"""
import argparse
import getpass
import json
import os
import re
import sys
import time
import traceback
from urllib.parse import urlparse

import requests

from . import __version__, catalog, config, logos, servers
from .engine import Engine


def select(colls, only=None, group=None, unpicked=()):
    """Pick collections by key and/or group. Unknown names are reported and skipped (for example the
    Halloween entries after the season); it is an error only if nothing at all matches. `unpicked` are the
    collections left out under `collections` in config.yml, so asking for one says so."""
    picked, skipped = colls, False
    left_out = {c["key"] for c in unpicked}
    if only:
        want = {k.strip() for k in only.split(",") if k.strip()}
        unknown = want - {c["key"] for c in colls}
        if unknown & left_out:
            skipped = True
            print(f"Note: not picked in config.yml (collections), skipped: {', '.join(sorted(unknown & left_out))}")
        if unknown - left_out:
            print(f"Note: not in the collections file, skipped: {', '.join(sorted(unknown - left_out))}")
        picked = [c for c in picked if c["key"] in want]
    if group:
        groups = {g.strip() for g in group.split(",") if g.strip()}
        unknown = groups - {c["group"] for c in colls}
        if unknown & {c["group"] for c in unpicked}:
            skipped = True
            print(f"Note: nothing picked in config.yml (collections) from group(s) "
                  f"{', '.join(sorted(unknown & {c['group'] for c in unpicked}))}, skipped")
            unknown -= {c["group"] for c in unpicked}
        if unknown:
            print(f"Note: no collections in group(s) {', '.join(sorted(unknown))}, skipped")
        picked = [c for c in picked if c["group"] in groups]
    if (only or group) and not picked:
        raise SystemExit("Nothing to do: none of those are picked in config.yml (collections). See: cinesets list"
                         if skipped else "No collections match. See: cinesets list")
    return picked


DEFAULT_SCHEDULE = [
    {"every_hours": 6, "only": "m-trending,s-trending"},
    {"every_hours": 24, "group": "seasonal,charts"},
    {"every_hours": 168, "all": True},
]


def reload(path, cfg, engine):
    """config.yml read again before each scheduled job, so changes (from the dashboard, for example) apply without a
    restart. If it no longer loads, say so and carry on with the settings from before."""
    try:
        fresh = config.load(path)
    except SystemExit as e:
        print(f"!! config.yml has a problem, so this job uses the settings from before: {e}")
        return cfg, engine
    return fresh, Engine(fresh, servers.connect(fresh))


def schedule(cfg, engine, path=None):
    jobs = cfg.get("schedule") or DEFAULT_SCHEDULE  # the jobs themselves change only with a restart
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
                    cfg, engine = reload(path, cfg, engine)
                    colls = catalog.load(cfg)  # re-read each time, so edits apply without a restart
                    chosen = catalog.picked(cfg, colls)
                    unpicked = [c for c in colls if c not in chosen]
                    picked = chosen if job.get("all") else select(chosen, job.get("only"), job.get("group"), unpicked)
                    engine.run("apply", picked, cfg["defaults"]["min_items"])
                except SystemExit as e:  # for example a renamed library: report it and try again next time
                    print(f"!! job {i + 1} stopped: {e}")
                except Exception:
                    traceback.print_exc()
                last[i] = time.time()
        sys.stdout.flush()
        time.sleep(300)


def show_list(cfg, colls, chosen):
    keys = {c["key"] for c in chosen}
    for group, members in catalog.sections(cfg, colls):
        n = sum(c["key"] in keys for c in members)
        print(f"{members[0]['section']} (section: {group}), {n} of {len(members)} picked")
        for c in members:
            print(f"  [{'x' if c['key'] in keys else ' '}] {c['key']:<24} {c['name']}")


def note_unpicked(engine, chosen):
    """Collections CineSets made that are no longer picked stay on the server untouched; say so once per run."""
    keys = {c["key"] for c in chosen}
    left = [k for k in engine.owned_keys() if k not in keys]
    if left:
        print(f"Note: these collections CineSets made are not picked any more, so they are no longer updated. They stay "
              f"on your server until you delete them with `remove --unpicked`: {', '.join(left)}")


def _numbers(text, most):
    """'1,3,5-8' -> {1, 3, 5, 6, 7, 8}. None if anything is not a number from 1 to `most`."""
    out = set()
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            return None
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if not 1 <= lo <= hi <= most:
            return None
        out.update(range(lo, hi + 1))
    return out


def _ask(prompt, allowed, default):
    while True:
        answer = input(prompt).strip().lower() or default
        if answer[:1] in allowed:
            return answer[:1]
        print(f"  Please answer {', '.join(sorted(allowed))}.")


def pick_block(cfg, colls, keys):
    """The `collections` block for config.yml that picks exactly `keys`, in as few lines as it can: a section that is
    mostly picked is listed with exclude for the rest, a section that is mostly not is left out with include."""
    sections, include, exclude = [], [], []
    for group, members in catalog.sections(cfg, colls):
        on = [c["key"] for c in members if c["key"] in keys]
        off = [c["key"] for c in members if c["key"] not in keys]
        if on and len(on) >= len(off):
            sections.append(group)
            exclude += off
        else:
            include += on
    every = set(sections) == {c["group"] for c in colls}
    return config.collections_block({"sections": "all" if every else sections, "include": include, "exclude": exclude})


def write_pick(path, block):
    """Put the `collections` block into config.yml in place of the old one (see config.write_block)."""
    config.write_block(path, "collections", block)


def pick(path):
    """Ask section by section which collections to make, then write the choice to config.yml."""
    if not sys.stdin.isatty():
        raise SystemExit("pick asks questions, so run it in a terminal (on Docker: docker compose run --rm cinesets pick). "
                         "Or edit `collections` in config.yml by hand.")
    path = config.config_path(path)
    cfg = config.load(path)
    colls = catalog.load(cfg)
    now = {c["key"] for c in catalog.picked(cfg, colls, quiet=True)}
    keys = set()
    print("Pick the collections CineSets makes, a section at a time. Press Enter to keep what is picked now.")
    for group, members in catalog.sections(cfg, colls):
        on = [c for c in members if c["key"] in now]
        default = "a" if len(on) == len(members) else "n" if not on else "c"
        shown = [c["name"].split(" - ", 1)[-1] for c in members]
        preview = ", ".join(shown[:10]) + (f" and {len(shown) - 10} more" if len(shown) > 10 else "")
        print(f"\n{members[0]['section']} ({len(members)}, {len(on)} picked now): {preview}")
        answer = _ask(f"  Use all of them, none, or choose? [a/n/c, Enter = {default}] ", {"a", "n", "c"}, default)
        if answer == "a":
            keys.update(c["key"] for c in members)
        elif answer == "c":
            for i, c in enumerate(members, start=1):
                print(f"  {i:>3}. [{'x' if c['key'] in now else ' '}] {c['name']}")
            while True:
                text = input("  Numbers to use, for example 1,3,5-8 (Enter keeps the ones marked x): ")
                chosen = _numbers(text, len(members)) if text.strip() else {
                    i for i, c in enumerate(members, start=1) if c["key"] in now}
                if chosen is not None:
                    break
                print(f"  Use numbers from 1 to {len(members)}, separated by commas, with a dash for a range.")
            keys.update(members[i - 1]["key"] for i in chosen)
    write_pick(path, pick_block(cfg, colls, keys))
    print(f"\nPicked {len(keys)} of {len(colls)} collections. Wrote them to `collections` in {path}.")
    print("Nothing on your server has changed yet: `plan` shows what would be made and `apply` makes it.")
    if now - keys:
        print("Any collections you unpicked that CineSets already made stay on your server: `remove --unpicked` "
              "deletes them.")


def detect_server(url):
    """(server type, address, note) for the server at `url`, from its public information (no API key needed), or None
    if no server module recognises it."""
    return servers.detect(url)


def find_server(url):
    """(address, server type or None) for the address typed at setup. A browser address with a page on the end works
    too, and a server module can point setup to the server's own address (Silo does, from its Jellyfin-compatible
    port) or ask for it."""
    found = detect_server(url)
    origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
    if not found and origin != url:
        found = detect_server(origin)
    if not found:
        return url, None
    kind, where, note = found
    if note:
        print(note)
    if not where:
        name = servers.names()[kind]
        typed = clean_address(input(f"{name}'s address, as you open it in a browser: "))
        again = detect_server(typed)
        if not again or again[0] != kind or not again[1]:
            raise SystemExit(f"{name} did not answer at {typed}. Check the address its web app opens on.")
        where = again[1]
    return where, kind


def clean_address(url):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return servers.trim(url.rstrip("/"))


def setup(path):
    """Interactive first-run setup: find the server and what it is, test the key, detect libraries, write config.yml."""
    path = config.config_path(path)
    if os.path.exists(path) and input(f"{path} exists. Overwrite it? [y/N] ").strip().lower() != "y":
        return
    url = clean_address(input("Server address, as you open it in a browser [http://127.0.0.1:8096]: ").strip()
                        or "http://127.0.0.1:8096")
    url, kind = find_server(url)
    names = servers.names()
    if kind:
        print(f"Found {names[kind]} at {url}.")
    else:
        choices = list(names.values())
        kind = input(f"Couldn't tell what server that is. {', '.join(choices[:-1])} or {choices[-1]}? [emby]: ").strip().lower() or "emby"
        config.check_type(kind)
    module = servers.server_class(kind)
    where = module.KEY_PAGE
    if getattr(module, "SETUP_NOTE", None):
        print(module.SETUP_NOTE)
    key = getpass.getpass(f"API key ({where} on your server; typing is hidden): ").strip()
    cfg = config.Config(config._merge(config.DEFAULTS, {"server": {"type": kind, "url": url, "api_key": key}}))
    cfg["base_dir"] = os.path.dirname(os.path.abspath(path))
    try:
        libs = servers.connect(cfg).media_libraries()
    except requests.RequestException as e:
        raise SystemExit(f"Could not reach the server at {url}: {type(e).__name__}. Check the address.")
    except RuntimeError as e:
        status = getattr(e, "status", None)
        if status in (401, 403):
            raise SystemExit(f"The server rejected the API key. Check it under {where}.")
        raise SystemExit(f"The server at {url} answered unexpectedly ({e}). Check the address and the API key.")
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
    if sys.stdin.isatty():
        answer = input("\nMake every collection? Answer n to choose sections or single collections now "
                       "(you can change this any time with `pick`). [Y/n] ").strip().lower()
        if answer.startswith("n"):
            pick(path)


def main():
    supported = list(servers.names().values())
    ap = argparse.ArgumentParser(prog="cinesets", description=f"Automatic, beautiful collections for "
                                 f"{', '.join(supported[:-1])} and {supported[-1]}. By blurbery.")
    ap.add_argument("cmd", choices=["index", "plan", "posters", "apply", "logos", "list", "pick", "web", "schedule", "setup",
                                    "adopt", "remove", "version"])
    ap.add_argument("--only", help="comma-separated collection keys")
    ap.add_argument("--group", help="comma-separated groups")
    ap.add_argument("--min", type=int, help="skip collections with fewer matches than this")
    ap.add_argument("--config", help="path to config.yml")
    ap.add_argument("--force", action="store_true", help="logos: download again even if present")
    ap.add_argument("--all", action="store_true", help="adopt/remove: every collection in the catalogue")
    ap.add_argument("--unpicked", action="store_true", help="remove: the ones CineSets made that config.yml no longer picks")
    ap.add_argument("--reshuffle", action="store_true", help="posters/apply: new random artwork (posters: artwork: random)")
    ap.add_argument("--yes", action="store_true", help="remove: do not ask for confirmation")
    ap.add_argument("--host", help="web: address to listen on (default from config.yml, else 127.0.0.1; 0.0.0.0 for "
                                   "other computers too)")
    ap.add_argument("--port", type=int, help="web: port (default from config.yml, else 8095)")
    ap.add_argument("--no-sign-in", action="store_true", help="web: no sign-in (only for a browser on this machine)")
    ap.add_argument("--public", action="store_true", help="web: reachable from the internet: sign-ins only over HTTPS")
    ap.add_argument("--demo", action="store_true", help="web: try the dashboard with made-up artwork, no server")
    ap.add_argument("--link", action="store_true", help="web: show the sign-in link and stop")
    ap.add_argument("--new-key", action="store_true", help="web: make a new access key, signing everyone out")
    ap.add_argument("--set-password", action="store_true", help="web: set a password to sign in with")
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
    if args.cmd == "pick":
        pick(args.config)
        return
    if args.cmd == "web":
        from . import web
        what = "link" if args.link else "new-key" if args.new_key else "set-password" if args.set_password else None
        if what:
            web.manage(args.config, what, args.host, args.port)
        else:
            web.serve(args.config, args.host, args.port, args.demo, False if args.no_sign_in else None,
                      True if args.public else None)
        return
    cfg = config.load(args.config)
    if args.cmd == "logos":
        try:
            logos.download(os.path.join(cfg.path("data_dir"), "logos"), force=args.force)
        except (requests.RequestException, KeyError, ValueError) as e:
            raise SystemExit(f"Could not download logos ({e}). Posters will show service names until you run this again.")
        return
    colls = catalog.load(cfg)
    chosen = catalog.picked(cfg, colls)
    unpicked = [c for c in colls if c not in chosen]
    if args.cmd == "list":
        show_list(cfg, colls, chosen)
        return
    engine = Engine(cfg, servers.connect(cfg))
    if args.cmd == "adopt":
        if not (args.only or args.group or args.all):
            raise SystemExit("adopt needs --only KEYS, --group GROUPS or --all")
        engine.adopt(colls if args.all else select(colls, args.only, args.group))
        return
    if args.cmd == "remove":
        if not (args.only or args.group or args.all or args.unpicked):
            raise SystemExit("remove needs --only KEYS, --group GROUPS, --unpicked or --all")
        owned = engine.owned_keys()
        if args.all:
            keys = owned
        else:
            keys = [k.strip() for k in (args.only or "").split(",") if k.strip()]
            if args.group:
                keys += [c["key"] for c in colls if c["group"] in args.group.split(",")]
            if args.unpicked:
                keys += [k for k in owned if k not in {c["key"] for c in chosen}]
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
        schedule(cfg, engine, args.config)
    else:
        if args.reshuffle and cfg["posters"]["artwork"] != "random":
            print("Note: --reshuffle only changes posters when config.yml has posters: artwork: random")
        engine.reshuffle = args.reshuffle
        engine.run(args.cmd, select(chosen, args.only, args.group, unpicked),
                   args.min if args.min is not None else cfg["defaults"]["min_items"])
        if not (args.only or args.group):
            note_unpicked(engine, chosen)


if __name__ == "__main__":
    main()
