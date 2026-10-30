#!/bin/bash
# Double-click in Finder. Adds the advisor to Claude Desktop and re-points the Claude config files.
cd "$(dirname "$0")/.." || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" jyotisha.py repair --desktop
