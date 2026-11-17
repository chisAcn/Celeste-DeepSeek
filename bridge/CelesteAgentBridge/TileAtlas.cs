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
            ["Z"] = "moving block", ["="] = "solid entity", ["o"] = "other entity",
            ["M"] = "Madeline"
        };

        for (int y = 0; y < rows; y++) {
            for (int x = 0; x < cols; x++) {
                int tx = (area.Left + x * Tile) / Tile;
                int ty = (area.Top + y * Tile) / Tile;
                try {
                    if (level.SolidsData[tx, ty] != '0') grid[y, x] = '#';
                } catch { }
            }
        }

        foreach (var entity in level.Entities) {
            if (entity is SolidTiles) continue;
            char symbol = Symbol(entity);
            if (symbol == ' ') continue;
            var bounds = entity.Collider?.Bounds ?? new Rectangle((int)entity.X, (int)entity.Y, 8, 8);
            int cx = (int)(bounds.Center.X - area.Left) / Tile;
            int cy = (int)(bounds.Center.Y - area.Top) / Tile;
            if (cx < 0 || cx >= cols || cy < 0 || cy >= rows) continue;
            if (grid[cy, cx] == 'M') continue;
            grid[cy, cx] = symbol;
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
            ["legend"] = legend,
            ["rows"] = lines
        };
    }

    static Rectangle CameraRect(Level level) {
        Vector2 position = J.Get(level.Camera, "Position") is Vector2 vec ? vec : Vector2.Zero;
        return new Rectangle((int)position.X, (int)position.Y, 320, 180);
    }

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
