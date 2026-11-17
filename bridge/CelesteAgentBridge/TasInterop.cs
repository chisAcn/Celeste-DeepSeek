using MonoMod.ModInterop;

namespace CelesteAgentBridge;

#pragma warning disable CS0649 // Populated by MonoMod.
[ModImportName("CelesteTAS")]
internal static class TasInterop {
    public static Func<bool>? IsTasActive;
    public static Func<bool>? IsTasRunning;
    public static Func<int, object?>? GetLatestSavestateForFrame;
    public static Func<object, int>? GetSavestateFrame;
    public static Func<object, bool>? LoadSavestate;
}

[ModImportName("SpeedrunTool.TasAction")]
internal static class SpeedrunInterop {
    public static Func<string, bool>? SaveState;
    public static Func<string, bool>? LoadState;
    public static Action<string>? ClearState;
    public static Func<string, bool>? TasIsSaved;

    public static bool Available => SaveState != null && LoadState != null
        && ClearState != null && TasIsSaved != null;
}
#pragma warning restore CS0649
