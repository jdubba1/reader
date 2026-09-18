#!/bin/sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 scripts/companion.py
else
  echo 'Install Python 3.10 or newer from https://python.org/downloads/ and reopen this launcher.'
fi
printf '\nPress Enter to close.'
read -r answer
