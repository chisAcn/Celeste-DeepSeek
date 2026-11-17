# Live validation — 2026-11-15

Backend: real Everest, Prologue. No player coordinates, abilities or physics were modified for these tests.

| Case | Evidence | Result |
|---|---|---|
| Jump | 8 frames; y 120 -> 106, vy -105, grounded true -> false | Passed |
| Climb | right+grab+up, 20 frames; y 168 -> 158; stamina 110 -> 99.393936 | Passed |
| Natural death | 90-frame left request interrupted at frame 24; y 198, dead=true | Passed |
| Respawn | next observation player=null, later alive at x=-32,y=136; subsequent 384-frame sequence accepted and completed | Passed |
| Room transition | requested 594 frames, interrupted at 525 near x398; subsequent execution started in room 1 at x407 and completed 168 frames | Passed |
| Additional transition | room 1 -> room 2, bridge remains responsive | Passed |
| Room reload | reset_room acknowledged; player returned to x=-32,y=136 | Passed; not equivalent to death |
| Dash | Reached visible DASH tutorial in room 3; right+up+dash submission rejected with -32602 / not playable while tutorial freezes game | BLOCKED: bridge eligibility rejects tutorial freeze |
| Dash in playable room | Room `1`, `up+right+dash` for 8 frames. Position (19,144) → (39,124), velocity (169.71,−169.71), charges 1 → 0. Execution `119ca0d2-91a9-4c18-aa3d-c4e3fda468cf` | Passed |

Observed limitation: actions during a cutscene can complete without useful movement. Current schema does not expose cutscene/player-control state; add explicit eligibility before claiming robust autonomous recovery. Real-time simulation continues between requests; an airborne final state may die after a successful execution response. This is not deterministic TAS validation.

Detailed local observations: logs/live-validation.jsonl and logs/live-reset.json (ignored by Git). The initial jump was observed directly in the test output; later polling overwrote the temporary jump file, so this table preserves that result.

Follow-up: cutscene eligibility guard added using locally verified Player.InControl and Level.InCutscene APIs; Release build passed (0 warnings/errors). The guard has not been live-tested. Tutorial freeze needs a separate input/clock design.


### Live save/restore result

On 2026-11-15, Everest loaded bridge 0.2.0 with both optional interfaces bound. In room 1, Speedrun Tool restored a grounded state at (19, 144), including dash charge and velocity. Two eight-frame up/right/dash executions had identical player and room samples on all eight updates, ending at (39, 124) with zero dash charges. A third restore followed by eight neutral frames began at the same observed state and reached a different endpoint. The test restored the starting point again and cleared the private slot.

Evidence: logs/live-state-restore.json and logs/live-state-branch.json. Studio playback was inactive throughout. Airborne savepoints, dynamic entities and loading a paused Studio breakpoint still require their own live cases.

### Airborne and Studio follow-up

The airborne test saved and loaded successfully. The first continuation started at (47, 116) with velocity (169.70563, -169.70563), and the first observation after load matched that state. The second continuation started one Level.Update later at (49, 114), so its eight-frame trace diverged. Separate realtime load and execute calls cannot validate exact airborne continuation in this case. See logs/live-state-airborne.json.

With Studio playback inactive, load_tas_state returned -32602 with "pause a supported TAS first", as expected. A real paused savestate and a moving platform trajectory remain unverified. The current bridge samples only player and room fields. A platform test requires a TAS entity watch or separate platform telemetry to compare the same entity position and movement phase before and after restore.

### Moving platform restore in room 6b

With bridge 0.2.1 and Speedrun Tool, room 6b exposed four JumpthruPlatform entities and two ZipMovers. ZipMover ordinal 0 returned to (2096, -1152) after restore and reached (2128, -1152) during each 45-update neutral-input run. Each run had 18 distinct platform samples. All six platform samples matched on all 45 paired updates. The final restore was accepted and the private slot was cleared. Raw evidence: logs/live-platform-6b-restore.json.

### Studio paused breakpoint restore

Bridge 0.2.1 accepted `load_tas_state(frame=30)` while CelesteTAS was active and paused. The player changed from room 6b at (2008, -1128), vx=90, to room 6a at (2003, -1128), vx=-90. Playback stayed paused and the bridge update counter stayed at 102636. Both ZipMover positions matched across observations. The JumpthruPlatform enumeration order changed across the room boundary, so ordinal-only matching is unsuitable there. Raw evidence: logs/live-studio-restore.json.

### Atomic airborne restore

Bridge 0.2.2 passed in room 6b from an airborne point at (2045, -1148) with vy=-240. Three repeats of the same eight-frame input matched the baseline at the restored starting state and every update. Left input from the same state produced a different horizontal velocity. The platform probe matched in all repeats but did not observe platform movement, so its movement coverage gate failed. Evidence: logs/live-atomic-airborne.json and logs/live-atomic-platform.json.

The atomic platform probe subsequently passed in room 6b with the player on an active ZipMover. All three 45-update repetitions matched the baseline starting state and every player, room and platform checkpoint. Platform movement was observed, satisfying the coverage check. Evidence: logs/live-atomic-platform-onboard.json.

### Phase 5 real-game candidate search

Bridge 0.2.3 passed its first complete live search in room 6b. Seven candidates were evaluated from the same saved start. The selected route reached the target tolerance and its independent replay matched the sampled player and platform trace. Evidence: logs/live-search-6b.json.

### Phase 5 stable landing and Phase 6 skill capture

The live search now supports a settling segment and requires an airborne sample followed by consecutive living, grounded samples within the target radius. Initial beam/fixed/random comparisons from shared saves did not find a stable landing at their selected targets. At a fixed lower ledge target (2057, -1128) in room 6b, the beam search found and verified a two-segment landing with three matching replays. The skill was stored in logs/live-skills.sqlite3. Evidence: logs/live-landing-6b-lower.json.
