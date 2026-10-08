# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""Media servers. The collections, list matching, posters and dashboard are the same for every server. Each server is
its own module here, cinesets/servers/<type>.py (emby.py, jellyfin.py, silo.py), whose SERVER class answers the
questions in base.py, the shell, and nothing else is shared between servers.

An install uses one server: connect() loads only that server's module, so no other server's code runs. Setup is the
one time CineSets asks every module, to work out which server answers at an address."""
import email.utils
import ipaddress
import os
import re
import sys
import time
import warnings
from urllib.parse import urlparse

import requests
import urllib3


class ServerError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def chunks(seq, n=40):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


RETRIES = 3              # a request is sent again at most this many times
BUSY = (429, 502, 503, 504)
LONGEST_WAIT = 60        # the longest CineSets waits before sending again, whatever Retry-After asks for


def send(request, url, retry=False, **kw):
    """request(url, **kw) for one HTTP request (a session's request with its method filled in, or requests.get), sent
    again after a dropped connection, a timeout or a busy answer (429, 502, 503, 504) when `retry` says that's safe: a
    read, or a write that does the same thing however often it arrives. A write that might have gone through before it
    failed, such as making a collection, is only sent again after a 429, which says the server turned it away.
    Waits 2, 4, then 8 seconds, or as long as Retry-After asks, up to a minute. Returns (the response, how long the try
    that got it took). Once the tries run out, the last answer or error is the caller's to deal with."""
    for attempt in range(RETRIES + 1):
        last = attempt == RETRIES
        start = time.time()
        try:
            r = request(url, **kw)
        except requests.exceptions.SSLError as e:  # never worth another try
            if untrusted_certificate(e):
                raise ServerError(untrusted(url)) from e
            raise
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
            if last or not retry:
                raise
            wait = 2 ** (attempt + 1)
        else:
            if last or r.status_code not in (BUSY if retry else (429,)):
                return r, time.time() - start
            wait = _retry_after(r, attempt)
        time.sleep(wait)


def _retry_after(r, attempt):
    """How long a busy server asked CineSets to wait (seconds, or until a date), up to a minute; or 2, 4, 8 seconds."""
    asked = str(r.headers.get("Retry-After") or "").strip()
    if re.fullmatch(r"\d+(\.\d+)?", asked):
        wait = float(asked)
    else:
        try:
            wait = email.utils.parsedate_to_datetime(asked).timestamp() - time.time()
        except (TypeError, ValueError, IndexError, OverflowError):
            wait = 2 ** (attempt + 1)
    return min(max(wait, 0), LONGEST_WAIT)


def untrusted_certificate(error):
    """Whether a TLS error is the server's certificate failing the check (self-signed, expired, made for another name),
    rather than, say, https sent to a port that speaks plain http."""
    text = str(error)
    return "CERTIFICATE_VERIFY_FAILED" in text or "doesn't match" in text


def untrusted(url):
    where = "{0.scheme}://{0.netloc}".format(urlparse(url))
    return (f"The certificate at {where} isn't trusted (it may be self-signed, expired or made for another name). If "
            "it's your server's own, set server.verify in config.yml to the CA certificate file that signed it, or to "
            "false to skip the check (see docs/setup.md).")


def verify_setting(cfg):
    """server.verify from config.yml, the way requests takes it: True checks the server's certificate against the usual
    authorities, False skips the check, and a file (relative to config.yml's folder) checks it against that CA
    certificate. It goes with every request to the server, Silo's artwork storage included."""
    srv = cfg["server"]
    value = srv.get("verify", True)
    if isinstance(value, bool):
        if not value and urlparse(srv["url"]).scheme == "https":
            # one plain warning here rather than urllib3's on every request
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            print(f"Warning: server.verify is false, so CineSets doesn't check the certificate at {srv['url']} and "
                  "can't tell your server from something pretending to be it. Setting it to the server's CA "
                  "certificate file is safer.", file=sys.stderr)
        return value
    if isinstance(value, str) and value.strip():
        path = os.path.expanduser(value.strip())
        if not os.path.isabs(path):
            path = os.path.join(cfg.get("base_dir") or ".", path)
        if not os.path.exists(path):
            raise SystemExit(f"server.verify: there is no CA certificate file at {path}")
        return path
    raise SystemExit(f"server.verify must be true, false or the path of a CA certificate file, not {value!r}")


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


_read = None  # public pages already read during one detect(), so modules asking for the same one share a request


def public_info(url, path, verify=True):
    """The JSON a server shows anyone at url + path (no API key goes with it), or None. A certificate that isn't
    trusted stops setup with what to do about it, since every other request would fail the same way."""
    if _read is not None and url + path in _read:
        return _read[url + path]
    try:
        r = requests.get(url + path, timeout=10, allow_redirects=False, headers={"accept": "application/json"},
                         verify=verify)
        info = r.json() if r.status_code == 200 else None
    except requests.exceptions.SSLError as e:
        if untrusted_certificate(e):
            raise SystemExit(untrusted(url) + " Setup can't take that setting yet: give it the server's http:// "
                             "address and change server.url afterwards, or fill in config.yml from "
                             "config.example.yml by hand.") from e
        info = None
    except (requests.RequestException, ValueError):
        info = None
    info = info if isinstance(info, dict) else None
    if _read is not None:
        _read[url + path] = info
    return info


def detect(url, verify=True):
    """(server type, its address, a note for setup to show) for the server that answers at `url`, from its public
    information, or None. The address is None when a module knows the server but needs its own address typed in.
    `verify` is server.verify, for the server's certificate."""
    global _read
    _read = {}
    try:
        for kind in ASK_ORDER:
            found = load(kind).detect(url, verify)
            if found:
                return found
        return None
    finally:
        _read = None


def trim(url):
    """A pasted browser address, tidied by every module (Emby's /web/index.html, say)."""
    for kind in SERVERS:
        url = load(kind).trim(url)
    return url
