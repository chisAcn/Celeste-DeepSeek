using System.Text;
using System.Text.Json.Nodes;
using Celeste;
using Microsoft.Xna.Framework;
using Monocle;

namespace CelesteAgentBridge;

// Cheap spatial overview: one character per 8x8 tile so a model can "see" the
// room layout in a few hundred tokens instead of parsing rectangles.
internal static class TileAtlas {
    const int Tile = 8;

    public static JsonObject Capture(Level level, bool wholeRoom) {
        Rectangle area = wholeRoom ? level.Bounds : CameraRect(level);
        int cols = Math.Clamp(area.Width / Tile, 1, 200);
        int rows = Math.Clamp(area.Height / Tile, 1, 100);
        var grid = new char[rows, cols];
        for (int y = 0; y < rows; y++)
            for (int x = 0; x < cols; x++)
                grid[y, x] = ' ';

        var legend = new JsonObject {
            ["#"] = "solid terrain", ["^"] = "spikes", ["*"] = "strawberry",
            ["H"] = "heart gem", ["C"] = "cassette", ["S"] = "spring",
            ["R"] = "refill", ["B"] = "booster", ["T"] = "trigger",
            ["Z"] = "moving block", ["-"] = "jump-through platform",
            ["="] = "solid entity", ["o"] = "other entity",
            ["M"] = "Madeline"
        };

        int solidTiles = 0;
        string? tileError = null;
        for (int y = 0; y < rows; y++) {
            for (int x = 0; x < cols; x++) {
                int tx = (area.Left + x * Tile) / Tile;
                int ty = (area.Top + y * Tile) / Tile;
                try {
                    if (level.SolidsData[tx, ty] != '0') solidTiles++;
                } catch (Exception e) {
                    tileError ??= e.GetType().Name + ": " + e.Message;
                }
            }
        }

        // Tile char arrays are indexed in a per-level space we cannot trust, so
        // the map is painted from the collider rectangles the engine actually
        // collides against.
        var solidRects = SolidProbe.Rectangles(level);
        int painted = SolidProbe.Paint(
            solidRects, area, grid, cols, rows, area.Left, area.Top, '#');

        // Priority keeps a background decal from erasing terrain or a spike.
        var rank = new byte[rows, cols];
        for (int y = 0; y < rows; y++)
            for (int x = 0; x < cols; x++)
                rank[y, x] = grid[y, x] == ' ' ? (byte)0 : (byte)1;

        foreach (var entity in level.Entities) {
            if (entity is SolidTiles) continue;
            char symbol = Symbol(entity);
            if (symbol == ' ') continue;
            byte p = Priority(symbol);
            var bounds = entity.Collider?.Bounds
                ?? new Rectangle((int)entity.X, (int)entity.Y, Tile, Tile);
            // Blocky things are painted at their real extent; point-like props
            // stay on a single cell so the map does not fill with noise.
            bool wide = p >= 3;
            int cx0 = wide ? (bounds.Left - area.Left) / Tile : (int)(bounds.Center.X - area.Left) / Tile;
            int cx1 = wide ? (bounds.Right - 1 - area.Left) / Tile : cx0;
            int cy0 = wide ? (bounds.Top - area.Top) / Tile : (int)(bounds.Center.Y - area.Top) / Tile;
            int cy1 = wide ? (bounds.Bottom - 1 - area.Top) / Tile : cy0;
            for (int cy = Math.Max(0, cy0); cy <= Math.Min(rows - 1, cy1); cy++)
                for (int cx = Math.Max(0, cx0); cx <= Math.Min(cols - 1, cx1); cx++)
                    if (p > rank[cy, cx]) { grid[cy, cx] = symbol; rank[cy, cx] = p; }
        }

        var player = level.Tracker.GetEntity<Player>();
        if (player != null) {
            int px = (int)(player.X - area.Left) / Tile;
            int py = (int)(player.Y - area.Top) / Tile;
            if (px >= 0 && px < cols && py >= 0 && py < rows) grid[py, px] = 'M';
        }

        var lines = new JsonArray();
        for (int y = 0; y < rows; y++) {
            var sb = new StringBuilder(cols);
            for (int x = 0; x < cols; x++) sb.Append(grid[y, x]);
            lines.Add(sb.ToString());
        }
        return new JsonObject {
            ["room"] = level.Session.Level,
            ["region"] = J.Rect(area),
            ["tile_size"] = Tile,
            ["width"] = cols, ["height"] = rows,
            ["solid_tiles"] = solidTiles,
            ["solid_cells"] = painted,
            ["solids"] = SolidProbe.Diagnose(level),
            ["tile_error"] = tileError,
            ["legend"] = legend,
            ["rows"] = lines
        };
    }

    static Rectangle CameraRect(Level level) {
        Vector2 position = J.Get(level.Camera, "Position") is Vector2 vec ? vec : Vector2.Zero;
        return new Rectangle((int)position.X, (int)position.Y, 320, 180);
    }

    static byte Priority(char symbol) => symbol switch {
        '^' => 5, 'Z' => 4, '-' => 3, '=' => 3,
        '*' or 'H' or 'C' or 'S' or 'R' or 'B' or 'T' => 2,
        _ => 1
    };

    static char Symbol(Entity entity) {
        string type = entity.GetType().Name;
        string kind = EntityScan.Kind(entity);
        return kind switch {
            "hazard" => '^',
            "collectible" => type.Contains("Heart") ? 'H' : type.Contains("Cassette") ? 'C' : '*',
            "spring" => 'S',
            "refill" => 'R',
            "booster" => 'B',
            "trigger" => 'T',
            "mover" => 'Z',
            "one_way" => '-',
            "solid" => '=',
            "platform" => '=',
            _ => 'o'
        };
    }
}
