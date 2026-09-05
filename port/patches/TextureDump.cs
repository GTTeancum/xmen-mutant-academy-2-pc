using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using RecompOne.Runtime.Assets;
using RecompOne.Runtime.Assets.Images;
using RecompOne.Runtime.Assets.Textures;
using RecompOne.Runtime.Events;

namespace Recompiled;

/// <summary>
/// Headless control of the runtime's texture dumper, which is otherwise only reachable
/// from the debug menu.
///
///   XMENMA2_DUMP=tiles     dump each texture tile the game samples
///   XMENMA2_DUMP=pages     dump whole 256-texel texture pages
///   XMENMA2_DUMP=images    dump pictures decoded straight into video memory
///   XMENMA2_DUMP=all       all of them
///
/// Both are worth having. Tiles are what the game actually draws and give the exact
/// hash a replacement is looked up by; pages are the catch-all, because when no tile
/// replacement exists the resolver falls back to the page the tile came from, so one
/// upscaled page covers every tile inside it -- including ones a play session never
/// happened to touch.
///
/// The dumper reads the game id from the asset manager, which is only resolved once
/// the disc is open, so this arms itself on the first frame rather than at startup.
/// </summary>
public static class TextureDump
{
    static bool _tiles, _pages, _images, _armed;

    public static void Install()
    {
        var spec = Environment.GetEnvironmentVariable("XMENMA2_DUMP");
        if (string.IsNullOrWhiteSpace(spec)) return;

        foreach (var part in spec.Split(','))
        {
            switch (part.Trim().ToLowerInvariant())
            {
                case "tiles": _tiles = true; break;
                case "pages": _pages = true; break;
                case "images": _images = true; break;
                case "all": _tiles = _pages = _images = true; break;
            }
        }
        if (!_tiles && !_pages && !_images) return;

        if (_images) InstallImageDump();
        if (!_tiles && !_pages) return;

        Event.AddListener<VSyncEvent>(Arm);
    }

    /// <summary>
    /// Pictures the game decodes straight into video memory never reach the texture
    /// dumper, because they are not textures. They are written out here instead, named
    /// by the hash the runtime will look a replacement up by, so an upscale of one of
    /// these files drops straight back into the pack under the same name.
    /// </summary>
    static void InstallImageDump()
    {
        string dir = Environment.GetEnvironmentVariable("XMENMA2_IMAGE_DIR") ?? "dump/images";
        Directory.CreateDirectory(dir);
        Console.WriteLine($"[dump] screen images -> {Path.GetFullPath(dir)}");

        var seen = new HashSet<ulong>();
        ScreenImages.Completed = (hash, w, h, px) =>
        {
            lock (seen)
                if (!seen.Add(hash)) return;

            // 15-bit colour with the mask bit on top, out to 8 bits a channel. The mask
            // is not opacity and would make a transparent PNG of a solid picture, so the
            // dump is written fully opaque.
            var rgba = new byte[w * h * 4];
            for (int i = 0; i < px.Length && i * 4 + 3 < rgba.Length; i++)
            {
                ushort v = px[i];
                rgba[i * 4 + 0] = (byte)((v & 0x1F) << 3);
                rgba[i * 4 + 1] = (byte)(((v >> 5) & 0x1F) << 3);
                rgba[i * 4 + 2] = (byte)(((v >> 10) & 0x1F) << 3);
                rgba[i * 4 + 3] = 255;
            }

            string path = Path.Combine(dir, $"{hash:x16}.png");
            try
            {
                PngWriter.WriteRgba(path, rgba, w, h);
                Console.WriteLine($"[dump] screen image {w}x{h} -> {Path.GetFileName(path)}");
            }
            catch (Exception ex) { Console.Error.WriteLine($"[dump] {path}: {ex.Message}"); }
        };
    }

    static void Arm(VSyncEvent e)
    {
        if (_armed || e.Frame < 2) return;
        _armed = true;
        if (_tiles) TextureDumper.SetTiles(true);
        if (_pages) TextureDumper.SetPages(true);
        Console.WriteLine($"[dump] texture dump on (tiles={_tiles} pages={_pages}) -> {TextureDumper.Root}");

        new Thread(Report) { IsBackground = true, Name = "dump-report" }.Start();
    }

    static void Report()
    {
        int last = -1;
        while (true)
        {
            Thread.Sleep(15000);
            int written = TextureDumper.Written;
            if (written == last) continue;
            last = written;
            Console.WriteLine($"[dump] seen={TextureDumper.UniqueSeen} written={written} " +
                              $"pending={TextureDumper.Pending} dropped={TextureDumper.Dropped} " +
                              $"failed={TextureDumper.Failed}");
        }
    }

    /// <summary>
    /// XMENMA2_TEXSTATS=1 -- report what the texture resolver is actually doing:
    /// how many lookups found a replacement, how many found nothing, and how many were
    /// refused because the GPU had written that VRAM this frame. That last number is
    /// the one that says whether a replacement is pulling its weight: a tile sampled
    /// out of the framebuffer is dynamic, so the resolver will never substitute it no
    /// matter what the pack contains.
    ///
    /// The second line breaks the whole-texture region lookups down by depth and by
    /// why each one was refused. Every 16bpp texture in this game has been falling back
    /// to the original, and these counts say which of the four ways that can happen is
    /// actually happening.
    /// </summary>
    public static void InstallStats()
    {
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("XMENMA2_TEXSTATS"))) return;
        new Thread(() =>
        {
            while (true)
            {
                Thread.Sleep(10000);
                var mgr = RecompOne.Runtime.Assets.AssetReplacerManager.Instance;
                Console.WriteLine($"[tex] hits={mgr.Stats.TextureHits} misses={mgr.Stats.TextureMisses} " +
                                  $"| {RecompOne.Runtime.Assets.Textures.TextureResolver.StatsLine()}");
                Console.WriteLine($"[tex] {RecompOne.Runtime.Assets.Textures.TextureResolver.RegionStatsLine()}");
            }
        })
        { IsBackground = true, Name = "tex-stats" }.Start();
        Console.WriteLine("[tex] resolver stats armed");
    }
}
