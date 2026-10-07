# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Media servers. The collections, list matching, posters and dashboard are the same for every server. Each server is
its own module here, cinesets/servers/<type>.py (emby.py, jellyfin.py, silo.py), whose SERVER class answers the
questions in base.py, the shell, and nothing else is shared between servers.

An install uses one server: connect() loads only that server's module, so no other server's code runs. Setup is the
one time CineSets asks every module, to work out which server answers at an address."""
import ipaddress
import sys
from urllib.parse import urlparse


class ServerError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def chunks(seq, n=40):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _private_host(host):
    if host in ("localhost",) or host.endswith((".local", ".lan", ".internal", ".home.arpa", ".ts.net")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host  # a bare name such as a Docker container name
    return not ip.is_global  # private, loopback, link-local and shared ranges such as Tailscale 100.64.0.0/10


def warn_plain_http(url):
    parsed = urlparse(url)
    if parsed.scheme == "http" and not _private_host(parsed.hostname or ""):
        print(f"Warning: {url} uses plain http over a public address, so your API key travels unencrypted. "
              "Use https:// if the server supports it.", file=sys.stderr)


# server.type -> the server's name; its module is cinesets/servers/<type>.py
SERVERS = {"emby": "Emby", "jellyfin": "Jellyfin", "silo": "Silo"}
# the order setup asks them who answers at an address: Silo's Jellyfin-compatible port also answers the Jellyfin
# question, and Jellyfin's public information would also pass Emby's looser check
ASK_ORDER = ("silo", "jellyfin", "emby")


def load(kind):
    """The class for one server type, importing that server's module and no other."""
    import importlib
    return importlib.import_module(f"{__name__}.{kind}").SERVER


def names():
    """server.type -> the server's name, for every server CineSets supports."""
    return dict(SERVERS)


def server_class(kind):
    return load(kind)


def connect(cfg):
    """The client for the server in config.yml."""
    return load(cfg["server"]["type"])(cfg)


def detect(url):
    """(server type, its address, a note for setup to show) for the server that answers at `url`, from its public
    information, or None. The address is None when a module knows the server but needs its own address typed in."""
    for kind in ASK_ORDER:
        found = load(kind).detect(url)
        if found:
            return found
    return None


def trim(url):
    """A pasted browser address, tidied by every module (Emby's /web/index.html, say)."""
    for kind in SERVERS:
        url = load(kind).trim(url)
    return url
