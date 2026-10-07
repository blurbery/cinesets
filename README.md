<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="branding/cinesets-logo-dark-bg.png">
    <img src="branding/cinesets-logo-light-bg.png" alt="CineSets" width="400">
  </picture>
</p>

<p align="center">Automatic, beautiful collections for Emby, Jellyfin and Silo</p>

<p align="center">
  <a href="https://github.com/blurbery/cinesets/actions/workflows/ci.yml"><img src="https://github.com/blurbery/cinesets/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/blurbery/cinesets/releases/latest"><img src="https://img.shields.io/github/v/release/blurbery/cinesets?label=release" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-AGPL--3.0--or--later-blue" alt="Licence: AGPL-3.0-or-later"></a>
</p>

I made CineSets because I wanted my server's Collections page to look good without having to look after it.
It builds trending, streaming, genre, best of, kids and seasonal collections, plus 65 movie franchises, from
what's already in your library. Each one gets a matching poster, they stay in a set order and they update on a
schedule.

It only ever touches collections it made itself. Your films, shows, libraries, users and settings are left
alone. It talks to your server, public [mdblist](https://mdblist.com) lists and Wikimedia Commons (for the
streaming logos), and that's it. No account, no tracking.

<p align="center"><b><a href="docs/preview.md">See every section and poster style in the preview</a> ·
<a href="docs/screenshots.md">See the dashboard</a></b></p>

> [!NOTE]
> Emby is fully supported. Jellyfin and Silo work and are tested on every change, but they're beta until more
> people have run them.

## Install

You need Python 3.9 or newer, git and an API key from your server (Dashboard > API Keys; on Silo, Admin > API
keys, made by an administrator with no scopes).

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

That's it. To change collections and posters later, open the dashboard with `./run.sh web`. Every setting is
also explained in `config.example.yml`.

<details>
<summary><b>Silo</b></summary>

Give setup the address Silo's web app opens on (port 8080 unless you changed it). If you give it Silo's
Jellyfin-compatible port, it finds Silo's own address for you. CineSets talks to Silo's own API, because the
Jellyfin-compatible one can't make collections.

- Collections are Silo library collections, and each one lives in one library, picked from where its titles are.
  That's usually your first Movies or TV Shows library in `config.yml`. A collection with at least two thirds of
  its titles in another library, like an anime library or an international one, goes there instead. A Silo
  collection only shows titles from its own library, so titles that are only in another library are left out,
  and the next ones on the list take their place.
- They're kept in Collections page order in each library. Collections CineSets didn't make keep their places.
- Silo's server-wide Collections page shows up to 20 per library. Each library's Collections tab shows them all.
- Silo adds titles to a collection one at a time, so the first `apply` takes a while on a big library.
- The first run also looks up each TV show's IMDb and TMDB ids once, so lists match the same shows they do on
  Emby. It keeps them in `data/silo-ids.json`.

</details>

<details>
<summary><b>Docker</b></summary>

```bash
git clone https://github.com/blurbery/cinesets.git && cd cinesets
cp docker-compose.example.yml docker-compose.yml    # set PUID and PGID to your user
docker compose build
docker compose run --rm cinesets setup     # your server's address and API key, and which collections
docker compose run --rm cinesets logos
docker compose up -d                       # creates the collections, then keeps them updated
```

Inside the container `127.0.0.1` is the container itself, so give setup your server's LAN address. `up -d` runs
the schedule from `config.yml`, starting with everything straight away. Changes to `config.yml` (from the dashboard or by hand) apply from the next job;
restart the container only after changing the `schedule` itself. Any command below works as
`docker compose run --rm cinesets <command>`.

</details>

## Commands

| Command | What it does |
|---|---|
| `./run.sh plan` | Dry run, shows what would change |
| `./run.sh apply` | Creates and updates the collections |
| `./run.sh posters` | Makes the posters only, with preview sheets in `data/samples` |
| `./run.sh web` | Opens the dashboard: pick collections, style the posters and choose their artwork |
| `./run.sh pick` | Asks which sections or collections you want and saves it in `config.yml` |
| `./run.sh list` | Lists every section and collection with its key, and what's picked |
| `./run.sh apply --reshuffle` | Picks new random artwork for the posters (with `artwork: random`) |
| `./run.sh adopt --all` | Takes your collections back after a reinstall |
| `./run.sh remove --only KEY` | Deletes a collection CineSets made (`--unpicked` for the ones you unpicked, `--all` for all of them) |

Most of them take `--only key1,key2` or `--group streaming`. `./run.sh --help` shows the rest.

## Dashboard

`./run.sh web` starts a web page where you pick collections, change the poster colours, shading and text, drag and
resize the title and label (for every poster, a whole section or one collection), shuffle or choose each
collection's artwork, set how many titles each collection holds, add MDBList lists or make new collections from
them, preview every poster, then save and apply. It prints a sign-in link; `./run.sh web --demo` tries it with
made-up artwork and no server.

[Screenshots](docs/screenshots.md) show each part of it. It listens on this machine only, needs you signed in,
and never shows your API key to the browser. Sign-in can be
turned off for use on this machine alone, or the dashboard can go on the internet behind its sign-in page and
your HTTPS proxy. To use it from another computer, put Tailscale or a reverse proxy with HTTPS in front of it.
[docs/dashboard.md](docs/dashboard.md) covers signing in, how your settings are kept, Tailscale, Caddy, nginx, and
keeping it running on Docker or systemd.

## Picking collections

The collections come in sections: trending and charts, genres, streaming, best of, kids and family, seasonal,
regional, and franchises and studios. Make them all, pick whole sections or pick single collections.
Use the dashboard, or `./run.sh pick` asks you a section at a time and saves your answer, or edit `collections`
in `config.yml`:

```yaml
collections:
  sections: [charts, genres, kids]   # or: all
  include: [m-oscars]                # single collections from other sections
  exclude: [s-trending]              # single collections to leave out
```

The [preview](docs/preview.md#sections) shows every section with its posters and keys. Unpicking a collection
doesn't delete it from your server, it just stops updating; `./run.sh remove --unpicked` deletes those.

## Poster style

Colours, shading, text and where the text sits are settings under `posters` in `config.yml`, easiest changed in the
dashboard. New installs also give every server its
own random artwork from its library, so no two look the same (streaming posters keep their own look). The
[preview](docs/preview.md#poster-style) has pictures of every setting.

```yaml
posters:
  artwork: random    # or fixed
  accent: auto       # each collection's own colour, or one for all: silver, orange, "#ff3366" and more
  shade: medium      # light, medium or dark
  title: gradient    # gradient, solid or white
  align: left        # left or centre
  case: normal       # normal or upper
```

## Your own collections

The easiest way is the dashboard's Lists tab: paste an [MDBList](https://mdblist.com) list's address and CineSets
makes a collection from it, or adds it to one you have. Those go in `custom-collections.yml`, which updates never
touch.

To change the built-in catalogue itself, copy `collections.yml` to `my-collections.yml` (on Docker, put it in
`./config`), set `collections_file: my-collections.yml` in `config.yml` and change whatever you like. The top of
the file explains every field. A collection needs at least 8 matches in your library before it's made, so
regional ones like Stan only show up if you have the shows.

<details>
<summary><b>Examples</b></summary>

From a public mdblist list (swap in a real `user/slug`):

```yaml
  - key: m-heist
    group: bestof
    type: movie
    title: "Heist"
    subtitle: "Movies"
    accent: gold
    lists: [some-user/best-heist-movies]
```

A franchise from a fixed list of films. It needs `min` because there are only three:

```yaml
  - key: m-karatekid
    group: universes
    type: movie
    title: "The Karate\nKid"
    accent: red
    min: 2
    titles:
      - ["The Karate Kid", 1984]
      - ["The Karate Kid Part II", 1986]
      - ["The Karate Kid Part III", 1989]
```

</details>

## Updating

```bash
git pull && ./install.sh
```

The installer keeps your settings, skips the questions you've already answered and won't add a second schedule.
On Docker it's `git pull && docker compose build && docker compose up -d`. What changed is on the
[Releases](https://github.com/blurbery/cinesets/releases) page.

> [!IMPORTANT]
> Keep the `data/` folder (Docker: `./config/data`). It's how CineSets knows which collections are its own. If
> you lose it, run `./run.sh adopt --all` so it takes them back instead of making new ones.

<details>
<summary><b>Uninstalling</b></summary>

Remove the schedule: `crontab -l | grep -v cinesets | crontab -` if the installer added it, `sudo rm
/etc/cron.d/cinesets` if you set it up there, or `docker compose down`. Then run `./run.sh remove --all` to delete
the collections CineSets made, and delete the folder.

</details>

## Contributing

Found a bug or got an idea? [Open an issue](https://github.com/blurbery/cinesets/issues/new/choose). PRs are
welcome too, just have a read of [CONTRIBUTING.md](CONTRIBUTING.md) first. Using AI is fine, but say so in the
PR. [How CineSets fits together](docs/architecture.md) shows the shared centre and the module each server gets.

> [!CAUTION]
> Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Licence

[AGPL-3.0-or-later](LICENSE) with a few extra terms in [NOTICE](NOTICE): keep the "CineSets by blurbery"
credit, mark your changes if you share a modified version, and the licence doesn't cover the CineSets name or
logo. Poppins is under the SIL Open Font License. Streaming logos belong to their owners and are downloaded to
your own server, not shipped with CineSets.
