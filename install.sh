#!/bin/sh
# CineSets installer: Python environment, settings, logos, a dry run, then (if you say yes) the collections
# and their schedule.
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

here=$(pwd)
ask() {  # ask a yes or no question when someone is at the keyboard; the answer is yes unless they say no
  [ -t 0 ] && [ -t 1 ] || return 1
  printf "%s [Y/n] " "$1"
  read -r answer
  case "$answer" in [Nn]*) return 1 ;; *) return 0 ;; esac
}

made=no
verb=Create; [ -s data/state.json ] && verb=Update
echo
if ask "$verb your collections on the server now? (the first time can take a while on a big library)"; then
  ./run.sh apply && made=yes
fi

# the schedule: skipped if one already runs this copy of CineSets (from crontab or /etc/cron.d)
scheduled=no
if crontab -l 2>/dev/null | grep -qF "$here/run.sh" || grep -qsF "$here/run.sh" /etc/cron.d/*; then
  scheduled=already
elif command -v crontab >/dev/null 2>&1 && ask "Keep them up to date automatically? (trending every 6 hours, charts daily, everything on Sundays)"; then
  { crontab -l 2>/dev/null
    echo "# CineSets schedule, added by install.sh (remove these four lines to stop it)"
    echo "0 */6 * * * \"$here/run.sh\" apply --only m-trending,s-trending > \"$here/logs/trending.log\" 2>&1"
    echo "30 4 * * * \"$here/run.sh\" apply --group seasonal,charts > \"$here/logs/daily.log\" 2>&1"
    echo "0 5 * * 0 \"$here/run.sh\" apply > \"$here/logs/weekly.log\" 2>&1"
  } | crontab - && scheduled=yes
fi

echo
echo "CineSets is installed."
[ "$made" = yes ] || echo "  $verb your collections:     ./run.sh apply"
case "$scheduled" in
  yes) echo "  Schedule: added to your crontab (crontab -l shows it)." ;;
  already) echo "  Schedule: already set up." ;;
  *) echo "  Keep them updated:           run ./install.sh again and answer yes, or see deploy/cron.example" ;;
esac
echo "  Change collections and posters in your browser:  ./run.sh web"
echo "  Every command:               ./run.sh --help    Help: README.md and docs/dashboard.md"
