# X-Men: Mutant Academy 2 — RecompOne port

A static recompilation of *X-Men: Mutant Academy 2* (SLUS-01382, USA) built with
[RecompOne](https://github.com/BlackLabelHQ/RecompOne). The PS1 executable and its
overlays are translated to C# ahead of time and linked against RecompOne's runtime,
which emulates the console's hardware around them. There is no interpreter and no
BIOS image; the disc in the repository root is the only game data required.

Runs at 60 fps, rasterised at 4× the console's resolution (a 1280×960 window by
default), from the boot logos through the FMVs, memory card check, menus, character
select and into full fights.

## Layout

```
port/
  config/xmen.json        recompiler config: overlays, patches, SDK routing
  config/funcmaps/        function maps (committed; regenerate with tools/)
  patches/                C# that replaces or hooks game functions
  tools/                  the map pipeline and the build driver
  generated/              recompiled C# (regenerated, not committed)
  Program.cs              entry point
```

The disc lives in the repository root and is not committed. `generated/` is derived
from it and is not committed either.

## Building

Requires the .NET 10 SDK. From `port/`:

```bash
bash tools/build.sh
```

That runs the whole pipeline: rebuild the function maps, recompile, close the call
graph, and build the executable. The first run also needs the raw sweeps:

```bash
bash tools/genmaps.sh
```

Then run `bin/Release/net10.0/XMenMA2.exe`. It finds the `.cue` by walking up from the
executable, so no arguments are needed.

## How the function maps are built

The game has no decompilation, so nothing hands us function boundaries or names. Four
passes produce them, in `tools/`:

1. **`genmaps.sh`** — RecompOne's linear sweep over the main executable and all 38
   overlays. This is the raw material and it is noisy: the sweep treats every word as
   a possible instruction, so data that happens to decode as `jal` invents function
   starts in the middle of real functions.

2. **PsyQ signature matching** (`config/funcmaps/psyq_main.json`) — the game statically
   links PsyQ 4.7. Matching each library function's code against the executable, with
   relocated fields masked out and ambiguities resolved by cross-checking relocation
   targets, recovers 258 SDK symbols. This is what makes the port possible: RecompOne
   routes libgpu/libcd/libpad/libcdstream calls to its runtime *by name*, so naming
   `VSync`, `DrawOTag`, `CdRead` and friends is what turns hardware access into
   something the host can serve. `manual.json` holds a handful of one-instruction
   library stubs that no signature can tell apart, resolved by reading the code.

3. **`fixmaps.py`** — rebuilds each map around one rule: a real function start is the
   first word of the module, a symbol we identified, a `jal` target read from inside a
   function we have already proven ends in a return, or a pointer target that lands on
   a boundary (nothing can fall through into it). Extents are natural — walk forward
   tracking the furthest forward branch, stop at the first return past it — and are
   deliberately allowed to overlap, because a function can legitimately be entered in
   the middle.

4. **`closure.py`** — RecompOne turns every control transfer that leaves a function
   into `Dispatcher.Call(addr)`, and a target nothing defines throws `unmapped call`
   the first time the game takes that path. Those are all visible in the generated C#,
   so this scans for them and feeds the ones that decode as code back in as forced
   starts. `build.sh` iterates until it stops finding new ones. About 60 remain: they
   are jump-table analysis running off the end of a real table into data, so no
   reachable code path can call them.

## Patches

`config/xmen.json` wires the C# in `patches/` over game functions.

- **`GpuPatches`** — the libgpu entry points RecompOne does not reimplement by
  default. The runtime takes over `DrawOTag`/`DrawSync`/`PutDrawEnv`/`PutDispEnv`,
  which bypasses libgpu's internal DMA command queue; every other libgpu call that
  reaches hardware dispatches through the same queue, so leaving them recompiled walks
  a queue nothing is filling and calls a null entry. They have to be reimplemented as
  a set.
- **`PadPatches`** — the game initialises input through `PadInitMtap`, not the
  `PadInitDirect` the runtime implements. It passes two 34-byte buffers 0x22 apart,
  i.e. only slot 0 of each port, so forwarding to direct mode gives exactly the layout
  it expects.
- **`Capture`** — headless verification: screenshots straight off the GPU backend,
  scripted controller input, and a frame limit. Off unless the environment asks.
- **`Diag`** — logging and freeze diagnosis, below.
- **`Trace`** — optional instrumentation on the movie player and the memory card path,
  silent unless `XMENMA2_TRACE` is set.
- **`TextureDump`** — headless control of the runtime's texture dumper, which is
  otherwise only reachable from the debug menu.

## Upscaled textures

`packs/xmenma2-4x/` replaces the game's textures with 4x Real-ESRGAN upscales.
The runtime looks each texture up by a hash of its VRAM contents and CLUT, and falls
straight back to the original when there is no match, so the pack is additive: a
missing or deleted texture costs nothing but sharpness. Delete the folder to turn the
whole thing off.

Textures come from the disc, not from a play session. The game ships every one of them
in `DATA/WAD.WAD` as a TIM -- pixels, palette, depth, and the VRAM coordinates it will
be uploaded to -- so they can all be read without playing at all, and without the
framing guesswork that reading them back out of VRAM involves.

**1. Extract.** Pull the archive off the disc and decode every image in it:

```bash
python tools/disc.py extract disc                       # ISO 9660 out of the MODE2/2352 image
python tools/extract_textures.py --wad disc/DATA/WAD.WAD --out dump/tim
```

`tools/tim.py` accepts a TIM only when its block lengths agree with the dimensions those
blocks declare and its VRAM coordinates land inside the framebuffer, which is strict
enough to sift 1,891 real images out of 54 MB of game data without false positives.
Each one is written under the name the runtime will look it up by, so the output is a
pack once it has been upscaled -- see `tools/vramhash.py`, which reimplements
`TextureTile.Hash` exactly.

A texture's palette in VRAM is not always the palette on the disc: uploading a CLUT with
the GPU's mask bit set turns bit 15 on in every entry, which leaves the colours alone
and changes the key. Both forms are written. A key the game never asks for costs a file
and nothing else.

**2. Check.** Confirm every image is something a person can recognise:

```bash
python tools/verify_textures.py --dir dump/tim/textures --out dump/tim/report
```

This separates two questions. A wrong-depth decode splits each byte into two nibbles and
interleaves a coarse picture with noise down alternating columns -- invisible in a
thumbnail, obvious in the statistics -- and anything showing that is rejected. Flat
panels, two-tone blocks and colour ramps are correct but are not pictures, so they are
flagged for a person rather than rejected. Contact sheets per verdict land in `--out`.

**3. Dump (optional, for what the disc does not explain).** Play with `XMENMA2_DUMP=all`,
which writes `dump/SLUS-01382/`:

```bash
XMENMA2_DUMP=all ./bin/Release/net10.0/XMenMA2.exe
```

`pages/` gets whole texture pages, and that is what the pack is built from. `textures/`
gets the individual tiles the game samples, which is worth understanding before using:
a tile is one triangle's UV window, not a texture. This game samples a couple of
hundred real textures through 35,000 such windows, the busiest one about eight times
over, so a tile-based pack is enormous, upscales every fragment without its
surroundings, and seams where neighbouring fragments meet. Pages are the actual
textures; the resolver falls back from a tile to the page it came from, so 265 page
files cover what 35,571 tile files did. Coverage is only as wide as what you visit, so play broadly; the dump accumulates
across runs. FMV never appears here — movie frames are decoded straight to the
framebuffer and are never sampled as textures.

16bpp textures are real, rare, and correctly left alone. `XMENMA2_TEXSTATS=1` counts
region lookups by depth and by outcome, and a short session — menus, character select,
one fight — shows no 16bpp lookups at all, which is easy to mistake for "the game does
not use them". A 26,000-frame session finds 448, and every one is refused because the
GPU had written that VRAM. That is the correct answer rather than a defect: a texture
the GPU just rendered into is dynamic, and substituting a fixed image for it would
replace something that changes every frame. The lesson is about measurement, not about
16bpp — a depth that never appears in a short run has not been shown to be absent.

**4. Upscale.**

```bash
python tools/upscale_textures.py --dump bin/Release/net10.0/dump/SLUS-01382 --out packs/xmenma2-4x --only pages
```

Four things about this game's textures decide how this has to work.

*Alpha is a flag, not a gradient.* A texel is transparent, semi-transparent (the STP
bit) or opaque, and the shader reads that back at exactly 0 / 128 / 255 — anything in
between changes which of the three a pixel means. So the network never sees the alpha
channel. It upscales RGB only, and the alpha is rebuilt by scaling one mask per state
and taking the winner per pixel, which keeps the three values exact while still giving
a 4x-resolution silhouette.

*Transparent pixels are black.* Feeding that in drags dark halos around every sprite
edge, so transparent areas are flood-filled with the nearest opaque colour first. That
fill is discarded afterwards; it exists only to give the network something sensible to
blend towards.

*The art is dithered, and dither does not survive magnification.* A 16-entry palette
cannot hold a gradient, so the artists alternated two entries every other pixel to fake
the shades in between — vertical stripes, horizontal stripes, checkerboard, whichever
suited. Enlarge that and it stops reading as shading and starts reading as grain, and a
network reads it as structure and redraws it into swirls. Neither is fixable by using
less of the network: mixing its output back towards a plain resample of the original
just trades invented linework for magnified noise, which is what the old `--strength`
dial did and why 0.4 still looked grainy.

So the dither is cancelled before the network sees it. Each of the three patterns is
measured on its own — multiply by the alternating sign and take an even-sized box mean,
and only that exact pattern survives — and cancelled only along the axes it runs
against, with a `[1,2,1]` kernel whose zero sits exactly at the dither's frequency.
Two guards keep it off things that only look like dither: the pattern has to cover an
area (a morphological opening, so the two dark rows inside a letter are not mistaken
for shading), and anything below the mask's dead zone is passed through bit-identical
rather than slightly blurred. That second guard matters more than it sounds — the
fonts and UI art are hard-edged pixel work, and the network is unstable enough on them
that a few levels of stray blur is the difference between clean glyphs and invented
marks inside them.

*The network will drift the colour if you let it.* Even on de-dithered input it shifts
hue and flattens shading. So only its high frequencies are used: everything coarser
than `--detail` (default 4 output pixels, one source texel) comes from the original,
plainly resampled.

Sweeping that radius from 4 to 32 and on to the raw network changes the sharpness of
the result not at all, and changes the colour drift by a factor of twenty-five — 0.1 at
radius 4 against 2.5 for the raw network, measured against the original's own low
frequencies. The default is cheap in exactly the way it should be: all of the network's
detail, almost none of its drift.

A warning about measuring this, because it cost a wrong conclusion. "High-frequency
energy" — the mean deviation from a blurred copy — is *not* a measure of detail here.
Nearest-neighbour magnification scores highest of anything on it, because hard pixel
steps are high frequency, so by that number a blocky image beats a good upscale and a
correct pack looks like a plain resize. Judge sharpness by looking at a crop at 1:1,
not by that statistic.

The default model is `realesrgan-x4plus-anime`, which came out visibly sharper on this
game's art than `realesr-animevideov3` — cleaner UI panel edges and defined shapes in
the character textures rather than a blur. The general `realesrgan-x4plus` model will
not fit in this machine's iGPU at any tile size. Don't run the upscaler while the game
is running: both want the GPU, and on shared memory the heavier models fail to
allocate.

## Diagnostics

Everything goes into one file: `logs/xmenma2-<timestamp>.log`, every line timestamped
and tagged with the frame number, flushed immediately. Console output is teed into it,
and so are the three things `Console` cannot be trusted to carry — unhandled
exceptions, which the .NET runtime writes straight to the native stderr handle;
watchdog output, which has to survive the game thread wedging while it holds Console's
lock; and primitive dumps, which are too bulky to interleave. Those paths take the
log's lock with a timeout and fall back to a second handle on the same file, so a
wedge elsewhere cannot silence them.

A watchdog thread tracks the frame rate — the rate, not just whether frames moved,
because the stall breaker keeps a wedged game crawling forward at a frame every few
seconds. Below 12 fps it reports the CPU context, the resident overlays, the display
and CD state, and the tail of the call ring collapsed into `function xN` runs, which
makes a tight spin obvious at a glance.

The call ring itself comes from RecompOne's `callRing` config option, which emits one
array store per function entry. That is cheap enough to leave on permanently, and
printing every entry (the `debug` option) is far too slow to reach a failure.

| variable | meaning |
| --- | --- |
| `XMENMA2_LOG` | `bios,sdk,cd,gpu,dma,spu,mdec,all` |
| `XMENMA2_LOG_DIR` | log directory (default `logs`) |
| `XMENMA2_STALL` | seconds below 12 fps before a dump (0 disables) |
| `XMENMA2_STALL_EXIT` | quit after the first stall dump |
| `XMENMA2_SHOT_EVERY` / `XMENMA2_SHOTS` | capture frames |
| `XMENMA2_SHOT_DIR` | where captures go (default `shots`) |
| `XMENMA2_SCRIPT` | `frame:button[:hold];...` scripted input |
| `XMENMA2_MARK` | log a marker every N frames |
| `XMENMA2_EXIT` | quit after frame N |
| `XMENMA2_TRACE` | enable the `Trace` hooks |
| `XMENMA2_PRIMS` | frames to log every drawn primitive on |
| `XMENMA2_DUMP` | `tiles`, `pages` or `all` — dump textures for upscaling |

## Changes made to RecompOne

The submodule under `tools/RecompOne` carries local changes. They are game-agnostic
and each fixes something this port hit:

- **Idle-loop breaker** (`Runtime.IdleTick`, `PSMemory`) — games wait for an interrupt
  by spinning on a variable their handler writes, but interrupts are only delivered
  while presenting a frame, so a wait loop that does not call `VSync` itself never
  exits. A long run of memory reads with no intervening write now presents a frame and
  delivers the vblank, the way the hardware's interrupt would have arrived.
- **Call-count stall breaker** (`Diagnostics/CallRing`) — the same problem for a loop
  whose body is a call rather than a memory read.
- **Asynchronous memory card completion** (`Bios/BiosB`) — libmcrd starts a card
  operation, then clears its event flags and only afterwards waits on them. A
  completion delivered inside the BIOS call is wiped by that clear and the wait never
  ends. Completions are now queued and re-offered while the game idles, until they age
  out.
- **Jump tables may leave the function** (`JumpTableAnalyzer`, `InstructionEmitter`) —
  a switch case that is a tail jump lands on the next function, and stopping at the
  first such entry silently discarded every case after it. Those fell through to the
  indirect fallback and crashed on any input that selected one. This was the cause of
  the mid-fight freeze.
- **`VSync(-1)` observes time passing** (`LibEtc`) — it reads the vblank counter
  without waiting, and on hardware that counter advances on its own, so a game can poll
  it to wait. Here it only moved when a frame was presented, so a poll loop only
  crawled forward via the stall breaker: the game ran at 0.6 fps whenever it took that
  path. It now presents a frame once a frame's worth of real time has elapsed.
- **`MoveImage` read the destination from the wrong registers** (`LibGpu`) — the
  signature is `MoveImage(RECT *rect, int x, int y)`, but the destination was taken
  from `a2`/`a3` instead of `a1`/`a2`. Every VRAM-to-VRAM copy landed somewhere else,
  which garbled the pause overlay and scattered texture data through the frame.
- **Per-overlay `debug`, and a `callRing` option** — tracing one overlay at a time is
  the only practical way to find where an overlay's state machine stalls.
- **Configurable window size** (`ViewConfig`, `HostWindow`) — defaults to 1280×960.
- **Texture pages span the whole UV range** (`TextureResolver`) — a page was sized by
  the hardware's texpage, 64 VRAM words, which is 256 texels at 4bpp but only 128 at
  8bpp and 64 at 16bpp. UVs are 8-bit at every depth, so a texture addresses up to 256
  texels and runs on into the neighbouring columns; everything past the page edge
  clamped and smeared into horizontal streaks. Pages are now 256 texels wide at every
  depth, which is what makes whole-texture replacement usable at all.
- **Replacement textures are evicted** (`GlCore`) — they were uploaded once and kept
  forever, which a large upscaled pack turns into an unbounded video-memory leak.
- **A texture is what the game uploaded, not the page it landed in** (`VramTracker`,
  `TextureResolver`) — the resolver used to identify a texture by a fixed 256-texel
  window around the tile being drawn. In a game that packs several images into the same
  VRAM rows that window is a slab of unrelated neighbours, all decoded with one depth
  and one palette, so most of every dumped "texture" was garbage and the hash covered
  data the texture does not own. `VramTracker` now records the rectangle of each image
  the CPU DMAs into VRAM, and the resolver identifies a tile by the upload that contains
  it. That is the only event in the GPU command set that says "these pixels are one
  picture". It is also what makes textures read straight off the disc addressable, since
  a TIM's own extent is the extent the game uploads.
- **Region lookups are counted by depth** (`TextureResolver`) — `XMENMA2_TEXSTATS=1`
  reports, per depth, how many whole-texture regions were accepted and how many were
  refused for each of the four possible reasons. Without that, "no 16bpp textures in
  the dump" reads identically to "every 16bpp texture is being refused", and the two
  call for opposite work.

## Publishing

`dotnet publish` produces a single self-contained `dist/XMenMA2.exe` — runtime, managed
dependencies and native libraries all bundled, nothing beside it but the game's data.
The properties are scoped to publishing so ordinary builds keep their layout.

The bundle extracts everything, not only the native libraries. Extracting the natives
alone leaves them in a temp folder while `AppContext.BaseDirectory` still points at the
executable, and Silk.NET searches `BaseDirectory` — so GLFW and OpenAL were never
found, and the published build came up with no window and no audio while the ordinary
build from `bin/` was fine. The log for it is distinctive:

```
[Host] context 4.5 unavailable: Couldn't find a suitable window platform.
[Host] no usable gl context were found
[Host] audio init failed: Could not load from any of the possible library names!
```

Extracting everything puts the managed assemblies and the natives in the same folder,
which is where the loader looks. Nothing depends on `BaseDirectory` staying next to the
executable: `Program.Main` resolves the executable through `Environment.ProcessPath` and
makes it the working directory, and packs, saves, logs and dumps all hang off that.
Test a publish by launching it, not by building it — this failed silently for anyone
reading build output alone.

## Known gaps

- CD-DA is not exercised: the game's music streams from the XA files, and although it
  reads the disc TOC it never issued a `CdlPlay` in testing. Worth confirming by ear.
- The intro FMVs play faster than on hardware; the stream feeds sectors as fast as the
  ring drains rather than pacing strictly to disc speed.
- Two-player input is wired for port A only in the scripted-capture path; the runtime
  handles port B normally.
