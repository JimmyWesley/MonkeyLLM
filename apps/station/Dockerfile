# MonkeyLLM Station — one image, two volumes (spec J.6).
#
# Build from the REPOSITORY ROOT so the engine source is in context:
#   docker build -f apps/station/Dockerfile -t monkeyllm-station .
FROM python:3.12-slim

WORKDIR /app

# Engine first: it changes least, so the layer caches well.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY apps/station/pyproject.toml ./apps/station/
COPY apps/station/monkeyllm_station/ ./apps/station/monkeyllm_station/
RUN pip install --no-cache-dir ./apps/station

# /forests  the forest registry (read-only mount is fine in Phase A)
# /registry the host registry: principals, keys, grants — never inside a forest
VOLUME ["/forests", "/registry"]
EXPOSE 8800

ENV MONKEYLLM_STATION_ROOT=/forests \
    MONKEYLLM_STATION_REGISTRY=/registry/station.db

CMD ["station", "serve", "--host", "0.0.0.0", "--port", "8800"]
