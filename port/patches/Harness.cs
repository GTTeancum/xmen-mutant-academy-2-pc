using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using RecompOne.Runtime;
using RecompOne.Runtime.Events;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Reaching parts of the game a scripted controller cannot reliably reach.
///
/// Texture coverage is limited by what gets loaded, and what gets loaded is decided by
/// menu state: which character, which costume, which stage. Driving that with pad input
/// means long fixed-frame scripts, and this game paces itself off the wall clock rather
/// than the frame counter, so those scripts drift. Writing the selection directly does
/// not drift.
///
///   XMENMA2_RAMDUMP=2700,2900     write ram-&lt;frame&gt;.bin at these frames
///   XMENMA2_POKE=3000:80098abc=5  write a byte (or =5:w / =5:l for 16/32-bit)
///   XMENMA2_WATCH=80098abc,4      log this address every frame it changes
///
/// Addresses are PlayStation addresses; the usual 0x8009xxxx form works, and so does a
/// bare RAM offset. All of this is off unless the environment asks for it.
/// </summary>
public static class Harness
{
    sealed class Poke
    {
        public long Frame;
        public uint Address;
        public uint Value;
        public int Width;
    }

    sealed class Watch
    {
        public uint Address;
        public int Width;
        public uint Last;
        public bool Seen;
    }

    const uint ScratchpadBase = 0x1F800000;
    const int ScratchpadSize = 1024;

    static readonly HashSet<long> _dumpFrames = new();
    static readonly List<Poke> _pokes = new();
    static readonly List<Watch> _watches = new();
    static string _dir = "ram";
    static bool _active;

    public static void Install()
    {
        ParseDumps(Environment.GetEnvironmentVariable("XMENMA2_RAMDUMP"));
        ParsePokes(Environment.GetEnvironmentVariable("XMENMA2_POKE"));
        ParseWatches(Environment.GetEnvironmentVariable("XMENMA2_WATCH"));
        _dir = Environment.GetEnvironmentVariable("XMENMA2_RAMDIR") ?? "ram";
        if (!_active) return;

        Directory.CreateDirectory(_dir);
        Event.AddListener<VSyncEvent>(OnFrame);
        Console.WriteLine($"[harness] armed: dumps={_dumpFrames.Count} pokes={_pokes.Count} " +
                          $"watches={_watches.Count} -> {Path.GetFullPath(_dir)}");
    }

    static void ParseDumps(string spec)
    {
        if (string.IsNullOrWhiteSpace(spec)) return;
        foreach (var part in spec.Split(',', StringSplitOptions.RemoveEmptyEntries))
            if (long.TryParse(part.Trim(), out long f)) { _dumpFrames.Add(f); _active = true; }
    }

    static uint ParseAddress(string s)
    {
        s = s.Trim();
        if (s.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) s = s[2..];
        return uint.TryParse(s, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out uint v) ? v : 0;
    }

    static void ParsePokes(string spec)
    {
        if (string.IsNullOrWhiteSpace(spec)) return;
        foreach (var part in spec.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            int colon = part.IndexOf(':');
            int eq = part.IndexOf('=');
            if (colon < 0 || eq < colon) continue;
            if (!long.TryParse(part[..colon].Trim(), out long frame)) continue;
            uint addr = ParseAddress(part[(colon + 1)..eq]);
            string val = part[(eq + 1)..];
            int width = 1;
            int slash = val.IndexOf(':');
            if (slash >= 0)
            {
                width = val[(slash + 1)..].Trim().ToLowerInvariant() switch { "w" => 2, "l" => 4, _ => 1 };
                val = val[..slash];
            }
            if (!uint.TryParse(val.Trim(), out uint value)) value = ParseAddress(val);
            _pokes.Add(new Poke { Frame = frame, Address = addr, Value = value, Width = width });
            _active = true;
        }
    }

    static void ParseWatches(string spec)
    {
        if (string.IsNullOrWhiteSpace(spec)) return;
        foreach (var part in spec.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            var bits = part.Split(',');
            var w = new Watch { Address = ParseAddress(bits[0]), Width = 1 };
            if (bits.Length > 1 && int.TryParse(bits[1].Trim(), out int width)) w.Width = width;
            _watches.Add(w);
            _active = true;
        }
    }

    static uint Read(IMemory mem, uint address, int width) => width switch
    {
        4 => mem.ReadU32(address),
        2 => mem.ReadU16(address),
        _ => mem.ReadU8(address),
    };

    static void OnFrame(VSyncEvent e)
    {
        var mem = Runtime.Mem;
        if (mem == null) return;

        foreach (var p in _pokes)
        {
            if (p.Frame != e.Frame) continue;
            switch (p.Width)
            {
                case 4: mem.WriteU32(p.Address, p.Value); break;
                case 2: mem.WriteU16(p.Address, (ushort)p.Value); break;
                default: mem.WriteU8(p.Address, (byte)p.Value); break;
            }
            Console.WriteLine($"[harness] poke 0x{p.Address:x8} = {p.Value} (w{p.Width}) at frame {e.Frame}");
        }

        foreach (var w in _watches)
        {
            uint now = Read(mem, w.Address, w.Width);
            if (w.Seen && now == w.Last) continue;
            Console.WriteLine($"[harness] 0x{w.Address:x8} = {now} (was {(w.Seen ? w.Last.ToString() : "-")}) frame {e.Frame}");
            w.Last = now;
            w.Seen = true;
        }

        if (!_dumpFrames.Contains(e.Frame)) return;
        if (mem is PSMemory ps)
        {
            string path = Path.Combine(_dir, $"ram-{e.Frame:D5}.bin");
            File.WriteAllBytes(path, ps.Ram.ToArray());

            // The scratchpad as well. It is only a kilobyte, it is not part of the RAM
            // array, and it is exactly where a PlayStation game puts the small hot
            // variables a menu cursor is made of -- so a differential search that only
            // looks at main RAM can miss the thing it is looking for entirely.
            var pad = new byte[ScratchpadSize];
            for (int i = 0; i < pad.Length; i++) pad[i] = mem.ReadU8((uint)(ScratchpadBase + i));
            File.WriteAllBytes(Path.Combine(_dir, $"pad-{e.Frame:D5}.bin"), pad);

            Console.WriteLine($"[harness] ram + scratchpad snapshot frame {e.Frame} -> {path}");
        }
        else
        {
            Console.Error.WriteLine("[harness] memory is not a PSMemory; cannot snapshot");
        }
    }
}
