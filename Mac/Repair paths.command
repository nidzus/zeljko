#!/bin/bash
# Double-click in Finder. Re-points the Claude config files at the app and data folders.
cd "$(dirname "$0")/.." || exit 1
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
"$PY" jyotisha.py repair
