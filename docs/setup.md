# Setting up CineSets

Everything about installing CineSets, connecting it to your server, keeping it running and taking it off again.
Back to the [README](../README.md).

## What you need

- Python 3.9 or newer and git, on any machine that can reach your server (the server itself is fine).
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
sudo git clone https://github.com/blurbery/cinesets.git /opt/cinesets
sudo chown -R "$(id -un)" /opt/cinesets
cd /opt/cinesets && ./install.sh
```

The installer does the rest:

1. It asks for your server's address and API key, and works out whether it's Emby, Jellyfin or Silo.
2. It finds your movie and TV libraries, and asks whether you want every collection or just some.
3. It downloads the streaming logos and does a dry run, which changes nothing.
4. It offers to create the collections, and to keep them updated: trending every 6 hours, charts and seasonal
   daily, and everything on Sundays.

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
Setup can't ask for it yet: give setup the server's `http://` address and change `url` afterwards, or fill in
`config.yml` from `config.example.yml` by hand.

## Docker

```bash
git clone https://github.com/blurbery/cinesets.git && cd cinesets
cp docker-compose.example.yml docker-compose.yml    # set PUID and PGID to your user
docker compose build
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

## Keeping it updated

The installer can add the schedule to your crontab: Trending Top 20 every 6 hours, charts and seasonal daily,
and everything on Sundays. To run it from `/etc/cron.d` instead, `deploy/cron.example` has the same jobs. Docker
runs the `schedule` from `config.yml`. CineSets takes its own lock, so overlapping runs wait for each other.

Each `plan` and `apply` ends with a line like `Summary: 3 created, 40 updated, 2 left as they are (below the
minimum), 1 failed`, and `Stopped early: ...` above it when it stopped to spare the server. It exits with code 1
when something failed or it stopped early, so cron mail, systemd and the dashboard show the problem. Collections
left as they are because too few of their titles are in your library don't count as failures.

## Updating CineSets

```bash
git pull && ./install.sh
```

The installer keeps your settings, skips the questions you've already answered and won't add a second schedule.
On Docker it's `git pull && docker compose build && docker compose up -d`. What changed is on the
[Releases](https://github.com/blurbery/cinesets/releases) page.

> [!IMPORTANT]
> Keep the `data/` folder (Docker: `./config/data`). It's how CineSets knows which collections are its own. If
> you lose it, run `./run.sh adopt --all` so it takes them back instead of making new ones.

## Uninstalling

1. Remove the schedule:
   - if the installer added it: `crontab -l | grep -v cinesets | crontab -`;
   - if you set it up in `/etc/cron.d`: `sudo rm /etc/cron.d/cinesets`;
   - on Docker: `docker compose down`.
2. Run `./run.sh remove --all` to delete the collections CineSets made. Everything else on your server is left as
   it was.
3. Delete the folder. On Silo, you can also revoke CineSets' key under Admin > API keys.
