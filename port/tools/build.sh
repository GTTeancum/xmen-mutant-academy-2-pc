#!/usr/bin/env bash
# Full port build: rebuild the maps, recompile, close the call graph, rebuild.
# Run from the port/ directory.
set -u
RECOMP="../tools/RecompOne/RecompOne.Recompiler"

recompile() {
  dotnet run --project "$RECOMP" -c Release --no-build -- config/xmen.json 2>&1 \
    | grep -E "total functions|applied [0-9]+ patches" || true
}

python tools/fixmaps.py . | tail -3
recompile

prev=999999
for i in 1 2 3 4 5 6; do
  missing=$(python tools/closure.py . | tee /dev/stderr | grep -oE "^missing [0-9]+" | grep -oE "[0-9]+")
  [ -z "$missing" ] && missing=0
  if [ "$missing" -eq 0 ]; then echo "call graph closed after $i pass(es)"; break; fi
  if [ "$missing" -ge "$prev" ]; then
    echo "call graph stable with $missing unreachable target(s) left in data"; break
  fi
  prev=$missing
  python tools/fixmaps.py . > /dev/null
  recompile
done

dotnet build XMenMA2.csproj -c Release 2>&1 | grep -E "error|Build succeeded" | head -5
