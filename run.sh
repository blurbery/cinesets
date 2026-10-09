#!/bin/sh
# Run CineSets from this folder:  ./run.sh plan | apply | ...  (./run.sh --help lists every command)
# CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
cd "$(dirname "$0")" || exit 1

# Root on a folder that belongs to someone else would leave files (data/, the lock) that their own runs can't change.
# Root on a root-owned folder, as in many LXC containers, is fine. (ls reads one folder's owner, not file names.)
# shellcheck disable=SC2012
uid=$(ls -ldn . | awk '{print $3}')
if [ "$(id -u)" = 0 ] && [ "$uid" != 0 ]; then
  owner=$(id -un "$uid" 2>/dev/null || echo "$uid")
  # older cron.example lines ran as root: carry on as the folder's owner, so those schedules keep working
  if [ "$owner" != "$uid" ] && command -v runuser >/dev/null 2>&1; then
    exec runuser -u "$owner" -- "$(pwd)/run.sh" "$@"
  fi
  echo "CineSets doesn't run as root here: this folder belongs to $owner. Run it as $owner instead, for example:" >&2
  echo "  sudo -u $owner $(pwd)/run.sh $*" >&2
  echo "In /etc/cron.d, put $owner in place of root (deploy/cron.example shows how)." >&2
  exit 1
fi

# the environment install.sh made: a Python upgrade can take away the Python it was made with
if ! venv/bin/python -c 'import yaml' >/dev/null 2>&1; then
  echo "The Python environment in $(pwd)/venv is missing or broken (a Python upgrade can do that)." >&2
  echo "Run ./install.sh to make it again. It keeps your settings and data." >&2
  exit 1
fi

# files an earlier run as root left behind stop this user's runs from saving
for f in data data/cinesets.lock data/state.json; do
  if [ -e "$f" ] && [ ! -w "$f" ]; then
    echo "Warning: $(id -un) can't change $(pwd)/$f, probably after a run as root. To fix it:" >&2
    echo "  sudo chown -R $(id -un) $(pwd)" >&2
    break
  fi
done

exec venv/bin/python -m cinesets "$@"
