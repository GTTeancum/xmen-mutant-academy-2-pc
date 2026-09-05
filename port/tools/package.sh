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

The game recompiled to run natively on Windows. It is not an emulator, and it does
not need a PlayStation BIOS.

You do need your own copy of the disc. Nothing in this download contains the game.


Installing
----------
1. Unzip it anywhere. There is no installer, and nothing is written outside this
   folder.

2. Put your disc image in this folder, beside XMenMA2.exe. Either:
     - a .cue file together with all of its .bin tracks, or
     - a single .chd

3. Run XMenMA2.exe.

It finds the .cue by itself and remembers where it is. If it cannot find one it
will ask, with a Browse button. You can also drag a .cue onto the executable.

Requirements: 64-bit Windows, and a graphics driver with OpenGL 2.1 or newer.
Nothing else to install.


Controls
--------
Keyboard, out of the box:

    D-pad     arrow keys        Start    Enter
    Cross     Z                 Select   Right Shift
    Circle    X
    Square    A
    Triangle  S
    L1  Q     R1  W
    L2  E     R2  R
    L3  F     R3  G

A gamepad is picked up automatically if one is plugged in. Both keyboard and pad
can be rebound under Settings > Input.


Settings
--------
    Settings > Display    16:9 widescreen, fullscreen, internal resolution
    Settings > Audio      volume
    Settings > Input      key and pad bindings
    F12                   screenshot of what is on screen, into shots/

Widescreen widens the view rather than stretching it, so a fight shows more of the
arena instead of a fatter picture. Menus and movies have no more picture to show
and stay 4:3. Turning it on resizes the window to match.


The packs folder
----------------
Upscaled artwork, 4x, built from the game's own art. Anything it does not cover
falls back to the original, so you can delete one file from it to compare that
texture against the original, or delete the whole folder to turn the upscales off.


Where things end up
-------------------
    carda.sav, cardb.sav    memory cards
    shots/                  screenshots
    logs/                   one log per run; start here if something goes wrong
    settings.json           disc path, volumes, controls
    interface.ini           window size and display settings
TXT

SIZE=$(du -sm "$STAGE" | cut -f1)
echo "staged ${SIZE} MB in $STAGE"

ARCHIVE="$OUT/XMenMA2-windows-x64.zip"
echo "compressing (this takes a minute)..."
powershell -NoProfile -Command \
  "Compress-Archive -Path '$STAGE' -DestinationPath '$ARCHIVE' -CompressionLevel Optimal -Force"

echo "$ARCHIVE -- $(du -sm "$ARCHIVE" | cut -f1) MB"
