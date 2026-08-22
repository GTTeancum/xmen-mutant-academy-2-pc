using System;
using System.Threading;
using RecompOne.Runtime.Assets.Textures;
using RecompOne.Runtime.Events;

namespace Recompiled;

/// <summary>
/// Headless control of the runtime's texture dumper, which is otherwise only reachable
/// from the debug menu.
///
///   XMENMA2_DUMP=tiles     dump each texture tile the game samples
///   XMENMA2_DUMP=pages     dump whole 256-texel texture pages
///   XMENMA2_DUMP=all       both
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
    static bool _tiles, _pages, _armed;

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
                case "all": _tiles = _pages = true; break;
            }
        }
        if (!_tiles && !_pages) return;

        Event.AddListener<VSyncEvent>(Arm);
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
