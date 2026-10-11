#!/usr/bin/env bash
# Install (or update) the `stoetzms-pdf` binary on Linux or macOS:
#
#     curl -fsSL https://pdf.stoetz.ms/install.sh | sudo bash -
#
# Installs into /usr/local/lib/stoetzms-pdf and links /usr/local/bin/stoetzms-pdf.
# Installs the newest release; set VERSION (e.g. VERSION=0.1.0) for another one.
set -euo pipefail

PREFIX=${PREFIX:-/usr/local}
VERSION=${VERSION:-}

if [ "$EUID" -ne 0 ]; then
  echo "script must be executed as root"
  exit 1
fi

for TOOL in curl tar xz; do
  if ! command -v "$TOOL" &>/dev/null; then
    echo "\"$TOOL\" not installed"
    exit 1
  fi
done

case "$(uname -s)" in
  Linux) PLAT=linux ;;
  Darwin) PLAT=macos ;;
  *) echo "operating system not supported"; exit 1 ;;
esac

case "$(uname -m)" in
  x86_64 | amd64) ARCH=x64 ;;
  aarch64 | arm64) ARCH=arm64 ;;
  *) echo "architecture not supported"; exit 1 ;;
esac

if [ "$PLAT" = macos ] && [ "$ARCH" = x64 ]; then
  echo "macOS on Intel is not supported; install with pip instead (see https://pdf.stoetz.ms/user-guide)"
  exit 1
fi

if [ -f /etc/alpine-release ]; then
  echo "Alpine Linux is not supported (the binary needs glibc)"
  exit 1
fi

NAME="stoetzms-pdf-${PLAT}-${ARCH}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

RELEASES=https://github.com/milesstoetzner/stoetzms-pdf/releases
if [ -z "$VERSION" ]; then
  URL="${RELEASES}/latest/download/${NAME}.tar.xz"
else
  URL="${RELEASES}/download/v${VERSION#v}/${NAME}.tar.xz"
fi

curl -fsSL "$URL" -o "$TMP/${NAME}.tar.xz"
tar -xJf "$TMP/${NAME}.tar.xz" -C "$TMP"

rm -rf "$PREFIX/lib/stoetzms-pdf"
mkdir -p "$PREFIX/lib" "$PREFIX/bin"
mv "$TMP/${NAME}" "$PREFIX/lib/stoetzms-pdf"
ln -sf "$PREFIX/lib/stoetzms-pdf/stoetzms-pdf" "$PREFIX/bin/stoetzms-pdf"

"$PREFIX/bin/stoetzms-pdf" --version
