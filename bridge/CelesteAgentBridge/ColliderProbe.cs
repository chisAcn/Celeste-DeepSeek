using System.Text.Json.Nodes;
using Monocle;

namespace CelesteAgentBridge;

// Rect / circle / list / grid colliders in one shape the agent can reason about.
internal static class ColliderProbe {
    public static JsonObject Describe(Collider? collider) {
        if (collider == null) return new JsonObject { ["type"] = "none" };
        var obj = new JsonObject {
            ["type"] = collider.GetType().Name,
            ["bounds"] = J.Rect(collider.Bounds)
        };
        switch (collider) {
            case Circle circle:
                obj["shape"] = "circle";
                obj["radius"] = J.Num(circle.Radius);
                break;
            case ColliderList list:
                obj["shape"] = "list";
                var parts = new JsonArray();
                foreach (var part in list.colliders) parts.Add(Describe(part));
                obj["parts"] = parts;
                break;
            case Grid grid:
                obj["shape"] = "grid";
                obj["cell_width"] = J.Num(grid.CellWidth);
                obj["cell_height"] = J.Num(grid.CellHeight);
                obj["cells_x"] = grid.CellsX;
                obj["cells_y"] = grid.CellsY;
                break;
            default:
                obj["shape"] = "rect";
                break;
        }
        return obj;
    }
}
