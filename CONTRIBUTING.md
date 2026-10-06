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
python3 -m venv venv && venv/bin/pip install -r requirements-dev.txt
venv/bin/python -m pytest tests --ignore=tests/e2e
```

The unit tests use a fake server (`tests/conftest.py`), so you don't need Emby or Jellyfin to run them. Every
PR also gets tested against real throwaway Emby and Jellyfin servers on GitHub Actions. On your first PR those
checks wait until I approve them.

## Ground rules

> [!IMPORTANT]
> CineSets only touches collections it made, only writes what changed, and stops when the server is
> struggling. Anything that weakens that won't get merged.

- Add tests for what you change.
- Keep it working on Python 3.9 and on both Emby and Jellyfin. Ask before adding a dependency.
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

PRs get squash merged, so the title becomes the commit and ends up in the release notes. Use
[Conventional Commits](https://www.conventionalcommits.org):

| Title | For | Next version |
|---|---|---|
| `feat: ...` | A new feature or collection | 1.**1**.0 |
| `fix: ...` | A bug fix | 1.0.**1** |
| `perf:`, `deps:`, `revert:` | Speed-ups, dependency bumps, undoing a change | 1.0.**1** |
| `docs:`, `test:`, `refactor:`, `style:`, `build:`, `ci:`, `chore:` | Things users won't notice | No release |

A scope is fine too, like `feat(collections): add Studio Ghibli`.

> [!CAUTION]
> Add `!` for a breaking change, like `feat!: rename the labels setting`. That makes the next version
> **2**.0.0, so only use it when people have to change their setup.

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
that bumps the version and adds to [CHANGELOG.md](CHANGELOG.md). When I merge that, the version gets tagged
and the notes go up on [Releases](https://github.com/blurbery/cinesets/releases).

> [!NOTE]
> You don't need to touch the version number or the changelog.

## Licence

By opening a PR you agree that your contribution is under [AGPL-3.0-or-later](LICENSE) with the extra terms
in [NOTICE](NOTICE), and that it's yours to give. Don't copy in code from other projects unless their licence
allows it, and say where it came from.
