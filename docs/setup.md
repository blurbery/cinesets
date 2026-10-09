# Setting up CineSets

Everything about installing CineSets, connecting it to your server, keeping it running and taking it off again.
Back to the [README](../README.md).

## What you need

- Python 3.9 or newer and git, on any machine that can reach your server (the server itself is fine). Or
  [Docker](#docker), which needs neither.
- An API key from your server, made by an administrator:

| Server | The address to give setup | Where to make the API key |
|---|---|---|
| Emby | the address you open it on, like `http://192.0.2.10:8096` | Dashboard > API Keys |
| Jellyfin | the address you open it on, like `http://192.0.2.10:8096` | Dashboard > API Keys |
| Silo | the address its web app opens on, like `http://192.0.2.10:8080` | Admin > API keys: a key for an administrator, with no scopes |

Running more than one server? Give each its own install: its own folder, `config.yml`, `data/` and schedule. They
share nothing, so one can't affect another, and each install only loads the code for its own server.

Every change is tested against real Emby 4.9 and 4.10, Jellyfin 10.10, 10.11 and 12.2, and a pinned Silo build,
and each week against the newest release of each. Emby is fully supported; Jellyfin and Silo are beta until more
people have run them. Plex is next.

## Install

```bash
sudo install -d -o "$(id -un)" /opt/cinesets
git clone https://github.com/blurbery/cinesets.git /opt/cinesets
cd /opt/cinesets && ./install.sh
```

The first line makes the folder and gives it to you, so everything after it runs as you. Run the installer and
CineSets as the user that owns the folder, not with sudo: files that root makes in there would stop that user's own
runs, so CineSets won't run as root in a folder that belongs to someone else. Root is fine where root owns the
folder, as in many LXC containers.

The installer does the rest:

1. It asks for your server's address and API key, and works out whether it's Emby, Jellyfin or Silo.
2. It finds your movie and TV libraries, and asks whether you want every collection or just some.
3. It downloads the streaming logos and does a dry run, which changes nothing.
4. It offers to create the collections, and to keep them updated: trending every 6 hours, charts and seasonal
   daily, and everything on Sundays.

Posters with Japanese, Chinese or Korean text need one more download, the font that draws it (Noto Sans CJK, about
38 MB, from GitHub). CineSets gets it by itself the first time a poster needs it, or `./run.sh fonts` gets it now
(`docker compose run --rm cinesets fonts` on Docker).

Then open the dashboard with `./run.sh web` to change collections and posters. Every setting is also explained
in `config.example.yml`.

## Your server

### Emby and Jellyfin

Collections are server-wide, on the Collections page, in the order CineSets gives them. Nothing else to set up.

### Silo

Give setup the address Silo's web app opens on (port 8080 unless you changed it). If you give it Silo's
Jellyfin-compatible port, it finds Silo's own address for you. CineSets talks to Silo's own API, because the
Jellyfin-compatible one can't make collections.

- **Where collections go:** they're Silo library collections, and each one lives in one library, picked from
  where its titles are.
  - That's usually your main Movies or TV Shows library. Setup lists each type's biggest library first in
    `config.yml`.
  - A collection with at least two thirds of its titles in another library, like an anime or an international
    one, goes there instead.
  - A Silo collection only shows titles from its own library. Titles that are only in another library are left
    out, and the next ones on the list take their place.
- **Order:** collections are kept in Collections page order in each library. Collections CineSets didn't make
  keep their places.
- **Seeing them all:** Silo's server-wide Collections page shows up to 20 per library. Each library's "Explore
  all" shows them all.
- **The first `apply`:** Silo adds titles to a collection one at a time, so it takes a while on a big library.
  The first run also looks up each TV show's IMDb and TMDB ids once, so lists match the same shows they do on
  Emby, and keeps them in `data/silo-ids.json`. A show missing some of them is looked up again after a week.

### A self-signed certificate

If your server's `https://` address has a certificate CineSets doesn't trust (a self-signed one, say), it stops
and says so. Set `verify` under `server` in `config.yml` to the CA certificate file that signed it (a path relative
to `config.yml`'s folder; on Docker, one inside the container), or to `false` to skip the check, which is only wise
on your own network. It covers everything CineSets fetches from the server, Silo's artwork storage included.
Setup asks about it when it meets such a certificate: point it to the CA certificate file, skip the check, or stop.
It writes your answer into `config.yml`. Run without a terminal, setup stops and says so instead.

## Docker

Each release is published as `ghcr.io/blurbery/cinesets` for amd64 and arm64. The `1` tag follows every 1.x
release, `latest` follows every release, and `1.5.0` (say) stays on that version.

```bash
mkdir cinesets && cd cinesets
curl -fsSLo docker-compose.yml https://raw.githubusercontent.com/blurbery/cinesets/main/docker-compose.example.yml
# set PUID and PGID in docker-compose.yml to your user (id -u and id -g)
docker compose pull
docker compose run --rm cinesets setup     # your server's address and API key, and which collections
docker compose run --rm cinesets logos
docker compose up -d                       # creates the collections, then keeps them updated
```

Inside the container `127.0.0.1` is the container itself, so give setup your server's LAN address (port 8080 for
Silo). `up -d` runs the schedule from `config.yml`, the first time starting with everything straight away. When
each job last ran is kept in `data/`, so a restart carries on where it left off, a job that didn't finish is tried
again after about an hour. `docker compose stop` lets it finish the collection it's on first, and if Docker's grace
period runs out nothing is lost, as the record is saved after each collection. Changes to
`config.yml`, from the dashboard or by hand, apply from the next job; restart the container only after changing
the `schedule` itself. Any command in the README works as `docker compose run --rm cinesets <command>`.

To build the image yourself instead, clone the repository, copy `docker-compose.example.yml` to
`docker-compose.yml`, swap its `image` line for the two `build` lines under it, and run
`docker compose build --pull` before `setup`. `--pull` fetches the newest Python base image, with its security
fixes; without it Docker keeps reusing the one it has.

More than one server on Docker: give each install its own folder with its own name, like `cinesets-emby` and
`cinesets-jellyfin` (Compose names the project after the folder, so two folders both called `cinesets` would
replace each other's containers). If you keep the dashboard running with the `cinesets-web` service, give each one
its own host port by changing the first number in `127.0.0.1:8095:8095`, like `127.0.0.1:8097:8095`, and point
Tailscale or your proxy at that port.

## Unraid, TrueNAS SCALE and Synology

Use the Docker image on these, with CineSets' folder somewhere that survives a reboot and an update:

- **Unraid** keeps its root filesystem in RAM, so `/opt` and the crontab are gone after a reboot. Use the template in
  `deploy/unraid/cinesets.xml`, which keeps everything in `/mnt/user/appdata/cinesets`. In Unraid's terminal:

  ```bash
  wget -O /boot/config/plugins/dockerMan/templates-user/my-CineSets.xml \
    https://raw.githubusercontent.com/blurbery/cinesets/main/deploy/unraid/cinesets.xml
  docker run --rm -it -e PUID=99 -e PGID=100 -v /mnt/user/appdata/cinesets:/config ghcr.io/blurbery/cinesets:1 setup
  docker run --rm -it -e PUID=99 -e PGID=100 -v /mnt/user/appdata/cinesets:/config ghcr.io/blurbery/cinesets:1 logos
  ```

  Then add the container from the CineSets template (Docker, Add Container) and turn on its autostart. Use
  `docker run` as above for other commands too, rather than the container's console, which runs as root.
- **TrueNAS SCALE** can't install `python3-venv`, so the installer can't make its Python environment. Run the same
  `setup` and `logos` commands in its shell, with a dataset of your own in place of `/mnt/user/appdata/cinesets` and
  the apps user (`PUID=568`, `PGID=568`). Then add a Custom App with the image `ghcr.io/blurbery/cinesets:1`, that
  dataset mounted at `/config` and the same `PUID` and `PGID`.
- **Synology** has no git or sudo by default. Make a Container Manager project from `docker-compose.example.yml` in
  a shared folder such as `/volume1/docker/cinesets`, with `PUID` and `PGID` set to your DSM user. Setup needs a
  terminal: turn on SSH, sign in as an administrator and run the `setup` and `logos` commands above with `sudo` in
  front, your user's ids and `/volume1/docker/cinesets/config` in place of `/mnt/user/appdata/cinesets`. Then start
  the project.

## Keeping it updated

The installer can add the schedule to your crontab: Trending Top 20 every 6 hours, charts and seasonal daily,
and everything on Sundays. To run it from `/etc/cron.d` instead, `deploy/cron.example` has the same jobs: put the
user that owns the folder in it, not root. No cron on the machine (some NAS systems and minimal containers)? Run the
same commands from a systemd timer or another scheduler, or use Docker, which runs the `schedule` from `config.yml`.
CineSets takes its own lock, so overlapping runs wait for each other.

Each `plan` and `apply` ends with a line like `Summary: 3 created, 40 updated, 2 left as they are (below the
minimum), 1 failed`, and `Stopped early: ...` above it when it stopped to spare the server. It exits with code 1
when something failed or it stopped early, so cron mail, systemd and the dashboard show the problem. Collections
left as they are because too few of their titles are in your library don't count as failures.

## Updating CineSets

```bash
git pull && ./install.sh
```

The installer keeps your settings, skips the questions you've already answered and won't add a second schedule. It
also brings the Python packages to the tested versions in `constraints.txt`, and makes the Python environment again
if a Python upgrade broke it.

On Docker:

- with the published image: `docker compose pull && docker compose up -d`;
- with an image you build: `git pull && docker compose build --pull && docker compose up -d`.

What changed is on the [Releases](https://github.com/blurbery/cinesets/releases) page.

> [!IMPORTANT]
> Keep the `data/` folder (Docker: `./config/data`). It's how CineSets knows which collections are its own. If
> you lose it, run `./run.sh adopt --all` so it takes them back instead of making new ones.

<details>
<summary><b>Updating an older install</b></summary>

- **A `docker-compose.yml` you copied before the published image** still builds from the folder, and `git pull`
  doesn't change it. To use the published image, replace its `build: .` and `image: cinesets:local` lines with
  `image: ghcr.io/blurbery/cinesets:1` (and drop `pull_policy: never` from `cinesets-web`), then
  `docker compose pull && docker compose up -d`. You can also drop `container_name`.
- **A schedule in `/etc/cron.d` that runs as root**, from an older `deploy/cron.example`, now stops with a note in
  `logs/` when the folder belongs to another user. Put that user in place of `root` in the file, and give them back
  anything root made there: `sudo chown -R <user> /opt/cinesets`. The installer warns about both.

</details>

## Uninstalling

With the installer:

1. `./install.sh --uninstall` takes this folder's schedule out of your crontab (only this folder's, so other installs
   keep theirs) and shows what it took out. If you installed with sudo, it's in root's crontab:
   `sudo ./install.sh --uninstall`. It also tells you about anything else that runs from the folder:
   - a schedule in `/etc/cron.d`: `sudo rm /etc/cron.d/cinesets`;
   - the dashboard's systemd unit (`deploy/cinesets-web.service`):
     `sudo systemctl disable --now cinesets-web && sudo rm /etc/systemd/system/cinesets-web.service && sudo systemctl daemon-reload`.
2. `./run.sh remove --all` deletes the collections CineSets made. Everything else on your server is left as it was.
3. Delete the folder: `sudo rm -rf /opt/cinesets` (sudo because `/opt` belongs to root).

On Docker, in the folder with `docker-compose.yml`:

1. `docker compose down` stops the schedule (and the dashboard, if you run it).
2. `docker compose run --rm cinesets remove --all` deletes the collections CineSets made.
3. `docker image rm ghcr.io/blurbery/cinesets:1` removes the image (`cinesets:local` if you built it).
4. Delete the folder, `config/` included.

You can also delete the API key you made for CineSets on your server (Emby and Jellyfin: Dashboard > API Keys;
Silo: Admin > API keys).
