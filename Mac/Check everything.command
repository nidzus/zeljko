#!/bin/bash
# Double-click in Finder. Runs every verification suite.
cd "$(dirname "$0")/.." || exit 1
if [ ! -x .venv/bin/python ]; then
  echo 'The environment is missing. Double-click "Install or repair.command" first.'
  exit 1
fi
.venv/bin/python jyotisha.py check
