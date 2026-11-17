using System.Text.Json.Nodes;
using Celeste;
using Microsoft.Xna.Framework;
using Monocle;

namespace CelesteAgentBridge;

// A collision world the agent can reason about without screenshots: the solid
// grid merged into rectangles, plus every collidable object and its role.
internal static class CollisionSnapshot {
    const int Tile = 8;

    public static JsonObject Capture(Level level, int maxRects) {
        var bounds = level.Bounds;
        int tx0 = bounds.Left / Tile, tx1 = bounds.Right / Tile;
        int ty0 = bounds.Top / Tile, ty1 = bounds.Bottom / Tile;

        bool complete = true;
        int solidTiles = 0;
        var rects = new JsonArray();
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
                    } catch {
                        complete = false;
                    }
                }
                if (solid) {
                    solidTiles++;
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
            // Runs that did not continue into this row are finished.
            var stale = new List<(int, int)>();
            foreach (var (key, rect) in open)
                if (rect.Bottom < ty * Tile + Tile) stale.Add(key);
            foreach (var key in stale) Flush(key);
        }
        foreach (var key in open.Keys.ToList()) Flush(key);

        foreach (var rect in closed) {
            if (rects.Count >= maxRects) { complete = false; break; }
            rects.Add(new JsonObject {
                ["x"] = rect.X, ["y"] = rect.Y,
                ["width"] = rect.Width, ["height"] = rect.Height,
                ["kind"] = "solid"
            });
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
                ["solid_tiles"] = solidTiles,
                ["solid_ratio"] = J.Num((float)solidTiles * Tile * Tile / roomArea),
                ["terrain_rects"] = rects.Count,
                ["objects"] = entityCount,
                ["terrain_complete"] = complete,
                ["objects_truncated"] = truncated
            },
            ["complete"] = complete && !truncated
        };
    }
}
