# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
"""End-to-end test of the dashboard behind real Caddy and nginx reverse proxies (used by CI).

  python tests/e2e/run_proxy_e2e.py                               (caddy, nginx and openssl from PATH)
  python tests/e2e/run_proxy_e2e.py --docker                      (the official caddy and nginx images)
  python tests/e2e/run_proxy_e2e.py --docker --image cinesets:ci  (the dashboard in its own container as well)

Makes a throwaway config.yml with a fresh library index, so no media server is needed, and starts the dashboard
three times: with sign-in, with public: true and with sign-in off. Caddy and nginx get the setups in
docs/dashboard.md, with HTTPS from Caddy's own certificate authority and a self-signed certificate for nginx. Through
each proxy it checks:

- its own name and under /cinesets/: the redirect to /cinesets/, the page, every file it loads and the API calls it
  makes, and a sign-in with the access key, the session cookie and a signed-in API call;
- public: true behind HTTPS: sign-in works, the cookie is Secure and HSTS is sent; over plain http, sign-ins are
  refused, even when the browser claims to be on HTTPS;
- sign-in off: requests carrying the forwarding headers these setups add are turned away;
- nginx: X-Forwarded-Proto is the one header the dashboard needs; Host and X-Forwarded-For are optional.

With --docker, the proxies run from the official images on the host network. With --image as well, the dashboard
runs from that image like the cinesets-web service in docker-compose.example.yml (listening on 0.0.0.0 in its
container) and the proxies reach it by its container name on a shared Docker network; sign-in off is then checked
to be refused at start-up, as it can't listen on 0.0.0.0.
"""
import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urljoin, urlparse

import requests
import urllib3

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NETWORK = "cinesets-proxy-e2e"
PORTS = {"signed": 18095, "public": 18096, "local": 18097}   # the dashboards, on this machine
CADDY = {"http": 18180, "https": 18143}
NGINX = {"http": 18280, "https": 18243}
NAMES = ("cinesets.test", "example.test", "public.test", "plain.test", "local.test", "proto-only.test",
         "no-headers.test")
HEADERS = ("proxy_set_header Host $host;\n"
           "      proxy_set_header X-Forwarded-Proto $scheme;\n"
           "      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # the test certificates aren't trusted
_getaddrinfo = socket.getaddrinfo


def _resolve(host, *args, **kw):
    """The test names all point at this machine, so HTTPS sends the right name (SNI) without touching /etc/hosts."""
    return _getaddrinfo("127.0.0.1" if host in NAMES else host, *args, **kw)


socket.getaddrinfo = _resolve


def log(msg):
    print(f"[proxy-e2e] {msg}", flush=True)


def check(cond, msg):
    if not cond:
        raise SystemExit("FAILED: " + msg)
    log("ok: " + msg)


# ------------------------------------------------------------ the proxies' settings
def caddyfile(up, folder, bind):
    """The Caddy setups from docs/dashboard.md. `up` maps each dashboard to the address Caddy passes requests to;
    `bind` is the address Caddy listens on, and `folder` is set when Caddy runs here and keeps its files in it."""
    extra = f"\tdefault_bind {bind}\n" if bind else ""
    extra += f"\tstorage file_system {folder}/caddy-data\n" if folder else ""
    text = (
        "{\n"
        "\tadmin off\n"
        f"\thttp_port {CADDY['http']}\n"
        f"\thttps_port {CADDY['https']}\n"
        "\tlocal_certs\n"            # certificates from Caddy's own authority: no outside network
        "\tskip_install_trust\n"     # and never added to this machine's trust store
        f"{extra}"
        "}\n\n"
        "# its own name\n"
        f"cinesets.test {{\n\treverse_proxy {up['signed']}\n}}\n\n"
        "# under a path of a site you already have\n"
        "example.test {\n"
        "\tredir /cinesets /cinesets/\n"
        f"\thandle_path /cinesets/* {{\n\t\treverse_proxy {up['signed']}\n\t}}\n"
        "}\n\n"
        "# public: true behind HTTPS, and the same over plain http\n"
        f"public.test {{\n\treverse_proxy {up['public']}\n}}\n\n"
        f"http://plain.test {{\n\treverse_proxy {up['public']}\n}}\n")
    if up.get("local"):
        text += f"\n# sign-in off\nhttp://local.test {{\n\treverse_proxy {up['local']}\n}}\n"
    return text


def nginx_conf(up, folder, bind, files):
    """The nginx setups from docs/dashboard.md, plus two that leave headers out. `files` is this folder as nginx
    sees it (for the certificate); `folder` is set when nginx runs here and keeps its own files in it."""
    listen = f"{bind}:" if bind else ""
    pid = f"pid {folder}/nginx.pid;\n" if folder else ""
    temp = "".join(f"  {kind}_temp_path {folder}/nginx-temp/{kind};\n"
                   for kind in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi")) if folder else ""

    def server(name, port, body, ssl=True):
        return (f"  server {{\n    listen {listen}{port}{' ssl' if ssl else ''};\n    server_name {name};\n"
                f"{body}  }}\n")

    def site(target, headers=HEADERS):
        return f"    location / {{\n      proxy_pass http://{target};\n      {headers}\n    }}\n"
    return (
        "worker_processes 1;\n"
        f"{pid}"
        "events { worker_connections 64; }\n"
        "http {\n"
        "  access_log off;\n"
        f"{temp}"
        f"  ssl_certificate {files}/cert.pem;\n"
        f"  ssl_certificate_key {files}/key.pem;\n"
        "  # its own name\n"
        + server("cinesets.test", NGINX["https"], site(up["signed"]))
        + "  # under a path of a site you already have (the slash after the address takes /cinesets off)\n"
        + server("example.test", NGINX["https"],
                 "    location = /cinesets { return 301 /cinesets/; }\n"
                 f"    location /cinesets/ {{\n      proxy_pass http://{up['signed']}/;\n      {HEADERS}\n    }}\n")
        + "  # public: true behind HTTPS, and the same over plain http\n"
        + server("public.test", NGINX["https"], site(up["public"]))
        + server("plain.test", NGINX["http"], site(up["public"]), ssl=False)
        + "  # only X-Forwarded-Proto, and no headers at all\n"
        + server("proto-only.test", NGINX["https"], site(up["public"], "proxy_set_header X-Forwarded-Proto $scheme;"))
        + server("no-headers.test", NGINX["https"], site(up["public"], "# nothing added"))
        + ("  # sign-in off\n" + server("local.test", NGINX["http"], site(up["local"]), ssl=False)
           if up.get("local") else "")
        + "}\n")


# ------------------------------------------------------------ starting and stopping things
class Run:
    """Everything this test starts, so all of it is stopped (and its logs kept) however the test ends."""

    def __init__(self, work, logs):
        self.work, self.logs, self.procs, self.containers, self.network = work, logs, [], [], False

    def start(self, name, cmd, env=None, cwd=None):
        out = open(os.path.join(self.logs, f"{name}.log"), "w")
        self.procs.append((name, subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=cwd or self.work,
                                                  env={**os.environ, **(env or {})}), out))

    def docker(self, *args, check=True):
        out = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=300)
        if check and out.returncode:
            raise SystemExit(f"docker {' '.join(args[:3])} ... exited {out.returncode}: {out.stderr.strip()[-600:]}")
        return out

    def container(self, name, *args):
        self.docker("rm", "-f", name, check=False)
        self.containers.append(name)
        self.docker("run", "-d", "--name", name, *args)

    def stop(self):
        for name in self.containers:
            with open(os.path.join(self.logs, f"{name}.log"), "w") as f:
                got = self.docker("logs", name, check=False)
                f.write(got.stdout + got.stderr)
            self.docker("rm", "-f", name, check=False)
        if self.network:
            self.docker("network", "rm", NETWORK, check=False)
        for name, proc, out in self.procs:
            proc.send_signal(signal.SIGINT)  # like Ctrl+C, so the dashboard removes its temporary folder
        for name, proc, out in self.procs:
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            out.close()

    def running(self):
        """A process that stopped early is the likely reason for a failure."""
        for name, proc, _ in self.procs:
            if proc.poll() is not None:
                raise SystemExit(f"FAILED: {name} stopped (exit {proc.returncode}); see {self.logs}/{name}.log")


def wait_for(what, test, seconds=90):
    last = None
    for _ in range(seconds * 2):
        try:
            if test():
                return
        except (requests.RequestException, OSError) as e:
            last = e
        time.sleep(0.5)
    raise SystemExit(f"FAILED: {what} did not come up ({last})")


def make_config(folder):
    """A config.yml for a server that is never asked anything, and a fresh library index so none is built."""
    os.makedirs(os.path.join(folder, "data"), exist_ok=True)
    with open(os.path.join(folder, "config.yml"), "w") as f:
        f.write('server: {type: emby, url: "http://127.0.0.1:9", api_key: "proxy-e2e"}\n'
                "libraries: [{name: Movies, type: movie}]\n")
    index = {"built": time.time(), "movie": {"imdb": {}, "tmdb": {}}, "show": {"tvdb": {}, "imdb": {}, "tmdb": {}},
             "items": {"m1": {"n": "Back to the Future", "y": 1985, "b": True, "k": "movie"}}}
    with open(os.path.join(folder, "data", "index.json"), "w") as f:
        json.dump(index, f)


def key_from(text):
    found = re.search(r"#key=([A-Za-z0-9_-]+)", text)
    if not found:
        raise SystemExit(f"FAILED: no sign-in link in {text!r}")
    return found.group(1)


# ------------------------------------------------------------ what a browser does
def page_and_files(s, base):
    """The page at `base`, and every file it loads, resolved the way a browser resolves them."""
    r = s.get(base)
    check(r.status_code == 200 and r.headers.get("Content-Type", "").startswith("text/html"),
          f"{base} serves the page ({r.status_code})")
    files = sorted({u for u in re.findall(r'(?:src|href)="([^"]+)"', r.text) if not urlparse(u).scheme})
    check({"app.js", "app.css", "icon.png"} <= set(files), f"the page loads its files by relative paths ({files})")
    for name in files:
        url = urljoin(base, name)
        got = s.get(url)
        check(got.status_code == 200 and len(got.content) > 50, f"{url} loads ({got.status_code})")
    return r


def api_calls():
    """Every API path the page calls, from app.js, so a new one is checked too."""
    with open(os.path.join(ROOT, "cinesets", "static", "app.js")) as f:
        text = f.read()
    return sorted(set(re.findall(r'api\("(api/[a-z/]+)', text)))


def sign_in_through(s, base, key, https):
    """Sign in at `base` like the page does, then make signed-in API calls with the cookie the browser kept."""
    headers = {"X-CineSets": "1"}
    paths = api_calls()
    check({"api/login", "api/session", "api/info", "api/settings", "api/collections"} <= set(paths),
          f"app.js calls the API by relative paths ({len(paths)} of them)")
    r = s.get(urljoin(base, "api/info"), headers=headers)
    check(r.status_code == 401, f"{base}: the API asks for a sign-in first ({r.status_code})")
    r = s.get(urljoin(base, "api/session"), headers=headers)
    check(r.status_code == 200 and r.json()["sign_in"] and not r.json()["signed_in"], f"{base}: not signed in yet")
    r = s.post(urljoin(base, "api/login"), json={"key": key}, headers=headers)
    check(r.status_code == 200 and r.json() == {"signed_in": True},
          f"{base}: the access key signs in ({r.status_code} {r.text[:120]})")
    cookie = r.headers.get("Set-Cookie", "")
    parts = [p.strip() for p in cookie.split(";")]
    check(parts[0].startswith("cinesets=") and "HttpOnly" in parts and "SameSite=Strict" in parts
          and not any(p.lower().startswith("path=") for p in parts),
          f"{base}: the session cookie is HttpOnly and SameSite=Strict, with no Path ({cookie.split('=')[0]}=...)")
    check(("Secure" in parts) == https, f"{base}: the cookie is {'' if https else 'not '}marked Secure")
    kept = [c for c in s.cookies if c.name == "cinesets"]
    want = urlparse(urljoin(base, "api/login")).path.rsplit("/", 1)[0]
    check(len(kept) == 1 and kept[0].path == want, f"{base}: the browser keeps the cookie for {want}")
    for path in ("api/session", "api/info", "api/settings", "api/collections"):
        r = s.get(urljoin(base, path), headers=headers)
        check(r.status_code == 200 and (path != "api/session" or r.json()["signed_in"]),
              f"{base}: signed in, {path} answers ({r.status_code})")
    r = s.get(urljoin(base, "api/info"))
    check(r.status_code == 403, f"{base}: an API call without the dashboard's header is refused ({r.status_code})")


def check_proxy(name, ports, key, has_local, header_sites):
    log(f"--- {name}")
    https, http = f"https://{{}}:{ports['https']}/", f"http://{{}}:{ports['http']}/"

    # a) its own name
    s = requests.Session()
    s.verify = False
    base = https.format("cinesets.test")
    r = page_and_files(s, base)
    check("Strict-Transport-Security" not in r.headers, f"{name}: no HSTS unless public")
    sign_in_through(s, base, key, https=True)

    # a) under a path, with the redirect to the path with a slash
    s = requests.Session()
    s.verify = False
    bare = https.format("example.test") + "cinesets"
    r = s.get(bare, allow_redirects=False)
    to = urljoin(bare, r.headers.get("Location", ""))
    check(r.status_code in (301, 302, 308) and to == bare + "/",
          f"{name}: /cinesets sends the browser to /cinesets/ ({r.status_code} to {r.headers.get('Location')})")
    page_and_files(s, bare + "/")
    sign_in_through(s, bare + "/", key, https=True)

    # b) public: true behind HTTPS
    s = requests.Session()
    s.verify = False
    base = https.format("public.test")
    r = page_and_files(s, base)
    check(r.headers.get("Strict-Transport-Security") == "max-age=31536000", f"{name}: public over HTTPS sends HSTS")
    sign_in_through(s, base, key, https=True)

    # b) and over plain http: refused, even when the browser claims HTTPS
    base = http.format("plain.test")
    for claim in ({}, {"X-Forwarded-Proto": "https"}):
        s = requests.Session()
        r = s.post(base + "api/login", json={"key": key}, headers={"X-CineSets": "1", **claim})
        how = " with a made-up X-Forwarded-Proto" if claim else ""
        check(r.status_code == 403 and "HTTPS" in r.json()["error"] and "Set-Cookie" not in r.headers,
              f"{name}: public over plain http refuses the sign-in{how} ({r.status_code})")
        check("Strict-Transport-Security" not in r.headers, f"{name}: no HSTS over plain http")

    # c) sign-in off: turned away through the proxy
    if has_local:
        base = http.format("local.test")
        for path, headers in (("", {}), ("api/session", {"X-CineSets": "1"})):
            r = requests.get(base + path, headers=headers)
            check(r.status_code == 403 and "Sign-in is turned off" in r.text,
                  f"{name}: sign-in off turns away {'the page' if not path else path} ({r.status_code})")

    # d) nginx: which proxy_set_header lines are needed
    if header_sites:
        s = requests.Session()
        s.verify = False
        sign_in_through(s, https.format("proto-only.test"), key, https=True)
        log(f"ok: {name}: with only X-Forwarded-Proto, public sign-in over HTTPS works (Host and X-Forwarded-For "
            "aren't needed)")
        r = requests.post(https.format("no-headers.test") + "api/login", json={"key": key},
                          headers={"X-CineSets": "1"}, verify=False)
        check(r.status_code == 403 and "HTTPS" in r.json()["error"],
              f"{name}: without X-Forwarded-Proto, public sign-in over HTTPS is refused ({r.status_code})")


# ------------------------------------------------------------ the test
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docker", action="store_true", help="run Caddy and nginx from their official Docker images")
    ap.add_argument("--image", help="also run the dashboard from this CineSets image, on a Docker network")
    ap.add_argument("--caddy-image", default="caddy:2")
    ap.add_argument("--nginx-image", default="nginx:stable")
    ap.add_argument("--logs", help="keep every log here (default: a temporary folder)")
    args = ap.parse_args()
    if args.image:
        args.docker = True
    work = tempfile.mkdtemp(prefix="cinesets-proxy-e2e-")
    logs = os.path.abspath(args.logs) if args.logs else os.path.join(work, "logs")
    os.makedirs(logs, exist_ok=True)
    folder = os.path.join(work, "config")
    make_config(folder)
    cfg = os.path.join(folder, "config.yml")
    run, passed = Run(work, logs), False
    try:
        # the certificate nginx serves; Caddy makes its own
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
                        "-subj", "/CN=cinesets.test", "-addext", "subjectAltName=" + ",".join(f"DNS:{n}" for n in NAMES),
                        "-keyout", os.path.join(work, "key.pem"), "-out", os.path.join(work, "cert.pem")],
                       check=True, capture_output=True)
        os.chmod(os.path.join(work, "key.pem"), 0o644)  # nginx in its container reads it as another user

        # the dashboards, after the sign-in link (which makes the access key, so they all start with the same one)
        if args.image:
            # the files in config/ stay this user's, so they can be read and removed afterwards
            ids = ["-e", f"PUID={os.getuid()}", "-e", f"PGID={os.getgid()}", "-v", f"{folder}:/config"]
            key = key_from(run.docker("run", "--rm", *ids, args.image, "web", "--link").stdout)
            refused = run.docker("run", "--rm", *ids, args.image, "web", "--host", "0.0.0.0", "--no-sign-in",
                                 check=False)
            check(refused.returncode != 0 and "Sign-in can only be turned off" in refused.stdout + refused.stderr,
                  "in a container, the dashboard won't start with sign-in off on 0.0.0.0")
            run.docker("network", "create", NETWORK)
            run.network = True
            # like the cinesets-web service in docker-compose.example.yml, published on the host's 127.0.0.1
            run.container("cinesets-web", "--network", NETWORK, "-p", f"127.0.0.1:{PORTS['signed']}:8095", *ids,
                          args.image, "web", "--host", "0.0.0.0")
            run.container("cinesets-web-public", "--network", NETWORK, "-p", f"127.0.0.1:{PORTS['public']}:8095", *ids,
                          args.image, "web", "--host", "0.0.0.0", "--public")
            up = {"signed": "cinesets-web:8095", "public": "cinesets-web-public:8095"}
        else:
            key = key_from(subprocess.run([sys.executable, "-m", "cinesets", "web", "--link", "--config", cfg],
                                          cwd=ROOT, capture_output=True, text=True, timeout=60).stdout)
            for which, flags in (("signed", []), ("public", ["--public"]), ("local", ["--no-sign-in"])):
                run.start(f"dashboard-{which}", [sys.executable, "-m", "cinesets", "web", "--config", cfg,
                                                 "--port", str(PORTS[which]), *flags], cwd=ROOT)
            up = {k: f"127.0.0.1:{p}" for k, p in PORTS.items()}
        session = {"X-CineSets": "1"}
        for which in [w for w in PORTS if w in up]:
            wait_for(f"the {which} dashboard", lambda: requests.get(f"http://127.0.0.1:{PORTS[which]}/api/session",
                                                                    headers=session, timeout=5).ok)
        # straight to the dashboard, as a browser on this machine (or a proxy on the host, for the container) does
        sign_in_through(requests.Session(), f"http://127.0.0.1:{PORTS['signed']}/", key, https=False)
        if "local" in up:
            check(requests.get(f"http://127.0.0.1:{PORTS['local']}/").status_code == 200,
                  "sign-in off answers a browser on this machine")

        # the proxies: on this machine or the host network, or beside the dashboard on its Docker network
        bind = None if args.image else "127.0.0.1"
        here = None if args.docker else work
        with open(os.path.join(work, "Caddyfile"), "w") as f:
            f.write(caddyfile(up, here, bind))
        with open(os.path.join(work, "nginx.conf"), "w") as f:
            f.write(nginx_conf(up, here, bind, "/work" if args.docker else work))
        if args.docker:
            mount = ["-v", f"{work}:/work:ro"]
            for name, ports, image, cmd in (
                    ("proxy-e2e-caddy", CADDY, args.caddy_image,
                     ["caddy", "run", "--config", "/work/Caddyfile", "--adapter", "caddyfile"]),
                    ("proxy-e2e-nginx", NGINX, args.nginx_image,
                     ["nginx", "-c", "/work/nginx.conf", "-g", "daemon off;"])):
                # the same port numbers inside and out, so nginx's redirect names the right port
                net = ["--network", "host"]
                if args.image:
                    net = ["--network", NETWORK] + [a for p in ports.values() for a in ("-p", f"127.0.0.1:{p}:{p}")]
                run.container(name, *net, *mount, image, *cmd)
        else:
            os.makedirs(os.path.join(work, "nginx-temp"), exist_ok=True)
            home = os.path.join(work, "caddy-home")  # Caddy keeps its files here, not in your home folder
            run.start("caddy", ["caddy", "run", "--config", "Caddyfile", "--adapter", "caddyfile"],
                      env={"HOME": home, "XDG_DATA_HOME": os.path.join(home, "data"),
                           "XDG_CONFIG_HOME": os.path.join(home, "config")})
            run.start("nginx", ["nginx", "-p", work, "-c", os.path.join(work, "nginx.conf"),
                                "-e", os.path.join(logs, "nginx-error.log"), "-g", "daemon off;"])
        for name, ports in (("Caddy", CADDY), ("nginx", NGINX)):
            wait_for(name, lambda: requests.get(f"https://cinesets.test:{ports['https']}/", verify=False,
                                                timeout=5).status_code == 200)
        run.running()

        check_proxy("Caddy", CADDY, key, has_local=not args.image, header_sites=False)
        check_proxy("nginx", NGINX, key, has_local=not args.image, header_sites=True)
        run.running()
        passed = True
        log("ALL CHECKS PASSED" + (f" (dashboard in {args.image})" if args.image else ""))
    finally:
        run.stop()
        if not passed:
            for name in sorted(os.listdir(logs)):
                with open(os.path.join(logs, name), errors="replace") as f:
                    print(f"----- {name} (last 60 lines)\n" + "".join(f.readlines()[-60:]), flush=True)
        shutil.rmtree(work, ignore_errors=True)  # the logs stay only when --logs puts them elsewhere


if __name__ == "__main__":
    main()
