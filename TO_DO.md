# TO DO

Open items for the X-Men: Mutant Academy 2 RecompOne port. Things stay here until
they are resolved, not until they are explained.

## Needs hardware / a human

- [ ] **Audio has never been heard.** Music streams from the XA files and the SPU path
      is exercised, but nothing has confirmed it actually sounds right — or sounds at
      all. Sam is remoting in and has no audio.
- [ ] **CD-DA may be unused.** The disc carries 12 Red Book audio tracks and the game
      reads the TOC (`CdlGetTN`/`CdlGetTD`), but no `CdlPlay` was seen in any traced
      session. Either the music is entirely XA, or something is stopping the game from
      starting a CD-DA track. Needs an ear on it to tell which.
- [ ] **Playback speed of the FMVs.** The intro movies finish faster than they should:
      the stream feeds sectors as fast as the ring drains rather than pacing strictly
      to disc speed. Hard to judge without watching them next to a reference.
- [ ] **In-game timing sanity.** Round timers, animation speed and music tempo have not
      been compared against real hardware or an emulator.

## Port coverage

- [ ] **Two-player.** Versus mode loads both character overlays fine, but only port A
      has ever been driven. Port B input is wired in the runtime but untested.
- [ ] **Character coverage.** Fights have exercised a handful of the 18 characters.
      Each has its own pair of `.R` overlays, so the rest are untested code paths.
- [ ] **Endings and credits.** The per-character outro FMVs and `CREDITS.STR` have
      never been reached.
- [ ] **Memory card save/load round trip.** The card is detected and the directory
      loads, but nothing has actually written a save and read it back.
- [ ] **Practice mode.** `PRACTICE.BIN` is recompiled as an overlay but has not been
      entered.

## Upscaled textures

- [x] **Coverage is only as wide as what was played.** No longer true for the pack's
      main source: textures are read from `DATA/WAD.WAD` on the disc, so all 1,297 of
      them exist whether or not anyone has visited the screen that draws them.
      (2026-08-21)
- [ ] **Textures the disc does not explain.** Of the distinct images a long session
      drew, 102 are TIMs in the archive and 127 are not — those are assembled in main
      memory before upload, so they exist only while the game runs and are picked up by
      `XMENMA2_DUMP=pages`. The pack carries the 239 seen so far. Widening that needs
      more play, and the input-mashing harness used so far is crude: it reaches arcade
      fights but does not deliberately enumerate characters, costumes or stages.
- [ ] **Reaching every character, costume and stage on purpose.** Needs the front-end
      overlay disassembled; a byte search has been taken as far as it goes.
      `patches/Harness.cs` provides `XMENMA2_RAMDUMP` (main RAM + scratchpad),
      `XMENMA2_POKE` and `XMENMA2_WATCH`, so the next attempt starts with tooling rather
      than from scratch. What is already ruled out:
      - **The scratchpad.** Zero bytes changed across four character-select snapshots.
      - **`0x800AAAC0`.** Read `[20, 26, 32, 38]` — a perfect six per press. It is an
        animation counter that increments every frame and wraps at 77, and the snapshots
        were 160 frames apart: 160 mod 77 = 6. Watch a candidate across consecutive
        frames before believing it.
      - **`0x800EFE02` / `0x800EFE06`.** These genuinely track the selection — 0 until
        character select loads at frame 1982, then the roster index, stable in between,
        so not a counter. But writing them changes neither the on-screen portrait nor
        who loads: poked to 5 and confirmed, the fight still started Cyclops, and the
        game rewrote the value to 19 on confirm. They are a downstream mirror.
      Two traps worth keeping: the cursor **toggled** Cyclops/Wolverine across the
      snapshots rather than advancing, so the variable took only two distinct values and
      every "four distinct values" filter missed it — check the captures to see what the
      cursor actually did before choosing a filter. And a 3-frame tap does not register;
      6 frames does.
- [ ] **Show upscales at 1:1, never fit-to-screen.** A whole 1024px texture shrunk into
      a comparison sheet is displayed at roughly the original's own resolution, which is
      precisely the condition under which an upscale is invisible — two such sheets were
      sent and both read as "nothing looks upscaled", fairly. Crop to a small region and
      show it at output resolution. The in-game equivalent: a HUD portrait is about 200
      pixels in a 2048x960 capture, so it has to be cropped to read at all.
- [ ] **Judge the result on a real screen.** Still open, and still the thing that needs
      a human. The pack is now built from correctly decoded source rather than VRAM
      slabs, verifies at zero rejects, and hits 827 against 269 misses in game — but it
      has been judged from contact sheets and single captures, never watched in motion.
- [ ] **62 textures flagged as correct but not pictures.** Flat fills, two-tone blocks
      and colour ramps. They are in the pack, since upscaling them is harmless; the
      contact sheet is in the verify report if they are ever worth a second look. One
      known false positive: a "DOWN TOWN MOTEL" sign trips the colour-ramp test.
- [x] **16bpp textures have no whole-texture replacement.** They are not character
      skins, and there are few of them: a short session shows none at all, and a
      26,000-frame session shows 448 lookups, every one refused because the GPU had
      written that VRAM. Those are render-to-texture surfaces, so refusing them is
      right — a fixed image cannot stand in for something redrawn every frame. Closed
      as not a defect. Note the measurement trap: two earlier sessions showed zero
      16bpp lookups and that was briefly read as "the game has none". (2026-08-21)
- [ ] **Video memory.** The pack is around 146 MB of PNG and every texture the game
      draws becomes a GL texture. There is now an LRU eviction with a 512 MB budget in
      the runtime, but it has not been watched under a long session on this iGPU.

## Widescreen

- [x] **The HUD came out a third wide.** It is flat artwork at fixed screen positions,
      so it skipped the projection squeeze but got the presentation stretch. Nothing in
      the GPU stream tells it from the stage — matching the positions the GTE produced
      misses 75,000 of 82,000 triangles, four CLUTs are shared, and a fight draws
      everything from one ordering table with no `DrawPrim` at all. The game's own code
      does separate them: `func_80073630` indexes a 225-entry sprite table at
      `0x800E30D8`, stride `0x58`, and that table holds every 2D element it draws.
      Primitives assembled inside it are squeezed to match. (2026-09-04)
- [ ] **Never seen in motion.** Judged from single frames. Things a still cannot show:
      whether the 3D/flat detection flips shape during a transition, whether anything
      the game parks off-screen becomes visible now the view is wider, and whether the
      hall of mirrors reported in play is actually gone.
- [ ] **The squeeze changes what the game's own code sees.** Projected screen positions
      feed anything the game does in screen space, not just drawing. Nothing has
      misbehaved, but a camera or effect that reads back a projected coordinate is now
      reading a squeezed one.
- [x] **The output flickered between 4:3 and 16:9 mid-fight.** Presenting can run ahead
      of the game, so a frame could go up with no projections since the last one purely
      because the game had not built the next yet, and a single quiet present dropped the
      shape back to 4:3. It now takes half a second of no 3D to count as a flat screen.
      (2026-09-04)
- [ ] **`wide_check.py` measures the old approach.** It compares brightness across the
      4:3 frame edge, which only means anything when the render target is widened.
      Harmless, but it answers a question the port no longer asks.

## Full-screen pictures

- [x] **The pack could not reach them.** Pictures decoded straight into video memory
      bypass the texture path entirely, so the splash stayed at console resolution in
      front of upscaled menus. The uploads are now reassembled, hashed and replaced at
      full internal resolution. (2026-09-04)
- [ ] **Only the splash is in the pack.** The other 87 concept-art plates need visiting
      once with `XMENMA2_DUMP=images` to collect them, then the same
      `--only images` upscale. That means reaching the gallery, which is the same
      "get to a specific screen on purpose" problem as the character select.
- [ ] **The mask bit is not carried over.** A replacement is written fully opaque. The
      originals set the mask on every pixel, and nothing has been seen drawing over one
      of these pictures with mask testing on, so this has cost nothing yet -- but it is
      an assumption, not a finding.
- [ ] **Judged from captures.** The splash is visibly sharper in a presented frame, but
      like the rest of the pack it has never been watched on a real screen.

## Known rough edges

- [ ] **~60 unreachable call targets.** `tools/closure.py` cannot resolve them because
      they are jump-table analysis running off the end of a real table into data. No
      reachable path calls them, but each one is a latent `unmapped call` if that
      reasoning is ever wrong.
- [ ] **Overlay eviction is by containment.** RecompOne's dispatcher only unloads an
      overlay when the incoming one fully covers its address range. All 18 REL1
      overlays share a base but differ in size, so a smaller character loading over a
      larger one leaves stale entries in the function map. Nothing has misbehaved yet,
      but overlapping eviction would be more correct.

## Upstream

- [ ] **RecompOne fixes are local only.** Several are genuine upstream bugs (`MoveImage`
      reading its destination from the wrong registers, jump tables truncated at the
      first out-of-function case, `VSync(-1)` not observing time). RecompOne rejects
      AI-authored PRs on principle, so if these go upstream they go under Sam's name,
      his review, and his words.
