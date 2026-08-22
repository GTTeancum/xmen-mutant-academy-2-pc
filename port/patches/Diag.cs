using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using RecompOne.Runtime;
using RecompOne.Runtime.Diagnostics;
using RecompOne.Runtime.Dispatch;

namespace Recompiled;

/// <summary>
/// Logging and freeze diagnosis. Everything lands in one file:
/// <c>logs/xmenma2-&lt;timestamp&gt;.log</c>.
///
/// Every line carries a timestamp and the frame number and is flushed immediately, so
/// a hard hang still leaves a complete tail. Console output is teed into it, and so
/// are the three things Console cannot be trusted to carry:
///
///   * unhandled exceptions, which the .NET runtime writes straight to the native
///     stderr handle -- without catching them the log just stops mid-sentence;
///   * the watchdog heartbeat and stall reports, which have to survive the game thread
///     wedging while it holds Console's lock;
///   * primitive dumps, which are far too bulky to interleave through Console.
///
/// Those paths take the log's own lock with a timeout and fall back to appending
/// through a second handle, so a wedge anywhere else cannot silence them.
///
/// A recompiled game that locks up gives you nothing by itself -- no PC, no
/// interpreter loop, just a window that goes "Not Responding" -- so the watchdog
/// reports the CPU context, the resident overlays, the display and CD state, and the
/// tail of the call ring collapsed into "function xN" runs, which makes a tight spin
/// obvious at a glance.
/// </summary>
public static class Diag
{
    public static long Frame;

    static FileStream _stream;
    static string _path;
    static readonly object _gate = new();

    static double _stallSeconds = 8;
    static bool _exitOnStall;
    static Dictionary<uint, string> _symbols;

    public static void Install()
    {
        string dir = Environment.GetEnvironmentVariable("XMENMA2_LOG_DIR") ?? "logs";
        if (double.TryParse(Environment.GetEnvironmentVariable("XMENMA2_STALL"),
                            NumberStyles.Float, CultureInfo.InvariantCulture, out var sv))
            _stallSeconds = sv;
        _exitOnStall = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("XMENMA2_STALL_EXIT"));

        try
        {
            Directory.CreateDirectory(dir);
            _path = Path.Combine(dir, $"xmenma2-{DateTime.Now:yyyyMMdd-HHmmss}.log");
            _stream = new FileStream(_path, FileMode.Create, FileAccess.Write, FileShare.ReadWrite);
            Console.SetOut(new Tee(Console.Out));
            Console.SetError(new Tee(Console.Error));
            Console.WriteLine($"[diag] logging to {Path.GetFullPath(_path)}");
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"[diag] could not open log file: {e.Message}");
        }

        LoadSymbols();
        InstallPrimDump();

        if (_stallSeconds > 0)
        {
            new Thread(Watch) { IsBackground = true, Name = "watchdog" }.Start();
            Console.WriteLine($"[diag] watchdog armed ({_stallSeconds:F0}s window)");
        }
    }

    // ---- the one log ------------------------------------------------------------

    /// <summary>Write raw text to the log, prefixing each line with time and frame.</summary>
    static void Write(string text)
    {
        if (_stream == null || string.IsNullOrEmpty(text)) return;

        var sb = new StringBuilder(text.Length + 64);
        long f = Interlocked.Read(ref Frame);
        string stamp = $"{DateTime.Now:HH:mm:ss.fff} f{f,-7} ";
        foreach (var line in text.Split('\n'))
            sb.Append(stamp).Append(line.TrimEnd('\r')).Append(Environment.NewLine);
        var bytes = Encoding.UTF8.GetBytes(sb.ToString());

        // Held only for the length of one write. A caller that cannot get in within a
        // couple of seconds is racing a wedged thread, and appending through a second
        // handle still puts the text in the same file.
        if (Monitor.TryEnter(_gate, 2000))
        {
            try { _stream.Write(bytes, 0, bytes.Length); _stream.Flush(); return; }
            catch { }
            finally { Monitor.Exit(_gate); }
        }
        try
        {
            using var fallback = new FileStream(_path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
            fallback.Write(bytes, 0, bytes.Length);
        }
        catch { }
    }

    /// <summary>Console.Out and Console.Error, mirrored into the log a line at a time.</summary>
    sealed class Tee : TextWriter
    {
        readonly TextWriter _inner;
        readonly StringBuilder _line = new();

        public Tee(TextWriter inner) => _inner = inner;

        public override Encoding Encoding => _inner.Encoding;

        public override void Write(char value)
        {
            _inner.Write(value);
            lock (_line)
            {
                // Diag.Write, not this class's own Write(string) -- that one forwards
                // back to Write(char), so the line would only ever append to itself.
                if (value == '\n') { Diag.Write(_line.ToString()); _line.Clear(); }
                else if (value != '\r') _line.Append(value);
            }
        }

        public override void Write(string value)
        {
            if (value != null) foreach (var ch in value) Write(ch);
        }

        public override void Flush() => _inner.Flush();
    }

    // ---- symbols ----------------------------------------------------------------

    // The funcmaps are embedded so a stall dump can name what it saw without a folder
    // of loose JSON beside the executable. A funcmaps/ directory next to the exe still
    // wins if one is there, which is handy for trying a regenerated map without a
    // rebuild.
    static void LoadSymbols()
    {
        _symbols = new Dictionary<uint, string>();

        string dir = Path.Combine(AppContext.BaseDirectory, "funcmaps");
        if (Directory.Exists(dir))
        {
            foreach (var path in Directory.GetFiles(dir, "*.json"))
                AddSymbols(Path.GetFileNameWithoutExtension(path), () => File.OpenRead(path));
        }
        else
        {
            var asm = System.Reflection.Assembly.GetExecutingAssembly();
            foreach (var name in asm.GetManifestResourceNames())
            {
                if (!name.StartsWith("funcmaps.", StringComparison.Ordinal)) continue;
                string module = Path.GetFileNameWithoutExtension(name["funcmaps.".Length..]);
                AddSymbols(module, () => asm.GetManifestResourceStream(name));
            }
        }

        Console.WriteLine($"[diag] {_symbols.Count} symbols loaded");
    }

    static void AddSymbols(string module, Func<Stream> open)
    {
        if (module.EndsWith("_sweep") || module is "psyq_main" or "manual" or "forced") return;
        try
        {
            using var stream = open();
            if (stream == null) return;
            using var doc = System.Text.Json.JsonDocument.Parse(stream);
            if (!doc.RootElement.TryGetProperty("functions", out var funcs)) return;
            foreach (var f in funcs.EnumerateArray())
            {
                uint a = Convert.ToUInt32(f.GetProperty("address").GetString(), 16);
                string label = $"{f.GetProperty("name").GetString()}@{module}";
                if (!_symbols.TryGetValue(a, out var prev)) _symbols[a] = label;
                else if (prev != label && !prev.Contains('/')) _symbols[a] = prev + "/" + label;
            }
        }
        catch { }
    }

    public static string Name(uint addr)
        => _symbols != null && _symbols.TryGetValue(addr, out var n) ? n : $"0x{addr:X8}";

    // ---- watchdog ---------------------------------------------------------------

    // A hang does not necessarily freeze the frame counter: the call-ring stall breaker
    // forces a frame every few million calls, so a game wedged in a retry loop still
    // crawls forward at a frame every several seconds. Watch the rate, not just whether
    // it moved at all.
    const double SlowFps = 12.0;

    static void Watch()
    {
        var window = new Queue<(DateTime At, long Frame)>();
        DateTime lastDump = DateTime.MinValue;
        DateTime lastBeat = DateTime.MinValue;
        bool slow = false;

        while (true)
        {
            Thread.Sleep(1000);
            var now = DateTime.UtcNow;
            long f = Interlocked.Read(ref Frame);
            window.Enqueue((now, f));
            while (window.Count > 0 && (now - window.Peek().At).TotalSeconds > _stallSeconds)
                window.Dequeue();
            if (window.Count < 2) continue;

            var oldest = window.Peek();
            double span = (now - oldest.At).TotalSeconds;
            if (span < _stallSeconds - 1.5) continue;
            double fps = (f - oldest.Frame) / Math.Max(span, 0.001);

            if ((now - lastBeat).TotalSeconds >= 15)
            {
                lastBeat = now;
                // Straight to the log, not through Console: this is the line that proves
                // the watchdog is alive when the game thread has stopped being.
                Write($"[diag] frame {f}, {fps:F1} fps, {CallRing.TotalCalls} calls, " +
                      $"{CallRing.StallBreaks} stall breaks");
            }

            if (fps >= SlowFps)
            {
                if (slow) Write($"[diag] recovered at frame {f} ({fps:F1} fps)");
                slow = false;
                continue;
            }

            slow = true;
            if ((now - lastDump).TotalSeconds < 20) continue;
            lastDump = now;

            var sb = new StringBuilder();
            sb.AppendLine("======== STALL ========");
            sb.AppendLine($"frame {f}, {fps:F2} fps over {span:F1}s, " +
                          $"{CallRing.TotalCalls} calls, {CallRing.StallBreaks} stall breaks");
            sb.Append(StateReport());
            sb.Append("=======================");
            Write(sb.ToString());

            if (_exitOnStall)
            {
                Write("[diag] exiting on stall");
                Environment.Exit(2);
            }
        }
    }

    /// <summary>
    /// Last-gasp report for an unhandled exception. The .NET runtime prints those
    /// straight to the native stderr handle, bypassing Console, so without this the
    /// log stops mid-sentence and the crash is invisible in it.
    /// </summary>
    public static void Fatal(Exception ex)
    {
        var sb = new StringBuilder();
        sb.AppendLine("======== CRASH ========");
        sb.AppendLine(ex?.ToString() ?? "(no exception object)");
        sb.Append(StateReport());
        sb.Append("=======================");
        Write(sb.ToString());
        try { Console.Error.WriteLine(ex); } catch { }
    }

    /// <summary>Everything the runtime knows about where the game currently is.</summary>
    public static string StateReport()
    {
        var sb = new StringBuilder();
        try
        {
            var c = Runtime.Cpu;
            if (c != null)
            {
                sb.AppendLine($"ra=0x{c.RA:X8} sp=0x{c.SP:X8} fp=0x{c.FP:X8} gp=0x{c.GP:X8}");
                sb.AppendLine($"v0=0x{c.V0:X8} v1=0x{c.V1:X8} a0=0x{c.A0:X8} a1=0x{c.A1:X8} a2=0x{c.A2:X8} a3=0x{c.A3:X8}");
                sb.AppendLine($"s0=0x{c.S0:X8} s1=0x{c.S1:X8} s2=0x{c.S2:X8} s3=0x{c.S3:X8}");
            }
        }
        catch (Exception e) { sb.AppendLine($"context unavailable: {e.Message}"); }

        try
        {
            sb.AppendLine("overlays: " + string.Join(", ", Dispatcher.ActiveNames));
            var gpu = Runtime.Gpu;
            if (gpu != null)
                sb.AppendLine($"display {gpu.DisplayWidth}x{gpu.DisplayHeight} at ({gpu.DisplayX},{gpu.DisplayY}) " +
                              $"enabled={gpu.DisplayEnabled} 24bpp={gpu.Display24Bit}");
            sb.AppendLine($"cdstream inUse={RecompOne.Runtime.Sdk.LibCdStream.InUse}");
        }
        catch (Exception e) { sb.AppendLine($"state unavailable: {e.Message}"); }

        try
        {
            var tail = CallRing.Tail(4096);
            sb.AppendLine($"call ring, most recent last ({tail.Length} entries):");
            var runs = new List<(uint Addr, int Count)>();
            foreach (var a in tail)
            {
                if (runs.Count > 0 && runs[^1].Addr == a) runs[^1] = (a, runs[^1].Count + 1);
                else runs.Add((a, 1));
            }
            foreach (var (addr, count) in runs.TakeLast(60))
                sb.AppendLine($"   {Name(addr),-44} {(count > 1 ? "x" + count : "")}");

            sb.AppendLine("hottest in window:");
            foreach (var g in tail.GroupBy(a => a).OrderByDescending(g => g.Count()).Take(8))
                sb.AppendLine($"   {Name(g.Key),-44} x{g.Count()}");
        }
        catch (Exception e) { sb.AppendLine($"call ring unavailable: {e.Message}"); }

        return sb.ToString();
    }

    // ---- primitive dump ---------------------------------------------------------

    // XMENMA2_PRIMS=4200,4210 -- log every primitive drawn on those frames. The event
    // fires per primitive, so this is only wired up when asked for.
    static readonly HashSet<long> _primFrames = new();

    static void InstallPrimDump()
    {
        var spec = Environment.GetEnvironmentVariable("XMENMA2_PRIMS");
        if (string.IsNullOrWhiteSpace(spec)) return;
        foreach (var part in spec.Split(','))
            if (long.TryParse(part.Trim(), out var n)) _primFrames.Add(n);
        if (_primFrames.Count == 0) return;

        RecompOne.Runtime.Events.Event.AddListener<RecompOne.Runtime.Events.RenderPrimEvent>(OnPrim);
        Console.WriteLine($"[diag] primitive dump armed for {_primFrames.Count} frame(s)");
    }

    static void OnPrim(RecompOne.Runtime.Events.RenderPrimEvent e)
    {
        if (!_primFrames.Contains(Interlocked.Read(ref Frame))) return;
        var v = new StringBuilder();
        for (int i = 0; i < e.Count; i++) v.Append($"({e.X[i]},{e.Y[i]}) ");
        Write($"[prim] n={e.Count} " +
              $"{(e.Textured ? "T" : "-")}{(e.SemiTransparent ? "S" : "-")}" +
              $"{(e.Gouraud ? "G" : "-")}{(e.Raw ? "R" : "-")} " +
              $"clut={e.Clut:X4} area=[{e.DrawLeft},{e.DrawTop}..{e.DrawRight},{e.DrawBottom}] {v}");
    }
}
