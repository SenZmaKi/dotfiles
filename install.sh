#!/bin/sh
# Standalone entry point: safe to download independently of the repository.
set -eu
repository=${DOTFILES_REPO:-https://github.com/SenZmaKi/dotfiles.git}
revision=${DOTFILES_REF:-main}
destination=${DOTFILES_DIR:-"$HOME/.local/share/dotfiles"}

case "$(uname -s)" in
  Darwin)
    if ! xcode-select -p >/dev/null 2>&1; then
      xcode-select --install
      echo 'Finish installing Command Line Tools, then rerun this command.'
      exit 1
    fi
    ;;
  Linux)
    if ! command -v git >/dev/null 2>&1; then
      if [ ! -f /etc/debian_version ]; then
        echo 'Install Git with your package manager, then rerun this command.' >&2
        exit 1
      fi
      sudo apt-get update
      sudo apt-get install -y git ca-certificates
    fi
    ;;
  *) echo 'Supported systems: macOS and Ubuntu/Debian Linux.' >&2; exit 1 ;;
esac

if [ -e "$destination" ] || [ -L "$destination" ]; then
  if [ ! -d "$destination/.git" ] || [ "$(git -C "$destination" remote get-url origin)" != "$repository" ]; then
    echo "Destination already exists and is not this repository: $destination" >&2
    exit 1
  fi
  current_revision=$(git -C "$destination" symbolic-ref --quiet --short HEAD || true)
  if [ "$current_revision" != "$revision" ]; then
    echo "Existing checkout is on $current_revision, expected $revision. Select its branch explicitly before rerunning." >&2
    exit 1
  fi
  echo "Using existing checkout: $destination (run ./setup update there to pull changes)"
else
  mkdir -p "$(dirname -- "$destination")"
  staging=$(mktemp -d "$(dirname -- "$destination")/.dotfiles-install.XXXXXXXX")
  trap 'rm -rf "$staging"' EXIT HUP INT TERM
  git clone --branch "$revision" --single-branch "$repository" "$staging/repository"
  mv "$staging/repository" "$destination"
  rm -rf "$staging"
  trap - EXIT HUP INT TERM
fi

cd -- "$destination"
exec ./bootstrap.sh "$@"
