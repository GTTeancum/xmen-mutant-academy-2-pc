using RecompOne.Runtime;
using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;
using RecompOne.Runtime.Sdk;

namespace Recompiled;

/// <summary>
/// libgpu entry points that RecompOne does not reimplement by default.
///
/// The runtime already takes over DrawOTag/DrawSync/PutDrawEnv/PutDispEnv, which
/// bypasses libgpu's internal DMA command queue. Every other libgpu call that reaches
/// hardware goes *through* that queue (each dispatches via the GPU driver vtable at
/// 0x800A882C), so leaving them recompiled walks a queue nothing is filling any more
/// and ends up calling a null entry. They have to be reimplemented as a set: either
/// all of libgpu's hardware paths run natively, or none of them do.
/// </summary>
public static class GpuPatches
{
    // int ResetGraph(int mode)
    public static void ResetGraph(CpuContext c, IMemory m)
    {
        var gpu = Runtime.Gpu;
        if (gpu != null)
        {
            // mode 0 is a full reset; 1 and 3 only flush the command queue, and the
            // game uses 3 between screens where blanking the display would flicker.
            gpu.WriteGp1((c.A0 & 7u) == 0 ? 0x00000000u : 0x01000000u);
        }
        c.V0 = 0u;
    }

    // int SetDispMask(int mask)  -- 1 shows the display, 0 blanks it
    public static void SetDispMask(CpuContext c, IMemory m)
    {
        Runtime.Gpu?.WriteGp1(0x03000000u | (c.A0 != 0 ? 0u : 1u));
        c.V0 = 0u;
    }

    // int DrawPrim(void *p) -- send a single primitive packet
    public static void DrawPrim(CpuContext c, IMemory m)
    {
        var gpu = Runtime.Gpu;
        if (gpu == null) { c.V0 = 0u; return; }

        uint p = c.A0;
        uint words = m.ReadU32(p) >> 24;
        for (uint i = 0; i < words; i++)
            gpu.WriteGp0(m.ReadU32(p + 4u + i * 4u));
        c.V0 = 0u;
    }

    // int DrawOTagEnv(u_long *ot, DRAWENV *env)
    public static void DrawOTagEnv(CpuContext c, IMemory m)
    {
        uint ot = c.A0;
        c.A0 = c.A1;
        LibGpu.PutDrawEnv(c, m);
        c.A0 = ot;
        LibGpu.DrawOTag(c, m);
        c.V0 = 0u;
    }

    // ClearOTagR(u_long *ot, int n) -- reverse ordering table, ot[n-1] is the head
    public static void ClearOTagR(CpuContext c, IMemory m)
    {
        uint ot = c.A0;
        int n = (int)c.A1;
        if (n <= 0) { c.V0 = 0u; return; }

        for (int i = n - 1; i > 0; i--)
            m.WriteU32(ot + (uint)i * 4u, (ot + (uint)(i - 1) * 4u) & 0x00FFFFFFu);
        m.WriteU32(ot, 0x00FFFFFFu);
        c.V0 = 0u;
    }

    // ClearOTag(u_long *ot, int n) -- forward ordering table, ot[0] is the head
    public static void ClearOTag(CpuContext c, IMemory m)
    {
        uint ot = c.A0;
        int n = (int)c.A1;
        if (n <= 0) { c.V0 = 0u; return; }

        for (int i = 0; i < n - 1; i++)
            m.WriteU32(ot + (uint)i * 4u, (ot + (uint)(i + 1) * 4u) & 0x00FFFFFFu);
        m.WriteU32(ot + (uint)(n - 1) * 4u, 0x00FFFFFFu);
        c.V0 = 0u;
    }

    static uint _drawSyncCallback;

    // void (*DrawSyncCallback(void (*func)()))()
    public static void DrawSyncCallback(CpuContext c, IMemory m)
    {
        // DrawSync completes instantly here, so the callback would fire on every
        // DrawOTag with nothing left to wait for; remember it and stay quiet.
        uint previous = _drawSyncCallback;
        _drawSyncCallback = c.A0;
        c.V0 = previous;
    }

    // int GetODE(void) -- current interlaced field
    public static void GetODE(CpuContext c, IMemory m)
        => c.V0 = Runtime.Gpu != null ? (Runtime.Gpu.ReadStat() >> 31) & 1u : 0u;

    // int SetGraphDebug(int level)
    public static void SetGraphDebug(CpuContext c, IMemory m) => c.V0 = 0u;

    // int GetGraphDebug(void)
    public static void GetGraphDebug(CpuContext c, IMemory m) => c.V0 = 0u;
}
