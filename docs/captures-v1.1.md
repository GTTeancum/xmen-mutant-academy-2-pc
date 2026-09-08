# v1.1 capture provenance

Captured on 2026-09-08 from the published Windows x64 v1.1.0 executable with the bundled 4x pack. Images were read through the game's native `ReadPresented` GPU capture path, using `port/patches/Capture.cs`. Scripted buttons were written only to the game's own pad buffers; no desktop input or desktop capture was used.

Common environment:

```text
XMENMA2_WIDE=on
XMENMA2_SHOT_PRESENTED=1
XMENMA2_SHOT_EVERY=300
```

| Run | XMENMA2_SCRIPT | XMENMA2_EXIT | Selected frame |
| --- | --- | --- | --- |
| Cyclops vs. Rogue | 2900:cross:10;3200:cross:10 | 5400 | 3900 |
| Wolverine vs. Phoenix | 2900:cross:10;3100:right:10;3200:cross:10 | 6600 | 3900 |

Gameplay originals: `gameplay.png` and `gameplay-wolverine.png`, each 2048x1152. `title.png` is run A frame 2700 and `splash.png` is run A frame 300. Both are 2048x1536.

The comparison diagrams preserve the gameplay capture at its original size, add a 120-pixel caption band, and outline the central 1536-pixel-wide region (x=256 to x=1792). This is a 4:3 field-of-view guide within the 16:9 image, not a second render with widescreen disabled. The overlays were drawn as SVG and rasterized with resvg; no game pixels were generated or retouched.

Game progress also depends on wall clock, so the same scripted inputs do not guarantee an identical opponent, stage, or pose on another run.

Validation: both published-executable runs reached gameplay and their configured exit frames; all 1,434 texture PNGs and the splash PNG passed image validation. The release archive passed ZIP CRC checks and contains only the executable, installation guide, and `packs/xmenma2-4x/` files.
