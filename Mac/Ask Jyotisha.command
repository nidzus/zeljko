#!/bin/bash
# Double-click in Finder. Claude Code with the jyotisha plugin loaded.
cd "$(dirname "$0")/.." || exit 1
echo "Starting Claude Code with the jyotisha plugin."
echo
echo "  /jyotisha:onboard   set up a profile"
echo "  /jyotisha:ask       ask about a decision"
echo "  /jyotisha:journal   review past advice"
echo
claude --plugin-dir ./jyotisha-plugin
