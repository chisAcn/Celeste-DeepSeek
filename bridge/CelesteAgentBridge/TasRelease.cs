using System.Reflection;

namespace CelesteAgentBridge;

// CelesteTAS keeps the level frozen while a run is loaded, even after the .tas
// file ends, so a game launched with --tas cannot be driven by the bridge until
// the run is stopped. The mod exports `IsTasActive`, which is just
// `TAS.Manager.Running` (verified in IL), and `Manager` has the static
// `EnableRun` / `DisableRun` pair the Start/Stop hotkey uses. Both are called
// through reflection so a missing member degrades to a report, not a crash.
internal static class TasRelease {
    const BindingFlags All = BindingFlags.Public | BindingFlags.NonPublic;
    const BindingFlags Static = All | BindingFlags.Static;

    public static (bool applied, string detail) SetRunning(bool running) {
        var seen = new List<string>();
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies()) {
            var name = assembly.GetName().Name ?? "";
            if (!name.Contains("TAS", StringComparison.OrdinalIgnoreCase)) continue;
            seen.Add(name);
            Type[] types;
            try { types = assembly.GetTypes(); }
            catch (ReflectionTypeLoadException) { continue; }
            foreach (var type in types) {
                if (type.Name != "Manager" || type.Namespace?.StartsWith("TAS") != true) continue;
                var method = type.GetMethod(running ? "EnableRun" : "DisableRun", Static);
                if (method == null) { seen.Add($"{type.FullName}: no {(running ? "EnableRun" : "DisableRun")}"); continue; }
                try {
                    method.Invoke(null, null);
                    return (true, $"{type.FullName}.{method.Name}");
                } catch (Exception exception) {
                    seen.Add($"{type.FullName}: {exception.GetType().Name} {exception.Message}");
                }
            }
        }
        return (false, seen.Count == 0 ? "no TAS assembly" : string.Join(", ", seen));
    }
}
