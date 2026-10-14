#!/usr/bin/env bash
# Run a TradingClawd data script inside the plugin's own Python environment.
#
#   scripts/run.sh get_news.py --ticker NVDA --start-date 2026-10-07 --end-date 2026-10-14
#
# The first call creates a venv under ${XDG_CACHE_HOME:-~/.cache}/tradingclawd/ and
# installs requirements.txt into it, so the scripts never depend on whichever
# `python` happens to be first on PATH or on the packages installed there. The
# venv is keyed by a hash of requirements.txt: changing the requirements builds a
# fresh one on the next call. Agents run in parallel, so creation is guarded by a
# lock directory and later callers wait for the first one to finish.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REQ="$HERE/../requirements.txt"
BASE="${XDG_CACHE_HOME:-$HOME/.cache}/tradingclawd"
HASH="$(shasum -a 256 "$REQ" | cut -c1-12)"
VENV="$BASE/venv-$HASH"
LOCK="$BASE/venv-$HASH.lock"

if [ $# -lt 1 ]; then
  echo "usage: run.sh <script.py> [args...]" >&2
  exit 2
fi
SCRIPT="$1"
shift

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

if [ ! -x "$VENV/bin/python" ] || [ ! -f "$VENV/.ready" ]; then
  mkdir -p "$BASE"
  waited=0
  until mkdir "$LOCK" 2>/dev/null; do
    # Another agent is building the venv. A lock older than 10 minutes was left
    # by a build that died, so take it over.
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
      rm -rf "$LOCK"
      continue
    fi
    sleep 2
    waited=$((waited + 2))
    if [ "$waited" -ge 600 ]; then
      echo "[error] timed out waiting for the TradingClawd Python environment to be built" >&2
      exit 1
    fi
  done
  trap 'rm -rf "$LOCK"' EXIT
  if [ ! -f "$VENV/.ready" ]; then
    PY="$(find_python)" || {
      echo "[error] TradingClawd needs Python 3.10 or later as python3 on PATH" >&2
      exit 1
    }
    echo "[setup] creating TradingClawd Python environment at $VENV (one-time)" >&2
    rm -rf "$VENV"
    "$PY" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip >&2
    "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$REQ" >&2
    touch "$VENV/.ready"
    # Environments built from older requirements are no longer used.
    find "$BASE" -maxdepth 1 -type d -name 'venv-*' ! -name "venv-$HASH" -exec rm -rf {} + 2>/dev/null || true
  fi
  rm -rf "$LOCK"
  trap - EXIT
fi

exec "$VENV/bin/python" "$HERE/$SCRIPT" "$@"
