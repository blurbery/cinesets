#!/bin/sh
# Run CineSets from this folder:  ./run.sh plan | apply | ...  (./run.sh --help lists every command)
# CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
cd "$(dirname "$0")" || exit 1
exec venv/bin/python -m cinesets "$@"
