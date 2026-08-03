#!/usr/bin/env bash
# Start the tracker. macOS / Linux.
cd "$(dirname "$0")" || exit 1
exec python3 server.py "$@"
