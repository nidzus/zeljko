#!/bin/bash
# Double-click in Finder. Builds .venv if missing or broken, then checks.
# Add --force when run from Terminal to rebuild regardless.
cd "$(dirname "$0")/.." || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python is not installed. See README.md, \"Install\"."
  exit 1
fi
python3 jyotisha.py install "$@"
