# Protocol 1.0

UTF-8 JSON，每行一个消息；JSON-RPC 2.0 加 protocol_version=1.0。请求 ID 为字符串，响应回传同一 ID。无法解析请求时 ID=null。当前错误统一为 -32602，细分解析、方法和执行错误待实现。

方法：ping / get_state / execute_frames / reset_room / get_execution / stop。
execute_frames 参数使用 ActionSequence 模型，单动作 1–120 帧、最多 64 动作、合计不超过 600 帧。空 buttons 表示松开所有键，每个动作的 buttons 完全替代上一动作。执行结束释放全部输入。执行 ID 不允许重复；客户端不会重试状态变更，超时关闭连接，执行结果视为未知。

Mock x 向右为正，速度为像素/秒，帧为虚拟 60 Hz 更新次数，状态在更新后采样。reset_room 保留全局帧计数。当前 Mock 执行同步完成，无法在执行中处理 stop，不代表真实游戏的逐帧输入系统。

真实游戏的更新位置、暂停/死亡/过场帧语义和重启语义需要在选定游戏版本上确认。

## Real bridge extension

Real execute_frames returns execution_id and status=running immediately. Poll get_execution until completed/interrupted. Terminal results contain before, after and executed_frames. Missing player is null. reset_room returns requested=true; observe again after reload. Requests run on Engine.Update, inputs apply before Level.Update and outcomes sample after. Only the owning connection disconnect interrupts its execution. stop can be called by any local connection. Pending queue limit 64; execution history limit 10000 per module lifetime.

The updated bridge advertises `playability` and `frame_checkpoints` in `ping`. Call `get_playability` to check the same eligibility predicate used to accept input. Pass `trace_frames: true` with at most 120 requested frames to receive one post-update `checkpoints` entry per executed frame. Regular executions keep their existing response shape. These are real-time Level.Update samples of observable state. The bridge reports `tas: false` and `state_restore: false`.

After installing the rebuilt DLL and restarting Celeste, enter room 1 and run `python -m agent.replay --output logs/diagonal-replay.jsonl`. The control is eight frames of up+right+dash. The report requires displacement, a consumed dash and three matching replays. When tracing is available it identifies the first differing frame.

### Optional CelesteTAS and Speedrun Tool integration

Tested build targets: CelesteTAS 3.47.1, Speedrun Tool 3.29.2, Everest 6696. Install both mods via their official releases and restart Celeste. Check `ping` for `celeste_tas`, `tas_active`, `tas_running` and `state_restore`. The existing `tas` field remains false because raw bridge input still uses the real-time clock.

- With Studio playback inactive, in a controllable room, call `save_state`, play an action, then call `load_state` and observe the game again. Both return `accepted` and `saved`. The bridge owns a single unique in-memory slot for its module lifetime. Call `clear_state` to release it.
- For a CelesteTAS script, create a savestate breakpoint in Studio and pause playback. Call `load_tas_state` with the exact TAS frame for that breakpoint. If the upstream lookup does not return that exact frame, the bridge reports `accepted: false`. Play or step the script in Studio. Real-time execution and room resets are rejected while TAS owns playback.
- API acceptance and state equivalence are separate checks. Verify restored player and room state, then compare two action traces from that restore point. The bridge does not expose hidden entity state or control the Studio frame clock.

Upstream: [CelesteTAS exports](https://github.com/EverestAPI/CelesteTAS-EverestInterop/blob/v3.47.1/CelesteTAS-EverestInterop/Source/Module/CelesteTasExports.cs), [Speedrun Tool TAS exports](https://github.com/DemoJameson/Celeste.SpeedrunTool/blob/v3.29.2/SpeedrunTool/Source/ModInterop/Advanced/TasSpeedrunToolInterop.cs).

### Information probes (bridge 0.3.1)

Read-only methods meant for an agent that needs to understand the room instead of guessing:

- `get_player` — sub-pixel position (`position` + `remainder`, plus `exact_position`), speed,
  named `Player.St*` state, dashes/max, stamina, facing, ground/duck/dead/in-control, held
  object, left/right wall contact, collider shape and the input-gating timers in seconds.
  `internals: true` adds about 40 raw private fields (lift speed, dash dir, last aim, wall
  slide/boost/retention, climb-no-move, force-move, low-friction, min-hold, ...) and the
  physics constants a re-implementation needs.
- `get_level` — chapter sid, area id, mode, room, bounds, camera, cutscene/skip/pause/
  transition flags, chapter ticks, deaths (total and in room), wind vector, core mode,
  freeze frames (seconds + whole frames, excluded from IGT) and the live dialogue state
  (open, page, index, waiting-for-input, text and choice nodes).
- `get_room_structure` — neighbour rooms with bounds and side, all spawn points, default
  spawn, current respawn point and every map trigger with its rectangle.
- `get_entities` (`fields`, `limit`, `whole_room`) — stable id, type, coarse kind
  (hazard/collectible/spring/refill/solid/one_way/trigger/mover/npc), collider shape,
  collidable/visible/depth, the map attributes, and optionally the entity's own simple
  fields (capped at 48, mod entities included).
- `get_collision` (`limit`) — the solid geometry as rectangles plus every object with
  kind, collidability and mutability. Terrain comes from the engine's own `SolidTiles`
  collider (`coverage.source: "collider"`), falling back to the tile array only when a
  level exposes no solid entity (`coverage.source: "solids_data"`).
  `coverage.terrain_complete`, `coverage.solids` and `complete` tell the caller whether
  the snapshot is whole; a partial result is never silently complete.
- `get_tiles` (`whole_room`) — one character per 8x8 tile: `#` terrain, `^` spikes,
  `*` strawberry, `H` heart gem, `C` cassette, `S` spring, `R` refill, `B` booster,
  `T` trigger, `Z` moving block, `-` jump-through platform, `=` solid entity, `o` other,
  `M` Madeline. `solid_cells` counts painted terrain cells and `solids` echoes the
  collider diagnostic so an empty map is distinguishable from a broken read.
- `get_menu` — TextMenu contents with the selected row, main-menu buttons with the
  up/down/left/right graph, and file-select slots.
- `get_save` — save name, slot, filename, play time, deaths, berries, unlocked areas,
  assist/variant/cheat flags and per-area mode stats. A pathological field never fails
  the whole call: `areas_error` reports what was skipped.
- `capture` + `capture_result` — two-phase PNG screenshot; `kind=level` is the finished
  frame, `kind=gameplay` renders the gameplay layer without lighting or HUD. The request
  returns immediately and the pixels are taken at the end of the next render pass.
- `trajectory_start` / `trajectory_stop` (`limit`) — one row per Level.Update tick with
  frame, exact position, speed, state, dashes, stamina and ground contact, for calibrating
  an external simulator against the real game.

`capture` needs two calls because the render pass happens after the update pass:
`{"method":"capture","params":{"kind":"level"}}` then poll
`{"method":"capture_result"}` until `status` is `ok` or `error`.

### Platform telemetry

`get_platforms` returns the current room, bridge frame, total platform count, and up to 16 platform samples. Each sample contains its runtime type, ordinal within that type, world coordinates and collision flag. Tile terrain is excluded. Type plus ordinal is valid for comparisons only while entity enumeration order and membership stay consistent. Consecutive points reveal observed movement direction. Internal path phase is not exposed.

For post-update samples in an execution, send `trace_frames: true` and `trace_platforms: true` together (up to 120 requested frames). A replay reports the first differing platform frame and rejects missing or truncated samples. Run `python -m agent.replay --trace-platforms` for the existing diagonal-dash replay with this extra telemetry. For a platform-specific test, use a room with a moving entity and verify that the same entity changes coordinates over the sampled updates.

### Pause while planning

Bridge 0.2.4 advertises `pause_control`. `pause_game` sets `Level.Paused` when no execution is active and CelesteTAS does not own playback; `resume_game` releases only a pause that the bridge itself created, so a user-opened pause menu is never closed by the client. Both report the resulting `paused` flag and bridge frame. The agent uses the pair to freeze the world while a slow model plans: pause, take the frozen observation, plan, resume, then run the usual pre-execution staleness check before executing. Run with `--pause-planning` (codex or deepseek modes).

### Restore and execute in one update

Bridge 0.2.2 advertises `restore_and_execute` when Speedrun Tool is bound. The request takes the same bounded parameters as `execute_frames`. The game thread validates the inputs before restoring the bridge-owned slot, captures the restored starting state, and queues the first input for the next Level.Update without a client round trip. Poll `get_execution` by execution ID as usual. With `trace_platforms: true`, the starting state includes the initial platform sample.

After restarting Celeste, run `python -m agent.restore_probe airborne` from a playable grounded position with one dash available. In room 6b with a ZipMover in motion, run `python -m agent.restore_probe platform --output logs/live-atomic-platform.json`. The probes require three complete matching repeats relative to a baseline. The airborne probe also requires an identical branch start and a different trace with alternate input. The platform probe requires a changing, complete platform trace.

### Phase 5 live candidate search

Restart with bridge 0.2.3, stop Studio playback, and start in a controllable room. Run `python -m agent.live_search --dx -12 --radius 6 --budget 21`. The target is relative to the restored player's position. Each bounded beam candidate restores the same slot and samples both player and platform state. Interrupted or dead candidates are excluded. The winner is replayed, and the JSON report includes every candidate and the independently sampled verification. A successful report requires reaching the target radius and matching the winning trace. The search attempts to restore the starting slot and clears it at exit.

Bridge 0.2.3 checks action eligibility after loading the slot. This addresses the first live attempt on 0.2.2, which was interrupted when the previous candidate left the player temporarily unplayable. Live acceptance on 0.2.3 passed in room 6b. See the dated live-validation report.

For landing search, add `--settle 45 --grounded-frames 4 --min-segments 2 --repeats 3`. Candidates have to go airborne and finish within the target radius for all four final grounded samples. `--benchmark` evaluates beam search, a seeded random frontier, and a fixed jump-and-move script from the same saved state. The candidate cap applies to each method; the fixed script may finish early after exhausting its single path. Reported results describe one starting state, not an aggregate success rate.

Add `--skill-name NAME --game-version VERSION` to export a winning route to SQLite after three matching repeats. The stored skill includes the exact observed starting player, room and platform sample, together with its measured landing. Inapplicable starts require a fresh search.
