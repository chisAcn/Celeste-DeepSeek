# Acceptance checklist

Compilation is not proof of successful game control.

1. Launch Everest and verify CelesteAgentBridge loads, localhost:32123 responds to ping.
2. Observe player coordinates/speed while manually moving. Missing player must be null.
3. Run ten right frames three times from the same manually established starting point; record before/after and deviations.
4. Verify right+jump, diagonal dash, grab, empty-button release and consecutive held jump semantics.
5. Disconnect during a long action; verify release. Test stop from another client.
6. Test pause, death, respawn, room transitions and leaving gameplay.
7. Check reset_room reloads the current room (not a snapshot restore).
8. Run a bounded model trial using either `--mode codex` with ChatGPT login or `--mode gpt` with API credentials. Inspect `logs/decisions.jsonl`.

Still unverified: live Mod loading/input timing, grab-setting interactions, real room completion and GPT API trial. The local protocol assumes trusted clients. Error codes are coarse. No screenshot/geometry observation yet. Updates continue while GPT thinks; no deterministic replay claim.

Verified 2026-11-15: real bridge loaded; ping/state succeeded; idle sequence executed 1 frame; right sequence executed 10 frames, x 58 -> 70, vx 0 -> 90. Python CI passed (12 tests). Remaining checklist items still pending.

See live-validation-2026-11-15.md: jump, climb, natural death/respawn and room transitions now observed successfully. Dash tutorial is blocked by frozen-level eligibility. This supersedes the earlier pending status for those four tested cases.

On 2026-11-16, `python -m agent.main --real --mode codex --steps 1` passed the
single-action closed loop in room 6b on Everest bridge 0.2.3. Codex planned
15 frames of right+jump and the bridge reported exactly 15 completed frames.
The player moved from (2016, -1128) to (2037, -1153), within the predicted
x range of 2035–2065. The decision log recorded `verified: true` under
execution ID `987dbe84-8b09-426d-b778-e01dae776b70`. The trial returned
`STOPPED` at the one-step limit with the room still incomplete. The direct
API mode and room completion remain unverified.

On 2026-11-16, a three-step Codex trial after resetting room 6b to its entrance
at (2016, -1128) reached x=2091 at the final execution boundary. All three
sequences completed and all three final x values passed their predicted ranges.

| Step | Input | Executed frames | Start x | End x | Predicted x |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | Right + jump | 18 | 2016 | 2042 | 2016–2046 |
| 2 | Right | 12 | 2047 | 2062 | 2056–2063 |
| 3 | Right + jump | 18 | 2065 | 2091 | 2087–2095 |

The run returned `STOPPED` at its three-step limit. The game kept updating
while Codex planned: the second plan referred to the jump's descent, but its
execution started on the ground. The decision log records execution boundary
states, so it does not independently confirm the exact observation sent to
the model. No action stalled or missed its predicted x range in this trial,
so recovery from prediction errors and full room completion remain unverified.
The three entries in `logs/decisions.jsonl` start at execution frame 122715.

On 2026-11-16, the stale-plan guard passed a controlled timing trial on the
real 6b bridge. The test substituted two fixed planner replies to make the
first response arrive after landing. The first plan observed the player in
the air at frame 144005. At frame 144026 the player was grounded, so the
guard logged `STALE_PLAN` with `ground_state_changed` and skipped execution.
The next plan used the grounded observation at frame 144027 and completed
12 right frames, moving x from 2016 to 2031 with `verified: true`.
Both planning and pre-execution observations appear in the decision log.
Rejected plans consume the existing step budget. The test exercised real
physics and bridge inputs with controlled planner responses.

The 2026-11-16 repeat used three real Codex replies on the live 6b bridge.
Plan 1 observed the player airborne at frame 149168 and was rejected after
landing at frame 156351. Plan 2 used grounded frame 156352, completed all
12 right+jump frames, and reached x=2033 from x=2016 within its predicted
range of 2025–2035. Plan 3 again observed the player airborne and was rejected
after landing. Both rejections logged `ground_state_changed` and issued no
inputs. The run returned `STOPPED` after consuming its three-step budget.
The last observed grounded position was (2038, -1128), with 6b incomplete.

The 6b full-room trial on 2026-11-16 did not pass. An initial unassisted
Codex route reached x=2081 in the air and stopped when the player temporarily
disappeared. The retry waited for respawn and gave real Codex the previously
verified 120-frame entrance route as an advisory hint. Across six plans,
that route landed on the first ZipMover twice. A jump toward the next
ZipMover was interrupted by death at x=2171, followed by a confirmed
respawn. Two plans were blocked because the platform carried the player
beyond the permitted position drift while Codex planned. The final plan
executed 24 idle frames to ride the platform. The bridge reported a live
player at (2158, -1152), still in 6b with `completed: false`, after the
budget ended. The decision log entries start at planning frame 177117.

The local TAS action prior was then tested with real Codex from the 6b
entrance and a six-plan limit. The run ended `FAILED` after four executed
plans. Their action-end x coordinates were 2092, 2089, 2083 and 2106, but
each settled observation returned to (2016, -1128). The first and fourth
passed their immediate x-range checks without confirming a landing.
The bridge still reported room 6b incomplete at frame 313518. No verified
room-specific route was supplied in this run, so this does not isolate
the effect of the action prior from the earlier route-assisted trial.

The 1A TAS route replay through room 6b passed the room-exit check on
2026-11-16. After loading `data/1A-through-6b.tas` in Celeste Studio, the live
bridge observed the player alive and grounded in 6c at (2340, -1304),
frame 460264. This verifies the recorded TAS route through 6b. The Codex
planner's own full-room trial remains separate.

The execution contract and the collaboration path were both run against bridge
0.3.2 in room 7 on 2026-11-17, from a standing start at (2600, -1480).

Execution contract:

- A contract whose `pre.x` was 100px away from the player returned `REJECTED`
  with `reason=position_changed`, `executed_frames=0`, no `get_execution`
  record, and the player still at (2600, -1480). No input reached the game.
- `right:60` with `Abort(timeout_frames=8)` returned `ABORTED`, `reason=timeout`,
  `at_frame=8`, `executed_frames=9` in 0.187s of wall time. The extra frame is
  the stop request itself: it is dequeued on the next `Engine.Update`, so one
  frame always lands after the decision. Expect `executed = at + 1`.
- `right:40` into the wall at x≈2624 returned `ABORTED`, `reason=stalled`,
  `executed_frames=36` (24 frames of travel, then 12 still frames).

That run also exposed a defect that the stubs could not: `get_execution`
returns no `executed_frames` while a job is running -- the field is written only
by `Finish` -- so a watchdog reading it saw zero forever and neither
`timeout_frames` nor `stall_frames` could ever trip. The executor now derives
the count from the room frame counter (`state.frame - start.frame`), which
advances on the same `Level.Update` that applies one input set.
`tests/test_executor.py::FrameOnly` reproduces the bridge's shape.

Bridge 0.3.3 closes the hole at the source instead: the running record carries
`executed_frames` and is rewritten on every tick, so the count is exact and the
room clock becomes a fallback for older bridges. The client prefers the reported
value whenever the key exists (`tests/test_executor.py::ClockAhead` pins that
precedence). Loaded 2026-11-17 and confirmed by `ping` reporting
`mod_version: 0.3.3`:

- A raw 30-frame run polled `executed_frames` at 0 → 9 → 14 → 19 → 24 → 29 while
  the job was still running, so the field is live rather than post-mortem.
- The same run showed why the clock fallback was loose: the start observation was
  frame 1014 and the job was accepted at frame 1017, three ticks later (`save_state`
  and `execute_frames` each take one). Derived counts were therefore biased high
  by however many calls preceded execution.
- `right:60` with `Abort(timeout_frames=8)` returned `ABORTED`, `at_frame=9`,
  `executed_frames=10`. The count is exact, but the decision lands on a sample:
  each poll costs a `get_state` and a `get_execution`, and both are serviced on
  frame boundaries, so the executor sees every other frame and reports the first
  one at or over the budget. Expect `at <= budget + 2` and `executed = at + 1`.
- The stall case reports the same way: `at_frame=37`, `executed_frames=38`
  against `stall_frames=12` after 24 frames of travel.
- The collaboration path is unchanged by the upgrade: three steps, all `LANDED`
  at 14 frames, `rejected=0`, `superseded=0`, zero pause calls.

Collaboration path, four steps with a 1.2s scripted planner:

- Every `VERIFY` carried the id of the `ANCHOR` before it; all four were
  `LANDED` at 14 frames.
- `pause_game`/`resume_game` were never called, and the room frame counter
  advanced from 72017 to 72486 across the run: the game kept running while the
  planner was thinking.
- `SESSION` reported `rejected=0`, `superseded=0`, `freezes=0`.

Unstable-world branches, forced with `still_for=0.8 --anchor-timeout 0.08`:

- Default `--on-unstable wait` ended on `NO_ANCHOR` with zero pause calls.
- `--on-unstable freeze` paused once, resumed before the first frame, and ran
  both steps to `LANDED` with 0.25s frozen. Pause and resume each happened
  exactly once.

A real DeepSeek run (`--collab --steps 2`, no exit room) reported `anchors=3`,
`steps=2`, `superseded=2`, `rejected=0`, `freezes=0`. The log reads as designed:
a 68-frame plan missed its band, the model was still thinking when she drifted
off and died, its plan arrived after the respawn anchor and was dropped unrun,
and the next plan died mid-step. `SUPERSEDED` cost frames but no rejection; a
plan that arrives after a death is wasted work, not a hazard.

With that established, the collaboration promise is checkable from the decision
log without watching the screen:

1. Every executed step is preceded by an `ANCHOR` event and followed by a
   `VERIFY` event carrying the same `anchor` id.
2. `STALE_PLAN` never appears, and `SESSION.rejected` is zero. A non-zero value
   means the anchor promise broke and should be treated as a defect, not a
   retry.
3. No `FREEZE` event appears in a room with static floors: the game must keep
   running while the model thinks.
4. `SUPERSEDED` is the only expected accounting entry, and `SESSION.standby_seconds`
   stays small for a player standing still.
5. On a moving platform, the run ends with `NO_ANCHOR` (default) or falls back to
   `FREEZE` with `--on-unstable freeze`; it must not spin.

Route replay was exercised live in room 7 on 2026-11-17 with a scripted planner
standing in for the model (1.0s per call):

- Step 1 came from the planner. Steps 2 and 3 reported `goal: replay learned-1`
  with `latency: 0.0`, all three `LANDED` at 14 frames, and the model was called
  exactly once.
- The promoted route recorded `start: [2600, -1480] -> end: [2600, -1480]`,
  `hits: 2`, `misses: 0`, `origin: session`.
- The first run showed `hits: 1`: the last step's outcome had no next plan
  waiting for it, so it was never drained into the book. `TeamSession.run` now
  drains once on the way out, which is why the second run counts both replays.

A replay is not a shortcut past the contract. It is sent as a normal plan with
the precondition pinned to the anchor, the success band at "last landing +- 6px"
and a frame budget of "route frames + slack", so a route that no longer fits its
ledge reports MISSED and loses a hit instead of quietly drifting.

Room 7 was cleared live on 2026-11-17, segment by segment, against the same
savestate:

- Steps 1-2 (spawn to `e3`): `restore_and_execute` ends at `(2738, -1592)` with
  `on_ground: true`, `dashes: 1`, `dead: false`. The savestate was written from
  that position so step 3 started where step 2 finished.
- Step 3 (`e3` to the exit): the run ends in room `8` at `(2719, -1704)`, resting
  on ground. The execution reports `interrupted` rather than `completed` because
  the room transition cancels the job mid-sequence -- expected, not a fault.

Two numbers from this room are worth keeping because they contradict the
reference sheet: a jump is 27px (`varJump` clamps `vy` at -105 for eleven
frames), and an up dash adds 42px. Together they are 69px, which is why the
80px between the two falling blocks cannot be crossed without the wall bounce.

### Deviation stop and traced replay, live (2026-11-19)

Run with the 0.3.4 bridge loaded (`ping` reports `expect: true`, `positions: true`,
`mod_version: 0.3.4`), standing on the floor of room 8 at `(2720, -1704)`,
`on_ground: true`, `dashes: 1`. Every step starts from the same Speedrun Tool
save slot, so the arcs are compared from an identical start rather than from
"roughly the same spot".

1. **The arc is real.** `execute_frames` with `right x20`,
   `capture_positions: true` returns `completed` after 20 frames and 20
   positions, ending at `(2747, -1704)`.
2. **A frame-7 lie stops on frame 7.** The same 20 frames are sent again with
   the captured arc, except that row 7 is moved 40px in x. The result is
   `status: deviated`, `executed_frames: 7`, and
   `deviation: {frame: 7, index: 7, expected: [2767, -1704], actual: [2727, -1704],
   offset: [40, 0], tolerance: 1.5}`. The remaining 13 frames are never sent.
3. **The check does not fire on its own.** The untouched arc, same tolerance,
   same start, completes all 20 frames with `deviation: null`. The room is
   translation-exact at this scale, so a stop here means the arc stopped
   fitting, not that 1.5px was too tight.
4. **Traced replay closes the loop.** The 20 captured frames were written as
   `logs/verify-routes.json` (`start: [2720, -1704]`, `end: [2747, -1704]`,
   20 `trace` rows) and run through `--collab --steps 1 --route-book`:
   `goal: replay verify-right20`, `latency: 0.0`, `expect: 20`, verdict
   `LANDED`, 20 frames, `planner_replays: 1`, `plan_failures: 0`,
   `kb_sections: 0` -- the model was never called.
5. **The guard protects the replay too.** Corrupting row 7 of the stored trace
   by 40px and replaying from the same start gives verdict `ABORTED`,
   `detail: deviated`, `frames: 7`, settled at `(2727, -1704)`: she stops on the
   floor instead of carrying the rest of the macro into the room. The book
   records `misses: 1`, `streak: 1`, and `end` moves to the settled
   `(2750, -1704)` of the earlier landed replay.

One gap this leaves: the replay's contract still only asks for "within 6px of
the recorded landing". The frame-by-frame promise is the `expect` array, and a
route recorded without one can still run all its frames past a changed room.

### The dash aim frame, live (2026-11-19)

Same room, same savestate, same start `(2720, -1704)` on the floor of room 8.
Each run is one `execute_frames` call with the trajectory recorder on, so the
speeds below are per-tick readings from the game, not arithmetic.

1. **The aim is read after the freeze, not on the press.** `[right+up+dash] x1`
   followed by `[right+up] x14` gives `vx, vy = (169.70, -169.70)` for nine
   consecutive `StDash` ticks -- a true up-right dash.
2. **Dropping the direction for one frame flattens it.** The same press
   followed by `[right + grab]` gives `(240, 0)`: horizontal. Nothing was
   broken; the chunk that covers the aim frame simply did not say up. This is
   the shape `agent/aims.py` now repairs, and the repaired version
   (`[right+up+dash]`, `[right+up] x1`, `[right] x14`) reproduces `(169.70,
   -169.70)` exactly.
3. **Super fires, in both halves of the window.** A jump on the first tick
   after the freeze and a jump eight ticks in both give `(260, -105)` in
   `StNormal` -- `SuperJumpH` and `SuperJumpSpeed`. The late one also has a
   dash in hand: the in-dash refill happened while she was still grounded.
4. **Hyper fires.** Crouch dash (`down+right+dash`, then `down` held into the
   jump) gives `(325, -52.5)` -- `SuperJumpH * DuckSuperJumpXMult` and
   `SuperJumpSpeed * DuckSuperJumpYMult`.
5. **The earlier "grab only climbs 3px" was geometry.** Holding grab on the
   left wall enters `StClimb`, waits out `ClimbNoMoveTime` (six ticks of no
   vertical movement), climbs 3.5 px to the top of the 8 px base and hops off
   it with `vy -120` (`ClimbHopY`). The grab channel was never the problem.

With super and an air dash both available, the right side of the pocket was
re-tried: horizontal dash, super at `2748`, jump held, up-right dash at
`-1712` reaches `(2804, -1741)` and stops against the falling block's left
face without entering `StClimb`, then falls back through the spike field. The
pocket is still not solved from here; that needs the 7 -> 7a route, not a
better input.

### Stance in the landing check (built 2026-11-19, in-game check pending)

The landing check had two postures, grounded and not, so hanging on a wall was
filed under "not" -- the same bucket as falling past the drop. `Success.stance`
adds the third one (`ground` / `climb` / `air`), and bridge 0.3.5 reports the
state machine name on `get_state` so the executor can read it.

Verified off-line (167 tests, ruff clean):

- `PlayerState.stance()` returns `climb` for `StClimb`, otherwise falls back to
  `on_ground`. A snapshot without a `state` key -- every bridge before 0.3.5 --
  parses with `state: ""` and degrades to the old two-way reading.
- A contract with `stance: "climb"` accepts a `StClimb` snapshot at the target
  coordinates and returns `not_climbing` for `StNormal` at the same coordinates.
  `stance: "ground"` returns `not_grounded` for the wall grab.
- A blind snapshot asked for `climb` returns `stance_unknown` rather than a
  guess.
- `stance: None` (the default, and what every existing route carries) changes
  nothing: the x/y bands decide, as before.
- `stance: "ground"` with `on_ground: false`, and `"air"` with `true`, are
  refused when the contract is built. `"climb"` is refused with neither: see
  the floor-level grab below.

### Stance, live (2026-11-19)

The 0.3.5 bridge was already loaded when this ran (`ping` reports
`mod_version: 0.3.5`, `player_state: true`), so no restart was needed. Same
savestate each time, room 8 on the floor at `(2716, -1704)`.

1. **The state machine now arrives.** `get_state` carries `state: "StNormal"`
   standing, and the same coordinates read `StClimb` while `left+grab` is held
   -- 60 of 78 trajectory rows, position `(2716, -1704)`, `v = (0, 0)`.
2. **A wall grab at floor level is grounded.** That `StClimb` row reports
   `on_ground: true`: the wall she is holding starts at the floor. So `climb`
   does not imply airborne, and the contract validator no longer pretends it
   does. This is the one place the live data overruled the off-line design.
3. **The landing snapshot keeps the grip.** `Finish` releases the input before
   it snapshots, so the question was whether the judged `after` still says
   `StClimb`. It does: all three runs below end with `state: StClimb` and
   `stamina 109.8` (drained by the hold), at `(2716, -1704)`.
4. **The executor judges by stance, not by the bands.** Running the same 52
   frames (`left x12`, `left+grab x40`) through `ExecutorAgent`:

   | contract | status | reason |
   |---|---|---|
   | `stance="climb"` | `SUCCEEDED` | `None` |
   | `stance="ground"` | `UNSATISFIED` | `not_grounded` |
   | `stance="air"` | `UNSATISFIED` | `not_airborne` |

5. **Holding a wall used to abort the step.** The first live run of those same
   three steps came back `ABORTED / stalled` at frame 13-14, not at 52: the
   still clock counted a grip as a plan that stopped moving, because `left`
   counted as intent to move and she was not moving. `grab` now holds the
   clock, so a step that ends on a wall reaches its landing at all. Walking
   into a wall without grab still stalls, and both shapes are pinned by tests.

STILL OPEN: `Standby.resting`, `SkillBook.match` and `LocalRetry.offer` still
require `on_ground`, so a step that ends on a wall publishes no anchor, is
never matched or retried, and the session waits out `anchor_timeout` instead of
continuing. The stance answers "was this a landing"; it does not yet answer
"can the next step be planned from up there". (Closed by 0.3.6 below: the
gates accept a climb, and the grip is kept so there is a wall to plan from.)

### Planning from a wall (built and confirmed in game 2026-11-19)

A climb landing has to survive the tick that ends the job. It does not: `Finish`
releases the virtual input, and the next `Update` drops her off the wall -- the
live check below shows `StClimb` becoming `StNormal` within 30ms of the job
ending. So relaxing the three grounded-only gates alone would have produced an
anchor that can never fire where it matters.

Bridge 0.3.6 adds `hold_after`: the buttons a finished job keeps pressed. The
executor derives it from the contract, `["grab"]` when the landing promises
`stance: "climb"`, and the route book records `end_stance` so a replayed wall
route carries the same promise.

Verified off-line (178 tests, ruff clean):

- `Standby.resting` accepts a wall grab and still rejects a slow fall. A
  `StClimb` snapshot anchors after the quiet window; the same snapshot with no
  state name (a bridge that cannot see walls) stays `SETTLING`.
- `SkillBook.match` and `LocalRetry.offer` accept a climb anchor and still
  refuse an airborne one, so a route can start on a wall instead of being a hit
  that is never used.
- `note()` promotes a step that ended on a wall, records `end_stance`, and
  still refuses one that ended mid-fall. A landing updates the stance; the
  field round-trips through the file, and a row written before it existed loads
  with `end_stance: None` and is judged by the bands.
- `ExecutorAgent._payload` asks for the grip only when the contract's stance is
  `climb`; a `ground` or unset stance sends an empty list, which the bridge
  reads as "release everything".
- End to end through the team session with a stub executor that keeps returning
  a `StClimb` snapshot: the second anchor is published, the model is asked a
  second time, and its context carries `footing.stance == "climb"`.

The client also ran a climb step against the still-loaded 0.3.5 bridge: no
error, the extra parameter is ignored, and the step behaves exactly as before
(`SUCCEEDED / climb`, `UNSATISFIED / not_grounded`, `UNSATISFIED /
not_airborne`). So the two sides deploy in either order and only the restart
turns the holding on.

To check after restarting Celeste:

1. `ping` reports `mod_version: 0.3.6` and `hold_after: true`.
2. A step ending in `left+grab` with `Success(stance="climb")` leaves her in
   `StClimb` after the job, not `StNormal` -- and stays there for a second.
3. The session publishes a second anchor from that state instead of waiting out
   `anchor_timeout`, which is what step three was for.

#### In game, after the restart

Celeste was restarted onto 0.3.6 and `ping` answered
`mod_version: "0.3.6"`, `hold_after: true`, `player_state: true`. All three
checks ran against the same save, room 8, in the pocket at the bottom left
(the one that has no exit; the geometry is a 16px wall stub at `x=2712` and a
taller wall at `x=2704` above it).

1. **The grip survives the job.** `execute_frames` with
   `left+grab x2, left+up+grab x10` and `hold_after: ["grab"]` reported
   `completed / 12`, and `after` was `StClimb`, `on_ground: false`, at
   `(2716, -1705)`. Sampled every 100ms for 1.2s she stayed `StClimb` at
   `(2716, -1705)` throughout, stamina draining 108.5 -> 94.3. The same wall
   with `hold_after: []` read `StClimb` in `after` and `StNormal` 30ms later --
   the exact 30ms drop this feature exists to remove.
2. **The session plans from the wall.** A 20-frame route
   (`left+grab x2, left+up+grab x18`, recorded live from `(2709, -1712)`,
   ending `StClimb` at `(2708, -1722)`) was put in the book with
   `end_stance: "climb"` and replayed by the real `ExecutorAgent` through
   `TeamSession`, `anchor_timeout` left at 8.0s:

   | t (s) | event |
   |---|---|
   | 0.33 | `ANCHOR 1` at `(2708, -1712)`, `still_for 0.23` |
   | 1.09 | `VERIFY 1` `LANDED`, `verified: true`, 20 frames, no deviation |
   | 1.11 | `ANCHOR 2` at `(2708, -1723)`, `still_for 0.23` |
   | 1.30 | `VERIFY 2` `LANDED` |

   The second anchor was published 20ms after the landing was verified. The
   session reported `anchors 2, standby_seconds 0.2, longest_standby 0.1` --
   not 8.0 -- and `planner_replays 1`, so the wall route was chosen by the book,
   not by the model. The one context the model was given (`ANCHOR 2`) carried
   `state: StClimb`, `on_ground: false` and `footing.stance: "climb"`.
3. **Release still drops her.** The step planned from that anchor
   (`grab x6`, no stance in its contract) sent an empty `hold_after`, and she
   was back on the pedestal at `(2708, -1712)`, `StNormal`, stamina refilled to
   110, when the session ended. The grip is a property of the promise, not of
   the button.

STILL OPEN: only a replayed route can promise `climb`. `Plan` has no stance
field, so a fresh model plan builds its contract through
`StepContract.for_plan`, whose `Success` carries an x band and no stance --
`_payload` then sends an empty `hold_after` and a plan that happens to end on a
wall drops her. Closing that needs a way for a plan to declare its landing
posture, which is a planner question, not a bridge one.

## Native CelesteTAS playback: room 8 is passable (2026-11-19)

`CelesteTAS 3.47.1` was already loaded -- it and `SpeedrunTool 3.29.2` sit in
`Mods` as zips and Everest unpacks them into `Mods/Cache`, so nothing had to be
installed. The mod takes `--tas <file>`, which settles the room from the other
side: let the mod play the reference run and watch the bridge.

Two launching details worth keeping:

- Direct `Celeste.exe` exits in under a second unless `steam_appid.txt`
  (`504230`) sits next to it -- `SteamAPI.RestartAppIfNecessary` hands off to
  Steam and Steam does not relaunch it.
- `console load 1` in a TAS file loads chapter 1 at its **start**, not at the
  saved checkpoint. A file trimmed to `#lvl_8` therefore plays its room-8
  inputs in room 1; the whole file has to be played.
- Playback starts on its own on the `--tas` path; no Studio needed.

Result: rooms 1 -> 8b in 1759 frames, no death, chapter finished (frame 2995,
no level loaded). Raw samples in `logs/tas-native.json`; 135 of them land in
room 8, entered at `(2717, -1672)` and left at `(3017, -1820)`.

| frame | x, y | state | vx, vy |
|---|---|---|---|
| 1624 | 2717, -1672 | `StNormal`, rising, 36 frames of door freeze | 0, -105 |
| 1672 | 2731, -1704 | `StDash`, 11 frames, **on the floor** | 240, 0 |
| 1683 | 2777, -1705 | `StNormal`, hyper out of that dash | **325, -52.5** |
| 1710 | 2897, -1734 | `StDash`, up dash against the right wall | 0, -240 |
| 1738 | 2938, -1793 | `StNormal`, hyper again off the ledge | **325, -52.5** |
| 1759 | 3017, -1820 | leaves for 8b | 280, -105 |

So the pocket is not a dead end: dash along the floor, hyper out of it, one more
jump, up dash on the right wall, land on the ledge at `y = -1792`, dash again,
hyper, and the exit is to the right.

The replay in `agent.tas_play` died at frame 41 because of how `Z` was read.
Aligning the samples against the file (observed frame - 34 = TAS row frame, from
the 325 super and the up dash) puts the dash three frames *into* the 14-frame
`14,R,Z` block, not on its first frame: `Z` is a crouch-dash mode, so it ducks
first and dashes once the duck is on the ground. Handing `down+dash` to the
block's first frame while she is still airborne turns it into a down-diagonal
dash, and the jump that follows leaves at 183 px/s instead of 325 -- five pixels
short of clearing the spikes. The fix, if we want our own replay to pass, is a
duck lead-in that keeps the frame count.
