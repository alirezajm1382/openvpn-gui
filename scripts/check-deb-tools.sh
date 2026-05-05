#!/usr/bin/env bash
set -euo pipefail

missing=()

for tool in dpkg fakeroot; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    missing+=("${tool}")
  fi
done

if ((${#missing[@]} > 0)); then
  echo "Missing Debian packaging tool(s): ${missing[*]}" >&2
  echo "Install them with:" >&2
  echo "  sudo apt install dpkg fakeroot" >&2
  exit 1
fi
