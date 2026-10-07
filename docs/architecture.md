# How CineSets fits together

CineSets is built like an atom. Everything that makes a collection good sits in the centre. Each media server is
its own module that orbits it, and the centre only ever talks to a server through one short list of operations.
So a fix for one server can't change what another one gets, and adding a server doesn't touch the centre. Back
to the [README](../README.md).

<p align="center"><img src="images/architecture.svg" alt="The CineSets centre as the nucleus of an atom, ringed by the shell of server operations, with Emby and Jellyfin orbiting on one module, Silo on its own, and a dashed spot for the next server" width="900"></p>

## The centre

This is the part every server shares. It decides what each collection holds, what its poster looks like and where
it sits on the page, without knowing which server it's talking to.

| File | What it does |
|---|---|
| `collections.yml` | The catalogue: every collection, its section, its lists or franchise titles and its colours |
| `catalog.py` | Reads the catalogue and `custom-collections.yml`, and works out names, page order and sizes |
| `lists.py` | Fetches public MDBList lists, refreshing them every few hours and keeping a copy in case MDBList is down |
| `engine.py` | The library index, list matching, posters and the writes, with the safety rules: CineSets only touches collections it made, writes only what changed and backs off when a server struggles |
| `posters.py` | Draws the posters |
| `logos.py` | Downloads the streaming logos onto your server |
| `scenes.py` | Made-up artwork for the docs and the dashboard's demo mode |
| `web.py`, `static/` | The dashboard |
| `cli.py`, `config.py`, `store.py` | Commands, settings and the record of what CineSets owns |

## The shell

`cinesets/servers/__init__.py` lists what the centre asks of a server. Every server module answers the same
questions:

| Group | Operations |
|---|---|
| Reads | `media_libraries`, `library_folders`, `library_items`, `genres`, `alive`, `backdrop_image` |
| Collections | `list_collections`, `create_collection`, `wait_until_ready`, `members`, `add_items`, `remove_items`, `upload_poster`, `set_details`, `delete_collection`, `admin_user` |
| Setup | `detect(url)`: is this my kind of server? (no API key needed) |
| Optional | `arrange`, `narrow` and `prepare`, for a server that orders collections by number or keeps each one in a single library (Silo) |

`servers.connect(cfg)` picks the module from `server.type` in `config.yml`, and `servers.detect(url)` asks each
module in turn during setup. The engine never builds a request itself.

## The servers

### Emby and Jellyfin: `servers/emby.py`

Emby and Jellyfin share one API (Jellyfin started as a fork of Emby), so they share one module. The few
differences live inside it:

- **Base path:** Emby serves the API under `/emby`; Jellyfin serves it at the root.
- **Reading a collection's titles:** Jellyfin only lists them for a user, so CineSets asks as the administrator.
- **Locking the sort name:** Emby can lock it; Jellyfin has no such lock.

### Silo: `servers/silo.py`

Silo's Jellyfin-compatible port can show collections but can't make them, so this module uses Silo's own API.

| | Emby and Jellyfin | Silo |
|---|---|---|
| API | `/emby/...` or `/...`, key in `X-Emby-Token` | `/api/v2/...`, `Authorization: Bearer` with an administrator's key that has no scopes |
| A collection is | a BoxSet, shown server-wide | a manual library collection, in one library |
| Which library | all of them | the first library of its type in `config.yml`, or the one holding at least two thirds of its titles (an anime or an international library, say). Setup lists each type's biggest library first |
| A title is | the server's item id | a Silo content id such as `movie-tmdb-105` |
| Matching ids | every provider id comes with the title | a content id carries one; a show's others are looked up once and kept in `data/silo-ids.json` |
| Adding titles | 40 at a time | one at a time, with a short pause between them |
| Poster | uploaded as base64 | uploaded as a file |
| Order inside a collection | `DisplayOrder` | a default sort: release date or title |
| Order on the page | a locked sort name | Silo's per-library order list, which CineSets rewrites only when it changes and without moving collections it didn't make |

## Adding a server

1. Write `cinesets/servers/<name>.py` with a class that answers every operation in the shell. Start from
   `silo.py` if the server has its own way of doing things, or from `emby.py` if it speaks the Emby API.
2. Add it to `NAMES` and `_classes()` in `cinesets/servers/__init__.py`, and its type to `check_type` in
   `config.py`.
3. Add unit tests with a fake server that answers the same paths as the real one (`tests/conftest.py` and
   `tests/test_silo.py` are both examples).
4. Add an end-to-end job in `.github/workflows/ci.yml` that runs CineSets against a real, throwaway server.

Nothing in the centre should need to change. If it does, the shell is missing an operation: add it there,
optional if only some servers need it, so the other modules stay as they are.

## How each part is tested

- **The centre and the Emby/Jellyfin module:** `tests/test_engine.py` and `tests/test_web.py` run against an in-memory
  server that uses the real Emby/Jellyfin operations, so they check the exact requests a server gets.
- **Silo:** `tests/test_silo.py` runs the real Silo module against an in-memory Silo that follows its rules.
- **Real servers:** every pull request runs CineSets end to end against throwaway Emby, Jellyfin and Silo
  servers on GitHub Actions (`tests/e2e/`). The Silo job sets up a brand-new Silo the way a new user would,
  `cinesets setup` included.
