#!/usr/bin/env bash
# Side-by-side check of the texture pack: run the same scripted session twice, once
# with packs/ in place and once with it moved aside, and stitch the captures together.
#
# The input script is frame-based, so both runs reach the same screens at the same
# frame numbers and the pairs line up.
#
# Usage: bash tools/ab_textures.sh [frames]      (default: a menu, a VS card, a fight)
set -u
cd "$(dirname "$0")/.."

RUN=bin/Release/net10.0
FRAMES="${1:-3000,3400,3600,4200}"
SCRIPT="2600:cross:10;2900:cross:10;3200:cross:10"
LAST="${FRAMES##*,}"

shoot() { # dir
  rm -rf "$RUN/$1"
  ( cd "$RUN" && XMENMA2_SHOTS="$FRAMES" XMENMA2_EXIT=$((LAST + 60)) \
      XMENMA2_SHOT_DIR="$1" XMENMA2_STALL=10 XMENMA2_SCRIPT="$SCRIPT" \
      timeout 400 ./XMenMA2.exe > /dev/null 2>&1 )
  echo "  $1: $(ls "$RUN/$1" 2>/dev/null | wc -l) frame(s)"
}

echo "with the pack:"
shoot shots_pack

# Disable the pack in place rather than moving packs/ aside: the runtime creates that
# directory at startup, so moving it away and back again nests the old one inside the
# new one. A leading dot is skipped by pack discovery, which is exactly what we want.
echo "without it:"
for p in "$RUN"/packs/*/; do
  [ -d "$p" ] || continue
  mv "$p" "$RUN/packs/.off-$(basename "$p")"
done
shoot shots_plain
for p in "$RUN"/packs/.off-*/; do
  [ -d "$p" ] || continue
  mv "$p" "$RUN/packs/$(basename "$p" | sed 's/^\.off-//')"
done

python - "$RUN" <<'PY'
import os, sys
from PIL import Image
run = sys.argv[1]
a_dir, b_dir = os.path.join(run, 'shots_plain'), os.path.join(run, 'shots_pack')
out = os.path.join(run, 'shots_ab')
os.makedirs(out, exist_ok=True)
for name in sorted(os.listdir(b_dir)):
    a_path = os.path.join(a_dir, name)
    if not os.path.exists(a_path):
        continue
    a, b = Image.open(a_path).convert('RGB'), Image.open(os.path.join(b_dir, name)).convert('RGB')
    # PS1 output is anamorphic; stretch to 4:3 so the pair reads the way it plays
    size = (a.width, int(a.width * 3 / 4))
    a, b = a.resize(size, Image.LANCZOS), b.resize(size, Image.LANCZOS)
    sheet = Image.new('RGB', (a.width, a.height * 2 + 6), (24, 24, 28))
    sheet.paste(a, (0, 0))
    sheet.paste(b, (0, a.height + 6))
    sheet.save(os.path.join(out, name))
    print(f'  {name}: original on top, pack below')
PY
