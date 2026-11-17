using System.Collections;
using System.Reflection;
using System.Text.Json.Nodes;
using Celeste;
using Monocle;

namespace CelesteAgentBridge;

// Menu + save inspection. Menus are reported generically so the controller can
// drive them with the same fixed macros a human would use.
internal static class MenuProbe {
    public static JsonObject Capture(Level? level) {
        var scene = Engine.Scene;
        var textMenus = new JsonArray();
        if (scene != null) {
            foreach (var entity in scene.Entities) {
                if (entity is TextMenu menu) textMenus.Add(DescribeMenu(menu));
            }
        }
        return new JsonObject {
            ["scene"] = scene?.GetType().Name,
            ["paused"] = level?.Paused ?? false,
            ["pause_menu_open"] = level?.PauseMainMenuOpen ?? false,
            ["text_menus"] = textMenus,
            ["main_menu"] = MainMenu(scene),
            ["file_select"] = FileSelect(scene)
        };
    }

    static JsonObject DescribeMenu(TextMenu menu) {
        var items = new JsonArray();
        int index = 0;
        var current = menu.Current;
        foreach (var item in menu.Items) {
            if (index >= 40) break;
            var entry = new JsonObject {
                ["index"] = index++,
                ["label"] = J.Value(J.Get(item, "Label")),
                ["selectable"] = item.Selectable,
                ["disabled"] = item.Disabled,
                ["visible"] = item.Visible,
                ["selected"] = ReferenceEquals(item, current)
            };
            var value = J.Get(item, "Value") ?? J.Get(item, "Values");
            if (value != null) entry["value"] = J.Value(value);
            items.Add(entry);
        }
        return new JsonObject {
            ["focused"] = menu.Focused,
            ["selection"] = menu.Selection,
            ["items"] = items
        };
    }

    static JsonNode? MainMenu(Scene? scene) {
        if (scene == null) return null;
        foreach (var entity in scene.Entities) {
            if (entity.GetType().Name != "OuiMainMenu") continue;
            if (J.Get(entity, "Buttons") is not IEnumerable buttons) return null;
            var list = new List<object>();
            foreach (var button in buttons) list.Add(button);
            var array = new JsonArray();
            for (int i = 0; i < list.Count && i < 20; i++) {
                var button = list[i];
                var entry = new JsonObject {
                    ["index"] = i,
                    ["label"] = J.Value(J.Get(button, "Label") ?? J.Get(button, "Title") ?? button.GetType().Name),
                    ["selected"] = J.B(button, "Selected"),
                    ["up"] = Link(list, J.Get(button, "UpButton")),
                    ["down"] = Link(list, J.Get(button, "DownButton")),
                    ["left"] = Link(list, J.Get(button, "LeftButton")),
                    ["right"] = Link(list, J.Get(button, "RightButton"))
                };
                array.Add(entry);
            }
            return new JsonObject { ["buttons"] = array, ["count"] = list.Count };
        }
        return null;
    }

    static JsonNode? Link(List<object> list, object? target) {
        if (target == null) return null;
        int index = list.FindIndex(x => ReferenceEquals(x, target));
        return JsonValue.Create(index >= 0 ? index : -1);
    }

    static JsonNode? FileSelect(Scene? scene) {
        if (scene == null) return null;
        foreach (var entity in scene.Entities) {
            if (entity.GetType().Name != "OuiFileSelect") continue;
            if (J.Get(entity, "Slots") is not IEnumerable slots) return null;
            var array = new JsonArray();
            int index = 0;
            foreach (var slot in slots) {
                var entry = new JsonObject {
                    ["index"] = index++,
                    ["name"] = J.Value(J.Get(slot, "Name")),
                    ["exists"] = J.B(slot, "Exists"),
                    ["assist"] = J.B(slot, "AssistMode"),
                    ["completed"] = J.B(slot, "Completed")
                };
                var areas = J.Get(slot, "Areas");
                if (areas != null) entry["areas"] = J.Value(areas);
                array.Add(entry);
            }
            return new JsonObject {
                ["slots"] = array,
                ["slot_index"] = J.I(entity, "SlotIndex"),
                ["slot_selected"] = J.B(entity, "SlotSelected")
            };
        }
        return null;
    }
}

// Active save file, plus per-area progress for the visited maps.
internal static class SaveProbe {
    public static JsonObject Capture() {
        var data = SaveData.Instance;
        if (data == null) return new JsonObject { ["available"] = false };
        var areas = new JsonArray();
        string? areasError = null;
        try {
            if (J.Get(data, "Areas") is IEnumerable list) {
                foreach (var stats in list) {
                    var entry = new JsonObject {
                        ["area_id"] = J.I(stats, "ID"),
                        ["name"] = AreaName(J.I(stats, "ID")),
                        ["modes"] = Modes(stats)
                    };
                    areas.Add(entry);
                }
            }
        } catch (Exception e) { areasError = e.GetType().Name + ": " + e.Message; }
        return new JsonObject {
            ["available"] = true,
            ["name"] = data.Name,
            ["slot"] = data.FileSlot,
            ["file"] = Filename(data),
            ["time_ticks"] = data.Time,
            ["time_seconds"] = J.Num(data.Time / 10000000.0),
            ["deaths"] = data.TotalDeaths,
            ["strawberries"] = data.TotalStrawberries,
            ["golden_strawberries"] = data.TotalGoldenStrawberries,
            ["unlocked_areas"] = data.UnlockedAreas,
            ["assist_mode"] = data.AssistMode,
            ["variant_mode"] = data.VariantMode,
            ["cheat_mode"] = data.CheatMode,
            ["last_area"] = AreaKeyJson(data),
            ["areas"] = areas,
            ["areas_error"] = areasError
        };
    }

    static JsonNode Modes(object stats) {
        var array = new JsonArray();
        if (J.Get(stats, "Modes") is not IEnumerable modes) return array;
        int index = 0;
        foreach (var mode in modes) {
            try {
                array.Add(new JsonObject {
                    ["mode"] = index++,
                    ["deaths"] = J.I(mode, "Deaths"),
                    ["time_ticks"] = J.Long(mode, "Time"),
                    ["strawberries"] = J.I(mode, "Strawberries"),
                    ["mapped"] = J.B(mode, "Mapped")
                });
            } catch { index++; }
        }
        return array;
    }

    static JsonNode? AreaKeyJson(SaveData data) {
        var key = J.Get(data, "LastArea");
        if (key == null) return null;
        int id = J.I(key, "ID");
        return new JsonObject {
            ["id"] = id,
            ["mode"] = J.Value(J.Get(key, "Mode")),
            ["name"] = AreaName(id)
        };
    }

    static string? AreaName(int id) {
        try {
            var areas = J.Static(typeof(AreaData), "Areas") as IList;
            if (areas == null || id < 0 || id >= areas.Count) return null;
            return J.Get(areas[id]!, "Name") as string;
        } catch { return null; }
    }

    static string? Filename(SaveData data) {
        try {
            for (var type = data.GetType(); type != null; type = type.BaseType) {
                foreach (var method in type.GetMethods(
                             BindingFlags.Public | BindingFlags.NonPublic
                             | BindingFlags.Instance | BindingFlags.DeclaredOnly)) {
                    if (method.Name != "GetFilename") continue;
                    var args = method.GetParameters().Length == 0
                        ? null : new object[] { data.FileSlot };
                    if (method.Invoke(data, args) is string path) return path;
                }
            }
        } catch { }
        return null;
    }
}
