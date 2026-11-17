using System.Collections;
using System.Text.Json.Nodes;
using Celeste;
using Microsoft.Xna.Framework;
using Monocle;

namespace CelesteAgentBridge;

// Chapter progress, timers, freeze frames, wind, dialogue state.
internal static class WorldProbe {
    public static JsonObject Capture(Level level, long frame) {
        var session = level.Session;
        var area = session.Area;
        var camera = J.Get(level.Camera, "Position");
        var respawn = session.RespawnPoint;
        float freeze = Convert.ToSingle(J.Get(Engine.Instance, "FreezeTimer") ?? 0f);

        return new JsonObject {
            ["frame"] = frame,
            ["sid"] = J.Value(J.Get(area, "SID")),
            ["area_id"] = J.Value(J.Get(area, "ID")),
            ["mode"] = J.Value(J.Get(area, "Mode")),
            ["room"] = session.Level,
            ["bounds"] = J.Rect(level.Bounds),
            ["camera"] = camera is Vector2 vec ? J.Vec(vec) : null,
            ["completed"] = level.Completed,
            ["in_cutscene"] = level.InCutscene,
            ["skipping_cutscene"] = level.SkippingCutscene,
            ["paused"] = level.Paused,
            ["pause_menu_open"] = level.PauseMainMenuOpen,
            ["frozen_or_paused"] = level.FrozenOrPaused,
            ["transitioning"] = level.Transitioning,
            ["timer_started"] = level.TimerStarted,
            ["timer_stopped"] = level.TimerStopped,
            ["timer_hidden"] = level.TimerHidden,
            ["time_ticks"] = session.Time,
            ["time_seconds"] = J.Num(session.Time / 10000000.0),
            ["deaths"] = session.Deaths,
            ["deaths_in_level"] = session.DeathsInCurrentLevel,
            ["dashes_at_level_start"] = session.DashesAtLevelStart,
            ["wind"] = J.Vec(level.Wind),
            ["core_mode"] = level.CoreMode.ToString(),
            ["space"] = level.InSpace,
            ["dark_room"] = level.DarkRoom,
            ["respawn_point"] = respawn.HasValue ? J.Vec(respawn.Value) : null,
            ["freeze"] = new JsonObject {
                ["seconds"] = J.Num(freeze),
                ["frames"] = (int)Math.Ceiling(freeze * 60f)
            },
            ["dialogue"] = DialogueState(level)
        };
    }

    static JsonNode? DialogueState(Level level) {
        var box = level.Tracker.GetEntity<Textbox>();
        if (box == null) return null;
        var nodes = new JsonArray();
        if (J.Get(box, "Nodes") is IEnumerable list) {
            int index = 0;
            foreach (var node in list) {
                if (index >= 40) break;
                var entry = new JsonObject { ["index"] = index++ };
                if (J.Get(node, "Text") is string text) entry["text"] = text;
                var choice = J.Get(node, "Choice");
                if (choice != null) {
                    var items = new JsonArray();
                    if (J.Get(choice, "Items") is IEnumerable choices) {
                        foreach (var item in choices) {
                            var label = J.Get(item, "Label") ?? J.Get(item, "Text") ?? item;
                            items.Add(J.Value(label));
                        }
                    }
                    entry["choice"] = new JsonObject {
                        ["items"] = items,
                        ["index"] = J.I(choice, "Index")
                    };
                }
                nodes.Add(entry);
            }
        }
        return new JsonObject {
            ["open"] = box.Opened,
            ["page"] = box.Page,
            ["index"] = J.I(box, "index"),
            ["start"] = box.Start,
            ["waiting_for_input"] = J.B(box, "waitingForInput"),
            ["can_skip"] = J.B(box, "canSkip"),
            ["portrait"] = box.PortraitName,
            ["nodes"] = nodes
        };
    }
}

// Neighbouring rooms, spawn points and map triggers for the active room.
internal static class RoomStructure {
    public static JsonObject Capture(Level level) {
        var session = level.Session;
        var map = session.MapData;
        var current = session.LevelData;
        var neighbours = new JsonArray();
        foreach (var other in map.Levels) {
            if (other.Name == current.Name) continue;
            if (!Adjacent(current.Bounds, other.Bounds)) continue;
            var bounds = other.Bounds;
            neighbours.Add(new JsonObject {
                ["room"] = other.Name,
                ["bounds"] = J.Rect(bounds),
                ["side"] = SideOf(current.Bounds, bounds)
            });
        }

        var spawns = new JsonArray();
        foreach (var spawn in current.Spawns) spawns.Add(J.Vec(spawn));

        var triggers = new JsonArray();
        foreach (var trigger in current.Triggers) {
            triggers.Add(new JsonObject {
                ["name"] = trigger.Name,
                ["id"] = trigger.ID,
                ["position"] = J.Vec(trigger.Position),
                ["width"] = trigger.Width,
                ["height"] = trigger.Height
            });
        }

        return new JsonObject {
            ["room"] = current.Name,
            ["bounds"] = J.Rect(current.Bounds),
            ["tile_bounds"] = J.Rect(current.TileBounds),
            ["neighbours"] = neighbours,
            ["spawns"] = spawns,
            ["default_spawn"] = current.DefaultSpawn.HasValue ? J.Vec(current.DefaultSpawn.Value) : null,
            ["respawn_point"] = session.RespawnPoint.HasValue ? J.Vec(session.RespawnPoint.Value) : null,
            ["triggers"] = triggers,
            ["map_bounds"] = J.Rect(map.Bounds),
            ["level_count"] = map.LevelCount
        };
    }

    static bool Adjacent(Rectangle a, Rectangle b) {
        bool verticalTouch = a.Right == b.Left || b.Right == a.Left;
        bool horizontalOverlap = a.Top < b.Bottom && b.Top < a.Bottom;
        bool horizontalTouch = a.Bottom == b.Top || b.Bottom == a.Top;
        bool verticalOverlap = a.Left < b.Right && b.Left < a.Right;
        return (verticalTouch && horizontalOverlap) || (horizontalTouch && verticalOverlap);
    }

    static string SideOf(Rectangle current, Rectangle other) {
        if (other.Left >= current.Right) return "right";
        if (other.Right <= current.Left) return "left";
        if (other.Top >= current.Bottom) return "down";
        return "up";
    }
}
