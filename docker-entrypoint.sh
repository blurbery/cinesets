#!/bin/sh
# CineSets container entrypoint: runs CineSets as an unprivileged user (PUID/PGID, default 1000).
# CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
if [ "$(id -u)" = "0" ]; then
  case "$PUID$PGID" in *[!0-9]*|"") echo "PUID and PGID must be numbers." >&2; exit 1 ;; esac
  if [ "$PUID" -eq 0 ] || [ "$PGID" -eq 0 ]; then
    echo "CineSets does not run as root: set PUID and PGID to a normal user (for example the output of id -u and id -g)." >&2
    exit 1
  fi
  mkdir -p /config
  # hand the config folder (and anything in it from older versions) to the run-as user; stay on this filesystem
  find /config -xdev \( ! -user "$PUID" -o ! -group "$PGID" \) -exec chown -h "$PUID:$PGID" {} +
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --no-new-privs --inh-caps=-all python -m cinesets "$@"
fi
exec python -m cinesets "$@"
