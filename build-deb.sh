#!/usr/bin/env bash
set -euo pipefail

if command -v yarn >/dev/null 2>&1; then
  yarn make:deb
elif command -v npm >/dev/null 2>&1; then
  npm run make:deb
else
  echo "Install Node.js with yarn or npm, then run npm run make:deb." >&2
  exit 1
fi
