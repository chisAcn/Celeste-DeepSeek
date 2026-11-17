using Celeste;
using Celeste.Mod;
using Microsoft.Xna.Framework;
using Monocle;
using MonoMod.ModInterop;
using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text.Json.Nodes;

namespace CelesteAgentBridge;

// Real-time Level.Update controller. Not a TAS frame stepper.
public sealed class Module : EverestModule {
    readonly ConcurrentQueue<Action> requests = new();
    readonly Dictionary<string, JsonObject> executions = new();
    TcpListener? listener;
    CancellationTokenSource? lifetime;
    JsonObject snapshot = new();
    long frame;
    Job? active;
    readonly InputController input = new();
    readonly string saveSlot = $"CelesteAgentBridge-{Guid.NewGuid():N}";
    bool agentPaused;
    bool TasActive => TasInterop.IsTasActive?.Invoke() == true;
    public override void Initialize() {
        typeof(TasInterop).ModInterop();
        typeof(SpeedrunInterop).ModInterop();
    }
    sealed class Job {
        public required string Id;
        public required JsonArray Actions;
        public required JsonObject Before;
        public required string Room;
        public JsonArray? Checkpoints;
        public bool TracePlatforms;
        public Guid Owner;
        public int Index, Remaining, Count;
    }
    public override void Load() {
        lifetime = new();
        listener = new(IPAddress.Loopback, 32123);
        listener.Start();
        On.Celeste.Level.Update += Update;
        On.Monocle.Engine.Update += EngineUpdate;
        _ = Serve(lifetime.Token);
    }
    public override void Unload() {
        lifetime?.Cancel(); listener?.Stop();
        On.Celeste.Level.Update -= Update;
        On.Monocle.Engine.Update -= EngineUpdate;
        if (agentPaused && Engine.Scene is Level pausedLevel) { pausedLevel.Paused = false; agentPaused = false; }
        input.Release(); active = null;
        while (requests.TryDequeue(out _)) { }
    }
    async Task Serve(CancellationToken token) {
        try { while (!token.IsCancellationRequested) {
            var client = await listener!.AcceptTcpClientAsync(token);
            _ = Connection(client, token);
        }} catch (OperationCanceledException) { } catch (SocketException) when (token.IsCancellationRequested) { }
    }
    async Task Connection(TcpClient client, CancellationToken token) {
        var owner=Guid.NewGuid();
        using (client) using (var reader = new StreamReader(client.GetStream()))
        using (var writer = new StreamWriter(client.GetStream()) { AutoFlush = true }) {
            try { while (!token.IsCancellationRequested) {
                // Bounded messages: never allocate an unbounded line from a local peer.
                var chars = new List<char>();
                var one = new char[1];
                while (await reader.ReadAsync(one.AsMemory(), token) != 0 && one[0] != '\n') {
                    if (chars.Count >= 65536) throw new IOException("message too large");
                    chars.Add(one[0]);
                }
                if (chars.Count == 0) break;
                JsonObject reply = new() { ["jsonrpc"]="2.0", ["protocol_version"]="1.0", ["id"]=null };
                try {
                    var req = JsonNode.Parse(new string(chars.ToArray()))!.AsObject();
                    reply["id"] = req["id"]?.DeepClone();
                    if (req["id"] is null || req["jsonrpc"]?.GetValue<string>() != "2.0" || req["protocol_version"]?.GetValue<string>() != "1.0") throw new ArgumentException("invalid envelope");
                    var completion = new TaskCompletionSource<JsonNode>(TaskCreationOptions.RunContinuationsAsynchronously);
                    if (requests.Count >= 64) throw new ArgumentException("queue full");
                    requests.Enqueue(() => { if (completion.Task.IsCompleted) return; try { completion.TrySetResult(Dispatch(req,owner)); } catch(Exception e) { completion.TrySetException(e); } });
                    using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
                    deadline.CancelAfter(TimeSpan.FromSeconds(3));
                    using var registration = deadline.Token.Register(() => completion.TrySetCanceled());
                    reply["result"] = await completion.Task;
                } catch(Exception e) { reply["error"] = new JsonObject { ["code"]=-32602, ["message"]=e.Message }; }
                await writer.WriteLineAsync(reply.ToJsonString());
            }} catch (Exception e) when (e is IOException or OperationCanceledException or SocketException) { }
            finally { requests.Enqueue(() => { if(active?.Owner == owner) Finish("interrupted"); }); }
        }
    }
    JsonNode Dispatch(JsonObject req, Guid owner) {
        var p = req["params"] as JsonObject ?? new();
        switch(req["method"]?.GetValue<string>()) {
            case "ping": return new JsonObject {
                ["backend"]="everest-realtime", ["tas"]=false,
                ["state_restore"]=SpeedrunInterop.Available,
                ["celeste_tas"]=TasInterop.IsTasActive != null,
                ["tas_active"]=TasActive, ["tas_running"]=TasInterop.IsTasRunning?.Invoke() == true,
                ["frame_checkpoints"]=true, ["playability"]=true, ["platform_telemetry"]=true,
                ["restore_and_execute"]=SpeedrunInterop.Available, ["pause_control"]=true,
                ["mod_version"]=Metadata.Version.ToString()
            };
            case "get_state": return snapshot.DeepClone();
            case "get_platforms":
                if (Engine.Scene is not Level platformLevel) throw new ArgumentException("no active room");
                return ObservePlatforms(platformLevel);
            case "get_room_info":
                if (Engine.Scene is not Level infoLevel) throw new ArgumentException("no active room");
                return RoomInfo(infoLevel);
            case "save_state":
            case "load_state":
            case "clear_state":
                if (!SpeedrunInterop.Available) throw new ArgumentException("Speedrun Tool API unavailable");
                if (active != null || TasActive) throw new ArgumentException("input execution active");
                string operation = req["method"]!.GetValue<string>();
                if (operation == "clear_state") {
                    SpeedrunInterop.ClearState!(saveSlot);
                    return new JsonObject { ["saved"]=SpeedrunInterop.TasIsSaved!(saveSlot) };
                }
                if (Engine.Scene is not Level || (operation == "save_state" && !IsPlayable(Engine.Scene as Level)))
                    throw new ArgumentException("not playable");
                bool accepted = operation == "save_state"
                    ? SpeedrunInterop.SaveState!(saveSlot)
                    : SpeedrunInterop.TasIsSaved!(saveSlot) && SpeedrunInterop.LoadState!(saveSlot);
                return new JsonObject { ["accepted"]=accepted, ["saved"]=SpeedrunInterop.TasIsSaved!(saveSlot) };
            case "load_tas_state":
                if (active != null || !TasActive || TasInterop.IsTasRunning?.Invoke() != false
                    || TasInterop.GetLatestSavestateForFrame == null || TasInterop.GetSavestateFrame == null
                    || TasInterop.LoadSavestate == null) throw new ArgumentException("pause a supported TAS first");
                int target = p["frame"]?.GetValue<int>() ?? -1;
                if (target < 0) throw new ArgumentException("invalid TAS frame");
                var handle = TasInterop.GetLatestSavestateForFrame(target);
                if (handle == null || TasInterop.GetSavestateFrame(handle) != target)
                    return new JsonObject { ["accepted"]=false, ["frame"]=target };
                return new JsonObject { ["accepted"]=TasInterop.LoadSavestate(handle), ["frame"]=target };
            case "pause_game":
            case "resume_game":
                if (TasActive) throw new ArgumentException("CelesteTAS owns playback");
                if (active != null) throw new ArgumentException("input execution active");
                if (Engine.Scene is not Level pauseLevel) throw new ArgumentException("no active room");
                if (req["method"]!.GetValue<string>() == "pause_game") {
                    if (!pauseLevel.Paused) { pauseLevel.Paused = true; agentPaused = true; }
                } else if (agentPaused) {
                    pauseLevel.Paused = false; agentPaused = false;
                }
                return new JsonObject { ["paused"]=pauseLevel.Paused, ["frame"]=frame };
            case "get_playability":
                return new JsonObject { ["playable"]=IsPlayable(Engine.Scene as Level), ["frame"]=frame };
            case "stop": if(active != null) Finish("interrupted"); input.Release(); return new JsonObject { ["stopped"]=true };
            case "get_execution": return executions[p["execution_id"]!.GetValue<string>()].DeepClone();
            case "reset_room":
                if (TasActive) throw new ArgumentException("CelesteTAS owns playback");
                if(active != null) Finish("interrupted");
                if (Engine.Scene is not Level current) throw new ArgumentException("no active room");
                current.Reload();
                return new JsonObject { ["requested"]=true };
            case "execute_frames":
            case "restore_and_execute":
                if (TasActive) throw new ArgumentException("CelesteTAS owns playback");
                if(active != null) throw new ArgumentException("busy");
                bool restore = req["method"]!.GetValue<string>() == "restore_and_execute";
                var level = Engine.Scene as Level;
                if(level == null || (!restore && !IsPlayable(level))) throw new ArgumentException("not playable");
                string id = p["execution_id"]!.GetValue<string>();
                if(id.Length is <1 or >128 || executions.ContainsKey(id)) throw new ArgumentException("invalid or duplicate execution ID");
                if(executions.Count >= 10000) throw new ArgumentException("session execution capacity reached");
                var actions = p["actions"]!.AsArray(); int total=0;
                if(actions.Count is <1 or >64) throw new ArgumentException("action count");
                foreach(var a in actions) {
                    int n=a!["frames"]!.GetValue<int>(); if(n is <1 or >120) throw new ArgumentException("frame bounds"); total+=n;
                    foreach(var b in a["buttons"]!.AsArray()) if(!InputController.Allowed.Contains(b!.GetValue<string>())) throw new ArgumentException("invalid button");
                }
                if(total>600) throw new ArgumentException("frame budget");
                bool trace = p["trace_frames"]?.GetValue<bool>() ?? false;
                bool tracePlatforms = p["trace_platforms"]?.GetValue<bool>() ?? false;
                if (tracePlatforms && !trace) throw new ArgumentException("platform traces require trace_frames");
                if(trace && total>120) throw new ArgumentException("trace exceeds 120 frames");
                if (restore) {
                    if (!SpeedrunInterop.Available || !SpeedrunInterop.TasIsSaved!(saveSlot))
                        throw new ArgumentException("bridge save slot unavailable or empty");
                    if (!SpeedrunInterop.LoadState!(saveSlot))
                        throw new ArgumentException("restore rejected");
                    level = Engine.Scene as Level;
                    if (level == null || !IsPlayable(level))
                        throw new ArgumentException("restored state is not playable");
                }
                var before = Observe(level);
                if (tracePlatforms) before["platform_sample"] = PlatformObserver.Capture(level);
                active = new Job { Id=id, Actions=(JsonArray)actions.DeepClone(), Before=before, Room=level.Session.Level, Owner=owner, Checkpoints=trace ? new JsonArray() : null, TracePlatforms=tracePlatforms };
                executions[id] = new JsonObject { ["execution_id"]=id, ["status"]="running" };
                return executions[id].DeepClone();
            default: throw new ArgumentException("unknown method");
        }
    }
    static bool IsPlayable(Level? level) =>
        level?.Tracker.GetEntity<Player>() is { Dead: false, InControl: true }
        && !level.InCutscene && !level.FrozenOrPaused && !level.Transitioning;
    void EngineUpdate(On.Monocle.Engine.orig_Update orig, Engine engine, Microsoft.Xna.Framework.GameTime time) {
        if(Engine.Scene is Level level) snapshot=Observe(level);
        else {
            snapshot=new JsonObject { ["protocol_version"]="1.0", ["frame"]=frame, ["player"]=null, ["room"]=new JsonObject { ["name"]="", ["completed"]=false } };
            if(active != null) Finish("interrupted");
        }
        for(int i=0;i<64 && requests.TryDequeue(out var request);i++) request();
        orig(engine,time);
    }
    void Update(On.Celeste.Level.orig_Update orig, Level level) {
        snapshot = Observe(level);
        var job=active;
        if(job != null) {
            var player=level.Tracker.GetEntity<Player>();
            if(TasActive || player == null || player.Dead || !player.InControl || level.InCutscene || level.FrozenOrPaused || level.Transitioning || level.Session.Level != job.Room) { Finish("interrupted"); job=null; }
        }
        if(job != null) {
            var action=job.Actions[job.Index]!;
            if(job.Remaining==0) job.Remaining=action["frames"]!.GetValue<int>();
            input.Apply(action["buttons"]!.AsArray().Select(b=>b!.GetValue<string>()));
        }
        try { orig(level); } catch { if(active != null) Finish("interrupted"); throw; }
        frame++; snapshot=Observe(level);
        if(job != null && active == job) {
            job.Count++; job.Remaining--;
            if (job.Checkpoints != null) {
                var checkpoint = snapshot.DeepClone();
                if (job.TracePlatforms) checkpoint["platform_sample"] = PlatformObserver.Capture(level);
                job.Checkpoints.Add(checkpoint);
            }
            var player=level.Tracker.GetEntity<Player>();
            if(player == null || player.Dead || level.Session.Level != job.Room || level.Transitioning) Finish("interrupted");
            else if(level.Completed || (job.Remaining==0 && ++job.Index>=job.Actions.Count)) Finish("completed");
        }
    }
    JsonObject ObservePlatforms(Level level) {
        var result = PlatformObserver.Capture(level);
        result["frame"] = frame;
        result["room"] = level.Session.Level;
        return result;
    }
    // Room geometry plus every boundary segment that leads into a neighbouring room.
    JsonObject RoomInfo(Level level) {
        var bounds = level.Bounds;
        var map = level.Session.MapData;
        var exits = new JsonArray();
        void Scan(string side, bool vertical) {
            int start = vertical ? bounds.Top : bounds.Left;
            int end = vertical ? bounds.Bottom : bounds.Right;
            string? current = null;
            int segmentStart = start, last = start;
            void Flush() {
                if (current == null) return;
                exits.Add(new JsonObject {
                    ["side"]=side, ["target"]=current, ["axis"]=vertical ? "y" : "x",
                    ["from"]=segmentStart, ["to"]=last
                });
            }
            for (int t = start; t <= end; t += 8) {
                Vector2 probe = side switch {
                    "left" => new Vector2(bounds.Left - 6, t),
                    "right" => new Vector2(bounds.Right + 6, t),
                    "up" => new Vector2(t, bounds.Top - 6),
                    _ => new Vector2(t, bounds.Bottom + 6),
                };
                var at = map.GetAt(probe);
                bool open = at != null && at.Name != level.Session.Level && !level.CollideCheck<Solid>(probe);
                string? key = open ? at!.Name : null;
                if (key != current) { Flush(); current = key; segmentStart = t; }
                last = t;
            }
            Flush();
        }
        Scan("left", true); Scan("right", true); Scan("up", false); Scan("down", false);
        return new JsonObject {
            ["room"]=level.Session.Level, ["frame"]=frame,
            ["bounds"]=new JsonObject {
                ["x"]=bounds.X, ["y"]=bounds.Y, ["width"]=bounds.Width, ["height"]=bounds.Height },
            ["exits"]=exits
        };
    }
    void Finish(string status) {
        if(active is not {} job) return;
        input.Release();
        executions[job.Id]=new JsonObject { ["execution_id"]=job.Id, ["status"]=status, ["executed_frames"]=job.Count, ["before"]=job.Before.DeepClone(), ["after"]=snapshot.DeepClone() };
        if(job.Checkpoints != null) executions[job.Id]["checkpoints"]=job.Checkpoints;
        active=null;
    }
    JsonObject Observe(Level level) {
        var p=level.Tracker.GetEntity<Player>();
        return new JsonObject {
            ["protocol_version"]="1.0", ["frame"]=frame,
            ["player"]=p==null?null:new JsonObject { ["x"]=p.X, ["y"]=p.Y, ["vx"]=p.Speed.X, ["vy"]=p.Speed.Y, ["on_ground"]=p.OnGround(), ["dashes"]=p.Dashes, ["stamina"]=p.Stamina, ["dead"]=p.Dead },
            ["room"]=new JsonObject { ["name"]=level.Session.Level, ["completed"]=level.Completed }
        };
    }
}
