using System.Globalization;
using System.Reflection;
using System.Text.Json.Nodes;
using Microsoft.Xna.Framework;

namespace CelesteAgentBridge;

// Shared JSON helpers: finite-number safe, reflection access with a cache.
internal static class J {
    static readonly Dictionary<(Type, string), MemberInfo?> cache = new();

    public static JsonNode Num(float v) => float.IsFinite(v)
        ? JsonValue.Create(v)!
        : JsonValue.Create(v.ToString(CultureInfo.InvariantCulture))!;

    public static JsonNode Num(double v) => double.IsFinite(v)
        ? JsonValue.Create(v)!
        : JsonValue.Create(v.ToString(CultureInfo.InvariantCulture))!;

    public static JsonObject Vec(Vector2 v) => new() { ["x"] = Num(v.X), ["y"] = Num(v.Y) };

    public static JsonObject Rect(Rectangle r) => new() {
        ["x"] = r.X, ["y"] = r.Y, ["width"] = r.Width, ["height"] = r.Height };

    public static JsonObject Rect(float x, float y, float w, float h) => new() {
        ["x"] = Num(x), ["y"] = Num(y), ["width"] = Num(w), ["height"] = Num(h) };

    static MemberInfo? Find(Type type, string name) {
        if (cache.TryGetValue((type, name), out var hit)) return hit;
        MemberInfo? found = null;
        for (var t = type; t != null && found == null; t = t.BaseType) {
            const BindingFlags all = BindingFlags.Public | BindingFlags.NonPublic
                | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
            found = t.GetField(name, all);
            if (found == null) {
                var p = t.GetProperty(name, all);
                if (p != null && p.GetIndexParameters().Length == 0) found = p;
            }
            if (found == null) {
                found = (MemberInfo?)t.GetFields(all)
                        .FirstOrDefault(f => f.Name.Equals(name, StringComparison.OrdinalIgnoreCase))
                    ?? (MemberInfo?)t.GetProperties(all)
                        .FirstOrDefault(x => x.Name.Equals(name, StringComparison.OrdinalIgnoreCase)
                            && x.GetIndexParameters().Length == 0);
            }
        }
        cache[(type, name)] = found;
        return found;
    }

    public static object? Get(object target, string name) => Read(target.GetType(), target, name);

    // Static members need the declaring type: Get(typeof(X), name) would search
    // the members of RuntimeType instead of X, which silently reads null.
    public static object? Static(Type type, string name) => Read(type, null, name);

    static object? Read(Type type, object? target, string name) {
        var member = Find(type, name);
        try {
            return member switch {
                FieldInfo f => f.GetValue(target),
                PropertyInfo p => p.GetValue(target),
                _ => null
            };
        } catch { return null; }
    }

    public static long? Long(object target, string name) {
        var direct = Get(target, name);
        if (direct is long l) return l;
        if (direct is int i) return i;
        // Fall back to any long member that mentions time, so a renamed field in
        // a future game version degrades to a guess rather than null.
        foreach (var field in target.GetType().GetFields(
                     BindingFlags.Public | BindingFlags.Instance))
            if (field.FieldType == typeof(long)
                && field.Name.Contains("time", StringComparison.OrdinalIgnoreCase))
                return field.GetValue(target) as long?;
        return null;
    }

    // Probes must never die on one hostile field (collections, EntityID sets,
    // arbitrary mod types). Numeric reads degrade to 0 instead of throwing.
    static readonly Dictionary<Type, bool> convertible = new();

    static bool Convertible(Type type) {
        if (convertible.TryGetValue(type, out var known)) return known;
        bool ok = typeof(IConvertible).IsAssignableFrom(type) && !type.IsEnum;
        convertible[type] = ok;
        return ok;
    }

    public static float F(object target, string name) {
        var v = Get(target, name);
        return v == null || !Convertible(v.GetType())
            ? 0f : Convert.ToSingle(v, CultureInfo.InvariantCulture);
    }

    public static bool B(object target, string name) => Get(target, name) is true;

    public static int I(object target, string name) {
        var v = Get(target, name);
        return v == null || !Convertible(v.GetType())
            ? 0 : Convert.ToInt32(v, CultureInfo.InvariantCulture);
    }

    public static JsonNode? Value(object? v) => v switch {
        null => null,
        float f => Num(f),
        double d => Num(d),
        Vector2 vec => Vec(vec),
        Rectangle r => Rect(r),
        bool b => JsonValue.Create(b),
        string s => JsonValue.Create(s),
        int i => JsonValue.Create(i),
        long l => JsonValue.Create(l),
        Enum e => JsonValue.Create(e.ToString()),
        Point p => new JsonObject { ["x"] = p.X, ["y"] = p.Y },
        _ => JsonValue.Create(v.ToString())
    };

    // Stable identifier for entities: map id when available, hash otherwise.
    public static string EntityKey(object entity) {
        var source = Get(entity, "SourceData");
        if (source != null) {
            int id = I(source, "ID");
            if (id != 0) return $"e{id}";
        }
        return $"r{System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(entity):x8}";
    }
}
