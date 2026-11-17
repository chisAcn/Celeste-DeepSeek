using System.Text.Json.Nodes;
using Celeste;
using Microsoft.Xna.Framework;
using Monocle;

namespace CelesteAgentBridge;

// A collision world the agent can reason about without screenshots: the solid
// grid as rectangles, plus every collidable object and its role.
internal static class CollisionSnapshot {
    const int Tile = 8;

    public static JsonObject Capture(Level level, int maxRects) {
        var bounds = level.Bounds;
        var rects = new JsonArray();
        bool complete = true;
        long solidArea = 0;
        string source = "collider";

        // Preferred source: the engine's own collider rectangles. Tile char
        // arrays are indexed in a per-level space that silently reads empty.
        var engineRects = SolidProbe.Rectangles(level);
        if (engineRects.Count > 0) {
            foreach (var rect in engineRects) {
                if (rects.Count >= maxRects) { complete = false; break; }
                solidArea += (long)rect.Width * rect.Height;
                rects.Add(Rect(rect));
            }
        } else {
            source = "solids_data";
            solidArea = ScanTiles(level, bounds, rects, maxRects,
                ref complete, out string? error);
            if (error != null) complete = false;
        }

        var objects = new JsonArray();
        int entityCount = 0;
        bool truncated = false;
        foreach (var entity in level.Entities) {
            if (entity is SolidTiles) continue;
            string kind = EntityScan.Kind(entity);
            if (kind == "entity" && entity.Collider == null) continue;
            entityCount++;
            if (objects.Count >= maxRects) { truncated = true; continue; }
            objects.Add(new JsonObject {
                ["id"] = J.EntityKey(entity),
                ["type"] = entity.GetType().Name,
                ["kind"] = kind,
                ["collidable"] = entity.Collidable,
                ["mutable"] = entity is Platform || entity.GetType().Name.Contains("Mover"),
                ["collider"] = ColliderProbe.Describe(entity.Collider)
            });
        }

        int roomArea = Math.Max(1, bounds.Width * bounds.Height);
        return new JsonObject {
            ["room"] = level.Session.Level,
            ["bounds"] = J.Rect(bounds),
            ["terrain"] = rects,
            ["objects"] = objects,
            ["coverage"] = new JsonObject {
                ["source"] = source,
                ["solid_tiles"] = (int)Math.Min(int.MaxValue, solidArea / (Tile * Tile)),
                ["solid_ratio"] = J.Num((float)solidArea / roomArea),
                ["terrain_rects"] = rects.Count,
                ["objects"] = entityCount,
                ["terrain_complete"] = complete,
                ["objects_truncated"] = truncated,
                ["solids"] = SolidProbe.Diagnose(level)
            },
            ["complete"] = complete && !truncated
        };
    }

    static JsonObject Rect(Rectangle rect) => new() {
        ["x"] = rect.X, ["y"] = rect.Y,
        ["width"] = rect.Width, ["height"] = rect.Height,
        ["kind"] = "solid"
    };

    // Fallback when the level exposes no SolidTiles: merge tile runs vertically.
    static long ScanTiles(Level level, Rectangle bounds, JsonArray rects,
                          int maxRects, ref bool complete, out string? error) {
        int tx0 = bounds.Left / Tile, tx1 = bounds.Right / Tile;
        int ty0 = bounds.Top / Tile, ty1 = bounds.Bottom / Tile;
        error = null;
        long area = 0;
        var open = new Dictionary<(int x, int w), Rectangle>();
        var closed = new List<Rectangle>();

        void Flush((int x, int w) key) {
            if (!open.TryGetValue(key, out var r)) return;
            open.Remove(key);
            closed.Add(r);
        }

        for (int ty = ty0; ty < ty1; ty++) {
            int runStart = -1;
            for (int tx = tx0; tx <= tx1; tx++) {
                bool solid = false;
                if (tx < tx1) {
                    try {
                        solid = level.SolidsData[tx, ty] != '0';
                    } catch (Exception e) {
                        error ??= e.GetType().Name + ": " + e.Message;
                    }
                }
                if (solid) {
                    area += Tile * Tile;
                    if (runStart < 0) runStart = tx;
                } else if (runStart >= 0) {
                    int width = tx - runStart;
                    var key = (runStart, width);
                    if (open.TryGetValue(key, out var existing) && existing.Bottom == ty * Tile) {
                        existing.Height += Tile;
                        open[key] = existing;
                    } else {
                        Flush(key);
                        open[key] = new Rectangle(runStart * Tile, ty * Tile, width * Tile, Tile);
                    }
                    runStart = -1;
                }
            }
            var stale = new List<(int, int)>();
            foreach (var (key, rect) in open)
                if (rect.Bottom < ty * Tile + Tile) stale.Add(key);
            foreach (var key in stale) Flush(key);
        }
        foreach (var key in open.Keys.ToList()) Flush(key);

        foreach (var rect in closed) {
            if (rects.Count >= maxRects) { complete = false; break; }
            rects.Add(Rect(rect));
        }
        return area;
    }
}
