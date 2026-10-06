# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""A thin client for the parts of the Emby and Jellyfin APIs CineSets uses. The two share these endpoints;
Emby serves them under /emby and Jellyfin at the root."""
import ipaddress
import sys
import time
from urllib.parse import urlparse

import requests

from . import __version__


def _private_host(host):
    if host in ("localhost",) or host.endswith((".local", ".lan", ".internal", ".home.arpa", ".ts.net")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." not in host  # a bare name such as a Docker container name
    return not ip.is_global  # private, loopback, link-local and shared ranges such as Tailscale 100.64.0.0/10


class ServerError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class MediaServer:
    def __init__(self, cfg):
        srv = cfg["server"]
        if not srv["api_key"]:
            raise SystemExit("No API key: set server.api_key in config.yml or CINESETS_API_KEY")
        self.kind = srv["type"]
        self.base = srv["url"] + ("/emby" if self.kind == "emby" else "")
        parsed = urlparse(srv["url"])
        if parsed.scheme == "http" and not _private_host(parsed.hostname or ""):
            print(f"Warning: {srv['url']} uses plain http over a public address, so your API key travels unencrypted. "
                  "Use https:// if the server supports it.", file=sys.stderr)
        self.pause = float(cfg["write_pause"])
        self.session = requests.Session()
        self.session.headers.update({"accept": "application/json", "X-Emby-Token": srv["api_key"],
                                     "User-Agent": f"CineSets/{__version__} (+https://github.com/blurbery/cinesets)"})
        if self.kind == "jellyfin":
            self.session.headers["Authorization"] = (
                f'MediaBrowser Client="CineSets", Device="CineSets", DeviceId="cinesets", '
                f'Version="{__version__}", Token="{srv["api_key"]}"')

    def call(self, method, path, timeout=120, **kw):
        # never follow redirects: the API key travels in headers and must not reach another host
        r = self.session.request(method, self.base + path, timeout=timeout, allow_redirects=False, **kw)
        if 300 <= r.status_code < 400:
            raise ServerError(f"{method} {path.split('?')[0]} was redirected to {r.headers.get('Location', '?')}: "
                              f"set server.url to the address the server answers on directly", r.status_code)
        if r.status_code not in (200, 201, 204):
            raise ServerError(f"{method} {path.split('?')[0]} -> {r.status_code} {r.text[:200]}", r.status_code)
        return r

    def get(self, path, **kw):
        return self.call("GET", path, **kw).json()

    def timed(self, method, path, **kw):
        """A write that backs off when the server is slow to take it."""
        t = time.time()
        r = self.call(method, path, **kw)
        took = time.time() - t
        time.sleep(self.pause + min(took, 10))
        return r, took

    def admin_user(self):
        return next(u["Id"] for u in self.get("/Users") if u.get("Policy", {}).get("IsAdministrator"))

    def item(self, user_id, item_id):
        """One item with full metadata, as the edit endpoint expects it back."""
        if self.kind == "jellyfin":
            return self.get(f"/Items/{item_id}?userId={user_id}")
        return self.get(f"/Users/{user_id}/Items/{item_id}")
