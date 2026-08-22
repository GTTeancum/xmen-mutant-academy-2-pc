# Handoff — X-Men: Mutant Academy 2 (RecompOne port)

State as of 2026-08-21, evening. Read `TO_DO.md` for the long-lived open items; this
file is just the live thread.

## Where the port stands

Playable end to end at 60 fps, 1280x960 window, 4x internal rasterisation. Single
self-contained `port/dist/XMenMA2.exe`, republished today so it carries the current
runtime. Logging, watchdog and crash capture in `port/patches/Diag.cs` write one file
to `logs/`.

**The published build could not open a window, and had not been able to for as long as
there are logs for it.** `IncludeNativeLibrariesForSelfExtract` puts the natives in a
temp folder while `AppContext.BaseDirectory` still points at the executable, and
Silk.NET searches `BaseDirectory` — so GLFW and OpenAL were never found and `dist`
came up headless and silent while the `bin/` build was fine. Publishing with
`IncludeAllContentForSelfExtract` fixes it; the exe is still one file. This is worth
knowing about the whole preceding record: any claim about how the game looks or runs
came from `bin/Release/net10.0/XMenMA2.exe`, never from `dist`. **Verify a publish by
launching it, not by reading build output.**

## The texture thread: where the pack comes from now

Sam's words were **"Still pretty grainy. If it's actually working, it's awful."** Then,
looking at the pack: **"Every image I see in my upscale page needs to be clearly
understandable. If not you decoded it wrong."** He was right on both counts, and the
second one turned out to explain the first.

**The old pack was built from slabs of VRAM, not from textures.** The resolver
identified a texture by a fixed 256-texel window around the tile being drawn. This game
packs many images into the same VRAM rows, so that window took in unrelated neighbours
and decoded all of them with the one depth and the one palette belonging to whichever
tile triggered the dump. Most of every "texture" in the old pack was garbage.

That also explains the grain. The 1-pixel vertical banding diagnosed earlier as
hand-dithering was mostly an 8-bit index being split into two nibbles: odd columns held
`index >> 4` (a coarse but coherent picture), even columns held `index & 15` (noise).
On correctly decoded textures the column-phase divergence drops from 27.1 to 6.6, and
only 18 of 594 exceed threshold. Real dither exists in this game but is rare, and the
de-dither's guards mean it now simply does not fire on most textures.

**Two changes fixed it.**

1. **`VramTracker` records every image the CPU DMAs into VRAM, and the resolver
   identifies a tile by the upload that contains it.** An image load is the only event
   in the GPU command set that says "these pixels are one picture". Regions resolved
   this way in a long session: 1,998 at 4bpp and 5,326 at 8bpp, against 240 and 14 still
   falling back to the old page logic.
2. **Textures come off the disc, not out of a play session.** `DATA/WAD.WAD` is a `PWF `
   archive; strict TIM validation finds 1,891 images in it, 1,297 unique. They do not
   depend on anyone having visited the screen that draws them.

**Keying them was the part that had to be got exactly right.** `tools/vramhash.py`
reimplements `TextureTile.Hash`, and a palette is transformed on its way into VRAM:
every entry gets bit 15 set, and the magenta colour key `0x7C1F` becomes `0x0000`.
Verified against every palette the running game was observed to upload -- 102 of 102
exact. That second rule is not cosmetic: 269 textures use that magenta as a visible
colour, so a pack built from the disc palettes renders magenta blobs where the game
shows transparency.

**Where it stands:** 1,434 textures (1,297 from the disc, 239 seen only at run time),
146 MB. `tools/verify_textures.py` reports 1,372 pass, 62 flagged as correct-but-not-a-
picture (flat panels, two-tone blocks, colour ramps), **zero rejected**. In game:
**827 hits against 269 misses**, and every drawn texture whose pixels are on the disc
matches on the full key -- 102 of 102.

**Still unjudged: nobody has watched this in motion.** That has not changed and it still
needs Sam.

## The 16bpp thread: real, rare, and correctly refused

An earlier pass concluded the game draws no 16bpp textures at all. That was wrong, and
wrong in an instructive way: two short sessions showed zero 16bpp region lookups, which
is what "there are none" looks like and also what "you did not play far enough" looks
like. A 26,000-frame session finds 448, every one refused because the GPU had written
that VRAM. Those are render-to-texture surfaces, and refusing them is correct -- a fixed
image cannot stand in for something redrawn every frame. No fix needed, but the
measurement lesson stands: a depth absent from a short run has not been shown absent.

## Where the pack lives now

There used to be two packs on disk that were not the same, which is how Sam ended up
judging one he had already rejected. Now there is one:

- `port/packs/xmenma2-4x/` — the real thing, 1,434 textures, 146 MB.
- `port/dist/packs/xmenma2-4x` and `port/bin/Release/net10.0/packs/xmenma2-4x` are
  **directory junctions** to it. Rebuild once and both the published exe and the
  headless harness see it. `dotnet publish` leaves them alone.

Note that `Program.Main` forces the working directory to the executable's own folder,
so the pack root follows the exe, not the shell. Renaming a pack folder does not
disable it — the loader reads any directory holding a `pack.json` — but a name starting
with `.` is skipped, which is how the A/B baseline was run.

## Commands

Rebuild the pack from scratch — disc extraction, merge with whatever a run has seen,
check, upscale:

```bash
cd "C:/Programming/GitHub/X-Men - Mutant Academy 2/port" && python tools/disc.py extract disc && python tools/extract_textures.py --wad disc/DATA/WAD.WAD --out dump/tim && python tools/merge_textures.py --disc dump/tim/textures --dump bin/Release/net10.0/dump/SLUS-01382/pages --out dump/merged/textures && python tools/verify_textures.py --dir dump/merged/textures --out dump/report && python tools/upscale_textures.py --dump dump/merged --out packs/xmenma2-4x --only tiles --force
```

Headless verify with captures and resolver stats:

```bash
cd "C:/Programming/GitHub/X-Men - Mutant Academy 2/port/bin/Release/net10.0" && XMENMA2_TEXSTATS=1 XMENMA2_SHOT_DIR=shots XMENMA2_SHOTS="2700,3050,3900" XMENMA2_EXIT=4200 XMENMA2_SCRIPT="2900:cross:10;3200:cross:10" ./XMenMA2.exe
```

Re-publish the single-file exe:

```bash
cd "C:/Programming/GitHub/X-Men - Mutant Academy 2/port" && dotnet publish -c Release
```

## Working notes

- Sam is remoting in with no audio and cannot judge playback speed. Don't ask him to.
- Runs are not frame-deterministic: the game's progress follows wall clock, not frame
  count, so two runs diverge by the character-select screen. Comparing two runs at the
  same frame number does not work — capture a burst and match by content instead.
- `XMENMA2_SHOTS` matches frame numbers exactly, and the frame counter jumps by more
  than one during the 15 fps FMV stretch, so a shot asked for in that window can be
  stepped straight over and never fire. Ask for frames after ~2400, or use
  `XMENMA2_SHOT_EVERY`.
- He rejected VRAM-window fragment dumps as wasteful; whole-texture regions only.
- RecompOne fixes stay local — upstream rejects AI-authored PRs.
