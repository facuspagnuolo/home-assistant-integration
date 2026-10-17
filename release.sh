#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: ./release.sh <version> [-f] (example: ./release.sh 46 -f)" >&2
}

force=false
version=""
for arg in "$@"; do
  case "$arg" in
    -f) force=true ;;
    -*) usage; exit 1 ;;
    *)
      if [[ -n "$version" || -z "$arg" ]]; then
        usage
        exit 1
      fi
      version="$arg"
      ;;
  esac
done

if [[ -z "$version" ]]; then
  usage
  exit 1
fi

if [[ ! "$version" =~ ^[0-9]+$ ]]; then
  echo "Version must be a number (example: 46)." >&2
  exit 1
fi
version="v0.0.$version"

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
git check-ref-format "refs/tags/$version"

if "$force"; then
  git tag -d -- "$version"
  git push origin --delete "refs/tags/$version"
fi
git tag -- "$version"
git push origin "refs/tags/$version"
if "$force"; then
  git push origin main -f
fi
