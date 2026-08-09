# MonkeyLLM Station — one image, two volumes (spec J.6).
#
# Build from the REPOSITORY ROOT so the engine source is in context:
#   docker build -f apps/station/Dockerfile -t monkeyllm-station .

# --- Studio: a static React/Vite bundle, no server half (J.5) --------------
FROM node:22-slim AS studio
WORKDIR /studio
COPY apps/studio/package.json apps/studio/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY apps/studio/ ./
RUN npm run build

# --- Station ---------------------------------------------------------------
FROM python:3.12-slim

# Writes are git commits inside the forest (spec A.3/C.7): gitops shells out
# to the git binary, so a writable Station cannot run without it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Shipping the image is distributing both works: the Apache-2.0 engine and
# the AGPL-3.0 host. Each license (and the NOTICE) has to be inside it.
COPY LICENSE NOTICE LICENSING.md ./

# Engine first: it changes least, so the layer caches well.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY apps/station/pyproject.toml apps/station/LICENSE ./apps/station/
COPY apps/station/monkeyllm_station/ ./apps/station/monkeyllm_station/
# Editable on purpose: the Station locates the Studio bundle relative to its
# own source tree (app.py's STUDIO_DIST), so the package must run from
# /app/apps/station for /app/apps/studio/dist to be found.
RUN pip install --no-cache-dir -e ./apps/station

# The Station serves this directory as static files and nothing else.
COPY --from=studio /studio/dist ./apps/studio/dist
COPY apps/studio/LICENSE ./apps/studio/

# /forests  the forest registry
# /registry the host registry: principals, keys, grants, provider secrets —
#           never inside a forest, and worth backing up with the snapshots
VOLUME ["/forests", "/registry"]
EXPOSE 8800

ENV MONKEYLLM_STATION_ROOT=/forests \
    MONKEYLLM_STATION_REGISTRY=/registry/station.db

CMD ["station", "serve", "--host", "0.0.0.0", "--port", "8800"]
