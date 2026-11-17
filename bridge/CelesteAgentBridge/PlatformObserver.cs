using Celeste;
using System.Text.Json.Nodes;

namespace CelesteAgentBridge;

internal static class PlatformObserver {
    public const int Limit = 16;

    public static JsonObject Capture(Level level) {
        var platforms = new JsonArray();
        var ordinals = new Dictionary<string, int>();
        int total = 0;
        foreach (var entity in level.Entities) {
            if (entity is not Platform platform || entity is SolidTiles) continue;
            total++;
            if (platforms.Count == Limit) continue;
            string type = platform.GetType().FullName ?? platform.GetType().Name;
            int ordinal = ordinals.GetValueOrDefault(type);
            ordinals[type] = ordinal + 1;
            platforms.Add(new JsonObject {
                ["type"] = type, ["ordinal"] = ordinal,
                ["x"] = platform.X, ["y"] = platform.Y,
                ["collidable"] = platform.Collidable
            });
        }
        return new JsonObject { ["platforms"] = platforms, ["total"] = total };
    }
}
