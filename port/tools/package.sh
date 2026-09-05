#!/usr/bin/env bash
# Build the download: one self-contained executable, the texture pack beside it, and a
# note telling whoever gets it that they supply the disc.
#
# The pack ships as a folder rather than being built into the executable on purpose.
# Anything without a replacement falls back to the game's own art, so deleting a file
# from the pack restores that texture and deleting the folder restores all of them --
# which is a real feature for comparing, and it disappears the moment the pack is sealed
# inside the exe. It also keeps the executable small enough to rebuild quickly.
#
# Run from the port/ directory:  bash tools/package.sh [pack-directory]
set -eu

cd "$(dirname "$0")/.."
PACK="${1:-packs/xmenma2-4x}"
OUT=dist
STAGE="$OUT/XMenMA2"

[ -d "$PACK" ] || { echo "no pack at $PACK -- build one first, or pass its path"; exit 1; }

echo "publishing..."
rm -rf "$OUT"
dotnet publish XMenMA2.csproj -c Release 2>&1 | grep -E "error|Build succeeded|-> " | tail -2

# dotnet publish writes straight into dist/, so move the executable into the staging
# folder the archive is made from.
mkdir -p "$STAGE"
mv "$OUT/XMenMA2.exe" "$STAGE/"

echo "adding $(basename "$PACK")..."
mkdir -p "$STAGE/packs"
cp -r "$PACK" "$STAGE/packs/"

cat > "$STAGE/README.txt" <<'TXT'
X-Men: Mutant Academy 2 -- PC port
==================================

You need your own copy of the disc. Nothing here contains the game.

Put the disc image next to XMenMA2.exe -- the .cue and all of its .bin tracks, or a
single .chd -- and run the executable. It will find the .cue on its own. You can also
drop a .cue onto the executable, or pass one as an argument.

  Settings > Display     widescreen (16:9), fullscreen, internal resolution
  F12                    screenshot of exactly what is on screen, into shots/

The packs folder holds upscaled artwork. Anything it does not cover falls back to the
game's own art, so you can delete individual files to compare them against the
originals, or delete the whole folder to turn the upscales off.
TXT

SIZE=$(du -sm "$STAGE" | cut -f1)
echo "staged ${SIZE} MB in $STAGE"

ARCHIVE="$OUT/XMenMA2-windows-x64.zip"
echo "compressing (this takes a minute)..."
powershell -NoProfile -Command \
  "Compress-Archive -Path '$STAGE' -DestinationPath '$ARCHIVE' -CompressionLevel Optimal -Force"

echo "$ARCHIVE -- $(du -sm "$ARCHIVE" | cut -f1) MB"
