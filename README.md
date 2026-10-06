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

> [!NOTE]
> Emby is fully supported. Jellyfin works and is tested on every change, but it's beta until more people have
> run it. Silo support is coming.

## Install

You need Python 3.9 or newer, git and an API key from your server (Dashboard > API Keys).

```bash
sudo git clone https://github.com/blurbery/cinesets.git /opt/cinesets
sudo chown -R "$(id -un)" /opt/cinesets
cd /opt/cinesets && ./install.sh
```

The installer asks for your server address and API key, finds your libraries and does a dry run that doesn't
change anything. Check `config.yml` (every setting is explained in `config.example.yml`), then:

```bash
./run.sh apply
```

Last step is the schedule the installer prints: trending every 6 hours, charts and seasonal daily, and
everything on Sundays.

<details>
<summary><b>Docker</b></summary>

```bash
git clone https://github.com/blurbery/cinesets.git && cd cinesets
cp docker-compose.example.yml docker-compose.yml    # set PUID and PGID to your user
docker compose build
docker compose run --rm cinesets setup
docker compose run --rm cinesets logos
docker compose run --rm cinesets plan
docker compose up -d
```

Inside the container `127.0.0.1` is the container itself, so give it your server's LAN address. `up -d` runs
the schedule from `config.yml`. Restart the container after you change `config.yml`. Any command below works
as `docker compose run --rm cinesets <command>`.

</details>

## Commands

| Command | What it does |
|---|---|
| `./run.sh plan` | Dry run, shows what would change |
| `./run.sh apply` | Creates and updates the collections |
| `./run.sh posters` | Makes the posters only, with preview sheets in `data/samples` |
| `./run.sh list` | Lists every collection and its key |
| `./run.sh adopt --all` | Takes your collections back after a reinstall |
| `./run.sh remove --only KEY` | Deletes a collection CineSets made (`--all` for all of them) |

Most of them take `--only key1,key2` or `--group streaming`. `./run.sh --help` shows the rest.

## Your own collections

Copy `collections.yml` to `my-collections.yml` (on Docker, put it in `./config`), set
`collections_file: my-collections.yml` in `config.yml` and change whatever you like. The top of the file
explains every field. A collection needs at least 8 matches in
your library before it's made, so regional ones like Stan only show up if you have the shows.

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

On Docker it's `git pull && docker compose build && docker compose up -d`. What changed is on the
[Releases](https://github.com/blurbery/cinesets/releases) page.

> [!IMPORTANT]
> Keep the `data/` folder (Docker: `./config/data`). It's how CineSets knows which collections are its own. If
> you lose it, run `./run.sh adopt --all` so it takes them back instead of making new ones.

<details>
<summary><b>Uninstalling</b></summary>

Remove the schedule (`sudo rm /etc/cron.d/cinesets`, or `docker compose down`), run `./run.sh remove --all` to
delete the collections CineSets made, then delete the folder.

</details>

## Contributing

Found a bug or got an idea? [Open an issue](https://github.com/blurbery/cinesets/issues/new/choose). PRs are
welcome too, just have a read of [CONTRIBUTING.md](CONTRIBUTING.md) first. Using AI is fine, but say so in the
PR.

> [!CAUTION]
> Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Licence

[AGPL-3.0-or-later](LICENSE) with a few extra terms in [NOTICE](NOTICE): keep the "CineSets by blurbery"
credit, mark your changes if you share a modified version, and the licence doesn't cover the CineSets name or
logo. Poppins is under the SIL Open Font License. Streaming logos belong to their owners and are downloaded to
your own server, not shipped with CineSets.
