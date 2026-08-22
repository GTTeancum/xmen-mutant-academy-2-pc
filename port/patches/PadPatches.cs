using RecompOne.Runtime.Context;
using RecompOne.Runtime.Memory;
using RecompOne.Runtime.Sdk;

namespace Recompiled;

/// <summary>
/// X-Men: Mutant Academy 2 initialises input through libpad's multitap entry point
/// (PadInitMtap) rather than PadInitDirect, which is the only variant the runtime
/// reimplements. The game passes two 34-byte buffers 0x22 apart, i.e. it only ever
/// uses slot 0 of each port, so forwarding to the direct-mode implementation gives
/// exactly the layout the game expects.
/// </summary>
public static class PadPatches
{
    /// <summary>Port A / port B pad buffers, as handed to PadInitMtap.</summary>
    public static uint Buf1, Buf2;

    // void PadInitMtap(u_char *pad1, u_char *pad2)
    public static void PadInitMtap(CpuContext c, IMemory m)
    {
        Buf1 = c.A0;
        Buf2 = c.A1;
        LibPad.PadInitDirect(c, m);
        c.V0 = 0;
    }

    // int PadChkMtap(void) -- no multitap is emulated
    public static void PadChkMtap(CpuContext c, IMemory m) => c.V0 = 0;
}
