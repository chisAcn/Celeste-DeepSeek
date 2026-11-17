using System.Reflection;
using System.Text.Json.Nodes;
using Celeste;
using Microsoft.Xna.Framework;

namespace CelesteAgentBridge;

// Sub-pixel player state, the timers that gate frame-perfect input, and the
// raw internals a re-implementation needs to continue from any given frame.
internal static class PlayerProbe {
    static Dictionary<int, string>? stateNames;

    static readonly string[] InternalFields = {
        "jumpGraceTimer", "varJumpSpeed", "varJumpTimer",
        "dashCooldownTimer", "dashRefillCooldownTimer", "dashAttackTimer",
        "wallSlideTimer", "wallSlideDir", "wallSpeedRetentionTimer", "wallSpeedRetained",
        "wallBoostDir", "wallBoostTimer", "climbNoMoveTimer",
        "forceMoveX", "forceMoveXTimer", "hopWaitX", "hopWaitXSpeed",
        "lastAim", "DashDir", "beforeDashSpeed", "minHoldTimer",
        "lowFrictionStopTimer", "gliderBoostTimer", "launchedTimer", "launched",
        "dreamDashCanEndTimer", "dreamJump", "noWindTimer",
        "maxFall", "highestAirY", "framesAlive", "lastDashes",
        "dashStartedOnGround", "fastJump", "canCurveDash", "wallBoosting",
        "windDirection", "currentLiftSpeed", "lastLiftSpeed", "dashTrailCounter"
    };

    static readonly string[] PhysicsConstants = {
        "MaxRun", "RunAccel", "RunReduce", "AirMult", "Gravity", "MaxFall", "FastMaxFall",
        "FastMaxAccel", "HalfGravThreshold", "JumpSpeed", "JumpHBoost", "VarJumpTime",
        "JumpGraceTime", "WallJumpHSpeed", "WallJumpForceTime", "WallJumpCheckDist",
        "SuperWallJumpSpeed", "SuperWallJumpH", "SuperWallJumpCheckDist",
        "DashSpeed", "EndDashSpeed", "EndDashUpMult", "DashTime", "SuperDashTime",
        "DashCooldown", "DashRefillCooldown", "DashCornerCorrection", "DashVFloorSnapDist",
        "WallSlideStartMax", "WallSlideTime", "WallSpeedRetentionTime",
        "ClimbMaxStamina", "ClimbUpCost", "ClimbStillCost", "ClimbJumpCost",
        "ClimbUpSpeed", "ClimbDownSpeed", "ClimbSlipSpeed", "ClimbAccel",
        "ClimbCheckDist", "ClimbUpCheckDist", "ClimbNoMoveTime", "ClimbHopX", "ClimbHopY",
        "DuckFriction", "DuckSuperJumpXMult", "DuckSuperJumpYMult",
        "DreamDashSpeed", "BoostMoveSpeed", "BounceSpeed", "SuperBounceSpeed",
        "ReflectBoundSpeed", "LaunchSpeed", "LiftYCap", "LiftXCap", "LowFrictionMult"
    };

    static Dictionary<int, string> Names() {
        if (stateNames != null) return stateNames;
        var map = new Dictionary<int, string>();
        foreach (var field in typeof(Player).GetFields(BindingFlags.Public | BindingFlags.Static)) {
            if (!field.Name.StartsWith("St", StringComparison.Ordinal)) continue;
            if (field.FieldType != typeof(int) || !field.IsLiteral) continue;
            if (field.GetRawConstantValue() is int value) map[value] = field.Name;
        }
        stateNames = map;
        return map;
    }

    public static string StateName(Player player) =>
        Names().TryGetValue(player.StateMachine.State, out var name)
            ? name : $"State{player.StateMachine.State}";

    public static JsonObject Capture(Level level, Player player, bool internals) {
        var obj = new JsonObject {
            ["state"] = StateName(player),
            ["state_index"] = player.StateMachine.State,
            ["room"] = level.Session.Level,
            ["position"] = J.Vec(player.Position),
            ["exact_position"] = J.Vec(player.ExactPosition),
            ["remainder"] = J.Vec(player.PositionRemainder),
            ["previous_position"] = J.Vec(player.PreviousPosition),
            ["speed"] = J.Vec(player.Speed),
            ["lift_speed"] = J.Vec(player.LiftSpeed),
            ["facing"] = player.Facing.ToString(),
            ["dashes"] = player.Dashes,
            ["max_dashes"] = player.MaxDashes,
            ["stamina"] = J.Num(player.Stamina),
            ["on_ground"] = player.OnGround(),
            ["on_safe_ground"] = player.OnSafeGround,
            ["ducking"] = player.Ducking,
            ["dead"] = player.Dead,
            ["in_control"] = player.InControl,
            ["holding"] = player.Holding == null ? null : player.Holding.GetType().Name,
            ["wall_left"] = player.CollideCheck<Solid>(player.Position + new Vector2(-1f, 0f)),
            ["wall_right"] = player.CollideCheck<Solid>(player.Position + new Vector2(1f, 0f)),
            ["collider"] = ColliderProbe.Describe(player.Collider),
            ["timers"] = new JsonObject {
                ["jump_grace"] = J.Num(J.F(player, "jumpGraceTimer")),
                ["var_jump"] = J.Num(J.F(player, "varJumpTimer")),
                ["var_jump_speed"] = J.Num(J.F(player, "varJumpSpeed")),
                ["dash_cooldown"] = J.Num(J.F(player, "dashCooldownTimer")),
                ["dash_refill_cooldown"] = J.Num(J.F(player, "dashRefillCooldownTimer")),
                ["dash_attack"] = J.Num(J.F(player, "dashAttackTimer")),
                ["wall_slide"] = J.Num(J.F(player, "wallSlideTimer")),
                ["wall_slide_dir"] = J.I(player, "wallSlideDir"),
                ["wall_speed_retention"] = J.Num(J.F(player, "wallSpeedRetentionTimer")),
                ["wall_boost_dir"] = J.I(player, "wallBoostDir"),
                ["wall_boost"] = J.Num(J.F(player, "wallBoostTimer")),
                ["climb_no_move"] = J.Num(J.F(player, "climbNoMoveTimer")),
                ["force_move_x"] = J.I(player, "forceMoveX"),
                ["force_move_x_timer"] = J.Num(J.F(player, "forceMoveXTimer")),
                ["min_hold"] = J.Num(J.F(player, "minHoldTimer")),
                ["launch"] = J.Num(J.F(player, "launchedTimer")),
                ["glider_boost"] = J.Num(J.F(player, "gliderBoostTimer")),
                ["dream_dash_can_end"] = J.Num(J.F(player, "dreamDashCanEndTimer")),
                ["no_wind"] = J.Num(J.F(player, "noWindTimer")),
                ["low_friction_stop"] = J.Num(J.F(player, "lowFrictionStopTimer"))
            },
            ["dash_dir"] = J.Vec((Vector2)(J.Get(player, "DashDir") ?? Vector2.Zero)),
            ["last_aim"] = J.Vec((Vector2)(J.Get(player, "lastAim") ?? Vector2.Zero)),
            ["frames_alive"] = J.I(player, "framesAlive"),
            ["auto_jump"] = player.AutoJump
        };
        if (!internals) return obj;
        var raw = new JsonObject();
        foreach (var name in InternalFields) {
            var value = J.Get(player, name);
            if (value != null) raw[name] = J.Value(value);
        }
        obj["internal"] = raw;
        var physics = new JsonObject();
        foreach (var name in PhysicsConstants) {
            var value = J.Get(player, name);
            if (value != null) physics[name] = J.Value(value);
        }
        obj["physics_constants"] = physics;
        return obj;
    }
}

// Per-frame trace, sampled from the same Update tick that advances the game.
internal static class Trajectory {
    const int Capacity = 200000;
    static readonly List<JsonObject> rows = new();
    public static bool Recording { get; private set; }

    public static void Start() {
        rows.Clear();
        Recording = true;
    }

    public static JsonObject Stop(int limit) {
        Recording = false;
        int skip = Math.Max(0, rows.Count - limit);
        var slice = new JsonArray();
        for (int i = skip; i < rows.Count; i++) slice.Add(rows[i].DeepClone());
        return new JsonObject { ["rows"] = slice, ["total"] = rows.Count };
    }

    public static void Record(Level level, Player? player, long frame) {
        if (!Recording || rows.Count >= Capacity) return;
        rows.Add(WriteTrajectoryRow(level, player, frame));
    }

    static JsonObject WriteTrajectoryRow(Level level, Player? player, long frame) {
        var row = new JsonObject {
            ["frame"] = frame,
            ["room"] = level.Session.Level
        };
        if (player == null) return row;
        row["x"] = J.Num(player.ExactPosition.X);
        row["y"] = J.Num(player.ExactPosition.Y);
        row["vx"] = J.Num(player.Speed.X);
        row["vy"] = J.Num(player.Speed.Y);
        row["state"] = PlayerProbe.StateName(player);
        row["dashes"] = player.Dashes;
        row["stamina"] = J.Num(player.Stamina);
        row["on_ground"] = player.OnGround();
        return row;
    }
}
