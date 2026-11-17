# Celeste TAS Agent

Python GPT planner + local Everest bridge, implementing Phase 0–3 foundations.

## Setup

Python 3.12+: create a virtual environment, then `pip install -e ".[dev]"`.
Run `python -m agent.main` for the offline flat Mock scenario.
Run `pytest -q` and `ruff check .` for verification.

Build real Mod: `./scripts/build_bridge.ps1 -CelesteDir 'F:\steam\steamapps\common\Celeste'`.
Copy the generated Release/net8.0/CelesteAgentBridge.dll and everest.yaml into Celeste/Mods/CelesteAgentBridge, then restart the game.
Enter a playable room and run `python -m agent.main --real --mode manual`.
For GPT, set OPENAI_API_KEY and OPENAI_MODEL in environment and use `--mode gpt`. Environment files are not automatically loaded. API billing is separate from Codex.

Manual plan example:
```json
{"goal":"move right","reason":"test movement","actions":[{"buttons":["right"],"frames":10}],"expected_x_min":0,"expected_x_max":10000}
```

## Status and limitations

- Real Mod compiles against locally installed Celeste/Everest assemblies: zero warnings/errors.
- Tests cover protocol, bounds, duplicate execution IDs, malformed requests, timeouts, disconnects, execution polling and Mock end-to-end completion.
- Mod installed and loaded in the real game. Verified ping, live state, one idle frame, and ten right frames in Prologue room 0: x=58 to x=70, actual count=10. Jump/dash/grab, death/respawn and room transitions remain UNVERIFIED.
- No paid GPT call or real room completion verified. Phase 0–3 acceptance is not yet complete.
- Mock is a flat protocol fixture, not Celeste physics. TAS integration, deterministic stepping and full-state restoration are not implemented.
- Current planner has bounded steps/retries and an allowlisted tool registry; scalar observations lack geometry. Full state-machine recovery and richer observation remain follow-up work.

The bridge binds localhost:32123. One active execution at a time; each action replaces the held button set, [] releases all. Terminal execution releases injected input and restores manual controls. Disconnect, scene/room change, pause and death interrupt execution. Frame count measures Level.Update calls, not guaranteed physics steps. Escape/pause remains available. Do not run multiple controllers concurrently.

Only source is published. Game binaries, logs, credentials and saves are ignored. Python CI does not require Celeste; C# builds locally against legal installed assemblies.

See docs/acceptance.md and docs/protocols.md.

## Codex-authorized playtest

Install the Codex CLI and run `codex login` with ChatGPT once. An existing
ChatGPT login shown by `codex login status` can be reused. The playtest uses
that login without requiring an OpenAI API key or storing a project token.
It sends game observations and recent action outcomes to Codex for planning.

```powershell
python -m agent.main --mode codex --steps 1
python -m agent.main --real --mode codex
```

The first command uses the simulated bridge. For the second, open a playable
room in Celeste with the Everest bridge loaded. Codex proposes actions in a
read-only session and the Agent validates and executes them through the
bridge. The default budget is three steps, adjustable with `--steps`.
`STOPPED` can mean the budget ended, while `SUCCESS` requires the bridge to
report completion. See `logs/decisions.jsonl` for the executed plans.

For an exit trial, start at the entrance of the desired room and run:

```powershell
python -m agent.main --real --mode codex --settle --exit-room 6b --steps 6
```

`--settle` waits up to three seconds for a stable grounded observation between
plans. `--exit-room` confirms the starting room and also accepts a live player
in a different room as success. The bridge supplies platform samples when
available. It excludes tile terrain.

## DeepSeek playtest

Set `DEEPSEEK_API_KEY` in the environment and run the simulated bridge or the
real game. `DEEPSEEK_MODEL` defaults to `deepseek-chat` and `DEEPSEEK_BASE_URL`
to `https://api.deepseek.com`.

```powershell
python -m agent.main --mode deepseek --steps 1
python -m agent.main --real --mode deepseek --settle --exit-room 6b --steps 6
```

DeepSeek plans through chat completions with JSON output; each reply is
validated against the bounded action-plan schema before execution. The mode
shares the Codex stale-plan guard: a plan is skipped without any input when
the grounded state, dash count or position changed while the model was
thinking. The default budget is three steps, adjustable with `--steps`, and
`--tas-prior` supplies optional action hints the same way as `--mode gpt`.

Replay-verified routes recorded by the Phase 6 skill workflow can be injected
as planner hints. The planner receives each matching skill's start/end
positions and exact action sequence, and is told to prefer replaying a skill
when its start matches the current grounded position. `--success-room` narrows
`--exit-room` so only the forward destination room counts as success.

```powershell
python -m agent.main --real --mode deepseek --settle --exit-room 6b --success-room 6c --steps 12 --skills logs/phase6-live-acceptance.sqlite3
```

With bridge 0.2.4 or newer, `--pause-planning` freezes the game while the
model thinks and resumes right before execution. This removes observation
drift on moving platforms (the main source of `STALE_PLAN` rejections) and
pairs well with `--settle`.

## Room inspection

The bridge can describe the game instead of only moving Madeline. Every probe is
read-only and safe to call while playing:

```shell
python -m agent.inspect --what player --internals   # sub-pixel state, timers, raw fields
python -m agent.inspect --what level                # chapter, timers, freeze frames, dialogue
python -m agent.inspect --what room                 # neighbours, spawns, triggers, doorways
python -m agent.inspect --what entities --fields    # entities with their own fields
python -m agent.inspect --what collision            # solid rectangles + every collidable object
python -m agent.inspect --what tiles                # ASCII map, one char per 8x8 tile
python -m agent.inspect --what menu,save            # menus and save-file progress
python -m agent.inspect --what capture --kind gameplay   # PNG of the gameplay layer
python -m agent.room_map --objects                  # labelled map + object bounds + doorways
```

`agent.room_map` prints the room with a world-coordinate ruler, the player's current
tile, every collidable object with its world bounds, and the neighbouring room on each
side — usually the fastest way to answer "where is the exit".

`get_collision` reports `complete: false` when terrain or objects were truncated, so a
partial snapshot is never mistaken for an empty room. Terrain is read from the engine's
own `SolidTiles` collider; `coverage.source` says which path was used and
`coverage.solids` echoes the diagnostic, because the tile char arrays are indexed in a
per-level space that can read empty without raising. Screenshots are two-phase
(`capture` then `capture_result`) because pixels can only be read at the end of a render
pass. `trajectory_start` / `trajectory_stop` record one row per update tick for
simulator calibration.

## Train from Celeste TAS

The local action prior learns which button combinations tend to follow a previous
combination. It trains on 1A and 1B, then tests held-out 2A against an unconditional
frequency baseline. The parser keeps gameplay-room actions, expands bounded
`Repeat` blocks and breaks the prediction context at unsupported inputs.
Use Celeste Studio to flatten scripts with `Read` or `Play` before using them.

```powershell
git clone https://github.com/VampireFlower/CelesteTAS.git data/tas-source
git -C data/tas-source checkout 49c21de0c9bb9106aba3569df9faf919a0a932f5
python -m agent.tas_training data/tas-source
python -m agent.main --real --mode gpt --tas-prior data/tas-training/action-prior.json
```

The trainer writes the dataset, model and holdout report under `data/tas-training`.
The GPT integration passes optional action hints and filters out dash hints when
the player has no dash available. The metric measures held-out action prediction.
Game-state imitation requires synchronized TAS playback and state observations.

For a local archive without Git metadata, select training and holdout files
explicitly. The report records the SHA-256 of each selected file. This run
includes Chapter 6B in training and reserves selected Chapter 7 and 8 routes
for evaluation:

```powershell
$routes = @(1..6 | ForEach-Object {
    foreach ($side in 'A','B','C') {
        if ($_ -ne 5 -or $side -ne 'A') { "$_${side}.tas" }
    }
})
python -m agent.tas_training 'E:\pw\CodeX\Celeste-TAS-data\CelesteTAS-master' --output data/tas-training-local --train @routes --holdout 7A.tas 7B.tas 7C.tas 8B.tas 8C.tas
python -m agent.main --real --mode codex --settle --exit-room 6b --steps 6 --tas-prior data/tas-training-local/action-prior.json
```

Start the playtest from the 6b entrance. The prior supplies action suggestions
to Codex. The holdout score measures button combinations, not room completion.

The PICO-8 Celeste Classic database uses a separate input format and timing.
Train it separately, holding out the `classic` and `classic2` folders:

```powershell
python -m agent.classic_training 'E:\pw\CodeX\Celeste-TAS-data\tasdatabase-master'
```

The outputs are under `data/tas-training-classic`. Duplicate decoded input
sequences are removed before training. Keep using the main-game prior for
Everest 6b: the Classic model scored lower on the same main-game holdout,
and its frame counts are in the source game's timing.

`CelesteTAS-EverestInterop-master` contains the TAS tooling source. To
collect state-conditioned examples, add `ExportGameInfo, dump.txt` before
the gameplay section of a TAS in Celeste Studio, play it in Celeste, and
convert the exported tab-separated dump:

```powershell
python -m agent.interop_dataset 'E:\path\to\dump.txt'
```

The converter writes `data/interop-training/transitions.jsonl`. Each action
belongs to the later frame because the exporter records state after the
update. Missing frames and room transitions break the pairing. Keep entire
recordings separate for training and evaluation.

## Phase 7 offline evaluation

Run the evaluator from the repository root with the Phase 6 training, comparison
and trajectory logs in `logs/`. Pass `--logs` to use another directory. These
recordings are local experiment data and are excluded from source control.

```powershell
python -m agent.evaluate
```

The report defaults to `logs/phase7-evaluation.json`. The command exits with
status 1 on a benchmark mismatch or 2 when its input cannot be read.
To view the report with Celeste closed, use Node.js 22.12 or newer and run:

```powershell
pip install -e ".[dashboard]"
npm --prefix dashboard ci
npm --prefix dashboard run build
python -m uvicorn agent.dashboard:app --host 127.0.0.1 --port 8000
```

Open [the local Dashboard](http://127.0.0.1:8000). Set
`CELESTE_EVALUATION_REPORT` before starting the server to view another exported
evaluation. The player state and timeline come from recorded samples. Optional
screenshots, token usage and API costs appear when the source report includes
them. Candidate retries count additional search trials from the saved start.

