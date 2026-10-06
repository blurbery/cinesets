# Security

CineSets holds an API key for your media server and makes changes on it, so I take security problems
seriously.

> [!CAUTION]
> Please don't report security problems in public issues or PRs.

## Reporting a problem

[Report it privately](https://github.com/blurbery/cinesets/security/advisories/new) through GitHub
(**Security > Report a vulnerability**). Only you and I can see it. Include:

- what the problem is and what someone could do with it
- your CineSets version (`./run.sh version`) and your server and its version
- the steps to reproduce it, with server addresses, API keys and user names removed

I'll reply as soon as I can, keep you posted while it's being fixed, and credit you in the advisory if you'd
like.

## Supported versions

Fixes go into the latest release. If you're on an older version, update first (`git pull && ./install.sh`)
and check the problem is still there.

## What counts

For example:

- the API key showing up in logs, output or files that other users can read
- CineSets changing or deleting anything it didn't create
- the Docker container keeping root or getting more access than it needs

> [!NOTE]
> Problems in Emby, Jellyfin or mdblist themselves should go to those projects.
