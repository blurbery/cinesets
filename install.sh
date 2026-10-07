#!/bin/sh
# CineSets installer: Python environment, settings, logos and a first dry run.
# CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || { echo "CineSets needs Python 3.9 or newer (python3 not found)."; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "CineSets needs Python 3.9 or newer."; exit 1; }
[ -w . ] || { echo "This folder is not writable by $(id -un). Run the installer as the user that owns it (or with sudo)."; exit 1; }

# a half-made environment (for example when python3-venv was missing) is removed and made again
if [ ! -x venv/bin/pip ]; then
  rm -rf venv
  echo "Creating the Python environment..."
  if ! python3 -m venv venv; then
    rm -rf venv
    echo "Could not create a Python environment. On Debian or Ubuntu run: apt install python3-venv"
    exit 1
  fi
fi
venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt
chmod +x run.sh
mkdir -p logs

[ -f config.yml ] || ./run.sh setup
[ -f config.yml ] || { echo "No config.yml was written; run ./run.sh setup again."; exit 1; }

./run.sh logos || echo "Logos skipped for now (posters will show service names). Run ./run.sh logos later."

echo "Running a dry run (this changes nothing and can take a few minutes on a big library)..."
if ! ./run.sh plan > logs/first-plan.txt 2>&1; then
  tail -n 20 logs/first-plan.txt
  echo "The dry run failed. Fix the problem above (see logs/first-plan.txt), then run ./install.sh again."
  exit 1
fi
total=$(grep -c '^[a-z0-9][a-z0-9-]* *list ' logs/first-plan.txt || true)
skipped=$(grep -c '^   skipped' logs/first-plan.txt || true)
echo "Collections that would be made: $((total - skipped)) ($skipped skipped because too few of their titles are in your library)"
grep -E '^!!' logs/first-plan.txt | head -n 20 || true
echo "Full dry run: $(pwd)/logs/first-plan.txt"

cat <<EOF

CineSets is installed. Check the dry run, then create your collections:

  ./run.sh apply

To change which collections are made, run ./run.sh pick (./run.sh list shows them all).

To keep them updated, install the schedule (trending every 6 hours, charts daily at 04:30, everything on
Sundays at 05:00, in this machine's time zone):

  sed -e "s#/opt/cinesets#$(pwd)#g" -e "s# root # $(id -un) #" deploy/cron.example | sudo tee /etc/cron.d/cinesets >/dev/null
EOF
