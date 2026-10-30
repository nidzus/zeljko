#!/bin/bash
# Double-click in Finder. The web app, opened in a browser. Close the window when done.
cd "$(dirname "$0")/.." || exit 1
if [ ! -x .venv/bin/python ]; then
  echo 'The environment is missing. Double-click "Install or repair.command" first.'
  exit 1
fi
.venv/bin/python jyotisha.py journal
