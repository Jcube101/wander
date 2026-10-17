#!/bin/sh
# Wander editor launcher (mac/Linux). Put a copy in a trip folder with
#   python3 tripmap/launcher.py "<trip folder>"
# which fills in the WANDER line below with where this repo is. Run straight
# from the repo, it finds serve.py next to itself; then pass a trip folder.
# macOS: rename the copy to .command to start it with a double-click.
HERE="$(cd "$(dirname "$0")" && pwd)"
WANDER="$HERE"
TRIP="${1:-$HERE}"
if [ ! -f "$WANDER/serve.py" ]; then
  echo "Could not find serve.py in $WANDER"
  echo "Run: python3 tripmap/launcher.py \"$TRIP\"   from the wander repo to refresh this launcher."
  exit 1
fi
PY="$(command -v python3 || command -v python)"
exec "$PY" "$WANDER/serve.py" "$TRIP"
