using System.Text.Json.Nodes;
using Celeste;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using Monocle;

namespace CelesteAgentBridge;

// Two-phase screenshot: a request is queued from the update thread and the
// pixels are taken at the end of the next render pass, so the caller never
// blocks the game loop.
internal static class Capture {
    static string? pending;
    static JsonObject last = new() { ["status"] = "idle" };

    public static string Directory_ => Path.Combine(AppContext.BaseDirectory, "CelesteAgentBridge_captures");

    public static JsonObject Request(string kind) {
        if (kind != "level" && kind != "gameplay") kind = "level";
        pending = kind;
        last = new JsonObject { ["status"] = "pending", ["kind"] = kind };
        return last.DeepClone().AsObject();
    }

    public static JsonObject Result() => last.DeepClone().AsObject();

    public static void OnRender() {
        string? kind = pending;
        if (kind == null) return;
        pending = null;
        if (Engine.Scene is not Level level) {
            last = new JsonObject { ["status"] = "error", ["message"] = "no active room" };
            return;
        }
        try {
            last = kind == "gameplay" ? Gameplay(level) : Level(level);
        } catch (Exception e) {
            last = new JsonObject { ["status"] = "error", ["message"] = e.Message, ["kind"] = kind };
        }
    }

    static string PathFor(string kind) {
        System.IO.Directory.CreateDirectory(Directory_);
        return Path.Combine(Directory_, $"{kind}-{DateTime.Now:yyyyMMdd-HHmmss-fff}.png");
    }

    static JsonObject Level(Level level) {
        var device = Engine.Instance.GraphicsDevice;
        int width = device.PresentationParameters.BackBufferWidth;
        int height = device.PresentationParameters.BackBufferHeight;
        if (width <= 0 || height <= 0) throw new InvalidOperationException("no backbuffer");
        var pixels = new Color[width * height];
        device.GetBackBufferData(pixels);
        string path = PathFor("level");
        using (var texture = new Texture2D(device, width, height)) {
            texture.SetData(pixels);
            using var stream = File.Create(path);
            texture.SaveAsPng(stream, width, height);
        }
        return new JsonObject {
            ["status"] = "ok", ["kind"] = "level", ["path"] = path,
            ["width"] = width, ["height"] = height,
            ["room"] = level.Session.Level
        };
    }

    static JsonObject Gameplay(Level level) {
        var device = Engine.Instance.GraphicsDevice;
        int width = 320, height = 180;
        string path = PathFor("gameplay");
        var previous = device.GetRenderTargets();
        using (var target = new RenderTarget2D(device, width, height)) {
            device.SetRenderTarget(target);
            device.Clear(Color.Transparent);
            try {
                level.GameplayRenderer.Render(level);
            } finally {
                if (previous.Length > 0 && previous[0].RenderTarget is RenderTarget2D back)
                    device.SetRenderTarget(back);
                else
                    device.SetRenderTarget(null);
            }
            using var stream = File.Create(path);
            target.SaveAsPng(stream, width, height);
        }
        return new JsonObject {
            ["status"] = "ok", ["kind"] = "gameplay", ["path"] = path,
            ["width"] = width, ["height"] = height,
            ["room"] = level.Session.Level
        };
    }
}
