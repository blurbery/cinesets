#!/bin/sh
# CineSets installer: Python environment, settings, logos, a dry run, then (if you say yes) the collections
# and their schedule. Run it again to update. ./install.sh --uninstall takes this folder's schedule off again.
# CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
set -e
cd "$(dirname "$0")"
here=$(pwd)
# who owns this folder, and their name (ls reads one folder here, not a list of file names)
# shellcheck disable=SC2012
uid=$(ls -ldn . | awk '{print $3}')
owner=$(id -un "$uid" 2>/dev/null || echo "$uid")

# Reads a crontab, an /etc/cron.d file or a systemd unit and prints the lines that run this folder's run.sh (the exact
# path, not a longer one that ends the same way) with install.sh's comment just above them ("cron_lines ours"), or
# every other line ("cron_lines others").
cron_lines() {
  RUN="$here/run.sh" awk -v want="$1" '
    function mine(line,   run, off, i, before, after) {
      run = ENVIRON["RUN"]; off = 0
      while ((i = index(substr(line, off + 1), run)) > 0) {
        off += i
        before = off > 1 ? substr(line, off - 1, 1) : ""
        after = substr(line, off + length(run), 1)
        if (before !~ /[^ \t"'\''=;&|(]/ && after !~ /[^ \t"'\'';&|)<>]/) return 1
      }
      return 0
    }
    function emit(line, isours) { if ((want == "ours") == isours) print line }
    held { emit(comment, mine($0)); held = 0 }
    index($0, "# CineSets schedule") == 1 { comment = $0; held = 1; next }
    { emit($0, mine($0)) }
    END { if (held) emit(comment, 0) }'
}

uninstall() {
  echo "Taking the CineSets schedule for $here off this machine."
  if ! command -v crontab >/dev/null 2>&1; then
    echo "  This machine has no crontab command, so there's no crontab to take it out of."
  elif ! current=$(crontab -l 2>/dev/null); then
    echo "  $(id -un) has no crontab, so there's nothing to take out of one."
  else
    # the crontab is written back only when it held this folder's lines, and then without just those lines
    removed=$(printf '%s\n' "$current" | cron_lines ours)
    if [ -z "$removed" ]; then
      echo "  $(id -un)'s crontab has no CineSets schedule for this folder."
    else
      rest=$(printf '%s\n' "$current" | cron_lines others)
      printf '%s\n' "$rest" | crontab -
      echo "  Removed from $(id -un)'s crontab:"
      printf '%s\n' "$removed" | sed 's/^/    /'
    fi
  fi
  if [ "$(id -u)" != 0 ]; then
    echo "  If you ever ran the installer with sudo, the schedule is in root's crontab: sudo ./install.sh --uninstall"
  fi
  for f in /etc/cron.d/*; do
    if [ -f "$f" ] && cron_lines ours < "$f" | grep -q .; then
      echo "  $f runs it too. Delete that file with: sudo rm $f (or take out its CineSets lines)"
    fi
  done
  for f in /etc/systemd/system/*.service; do
    if [ -f "$f" ] && cron_lines ours < "$f" | grep -q .; then
      unit=$(basename "$f")
      echo "  The dashboard service $unit runs from here. Stop and remove it with:"
      echo "    sudo systemctl disable --now $unit && sudo rm $f && sudo systemctl daemon-reload"
    fi
  done
  sudo=""
  [ -w "$(dirname "$here")" ] || sudo="sudo "
  as=""
  if [ "$(id -u)" = 0 ] && [ "$uid" != 0 ]; then as=" (as $owner)"; fi
  echo
  echo "To finish:"
  echo "  1. Delete the collections CineSets made$as (it needs this folder's data/ to know which ones):"
  echo "       ./run.sh remove --all"
  echo "  2. Delete this folder:  cd .. && ${sudo}rm -rf \"$here\""
  echo "  3. If you like, delete the API key you made for CineSets on your server."
}

case "${1-}" in
  "") ;;
  --uninstall) uninstall; exit 0 ;;
  -h|--help)
    echo "./install.sh               install CineSets in this folder, or update it (keeps your settings)"
    echo "./install.sh --uninstall   take this folder's schedule off, and say what else to do"
    exit 0 ;;
  *) echo "Unknown option: $1. Use ./install.sh, or ./install.sh --uninstall."; exit 1 ;;
esac

# Root on a folder that belongs to someone else would leave files (the environment, data/, the lock) that their own
# runs can't change. Root on a root-owned folder, as in many LXC containers, is fine.
if [ "$(id -u)" = 0 ] && [ "$uid" != 0 ]; then
  echo "This folder belongs to $owner. Run the installer as $owner, not as root or with sudo (log in as $owner, or"
  echo "use: sudo -u $owner ./install.sh), so CineSets' files stay $owner's."
  exit 1
fi
[ -w . ] || { echo "This folder is not writable by $(id -un). Run the installer as the user that owns it ($owner)."; exit 1; }
if [ "$(id -u)" != 0 ] && [ "$uid" != 0 ]; then
  stray=$(find . -user 0 2>/dev/null | head -n 1)
  if [ -n "$stray" ]; then
    echo "Some files here belong to root (like $stray), left by running CineSets with sudo or as root from cron."
    echo "Give them back to $(id -un), then run ./install.sh again:  sudo chown -R $(id -un) \"$here\""
    exit 1
  fi
fi
command -v python3 >/dev/null 2>&1 || { echo "CineSets needs Python 3.9 or newer (python3 not found)."; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || { echo "CineSets needs Python 3.9 or newer."; exit 1; }

# a missing, half-made (python3-venv was missing) or broken environment (a Python upgrade took away the Python it was
# made with) is removed and made again
if ! venv/bin/python -c 'import pip' >/dev/null 2>&1; then
  if [ -d venv ]; then
    echo "The Python environment in venv/ doesn't work any more (often after a Python upgrade). Making it again."
  fi
  rm -rf venv
  echo "Creating the Python environment..."
  if ! python3 -m venv venv; then
    rm -rf venv
    echo "Could not create a Python environment. On Debian or Ubuntu run: apt install python3-venv"
    exit 1
  fi
fi
# the tested versions in constraints.txt, upgraded (or changed back) to match on every run
venv/bin/python -m pip install -q --disable-pip-version-check --upgrade -r requirements.txt -c constraints.txt
chmod +x run.sh
mkdir -p logs

[ -f config.yml ] || ./run.sh setup
[ -f config.yml ] || { echo "No config.yml was written; run ./run.sh setup again."; exit 1; }

./run.sh logos || echo "Logos skipped for now (posters will show service names). Run ./run.sh logos later."

echo "Running a dry run (this changes nothing and can take a few minutes on a big library)..."
# a plan that got to its Summary line ran, even if a list or two failed (those are shown below)
./run.sh plan > logs/first-plan.txt 2>&1 || true
if ! grep -q '^Summary:' logs/first-plan.txt || grep -q '^Stopped early:' logs/first-plan.txt; then
  tail -n 20 logs/first-plan.txt
  echo "The dry run failed. Fix the problem above (see logs/first-plan.txt), then run ./install.sh again."
  exit 1
fi
total=$(grep -c '^[a-z0-9][a-z0-9-]* *list ' logs/first-plan.txt || true)
skipped=$(grep -cE ', so it is (not made|left as it is on the server)$' logs/first-plan.txt || true)
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
  ./run.sh apply && made=yes || made=partly  # exit code 1: something failed or the run stopped early
fi

# the schedule: skipped if one already runs this copy of CineSets (from crontab or /etc/cron.d)
scheduled=no
if crontab -l 2>/dev/null | cron_lines ours | grep -q . || cat /etc/cron.d/* 2>/dev/null | cron_lines ours | grep -q .; then
  scheduled=already
elif command -v crontab >/dev/null 2>&1 && ask "Keep them up to date automatically? (trending every 6 hours, charts daily, everything on Sundays)"; then
  { crontab -l 2>/dev/null
    echo "# CineSets schedule for $here, added by install.sh (./install.sh --uninstall takes it off)"
    echo "0 */6 * * * \"$here/run.sh\" apply --only m-trending,s-trending > \"$here/logs/trending.log\" 2>&1"
    echo "30 4 * * * \"$here/run.sh\" apply --group seasonal,charts > \"$here/logs/daily.log\" 2>&1"
    echo "0 5 * * 0 \"$here/run.sh\" apply > \"$here/logs/weekly.log\" 2>&1"
  } | crontab - && scheduled=yes
fi
# /etc/cron.d jobs that run as root on a folder that isn't root's now stop at run.sh's check, with a note in logs/
if [ "$uid" != 0 ]; then
  for f in /etc/cron.d/*; do
    if [ -f "$f" ] && cron_lines ours < "$f" | awk '!/^#/ && NF { u = ($1 ~ /^@/) ? $2 : $6; if (u == "root") bad = 1 } END { exit !bad }'; then
      echo "Warning: $f runs CineSets as root, so those jobs now stop without doing anything."
      echo "Put $owner in place of root in it (sudo nano $f), as deploy/cron.example shows."
    fi
  done
fi

echo
echo "CineSets is installed."
case "$made" in
  yes) ;;
  partly) echo "  Some collections had a problem (the lines starting with !! above): fix it, then run ./run.sh apply" ;;
  *) echo "  $verb your collections:     ./run.sh apply" ;;
esac
case "$scheduled" in
  yes) echo "  Schedule: added to your crontab (crontab -l shows it, ./install.sh --uninstall takes it off)." ;;
  already) echo "  Schedule: already set up." ;;
  *) if command -v crontab >/dev/null 2>&1; then
       echo "  Keep them updated:           run ./install.sh again and answer yes, or see deploy/cron.example"
     else
       echo "  Keep them updated:           this machine has no cron (no crontab command). Run the jobs in"
       echo "                               deploy/cron.example from a systemd timer or another scheduler, or use"
       echo "                               Docker, which has its own schedule (docs/setup.md)."
     fi ;;
esac
echo "  Change collections and posters in your browser:  ./run.sh web"
echo "  Every command:               ./run.sh --help    Help: README.md and docs/dashboard.md"
