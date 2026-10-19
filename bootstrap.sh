#!/bin/sh
# Run from a cloned/downloaded repository. No repository URL is hardcoded.
set -eu
cd -- "$(dirname -- "$0")"
[ "$#" -gt 0 ] || set -- install
# Only install prerequisites for installation; preview/doctor remain read-only.
if [ "$1" = install ]; then
  case "$(uname -s)" in
    Darwin)
      if ! xcode-select -p >/dev/null 2>&1; then
        xcode-select --install
        echo 'Finish installing Command Line Tools, then rerun this command.'
        exit 1
      fi
      ;;
    Linux)
      if [ ! -f /etc/debian_version ]; then
        echo 'Bootstrap supports Ubuntu/Debian Linux. Install prerequisites yourself on other distributions.' >&2
        exit 1
      fi
      sudo apt-get update
      sudo apt-get install -y build-essential procps curl file git python3 ca-certificates
      ;;
    *) echo 'Supported systems: macOS and Ubuntu/Debian Linux.' >&2; exit 1 ;;
  esac
  for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    if [ -x "$brew_bin" ]; then
      eval "$("$brew_bin" shellenv)"
      break
    fi
  done
  if ! command -v brew >/dev/null 2>&1; then
    installer=$(mktemp)
    trap 'rm -f "$installer"' EXIT HUP INT TERM
    curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"
    /bin/bash "$installer"
    for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
      if [ -x "$brew_bin" ]; then eval "$("$brew_bin" shellenv)"; break; fi
    done
  fi
  if ! command -v python3 >/dev/null 2>&1; then brew install python; fi
fi
exec ./setup "$@"
