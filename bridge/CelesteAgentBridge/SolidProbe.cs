using Celeste;
using Microsoft.Xna.Framework;
using Monocle;

namespace CelesteAgentBridge;

// The authoritative solid geometry. Tile char arrays are a VirtualMap indexed in
// a per-level space that reads empty without raising, so both the ASCII map and
// the collision snapshot read the SolidTiles collider instead: those rectangles
// are exactly what the physics engine collides against.
internal static class SolidProbe {
    public const int Tile = 8;

    public static SolidTiles? Entity(Level level) {
        try { return level.Tracker.GetEntity<SolidTiles>(); } catch { return null; }
    }

    // Solid rectangles intersecting `area`, merged and clipped to it. Room
    // scoped so a whole-map grid (tens of thousands of cells) stays small.
    public static List<Rectangle> Rectangles(Level level, Rectangle area) {
        var result = new List<Rectangle>();
        var solids = Entity(level);
        if (solids?.Collider == null) return result;
        if (solids.Collider is Grid grid) {
            MergeGrid(grid, area, result);
        } else {
            var raw = new List<Rectangle>();
            CollectRects(solids.Collider, raw);
            foreach (var rect in raw) Clip(rect, area, result);
        }
        return result;
    }

    static void Clip(Rectangle rect, Rectangle area, List<Rectangle> into) {
        var hit = Rectangle.Intersect(rect, area);
        if (hit.Width > 0 && hit.Height > 0) into.Add(hit);
    }

    // Greedy merge: rows into horizontal runs, then identical runs stacked
    // vertically. A 40x36 room collapses from ~1400 cells to a few dozen rects.
    static void MergeGrid(Grid grid, Rectangle area, List<Rectangle> into) {
        int cw = (int)grid.CellWidth, ch = (int)grid.CellHeight;
        if (cw <= 0 || ch <= 0) return;
        int left = (int)grid.AbsoluteLeft, top = (int)grid.AbsoluteTop;

        int x0 = Math.Max(0, (int)Math.Floor((area.Left - left) / (double)cw));
        int x1 = Math.Min(grid.CellsX - 1, (int)Math.Ceiling((area.Right - left) / (double)cw));
        int y0 = Math.Max(0, (int)Math.Floor((area.Top - top) / (double)ch));
        int y1 = Math.Min(grid.CellsY - 1, (int)Math.Ceiling((area.Bottom - top) / (double)ch));

        var open = new Dictionary<(int x, int w), Rectangle>();
        var closed = new List<Rectangle>();

        void Flush((int x, int w) key) {
            if (open.Remove(key, out var r)) closed.Add(r);
        }

        for (int y = y0; y <= y1; y++) {
            var runs = new List<(int x, int w)>();
            int start = -1;
            for (int x = x0; x <= x1 + 1; x++) {
                bool solid = x <= x1 && grid[x, y];
                if (solid && start < 0) start = x;
                else if (!solid && start >= 0) { runs.Add((start, x - start)); start = -1; }
            }
            int rowTop = top + y * ch;
            var alive = new HashSet<(int x, int w)>();
            foreach (var key in runs) {
                alive.Add(key);
                if (open.TryGetValue(key, out var existing) && existing.Bottom == rowTop) {
                    existing.Height += ch;
                    open[key] = existing;
                } else {
                    Flush(key);
                    open[key] = new Rectangle(left + key.x * cw, rowTop, key.w * cw, ch);
                }
            }
            foreach (var key in open.Keys.ToList())
                if (!alive.Contains(key)) Flush(key);
        }
        foreach (var key in open.Keys.ToList()) Flush(key);

        foreach (var rect in closed) Clip(rect, area, into);
    }

    static void CollectRects(Collider collider, List<Rectangle> into) {
        switch (collider) {
            case ColliderList list:
                foreach (var child in list.colliders) CollectRects(child, into);
                break;
            case Grid grid:
                for (int y = 0; y < grid.CellsY; y++)
                    for (int x = 0; x < grid.CellsX; x++)
                        if (grid[x, y])
                            into.Add(new Rectangle(
                                (int)(grid.AbsoluteLeft + x * grid.CellWidth),
                                (int)(grid.AbsoluteTop + y * grid.CellHeight),
                                (int)grid.CellWidth, (int)grid.CellHeight));
                break;
            case Circle circle:
                into.Add(circle.Bounds);
                break;
            default:
                var bounds = collider.Bounds;
                if (bounds.Width > 0 && bounds.Height > 0) into.Add(bounds);
                break;
        }
    }

    // Paint every world rectangle onto a tile grid anchored at the area origin.
    public static int Paint(List<Rectangle> rects, int originX, int originY,
                            char[,] grid, int cols, int rows, char symbol) {
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
            ["collider"] = solids?.Collider?.GetType().Name
        };
        if (solids == null) return report;
        if (solids.Collider is Grid grid) {
            report["grid_cells"] = $"{grid.CellsX}x{grid.CellsY}";
            report["cell"] = $"{grid.CellWidth}x{grid.CellHeight}";
        }
        if (solids.Collider != null) report["bounds"] = J.Rect(solids.Collider.Bounds);
        try { report["solids_data"] = level.SolidsData?.GetType().Name; }
        catch (Exception e) { report["solids_data"] = e.GetType().Name; }
        return report;
    }
}
