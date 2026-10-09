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
  <a href="https://github.com/sponsors/blurbery"><img src="https://img.shields.io/badge/sponsor-%E2%9D%A4-ea4aaa?logo=githubsponsors&logoColor=white" alt="Sponsor blurbery"></a>
</p>

<p align="center">
  <a href="docs/setup.md"><b>Setup</b></a> ·
  <a href="docs/preview.md"><b>Preview</b></a> ·
  <a href="docs/screenshots.md"><b>Dashboard tour</b></a> ·
  <a href="docs/architecture.md"><b>How it fits together</b></a> ·
  <a href="https://github.com/blurbery/cinesets/releases"><b>Releases</b></a> ·
  <a href="https://github.com/sponsors/blurbery"><b>♥ Sponsor</b></a>
</p>

I made CineSets because I wanted my server's Collections page to look good without having to look after it.
It builds trending, streaming, genre, best of, kids, regional and seasonal collections, plus 114 franchises and
studios (89 movie franchises from fixed film lists, 14 more from public lists, 7 studios and directors and 4 TV
universes), from what's already in your library. Each one gets a matching poster, they stay in a set order and
they update on a schedule.

It only ever touches collections it made itself. Your films, shows, libraries, users and settings are left
alone. It talks to your server, public [mdblist](https://mdblist.com) lists and Wikimedia Commons (for the
streaming logos), and that's it. No account, no tracking.

> [!NOTE]
> Emby is fully supported. Jellyfin and Silo work and are tested on every change, but they're beta until more
> people have run them. Plex is next.

## Quick start

You need Python 3.9 or newer, git and an API key from your server, made by an administrator.

```bash
sudo git clone https://github.com/blurbery/cinesets.git /opt/cinesets
sudo chown -R "$(id -un)" /opt/cinesets
cd /opt/cinesets && ./install.sh
```

The installer works out whether your server is Emby, Jellyfin or Silo, finds your libraries, asks which
collections you want, does a dry run and offers to make them and keep them updated. The
[setup guide](docs/setup.md) has each server's details, Docker, updating and uninstalling.

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
| `./run.sh forget KEY` | Stops managing a collection and leaves it on your server as it is (`adopt` takes it back) |

Most of them take `--only key1,key2` or `--group streaming`. `./run.sh --help` shows the rest.

## Dashboard

`./run.sh web` starts a web page where you pick collections, change the poster colours, shading, text and font,
drag and resize the title and label (for every poster, a whole section or one collection), shuffle or choose each
collection's artwork, set how many titles each collection holds, add MDBList lists or make new collections from
them, preview every poster, then save and apply. It prints a sign-in link; `./run.sh web --demo` tries it with
made-up artwork and no server.

It listens on this machine only, needs you signed in and never shows your API key to the browser.
The [dashboard tour](docs/screenshots.md) shows each part of it, and the [dashboard guide](docs/dashboard.md) covers
signing in, reaching it from another computer (Tailscale, Caddy, nginx) and keeping it running.

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

Colours, shading, text, the font and where the text sits are settings under `posters` in `config.yml`, easiest
changed in the dashboard. New installs also give every server its
own random artwork from its library, so no two look the same (streaming posters keep their own look). The
[preview](docs/preview.md#poster-style) has pictures of every setting.

```yaml
posters:
  artwork: random    # or fixed
  accent: auto       # each collection's own colour, or one for all: silver, orange, "#ff3366" and more
  shade: medium      # light, medium or dark
  title: gradient    # gradient, solid or white
  font: poppins      # or bebas-neue, cinzel-decorative, creepster and eight more
  align: left        # left or centre
  case: normal       # normal or upper
```

Twelve fonts come with CineSets, for every poster, a whole section or a single collection. Here's each one on a
collection it suits; the [preview](docs/preview.md#fonts) lists them all.

![Every font, each on a collection it suits](docs/images/style-fonts.jpg)

## Your own collections

The easiest way is the dashboard's Lists tab: paste an [MDBList](https://mdblist.com) list's address and CineSets
makes a collection from it, or adds it to one you have. Those go in `custom-collections.yml`, which updates never
touch.

To change the built-in catalogue itself, copy `collections.yml` to `my-collections.yml` (on Docker, put it in
`./config`), set `collections_file: my-collections.yml` in `config.yml` and change whatever you like. The top of
the file explains every field. A collection needs at least 8 matches in your library before it's made (fewer for
franchises and small lists), so streaming ones like Stan and regional ones like Korean Series only show up if you
have enough of their titles.

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

## Docs

- [Setup guide](docs/setup.md): installing, each server's address and API key, Docker, updating and uninstalling
- [Preview](docs/preview.md): every section and poster style
- [Dashboard tour](docs/screenshots.md): every tab of the dashboard, in pictures
- [Dashboard guide](docs/dashboard.md): signing in, [reaching it from another computer](docs/dashboard.md#reaching-it-from-another-computer)
  (Tailscale, Caddy, nginx, Docker) and keeping it running
- [How CineSets fits together](docs/architecture.md): the shared centre and the module each server gets

If CineSets is useful to you, you can [sponsor me on GitHub](https://github.com/sponsors/blurbery). Thank you.

## Contributing

Found a bug or got an idea? [Open an issue](https://github.com/blurbery/cinesets/issues/new/choose). PRs are
welcome too, just have a read of [CONTRIBUTING.md](CONTRIBUTING.md) first. Using AI is fine, but say so in the
PR.

> [!CAUTION]
> Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Licence

[AGPL-3.0-or-later](LICENSE) with a few extra terms in [NOTICE](NOTICE): keep the "CineSets by blurbery"
credit, mark your changes if you share a modified version, and the licence doesn't cover the CineSets name or
logo. The poster fonts in `assets/fonts` are under the SIL Open Font License. Streaming logos belong to their
owners and are downloaded to your own server, not shipped with CineSets.
