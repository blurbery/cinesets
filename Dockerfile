# CineSets container: runs `cinesets schedule` (the schedule in config.yml).
# CineSets by blurbery (https://github.com/blurbery/cinesets). SPDX-License-Identifier: AGPL-3.0-or-later
# Additional terms under AGPL-3.0 section 7 apply: see NOTICE.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="CineSets" \
      org.opencontainers.image.description="Automatic, beautiful collections for Emby, Jellyfin and Silo" \
      org.opencontainers.image.authors="blurbery" \
      org.opencontainers.image.source="https://github.com/blurbery/cinesets" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

WORKDIR /app
# the tested versions in constraints.txt; a change to either file builds this layer again
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY cinesets ./cinesets
COPY assets ./assets
COPY collections.yml config.example.yml LICENSE NOTICE docker-entrypoint.sh ./

# CineSets runs as PUID:PGID (default 1000:1000), never as root; the entrypoint drops privileges
ENV PYTHONUNBUFFERED=1 CINESETS_CONFIG=/config/config.yml HOME=/tmp PUID=1000 PGID=1000
VOLUME ["/config"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["schedule"]
