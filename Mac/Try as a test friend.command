#!/bin/bash
# Double-click in Finder. Claude Code as a friend sees it: only the shared server.
cd "$(dirname "$0")/.." || exit 1
echo "Opens Claude Code the way a friend would see the advisor: only the"
echo "shared server, no plugin, none of your own data."
echo "\"Start shared server\" must already be running in another window."
echo
read -r -p "Which test friend, A or B? " who
case "$who" in [bB]*) WHO=b ;; *) WHO=a ;; esac
CONFIG="$PWD/tools/friend-$WHO.mcp.json"
WORK="${TMPDIR:-/tmp}/jyotisha-friend-$WHO"
mkdir -p "$WORK" && cd "$WORK" || exit 1
echo
echo "In Claude Code type  /mcp  , choose jyotisha-$WHO and Authenticate."
echo
claude --strict-mcp-config --mcp-config "$CONFIG"
