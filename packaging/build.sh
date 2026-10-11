#!/usr/bin/env bash
# Build the standalone binary for this machine and pack it for a release:
#
#     packaging/build.sh
#
# Produces dist/stoetzms-pdf-<os>-<arch>.tar.xz (.zip on Windows): a folder
# with the `stoetzms-pdf` executable and the libraries it needs. Needs Python with this
# project and PyInstaller installed, and the Pango libraries (see
# docs/development.md). Run from the repository root.
set -euo pipefail

case "$(uname -s)" in
  Linux) OS=linux ;;
  Darwin) OS=macos ;;
  MINGW* | MSYS* | CYGWIN*) OS=windows ;;
  *) echo "unsupported system: $(uname -s)" >&2; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) ARCH=x64 ;;
  aarch64 | arm64) ARCH=arm64 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
NAME="stoetzms-pdf-${OS}-${ARCH}"

# PyInstaller finds the Pango libraries to bundle with ctypes.util.find_library,
# which only looks in Homebrew's lib folder if told to (e.g. with python.org's
# Python).
if [ "$OS" = macos ] && command -v brew >/dev/null; then
  export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
fi

rm -rf build/pyinstaller "dist/${NAME}" "dist/${NAME}".*
python -m PyInstaller --noconfirm --log-level WARN \
  --workpath build/pyinstaller --distpath build/pyinstaller/dist packaging/stoetzms-pdf.spec

mkdir -p dist
mv build/pyinstaller/dist/stoetzms-pdf "dist/${NAME}"
cp LICENSE "dist/${NAME}/"
if ! ls "dist/${NAME}/_internal" | grep -qi pango; then
  echo "the Pango libraries were not bundled; is Pango installed?" >&2
  exit 1
fi
"dist/${NAME}/stoetzms-pdf" --version

if [ "$OS" = windows ]; then
  (cd dist && 7z a -tzip -bso0 "${NAME}.zip" "${NAME}")
  echo "dist/${NAME}.zip"
else
  tar -C dist -cJf "dist/${NAME}.tar.xz" "${NAME}"
  echo "dist/${NAME}.tar.xz"
fi
