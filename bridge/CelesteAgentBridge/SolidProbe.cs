using Celeste;
using Microsoft.Xna.Framework;
using Monocle;

namespace CelesteAgentBridge;

// The authoritative solid geometry. Tile char arrays are indexed in an
// undocumented space (absolute map tiles scaled per level), so the ASCII map
// and the collision snapshot both read the SolidTiles collider instead: those
// rectangles are exactly what the physics engine collides against.
internal static class SolidProbe {
    public const int Tile = 8;

    public static SolidTiles? Entity(Level level) {
        try { return level.Tracker.GetEntity<SolidTiles>(); } catch { return null; }
    }

    // World-space rectangles, already merged into large blocks by the game.
    public static List<Rectangle> Rectangles(Level level) {
        var result = new List<Rectangle>();
        var solids = Entity(level);
        if (solids?.Collider == null) return result;
        CollectRects(solids.Collider, result);
        return result;
    }

    static void CollectRects(Collider collider, List<Rectangle> into) {
        switch (collider) {
            case ColliderList list:
                foreach (var child in list.colliders) CollectRects(child, into);
                break;
            case Grid grid:
                for (int y = 0; y < grid.CellsY; y++)
                    for (int x = 0; x < grid.CellsX; x++)
                        if (grid[x, y]) {
                            var cell = new Rectangle(
                                (int)(grid.AbsoluteLeft + x * grid.CellWidth),
                                (int)(grid.AbsoluteTop + y * grid.CellHeight),
                                (int)grid.CellWidth, (int)grid.CellHeight);
                            into.Add(cell);
                        }
                break;
            case Circle circle:
                var b = circle.Bounds;
                into.Add(b);
                break;
            default:
                var bounds = collider.Bounds;
                if (bounds.Width > 0 && bounds.Height > 0) into.Add(bounds);
                break;
        }
    }

    // Paint every world rectangle onto a tile grid anchored at `area`.
    public static int Paint(List<Rectangle> rects, Rectangle area, char[,] grid,
                            int cols, int rows, int originX, int originY, char symbol) {
        int painted = 0;
        foreach (var rect in rects) {
            int x0 = Math.Max(0, (rect.Left - originX) / Tile);
            int x1 = Math.Min(cols - 1, (rect.Right - 1 - originX) / Tile);
            int y0 = Math.Max(0, (rect.Top - originY) / Tile);
            int y1 = Math.Min(rows - 1, (rect.Bottom - 1 - originY) / Tile);
            for (int y = y0; y <= y1; y++)
                for (int x = x0; x <= x1; x++)
                    if (grid[y, x] == ' ') { grid[y, x] = symbol; painted++; }
        }
        return painted;
    }

    // Human readable diagnostic so a mismatch is obvious instead of silent.
    public static System.Text.Json.Nodes.JsonObject Diagnose(Level level) {
        var solids = Entity(level);
        var report = new System.Text.Json.Nodes.JsonObject {
            ["entity"] = solids != null,
            ["rects"] = 0,
            ["collider"] = solids == null ? "none" : solids.Collider?.GetType().Name
        };
        if (solids == null) return report;
        var rects = Rectangles(level);
        report["rects"] = rects.Count;
        if (solids.Collider != null) report["bounds"] = J.Rect(solids.Collider.Bounds);
        try { report["solids_data"] = level.SolidsData?.GetType().Name; }
        catch (Exception e) { report["solids_data"] = e.GetType().Name; }
        return report;
    }
}
