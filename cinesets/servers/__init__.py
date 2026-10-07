# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Media servers. The collections, list matching, posters and dashboard are the same for every server; each server
is its own module here (emby.py covers Emby and Jellyfin, silo.py covers Silo), and the rest of CineSets only uses these operations:

  reads         media_libraries, library_folders, library_items, genres, alive, backdrop_image
  collections   list_collections, create_collection, wait_until_ready, members, add_items, remove_items,
                upload_poster, set_details, delete_collection, admin_user
  setup         detect(url): which server answers at an address (a static method, no API key)
  optional      arrange(owned): put the collections in page order, for a server without sort names (Silo)

A server's quirks stay in its own module, so a change for one server can't change what another one gets."""
import ipaddress
import sys
from urllib.parse import urlparse

NAMES = {"emby": "Emby", "jellyfin": "Jellyfin", "silo": "Silo"}


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


def _classes():
    from .emby import MediaServer
    from .silo import SiloServer
    # Silo is asked first: its Jellyfin-compatible port also answers the Jellyfin question
    return {"silo": SiloServer, "emby": MediaServer, "jellyfin": MediaServer}


def connect(cfg):
    """The client for the server in config.yml."""
    return _classes()[cfg["server"]["type"]](cfg)


def detect(url):
    """Which server answers at `url` (emby, jellyfin, silo, or silo-compat for Silo's Jellyfin-compatible port), from
    its public information, or None."""
    for cls in dict.fromkeys(_classes().values()):
        kind = cls.detect(url)
        if kind:
            return kind
    return None
