#!/usr/bin/env bash
# Generates linear-sweep function maps for every overlay in X-Men: Mutant Academy 2.
# Run from the port/ directory.
set -u

RECOMP="../tools/RecompOne/RecompOne.Recompiler"
CUE="../X-Men - Mutant Academy 2 (USA).cue"
OUT="config/funcmaps"

CHARS="BEA CYC FOR GAM HAV JUG MAG MYS NIG PHO PSY ROG SAB SPI STO TOA WOL XAV"

mkdir -p "$OUT"

gen() { # name file base
  local name="$1" file="$2" base="$3"
  if [ -f "$OUT/${name}_sweep.json" ]; then
    echo "skip $name (exists)"
    return
  fi
  echo "== $name  ($file @ $base)"
  dotnet run --project "$RECOMP" -c Release --no-build -- \
    --generate-function-file -linear-sweep -disc "$CUE" \
    -base "$base" -file "$file" -out "$OUT/${name}_sweep.json" 2>&1 | tail -2
}

for c in $CHARS; do
  gen "${c}_rel1" "DATA/REL_CODE/ONE/${c}_REL1.R" 0x80107EF0
  gen "${c}_rel2" "DATA/REL_CODE/TWO/${c}_REL2.R" 0x80110EF0
done

gen "front"    "DATA/FRONT.BIN"    0x801C9000
gen "practice" "DATA/PRACTICE.BIN" 0x801EF000

echo "done"
