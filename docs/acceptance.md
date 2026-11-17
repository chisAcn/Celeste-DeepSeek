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
