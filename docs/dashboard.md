# The dashboard

`./run.sh web` starts a web page for picking collections, styling the posters (for every poster, a whole section or
one collection), moving and resizing their text, choosing their artwork, setting how many titles each collection
holds, and making new collections from MDBList lists. Back to the [README](../README.md).

![The Design tab: one collection's poster with its text boxes, and the style settings](images/dashboard.jpg)

[More screenshots](screenshots.md) show each tab and the sign-in page.

## Signing in

The first time it starts, CineSets makes an access key and keeps it in `data/web.json`, which only you can read.
In a terminal, the dashboard prints a link with the key on the end. Open it and you're signed in for 30 days on
that browser.

```bash
./run.sh web --link           # show the sign-in link again
./run.sh web --set-password   # sign in with a password of your own as well (12 characters or more)
./run.sh web --new-key        # a new key: everyone is signed out and old links stop working
```

On Docker, put `docker compose run --rm cinesets` in front of `web ...`.

> [!TIP]
> The key sits after `#` in the link, so it never reaches your server or proxy logs. If you see the dashboard
> through Tailscale, a proxy or another computer, use that address with the same `#key=...` on the end.

What keeps other people and other sites out:

- It listens on this machine only (127.0.0.1) unless you ask for more with `--host`.
- Every request needs your session, which is an HttpOnly, SameSite=Strict cookie signed with a secret only this
  machine knows. It's marked Secure behind an HTTPS proxy.
- Every request must also carry a header that other web sites can't add, so a page you visit elsewhere can't use
  your session.
- Wrong keys and passwords are rate limited.
- Your media server's API key never reaches the browser.
- The page loads nothing from the internet.

## Designing

The Design tab has two modes:

- **Whole section:** pick a section, or **Every section**, and change the text and the poster colour, shade and
  tint for every poster in it.
- **Each poster:** pick one poster and change anything about it, including its artwork and its words.

A poster's own settings win over its section's, which win over Every section. Streaming posters keep the service's
artwork, but can use another version of its logo where there is one (the Netflix N, the 2024 Prime Video logo,
the Apple TV logo and others), in its own colours or all white. `./run.sh logos` downloads every version.

## No sign-in, on this machine only

If you only ever use the dashboard on the machine CineSets runs on, you can turn sign-in off:

```yaml
web:
  sign_in: false
```

Or just for one run: `./run.sh web --no-sign-in`. It only works when the dashboard listens on 127.0.0.1, and then
it answers only that machine: a browser on it, or an SSH tunnel from your own computer (which needs a login to the
machine anyway). Anything passed on by a proxy or Tailscale, or using another name for the machine, is turned
away. So turning sign-in off can't put an open dashboard on your network or the internet.

## On the internet, behind the sign-in page

To reach it from anywhere, put it behind a reverse proxy with HTTPS (see below) and tell CineSets it's public:

```yaml
web:
  public: true
```

Or `./run.sh web --public` for one run. Then:

- sign-ins are only taken over HTTPS;
- browsers are told to always use HTTPS;
- the session cookie is marked Secure;
- wrong keys and passwords stay rate limited.

Set a password of your own with `./run.sh web --set-password`, or use the access key link.

> [!WARNING]
> Keep CineSets updated if it's reachable from the internet, and think about adding your proxy's own sign-in in
> front (basic auth, Authelia, Authentik or similar) for a second lock.

## Lists and your own collections

The Lists tab shows the MDBList lists behind every collection, each linking to its page.

- **Add a list** to a collection, or **make a new collection** by pasting a list's address. CineSets shows how many
  titles the list has and how many are in your library before you save.
- **Your collections and added lists** go in `custom-collections.yml` next to `config.yml`. CineSets reads it as
  well as its own catalogue, so updating CineSets never overwrites them.
- **Removing** a collection there doesn't delete it from your server. `./run.sh remove --unpicked` does that.
- **Franchises** use fixed lists of films, so they can't take extra lists.

## How many titles

"Most titles per collection" caps every collection, so with 25 none holds more than 25. It never makes one bigger:
a Top 20 stays 20. A whole section or a single collection can have its own number instead, higher or lower than
usual. Franchises always keep every film in their list. These are saved under `limits` in `config.yml`.

## Your settings

- **Saving:** writes the `posters`, `collections` and `limits` blocks in `config.yml` and leaves every other line
  and comment alone. The file stays readable by you only, and the old version is kept as `config.yml.bak`.
- **Two people at once:** if `config.yml` changed after you opened the dashboard (another tab, someone else, or a
  hand edit), saving says so instead of overwriting the changes. Reload, then save again.
- **Artwork:** choices are saved as soon as you make them, in `data/state.json` with the rest of CineSets' record.
  Keep the `data/` folder, as the README says.
- **When posters change:** on the next apply, whether that's the Apply button, `./run.sh apply` or the schedule. On
  Docker the schedule reads `config.yml` again before every job, so there's nothing to restart.

## Using it from another computer

Keep the dashboard on 127.0.0.1 and put something in front of it that adds HTTPS and keeps it off the open
internet. Tailscale is the easiest.

> [!CAUTION]
> Don't open the port straight to the internet, and don't use `tailscale funnel`, which makes it public. If it
> must be reachable from the internet, use HTTPS and add your proxy's own sign-in on top (basic auth, Authelia,
> Authentik or similar).

<details>
<summary><b>Tailscale</b></summary>

On the machine running CineSets, with the dashboard running:

```bash
tailscale serve --bg 8095
```

It's then at `https://<machine>.<tailnet>.ts.net/` for devices on your tailnet only, with a proper certificate.
If something else already uses that address, give the dashboard its own port:
`tailscale serve --bg --https 8443 8095`. `tailscale serve reset` turns it off.

Or skip `serve` and listen on the machine's Tailscale address, plain http inside your tailnet:
`./run.sh web --host 100.x.y.z`.

</details>

<details>
<summary><b>Caddy</b></summary>

Its own name:

```caddy
cinesets.example.com {
	reverse_proxy 127.0.0.1:8095
}
```

Or under a path of a site you already have. `handle_path` takes the path off before passing the request on:

```caddy
example.com {
	redir /cinesets /cinesets/
	handle_path /cinesets/* {
		reverse_proxy 127.0.0.1:8095
	}
}
```

</details>

<details>
<summary><b>nginx</b></summary>

```nginx
location = /cinesets { return 301 /cinesets/; }
location /cinesets/ {
    proxy_pass http://127.0.0.1:8095/;    # the slash at the end takes /cinesets off
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

For its own name, use `location /` with `proxy_pass http://127.0.0.1:8095;` and the same headers.

</details>

<details>
<summary><b>An SSH tunnel</b></summary>

From your own computer:

```bash
ssh -L 8095:127.0.0.1:8095 you@your-server
```

Then open the sign-in link on your own computer. It's already `http://127.0.0.1:8095/#key=...`.

</details>

<details>
<summary><b>Your home network</b></summary>

`./run.sh web --host 0.0.0.0` listens on every address of the machine. It's plain http, so the sign-in travels
unencrypted on your network, and anyone there who gets the link can change your settings. Tailscale or a proxy
with HTTPS is better.

</details>

## Keeping it running

By default the dashboard runs only while `./run.sh web` does. To have it always there, for example behind
Tailscale or a proxy:

<details>
<summary><b>Docker</b></summary>

Uncomment the `cinesets-web` service in `docker-compose.yml` (see `docker-compose.example.yml`) and run
`docker compose up -d`. It publishes the dashboard on the host's own 127.0.0.1:8095, for Tailscale or a proxy on
the host to pass on. Get the link with `docker compose run --rm cinesets web --link`.

</details>

<details>
<summary><b>systemd</b></summary>

Copy `deploy/cinesets-web.service` to `/etc/systemd/system/`, set `User` to the account that owns
`/opt/cinesets` (and the paths, if yours differ), then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cinesets-web
./run.sh web --link
```

</details>

Logs from a service or container never show the key; `web --link` does.
