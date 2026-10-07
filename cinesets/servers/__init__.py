# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Media servers. The collections, list matching, posters and dashboard are the same for every server; each server
is its own module here (emby.py covers Emby and Jellyfin, silo.py covers Silo), and the rest of CineSets only uses these operations:

  reads         media_libraries, library_folders, library_items, genres, alive, backdrop_image
  collections   list_collections, create_collection, wait_until_ready, members, add_items, remove_items,
                upload_poster, set_details, delete_collection, admin_user
  setup         NAMES, KEY_PAGE, SETUP_NOTE (optional) and trim(url): what setup says and how it tidies an address;
                detect(url): (type, address, note) if this server answers at an address, or None (no API key needed)
  optional      arrange(owned): put the collections in page order, for a server without sort names (Silo)
                narrow(coll, ids) and prepare(cid, coll): for a server whose collections live in one library (Silo)

A server's quirks stay in its own module, so a change for one server can't change what another one gets."""
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


def _modules():
    """Every server module's class, in the order setup asks them who answers at an address. Silo goes first: its
    Jellyfin-compatible port also answers the Jellyfin question."""
    from .emby import MediaServer
    from .silo import SiloServer
    return [SiloServer, MediaServer]


def names():
    """server.type -> the server's name, for every server CineSets supports."""
    out = {}
    for cls in reversed(_modules()):
        out.update(cls.NAMES)
    return out


def server_class(kind):
    return next(cls for cls in _modules() if kind in cls.NAMES)


def connect(cfg):
    """The client for the server in config.yml."""
    return server_class(cfg["server"]["type"])(cfg)


def detect(url):
    """(server type, its address, a note for setup to show) for the server that answers at `url`, from its public
    information, or None. The address is None when a module knows the server but needs its own address typed in."""
    for cls in _modules():
        found = cls.detect(url)
        if found:
            return found
    return None


def trim(url):
    """A pasted browser address, tidied by every module (Emby's /web/index.html, say)."""
    for cls in _modules():
        url = cls.trim(url)
    return url
