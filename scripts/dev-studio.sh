#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley
#
# Bring the console up locally, in one command.
#
# Two processes, because in development the Studio is not served by the
# Station: Vite serves it with hot reload and proxies `/v1` to a Station
# running beside it (apps/studio/vite.config.js reads STATION_URL). So this
# script starts the Station in the background, Vite in the foreground, and
# stops both on Ctrl-C.
#
# Everything it writes lives in .dev/ — the registry, the log — because a
# dev Station's registry is disposable and must never be mistaken for the
# one a deployment backs up. `--reset` throws it away and gives you the
# first-run screen back (spec J.2.4).
#
#   scripts/dev-studio.sh                 # Studio :5173  ->  Station :8800
#   scripts/dev-studio.sh --reset         # ...starting from an owner-less Station
#   scripts/dev-studio.sh --build         # the real bundle, served by the Station

set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

STUDIO_PORT=5173
STATION_PORT=8800
FOREST_ROOT="$ROOT/forests"
DEV_DIR="$ROOT/.dev"
REGISTRY=""            # defaults to $DEV_DIR/station.db once flags are read
WRITABLE=1
RESET=0
BUILD=0
INSTALL=1
OPEN=0

usage() {
    cat <<'EOF'
Usage: scripts/dev-studio.sh [options]

  --port N          Studio (Vite) port                     [5173]
  --station-port N  Station port                           [8800]
  --root DIR        forest registry root                   [./forests]
  --registry FILE   host registry SQLite file              [./.dev/station.db]
  --read-only       start the Station without --writable (writes, ingest and
                    forest creation are refused with E_READONLY)
  --reset           delete the dev registry first: no owner, no keys, no
                    grants — the first-run setup screen comes back
  --build           build apps/studio and let the Station serve the bundle
                    itself (no Vite, no hot reload — the production path)
  --skip-install    do not check or install Python/npm dependencies
  --open            open the console in a browser once it answers
  -h, --help        this

The .env file at the repository root is loaded if present (variables already
set in your shell win), so an LLM endpoint configured there arrives in the
Models console as a ready provider (spec J.10.1).
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --port)          STUDIO_PORT="$2"; shift 2 ;;
        --station-port)  STATION_PORT="$2"; shift 2 ;;
        --root)          FOREST_ROOT="$2"; shift 2 ;;
        --registry)      REGISTRY="$2"; shift 2 ;;
        --read-only)     WRITABLE=0; shift ;;
        --reset)         RESET=1; shift ;;
        --build)         BUILD=1; shift ;;
        --skip-install)  INSTALL=0; shift ;;
        --open)          OPEN=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        *) echo "dev-studio: unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

say()  { printf '\033[36mdev-studio:\033[0m %s\n' "$*"; }
warn() { printf '\033[33mdev-studio:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31mdev-studio:\033[0m %s\n' "$*" >&2; exit 1; }

# -- .dev/ ------------------------------------------------------------------
# Self-ignoring, so a dev run never shows up in `git status` and nobody has
# to remember to add it to .gitignore.
mkdir -p "$DEV_DIR"
[ -f "$DEV_DIR/.gitignore" ] || printf '*\n' > "$DEV_DIR/.gitignore"
[ -n "$REGISTRY" ] || REGISTRY="$DEV_DIR/station.db"
STATION_LOG="$DEV_DIR/station.log"

if [ "$RESET" = 1 ]; then
    say "reset: removing $(basename "$REGISTRY") — the Station comes back owner-less"
    rm -f "$REGISTRY" "$REGISTRY-wal" "$REGISTRY-shm"
fi

# -- environment ------------------------------------------------------------
# No python-dotenv outside Docker (see .env.example): read KEY=VALUE lines
# ourselves rather than sourcing, so an unquoted value with spaces in it is
# a variable and not a syntax error. Anything already exported wins.
if [ -f "$ROOT/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|'#'*) continue ;; esac
        case "$line" in *=*) ;; *) continue ;; esac
        key=${line%%=*}
        value=${line#*=}
        key=$(printf '%s' "$key" | tr -d '[:space:]')
        case "$key" in ''|*[!A-Za-z0-9_]*) continue ;; esac
        # Strip one matching pair of surrounding quotes, and a trailing \r
        # from a file that once passed through Windows.
        value=${value%$'\r'}
        case "$value" in
            \"*\") value=${value#\"}; value=${value%\"} ;;
            \'*\') value=${value#\'}; value=${value%\'} ;;
        esac
        [ -n "${!key-}" ] || export "$key=$value"
    done < "$ROOT/.env"
    say "loaded .env"
fi

# The registry root and file are passed on the command line below; clear the
# container defaults so a .env written for Docker (/forests, /registry) does
# not follow us onto the laptop.
unset MONKEYLLM_STATION_ROOT MONKEYLLM_STATION_REGISTRY 2>/dev/null || true

# -- python -----------------------------------------------------------------
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
    if [ "$INSTALL" = 0 ]; then
        die "no .venv (and --skip-install): create one with 'python3 -m venv .venv'"
    fi
    say "creating .venv"
    python3 -m venv "$ROOT/.venv"
fi

if [ "$INSTALL" = 1 ] && ! "$PY" -c 'import monkeyllm, monkeyllm_station' 2>/dev/null; then
    say "installing the engine and the Station (editable)"
    "$PY" -m pip install -q -e "$ROOT" -e "$ROOT/apps/station"
fi
"$PY" -c 'import monkeyllm_station' 2>/dev/null \
    || die "monkeyllm_station is not importable — run without --skip-install"

# -- forests ----------------------------------------------------------------
[ -d "$FOREST_ROOT" ] || die "forest root does not exist: $FOREST_ROOT"
have_forest=0
for d in "$FOREST_ROOT"/*/; do
    if [ -f "$d/_index.md" ]; then have_forest=1; break; fi
done
if [ "$have_forest" = 0 ]; then
    if [ -f "$ROOT/forests/scripts/build_fixture.py" ]; then
        say "no forest under $FOREST_ROOT — building the fixture"
        "$PY" "$ROOT/forests/scripts/build_fixture.py"
    else
        warn "no forest under $FOREST_ROOT: the console will come up empty"
    fi
fi

# -- studio deps ------------------------------------------------------------
STUDIO="$ROOT/apps/studio"
if [ "$INSTALL" = 1 ]; then
    command -v npm >/dev/null 2>&1 || die "npm not found — install Node 18+"
    if [ ! -d "$STUDIO/node_modules" ] || [ "$STUDIO/package-lock.json" -nt "$STUDIO/node_modules" ]; then
        say "npm ci (apps/studio)"
        (cd "$STUDIO" && npm ci)
    fi
fi

# -- ports ------------------------------------------------------------------
port_busy() {
    command -v lsof >/dev/null 2>&1 || return 1
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}
if port_busy "$STATION_PORT"; then
    die "port $STATION_PORT is taken — pass --station-port N"
fi
if [ "$BUILD" = 0 ] && port_busy "$STUDIO_PORT"; then
    die "port $STUDIO_PORT is taken — pass --port N"
fi

STATION_URL="http://127.0.0.1:$STATION_PORT"
CONSOLE_URL="http://localhost:$STUDIO_PORT"
[ "$BUILD" = 0 ] || CONSOLE_URL="http://localhost:$STATION_PORT"

open_console() {
    [ "$OPEN" = 1 ] || return 0
    if command -v open >/dev/null 2>&1; then open "$CONSOLE_URL" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$CONSOLE_URL" >/dev/null 2>&1 || true
    fi
}

serve_args=(serve --root "$FOREST_ROOT" --registry "$REGISTRY"
            --host 127.0.0.1 --port "$STATION_PORT")
[ "$WRITABLE" = 0 ] || serve_args+=(--writable)

banner() {
    printf '\n'
    say "console   $CONSOLE_URL"
    [ "$BUILD" = 1 ] || say "station   $STATION_URL   (REST /v1, MCP /mcp)"
    say "forests   $FOREST_ROOT"
    say "registry  ${REGISTRY#$ROOT/}"
    if [ "$WRITABLE" = 1 ]; then
        say "writes    enabled (--read-only to refuse them)"
    else
        say "writes    refused with E_READONLY (--read-only)"
    fi
    printf '\n'
}

# -- build mode: no Vite, the Station serves the bundle ---------------------
if [ "$BUILD" = 1 ]; then
    say "building apps/studio"
    (cd "$STUDIO" && npm run build)
    banner
    open_console
    exec "$PY" -m monkeyllm_station.cli "${serve_args[@]}"
fi

# -- dev mode: Station in the background, Vite beside it --------------------
# Its output is teed rather than tailed: piping it straight out of the
# process means the prefixer ends when the Station does, so nothing survives
# the run holding the log open.
: > "$STATION_LOG"
"$PY" -m monkeyllm_station.cli "${serve_args[@]}" \
    > >(tee -a "$STATION_LOG" | sed 's/^/[station] /') 2>&1 &
STATION_PID=$!

STUDIO_PID=""
cleanup() {
    trap - INT TERM EXIT
    for pid in $STUDIO_PID $STATION_PID; do
        kill "$pid" 2>/dev/null || true
    done
    wait $STUDIO_PID $STATION_PID 2>/dev/null || true
    printf '\n'
    say "stopped"
}
trap cleanup INT TERM EXIT

# Wait for the socket rather than for a sleep: a first run has a registry to
# create and a warm-up to do (J.6.1), and Vite proxying into nothing looks
# exactly like a broken console.
ready=0
i=0
have_curl=0
command -v curl >/dev/null 2>&1 && have_curl=1
while [ "$i" -lt 120 ]; do
    if [ "$have_curl" = 0 ]; then sleep 2; ready=1; break; fi
    if curl -sf "$STATION_URL/v1/health" >/dev/null 2>&1; then ready=1; break; fi
    kill -0 "$STATION_PID" 2>/dev/null || break
    sleep 0.25
    i=$((i + 1))
done
if [ "$ready" = 0 ]; then
    warn "the Station did not answer on $STATION_PORT — its log follows"
    tail -n 30 "$STATION_LOG" >&2 || true
    exit 1
fi

# The first-run instruction the Station prints goes to its log, where nobody
# is looking, so repeat the one line that matters here (J.2.5).
setup=$(curl -sf "$STATION_URL/v1/health" 2>/dev/null \
        | "$PY" -c 'import json,sys; print("yes" if json.load(sys.stdin).get("setup_required") else "no")' \
        2>/dev/null || echo no)

banner
if [ "$setup" = yes ]; then
    say "first run — nobody owns this Station: open the console and create the owner"
    printf '\n'
fi

open_console
say "starting Vite — Ctrl-C stops both"
# Backgrounded and waited on, not run in front: bash defers a trap until the
# foreground command returns, so a Station stopped by anything other than
# Ctrl-C (a `kill`, a supervisor) would leave Vite holding the port. And not
# `npm run dev` either — a killed npm can leave its Vite child behind.
cd "$STUDIO"
STATION_URL="$STATION_URL" node_modules/.bin/vite --port "$STUDIO_PORT" --strictPort &
STUDIO_PID=$!
wait "$STUDIO_PID" 2>/dev/null || true
