using System.Collections;
using System.Reflection;
using System.Text.Json.Nodes;
using Celeste;
using Microsoft.Xna.Framework;
using Monocle;

namespace CelesteAgentBridge;

// Entity dump: stable id, type, coarse kind, collider shape, map attributes and
// optionally every simple field the entity declares itself.
internal static class EntityScan {
    static readonly HashSet<string> Hazards = new() {
        "Spikes", "FireBall", "FireBarrier", "Seeker", "Puffer", "AngryOshiro",
        "Badeline", "Tentacle", "Blade", "SandwichLava", "IceBlock", "Explosion"
    };
    static readonly HashSet<string> Collectibles = new() {
        "Strawberry", "HeartGem", "Cassette", "SummitGem", "TheoCrystal"
    };

    public static JsonObject Capture(Level level, bool fields, int limit, bool wholeRoom) {
        var view = wholeRoom ? level.Bounds : CameraRect(level);
        var found = new List<Entity>();
        foreach (var entity in level.Entities) {
            if (entity is SolidTiles) continue;
            if (!wholeRoom && !entity.CollideRect(view) && !view.Contains((int)entity.X, (int)entity.Y)) continue;
            found.Add(entity);
        }
        found.Sort((a, b) => {
            int byY = a.Y.CompareTo(b.Y);
            return byY != 0 ? byY : a.X.CompareTo(b.X);
        });

        var array = new JsonArray();
        foreach (var entity in found) {
            if (array.Count >= limit) break;
            array.Add(Describe(entity, fields));
        }
        return new JsonObject {
            ["entities"] = array,
            ["total"] = found.Count,
            ["truncated"] = found.Count > limit,
            ["region"] = J.Rect(view)
        };
    }

    static Rectangle CameraRect(Level level) {
        Vector2 position = J.Get(level.Camera, "Position") is Vector2 vec ? vec : Vector2.Zero;
        return new Rectangle((int)position.X, (int)position.Y, 320, 180);
    }

    public static string Kind(Entity entity) {
        string type = entity.GetType().Name;
        if (Hazards.Contains(type)) return "hazard";
        if (Collectibles.Contains(type)) return "collectible";
        if (entity is Trigger) return "trigger";
        if (entity is Spikes) return "hazard";
        if (entity is Strawberry) return "collectible";
        if (entity is Refill) return "refill";
        if (entity is Spring) return "spring";
        if (entity is Booster) return "booster";
        if (entity is JumpThru) return "one_way";
        if (entity is Solid) return type.Contains("Mover") ? "mover" : "solid";
        if (entity is Platform) return "platform";
        if (entity is NPC) return "npc";
        if (type.Contains("Mover")) return "mover";
        if (type.Contains("Crystal")) return "collectible";
        return "entity";
    }

    static JsonObject Describe(Entity entity, bool fields) {
        var obj = new JsonObject {
            ["id"] = J.EntityKey(entity),
            ["type"] = entity.GetType().FullName ?? entity.GetType().Name,
            ["kind"] = Kind(entity),
            ["position"] = J.Vec(entity.Position),
            ["collider"] = ColliderProbe.Describe(entity.Collider),
            ["collidable"] = entity.Collidable,
            ["visible"] = entity.Visible,
            ["active"] = entity.Active,
            ["depth"] = entity.Depth
        };
        var source = J.Get(entity, "SourceData");
        if (source != null) {
            obj["map_name"] = J.Value(J.Get(source, "Name"));
            obj["map_id"] = J.Value(J.Get(source, "ID"));
            if (J.Get(source, "Values") is IDictionary values) {
                var props = new JsonObject();
                foreach (DictionaryEntry entry in values) {
                    string key = entry.Key?.ToString() ?? "";
                    if (key.Length == 0 || props.Count >= 24) continue;
                    props[key] = J.Value(entry.Value);
                }
                if (props.Count > 0) obj["map_props"] = props;
            }
        }
        if (fields) {
            var declared = ReadFields(entity, 48);
            if (declared.Count > 0) obj["fields"] = declared;
        }
        return obj;
    }

    // Only scalar-ish values: textures, sounds and collections would bloat the reply.
    public static JsonObject ReadFields(object target, int limit) {
        var obj = new JsonObject();
        var type = target.GetType();
        const BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
        foreach (var field in type.GetFields(flags)) {
            if (obj.Count >= limit) break;
            if (field.IsStatic) continue;
            Type ft = field.FieldType;
            bool simple = ft.IsPrimitive || ft.IsEnum || ft == typeof(string)
                || ft == typeof(Vector2) || ft == typeof(Rectangle) || ft == typeof(Point);
            if (!simple) continue;
            object? value;
            try { value = field.GetValue(target); } catch { continue; }
            if (value == null) continue;
            if (value is float f) obj[field.Name] = J.Num(f);
            else obj[field.Name] = J.Value(value);
        }
        return obj;
    }
}
