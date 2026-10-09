# Contributing

Thanks for wanting to help. Bug reports, new collections, fixes and features are all welcome.

> [!NOTE]
> Anyone can open an issue or a pull request, but I'm the only one who merges into `main` and puts out
> releases.

## Before you start

- Small fixes can go straight to a PR. For anything bigger (a new command, a new server type, changing what
  CineSets touches on a server), [open an issue](https://github.com/blurbery/cinesets/issues/new/choose) first
  so we can agree on it before you put the time in.
- Found a security problem? Don't open a public issue. See [SECURITY.md](SECURITY.md).
- Be decent to each other. See the [code of conduct](CODE_OF_CONDUCT.md).

> [!WARNING]
> Keep private stuff out of issues and PRs: server addresses, API keys, user names, and logs you haven't
> cleaned up. Use placeholders like `http://192.0.2.10:8096` and `<api-key>`.

## Reporting a bug

Use the [bug report form](https://github.com/blurbery/cinesets/issues/new?template=bug_report.yml). It asks for
your CineSets version, your server, how you installed CineSets, what you ran and what happened.

> [!TIP]
> `./run.sh plan` doesn't change anything, and its output usually shows what's going on. Paste the part that
> matters, cleaned up.

## Setting up

```bash
git clone https://github.com/<your-user>/cinesets.git && cd cinesets
python3 -m venv venv && venv/bin/pip install -r requirements-dev.txt -c constraints.txt
venv/bin/python -m pytest tests --ignore=tests/e2e
venv/bin/ruff check . && shellcheck install.sh run.sh docker-entrypoint.sh
```

`constraints.txt` holds the dependency versions CineSets is tested with, and install.sh, the Docker image and CI all
install those. `requirements.txt` keeps the oldest versions it works with. Dependabot proposes newer versions every
week. The **Lint** check runs ruff (the rules in `ruff.toml`) and shellcheck, as above.

The unit tests use fake servers (`tests/conftest.py` for Emby and Jellyfin, `tests/test_silo.py` for Silo), so
you don't need a real server to run them. To work on the dashboard, `venv/bin/python -m cinesets web --demo` runs
it with made-up artwork and no server; its page is plain HTML, CSS and JavaScript in `cinesets/static`, with no
build step. `docs/make_preview.py` redraws the pictures in `docs/` after poster changes. Every PR also gets tested
against real throwaway Emby, Jellyfin and Silo servers on GitHub Actions. On your first PR those checks wait until
I approve them.

## Ground rules

> [!IMPORTANT]
> CineSets only touches collections it made, only writes what changed, and stops when the server is
> struggling. Anything that weakens that won't get merged.

- Add tests for what you change.
- Keep it working on Python 3.9 and on Emby, Jellyfin and Silo. Ask before adding a dependency.
- Each media server has its own module in `cinesets/servers/` (`emby.py`, `jellyfin.py`, `silo.py`), and each
  answers every question in `cinesets/servers/base.py` itself. The collections, matching, posters and dashboard
  only ask those questions, so anything server-specific goes in that server's module, where it can't change what
  the others get. `tests/test_layout.py` checks it. [docs/architecture.md](docs/architecture.md) shows how it fits
  together and how to add a server.
- New source files get the same header as the others.
- New collections go in `collections.yml` (the top of the file explains every field). Lists have to be public
  mdblist lists, and franchises use fixed `[title, year]` lists so remakes don't sneak in.
- One thing per PR.

<details>
<summary><b>The header for new files</b></summary>

Python files start with:

```python
# CineSets by blurbery (https://github.com/blurbery/cinesets)
# Copyright (C) 2026 blurbery
# SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
```

Shell scripts, YAML files and the Dockerfile use the short version:

```sh
# CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
```

Markdown and JSON files don't need one.

</details>

## PR titles

PRs get squash merged, so the title becomes the commit and its line in the release notes. Use
[Conventional Commits](https://www.conventionalcommits.org):

| Title | For | Next version |
|---|---|---|
| `feat: ...` | A new feature or collection | 1.**1**.0 |
| `fix: ...` | A bug fix | 1.0.**1** |
| `perf:`, `deps:`, `revert:` | Speed-ups, dependency bumps, undoing a change | 1.0.**1** |
| `docs:`, `test:`, `refactor:`, `style:`, `build:`, `ci:`, `chore:` | Docs, tests, tidying and tooling | 1.0.**1** |

A scope is fine too, like `feat(collections): add Studio Ghibli`. Each type has its own heading in the release
notes, so every merged PR shows up there.

> [!CAUTION]
> Add `!` for a breaking change, like `feat!: rename the labels setting`. That makes the next version
> **2**.0.0, so only use it when people have to change their setup.

### A PR with more than one change

The title gives a PR one line in the release notes. If it makes several changes, list every one of them (the
title's too) in the **Release notes** box in the PR description, one per line and each written like a title. Each
line becomes its own line in the notes:

```text
BEGIN_COMMIT_OVERRIDE
feat(posters): a choice of fonts
fix(web): the run log keeps updating on long runs
docs: how to uninstall a Docker install
END_COMMIT_OVERRIDE
```

Leave the box empty to use the title. Lines need to start right at the beginning, with no `-` in front, and nothing
else can go in the box, comments included: the release notes would quietly leave out anything they can't read, so
the **Title and AI disclosure** check fails on it instead. When the check passes, its summary shows the lines the
PR will add. Ending a line with the PR's number, like `(#31)`, links it in the notes.

## AI use

> [!IMPORTANT]
> Using AI is fine, but you have to say so. Every PR has an AI disclosure section, and the
> **Title and AI disclosure** check fails until it's filled in.

Tick **No AI tools were used**, or tick **AI tools were used** and write which tools and what they did. That
covers code, tests, docs, images and the PR text. Spell check and single-word autocomplete don't count. If you
fix the description, the check runs again.

<details>
<summary><b>Example disclosures</b></summary>

> Claude Opus wrote the first draft of the list parser and its tests. I went through every line, cleaned up
> the error handling and ran it against my own Emby server.

> GitHub Copilot autocompleted parts of the poster code. I checked each suggestion and ran the tests.

</details>

You're responsible for everything in your PR however it was written, so make sure you understand it and can
explain it. PRs, issues and comments posted by an AI agent without a person checking them first get closed,
and so do PRs with AI use that wasn't disclosed.

## Releases

Releases are automatic and follow [semantic versioning](https://semver.org). Each merge updates a release PR
that bumps the version and adds to [CHANGELOG.md](CHANGELOG.md). When I merge that, the version gets tagged,
the notes go up on [Releases](https://github.com/blurbery/cinesets/releases), and the Docker image
`ghcr.io/blurbery/cinesets` is built from the tag for amd64 and arm64 and published as `1.5.0`, `1.5`, `1` and
`latest` (for version 1.5.0).

> [!NOTE]
> You don't need to touch the version number or the changelog.

<details>
<summary><b>Merging a release PR (for the maintainer)</b></summary>

GitHub doesn't start the checks on a PR made by the release workflow until someone who can write to the repository
presses **Approve workflows to run** in its merge box. Every merge to `main` updates the release PR and asks again,
so press it just before merging, wait for the checks to pass, then merge.

To skip that step, give the release workflow a GitHub App of its own:

1. Make a GitHub App (Settings, Developer settings, GitHub Apps, New GitHub App) with the webhook turned off and
   these repository permissions: Contents, Issues and Pull requests, each "Read and write".
2. Generate a private key for it and install it on this repository only.
3. In this repository's Settings, Secrets and variables, Actions, add a variable `RELEASE_APP_CLIENT_ID` holding the
   App's client ID and a secret `RELEASE_APP_PRIVATE_KEY` holding the whole private key file.

From the next merge on, the App makes the release PR and its checks start by themselves. Delete the variable to go
back.

To change the notes of a PR that's merged but not released yet, edit its release notes box, then run the **Release**
workflow by hand (Actions, Release, Run workflow) so the release PR catches up.

The first release that publishes the Docker image creates the `cinesets` package on ghcr.io, and GitHub may make
it private. If so, make it public once: on GitHub, Your profile, Packages, cinesets, Package settings, Change
visibility. Later releases keep that setting.

Every Monday, **Newest servers** tests CineSets against the newest Jellyfin, Emby (release and beta) and Silo, and
**MDBList lists** checks every list in `collections.yml`. GitHub emails you when a scheduled run fails. Dependabot's
PRs are titled `deps: ...` (pip and Docker) or `ci: ...` (actions), so each title works as its release notes line
as it is. The title check skips them, as it does the release PR.

</details>

## Licence

By opening a PR you agree that your contribution is under [AGPL-3.0-or-later](LICENSE) with the extra terms
in [NOTICE](NOTICE), and that it's yours to give. Don't copy in code from other projects unless their licence
allows it, and say where it came from.
