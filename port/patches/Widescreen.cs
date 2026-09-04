using System;
using ImGuiNET;
using RecompOne.Runtime;
using RecompOne.Runtime.Config;
using RecompOne.Runtime.Events;

using RecompOne.Runtime.Hle;
using RecompOne.Runtime.Host;
using RecompOne.Runtime.Host.Window;

namespace Recompiled;

/// <summary>
/// Widescreen output: 4:3 or 16:9, nothing in between.
///
/// The runtime can rasterise into a target wider than the console's framebuffer and
/// present it at a wider aspect. <see cref="Display.WideAspect"/> asks for a margin of
/// extra pixels on each side -- 86 either side of the game's 512 at 16:9 -- the draw
/// clip is opened to cover them whenever the game clips to the whole screen, and the
/// frame is presented at 16:9 instead of 4:3.
///
/// Nothing is stretched. The console's own 512 pixels keep exactly the shape they had,
/// and the margins are filled by arena geometry the hardware would have clipped at the
/// screen edge, so a fight really does show more of the stage.
///
/// Only the 3D can fill that. The logos, the FMVs, the front end and the VS card are
/// full-screen 2D pictures with nothing more to give, so they stay 4:3 -- letterboxed
/// in the middle of the 16:9 frame, never stretched and never cropped. The frame itself
/// stays 16:9 throughout, so the window keeps one shape from boot to credits; see the
/// pillar handling in GlCore.PresentDisplay, which pads those out rather than letting
/// each screen report its own aspect.
///
/// Off unless asked for, by either route:
///
///   interface.ini   Widescreen=16:9   -- written by Settings > Display
///   XMENMA2_WIDE    on | 16:9 | off | 4:3, and overrides the setting
/// </summary>
public static class Widescreen
{
    const string Key = "Widescreen";
    const string On = "16:9";
    const string Off = "off";

    // The game's 2D overlay list, as a RAM offset. From func_80073630, which asserts the
    // sprite index is below SpriteCount and indexes SpriteTable by SpriteStride.
    const uint SpriteTable = 0x000E30D8;
    const uint SpriteCount = 225;
    const uint SpriteStride = 0x58;

    static string _forced;      // XMENMA2_WIDE, if it was set
    static string _applied;     // what Display.WideAspect currently reflects

    public static void Install()
    {
        var env = Environment.GetEnvironmentVariable("XMENMA2_WIDE");
        if (!string.IsNullOrWhiteSpace(env)) _forced = Enabled(env) ? On : Off;

        // The settings popup only draws once the host window is up, and the registry is
        // a plain static list, so registering this early is safe.
        SettingsRegistry.Extend("display", Draw);

        // interface.ini is not read until the window opens, which is after Main has run
        // its installers -- so pick the stored value up on the first frame instead, and
        // keep watching it so the setting applies the moment it is changed.
        Event.AddListener<VSyncEvent>(_ => Sync());
    }

    static void Sync()
    {
        string want = _forced ?? (Enabled(ConfigManager.View.GetString(Key, Off)) ? On : Off);
        if (want == _applied) return;

        Apply(want);
        ShapeWindow(want == On);
    }

    static bool _shaped;

    static void Apply(string spec)
    {
        bool first = _applied == null;
        _applied = spec;

        bool on = spec == On;

        // Widescreen by squeezing the game's own projection, not by widening the draw
        // area. The game culls geometry that projects outside its screen, so a wider
        // draw area is handed nothing to put in it and the sides of a stage stay empty
        // however far out the renderer is willing to go. Squeezing the projection by
        // 3/4 puts a 16:9 field of view inside the 4:3 screen the game believes in, so
        // its own culling keeps all of it, and the frame is stretched back out at
        // presentation. See Gte.SqueezeX.
        Display.WideAspect = on ? 16f / 9f : 0f;
        Display.Squeezing = on;
        Gte.SqueezeX = on ? (3 * 65536) / 4 : 65536;

        // The HUD is drawn flat at fixed screen positions, so it never goes through that
        // squeeze but does get the stretch, and would come out a third wide. It has to be
        // squeezed to match, which means telling it apart from the stage -- and nothing in
        // the GPU stream does: both are gouraud textured triangles, in one ordering table,
        // sharing palettes.
        //
        // The game's own code does. func_80073630 bounds-checks a sprite index against
        // 225 and indexes a table at 0x800E30D8 with a stride of 0x58, each record holding
        // two POLY_FT4 packets -- one per framebuffer -- and their two tag words. That
        // table is the game's entire 2D overlay list. Checked against a fight: every one of
        // the HUD's primitives is assembled inside it, all 1,371 of the frame's others are
        // outside it, and no packet below the table's neighbourhood belongs to anything
        // else.
        Display.SetOverlay(on ? SpriteTable : 0, on ? SpriteTable + SpriteCount * SpriteStride : 0,
                           on ? 0.75f : 0f);

        // 4:3 on the first frame is the default; only say something once it matters.
        if (first && !on) return;

        Console.WriteLine(on
            ? $"[wide] 16:9, {Display.WideMargin(512)} extra pixels each side of a 512-wide frame"
            : "[wide] off, 4:3");
    }

    static void Draw()
    {
        ImGui.Separator();

        bool on = (_forced ?? ConfigManager.View.GetString(Key, Off)) == On;

        if (_forced != null) ImGui.BeginDisabled();
        if (ImGui.Checkbox("Widescreen (16:9)", ref on))
        {
            ConfigManager.View.SetString(Key, on ? On : Off);
            ShapeWindow(on);
            ConfigManager.SaveView(PanelManager.Panels);
            Sync();
        }
        if (_forced != null) ImGui.EndDisabled();

        if (ImGui.IsItemHovered())
            ImGui.SetTooltip("Widens the view rather than stretching it: the fights show more\n" +
                             "of the arena. The movies, the front end and the VS card have no\n" +
                             "more picture to show and stay 4:3 in the middle of the frame.");

        if (_forced != null)
            ImGui.TextDisabled($"forced {(_forced == On ? "on" : "off")} by XMENMA2_WIDE");

    }

    /// <summary>
    /// Take the window with it.
    ///
    /// The output is one shape or the other -- 4:3 or 16:9 -- and whichever it is, the
    /// window should be that shape too. Leave a 4:3 window around a 16:9 frame and the
    /// frame is letterboxed into it, and then a 4:3 menu is pillarboxed inside that:
    /// black on all four sides and the picture smaller than it was before widescreen
    /// was turned on, which is the opposite of what the setting promises. So the
    /// checkbox reshapes the window rather than explaining why it looks wrong.
    ///
    /// Width is left alone; only the height moves, so the window keeps the size the
    /// player chose in the dimension they are most likely to have chosen deliberately.
    /// </summary>
    static void ShapeWindow(bool wide)
    {
        if (ConfigManager.View.Fullscreen) return;

        int w = ConfigManager.View.WindowWidth;
        int h = (int)MathF.Round(w * (wide ? 9f / 16f : 3f / 4f));

        // Unconditional. Comparing against the stored height and skipping when it looks
        // right is how a 4:3 window ended up around a 16:9 frame: the setting had been
        // saved but never applied to the window, so the two disagreed and the guard
        // believed the wrong one. Setting it every time costs nothing.
        bool changed = !_shaped || h != ConfigManager.View.WindowHeight;
        _shaped = true;
        ConfigManager.View.WindowHeight = h;
        try { HostWindow.SetSize(w, h); } catch { }
        if (changed) Console.WriteLine($"[wide] window {w}x{h}, matching the {(wide ? "16:9" : "4:3")} output");
    }

    // "16:9" and "on" mean on; anything else, including "off" and "4:3", means off.
    static bool Enabled(string spec)
    {
        spec = spec?.Trim();
        return spec != null
            && (spec.Equals(On, StringComparison.OrdinalIgnoreCase)
                || spec.Equals("on", StringComparison.OrdinalIgnoreCase)
                || spec.Equals("true", StringComparison.OrdinalIgnoreCase)
                || spec == "1");
    }
}
