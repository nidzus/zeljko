#!/bin/bash
# Double-click in Finder. Claude Code with the zeljko plugin loaded.
cd "$(dirname "$0")/.." || exit 1
echo "Starting Claude Code with the zeljko plugin."
echo
echo "  /zeljko:onboard   set up a profile"
echo "  /zeljko:ask       ask about a decision"
echo "  /zeljko:journal   review past advice"
echo
claude --plugin-dir ./zeljko-plugin
