using System;
using System.IO;
using System.Linq;
using RecompOne.Runtime.Memory;
using Recompiled;
using Capture = Recompiled.Capture;

namespace XMenMA2;

public static class Program
{
    const string Title = "X-Men: Mutant Academy 2";
    const string DiscVolumeId = "SLUS_01382";

    public static int Main(string[] args)
    {
        // Everything the game writes -- packs, logs, saves, dumps -- is resolved against
        // the working directory, so anchor that to the executable. Otherwise a shortcut
        // or a launch from elsewhere scatters those wherever the shell happened to be.
        try
        {
            string home = ExeDirectory();
            if (home != null) Directory.SetCurrentDirectory(home);
        }
        catch { }

        string cue = ResolveCue(args);
        if (cue != null) SeedSettings(cue);

        Diag.Install();
        RecompOne.Runtime.Runtime.DiscValidator = ValidateDisc;
        EnableLogs(Environment.GetEnvironmentVariable("XMENMA2_LOG"));
        Capture.Install();
        TextureDump.Install();
        TextureDump.InstallStats();
        Harness.Install();
        Widescreen.Install();

        AppDomain.CurrentDomain.UnhandledException += (_, e) => Diag.Fatal(e.ExceptionObject as Exception);

        try
        {
            RecompOne.Runtime.Runtime.Run(() =>
            {
                var mem = new PSMemory();
                Entry.Run(mem, cue, Title);
            });
        }
        catch (Exception ex)
        {
            Diag.Fatal(ex);
            RecompOne.Runtime.Runtime.Shutdown();
            return 3;
        }

        RecompOne.Runtime.Runtime.Shutdown();
        return 0;
    }

    // XMENMA2_LOG=bios,sdk,cd,gpu,dma,spu,mdec
    static void EnableLogs(string spec)
    {
        if (string.IsNullOrWhiteSpace(spec)) return;
        foreach (var raw in spec.Split(','))
        {
            switch (raw.Trim().ToLowerInvariant())
            {
                case "bios": RecompOne.Runtime.Log.BiosOn = true; break;
                case "sdk": RecompOne.Runtime.Log.SdkOn = true; break;
                case "cd": RecompOne.Runtime.Log.CdOn = true; break;
                case "gpu": RecompOne.Runtime.Log.GpuOn = true; break;
                case "dma": RecompOne.Runtime.Log.DmaOn = true; break;
                case "spu": RecompOne.Runtime.Log.SpuOn = true; break;
                case "mdec": RecompOne.Runtime.Log.MdecOn = true; break;
                case "all":
                    RecompOne.Runtime.Log.BiosOn = RecompOne.Runtime.Log.SdkOn =
                    RecompOne.Runtime.Log.CdOn = RecompOne.Runtime.Log.GpuOn =
                    RecompOne.Runtime.Log.DmaOn = RecompOne.Runtime.Log.SpuOn =
                    RecompOne.Runtime.Log.MdecOn = true;
                    break;
            }
        }
        Console.WriteLine($"[XMenMA2] logging: {spec}");
    }

    /// <summary>
    /// Where the executable itself lives. AppContext.BaseDirectory is not it for a
    /// single-file build that extracts to disk -- that points at the extraction folder.
    /// </summary>
    static string ExeDirectory()
    {
        string exe = Environment.ProcessPath;
        return string.IsNullOrEmpty(exe) ? AppContext.BaseDirectory : Path.GetDirectoryName(exe);
    }

    // The disc lives in the repository root; the build output sits a few levels below it.
    static string ResolveCue(string[] args)
    {
        if (args.Length > 0 && File.Exists(args[0])) return Path.GetFullPath(args[0]);

        foreach (var dir in CandidateDirs())
        {
            if (!Directory.Exists(dir)) continue;
            var hit = Directory.GetFiles(dir, "*.cue").FirstOrDefault();
            if (hit != null) return Path.GetFullPath(hit);
        }
        return null;
    }

    static System.Collections.Generic.IEnumerable<string> CandidateDirs()
    {
        var here = ExeDirectory() ?? AppContext.BaseDirectory;
        yield return here;
        var d = new DirectoryInfo(here);
        for (int i = 0; i < 6 && d != null; i++)
        {
            yield return d.FullName;
            d = d.Parent;
        }
        yield return Directory.GetCurrentDirectory();
    }

    // Written once so the runtime's "pick a disc" gate passes without user interaction.
    static void SeedSettings(string cue)
    {
        try
        {
            const string path = "settings.json";
            if (File.Exists(path))
            {
                var text = File.ReadAllText(path);
                if (text.Contains("\"CdPath\"") && !text.Contains("\"CdPath\": \"\"")) return;
            }
            var json = System.Text.Json.JsonSerializer.Serialize(
                new RecompOne.Runtime.Config.GameConfig { CdPath = cue },
                new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(path, json);
        }
        catch (Exception e)
        {
            Console.Error.WriteLine($"[XMenMA2] could not seed settings.json: {e.Message}");
        }
    }

    static string ValidateDisc(string path)
    {
        try
        {
            using var fs = RecompOne.Runtime.Cdrom.DiscFs.Open(path);
            var pvd = fs.ReadSector(16);
            var volume = System.Text.Encoding.ASCII.GetString(pvd, 40, 32).Trim();
            if (!volume.StartsWith(DiscVolumeId, StringComparison.OrdinalIgnoreCase))
                return $"expected {DiscVolumeId} (X-Men: Mutant Academy 2, USA), found '{volume}'";
            return null;
        }
        catch (Exception e)
        {
            return e.Message;
        }
    }
}
