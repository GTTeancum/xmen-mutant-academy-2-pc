using System;
using RecompOne.Runtime;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;

namespace Recompiled;

/// <summary>
/// Temporary instrumentation hooks, wired by address from config/xmen.json.
/// Enabled only when XMENMA2_TRACE is set.
/// </summary>
public static class Trace
{
    static readonly bool On = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("XMENMA2_TRACE"));

    static long _movieCalls;
    static long _waitCalls;

    // front: PlayMovie(struct *) at 0x801CC764
    public static void PlayMovieEnter(CpuContext c, IMemory m)
    {
        if (!On) return;
        uint id = m.ReadU16(c.A0);
        Console.WriteLine($"[trace] PlayMovie #{++_movieCalls} arg=0x{c.A0:X8} fileId={id}");
    }

    public static void PlayMovieExit(CpuContext c, IMemory m)
    {
        if (!On) return;
        Console.WriteLine($"[trace] PlayMovie returned v0={c.V0}");
    }

    static long _waitEvt;

    // libcard flags the card callbacks set (0x801065B8.. and 0x801065C8..)
    static string Flags(IMemory m)
    {
        string s = "";
        for (uint i = 0; i < 8; i++)
            s += m.ReadU32(0x801065B8u + i * 4u).ToString() + (i == 3 ? "|" : "");
        return s;
    }

    public static void ClrCardEvent(CpuContext c, IMemory m)
    {
        if (!On) return;
        Console.WriteLine($"[trace] _clr_card_event flags={Flags(m)}");
    }

    public static void GetCardEventX(CpuContext c, IMemory m)
    {
        if (!On) return;
        Console.WriteLine($"[trace] _get_card_event_x enter flags={Flags(m)}");
    }

    public static void GetCardEventXExit(CpuContext c, IMemory m)
    {
        if (!On) return;
        Console.WriteLine($"[trace] _get_card_event_x -> v0={c.V0}");
    }

    public static void MemCardOp(CpuContext c, IMemory m)
    {
        if (!On) return;
        Console.WriteLine($"[trace] MemCardGetDirentry(chan={c.A0}) flags={Flags(m)}");
    }

    public static void MemCardOpExit(CpuContext c, IMemory m)
    {
        if (!On) return;
        Console.WriteLine($"[trace] MemCardGetDirentry -> v0={c.V0}");
    }

    // front: wait-for-stream-frame at 0x801CC530
    public static void WaitFrameEnter(CpuContext c, IMemory m)
    {
        if (!On) return;
        if ((++_waitCalls % 200000) == 0)
            Console.WriteLine($"[trace] StGetNext wait spin x{_waitCalls}");
    }
}
