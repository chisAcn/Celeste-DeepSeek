# Phase 4–7 implementation status

This is a partial implementation, not phase acceptance.

- Phase 4: recording schema, JSONL export, reset/replay, sampled position/velocity and discrete-state comparison. Live reset and replay were exercised in room 1. Runtime version reporting remains incomplete. No full-state restoration or determinism claim.
- Phase 5: abstract beam search, A* and one-step MPC. Batch evaluation, real-game branch validation, benchmark baselines and persisted successful searches remain outstanding.
- Phase 6: verified landing extraction, version-scoped retrieval, two-skill route composition, per-trial outcomes, SQLite and JSONL trajectories, and assisted versus unassisted beam search. The single-skill and two-skill live comparisons passed in room 6b.
- Phase 7: offline room 6b benchmark runner, JSON export and FastAPI/React trajectory dashboard. The runner independently checks reported outcomes, skill boundaries, replay traces and JSONL archive entries. The Dashboard uses recorded data and exposes available screenshot and API usage fields.

Regression coverage added for sampled replay divergence and abstract routing. The live smoke test below covers one short input sequence.

## Real-game replay smoke test

Run `python -m agent.replay` with the Everest bridge loaded and a playable room open. This resets the current room, records ten right-input frames and compares three replays by default. Logs are written to `logs/live-replay.jsonl` and `logs/live-replay.report.json`.

On 2026-11-15, the bridge reported ten executed frames for all four room 1 runs, but the player did not move. The three comparisons had zero observed position and velocity error at the two sampled boundaries. The bridge reported protocol 1.0 and Everest realtime mode. The installed bridge did not report game or mod version numbers. Full determinism and arbitrary state restoration remain unverified.


## Extended determinism and restore audit

Room 1, Everest realtime, protocol 1.0. Across 18 input cases with one reference and three repeats each, 53 of 54 comparisons matched exactly. One 30-frame left run diverged at checkpoint 1 with zero position error and a horizontal velocity difference of 16.666698. All tested endpoints stayed at (19, 144); frame acknowledgements alone did not establish movement control. The smoke CLI now requires observed displacement to pass.

The installed bridge has no save/load-state API. Its reset calls Level.Reload, and ping reports tas=false. Neither CelesteTAS nor Speedrun Tool was present in the inspected Mods directory. Arbitrary mid-run restoration could not be exercised. The CelesteTAS upstream README identifies Speedrun Tool as its savestate provider.

Raw outputs: logs/live-determinism.json and logs/live-determinism-alternate.json.

## Phase 6 skill workflow

Import an existing successful landing report with three matching replays. Use the same game and mod build identifier during import and search. The bridge currently does not supply that identifier automatically.

```powershell
python -m agent.memory logs/live-landing-6b-lower.json --name lower-ledge --game-version YOUR_BUILD --memory logs/phase6.sqlite3
python -m agent.live_search --target 2057 -1128 --compare-skills --game-version YOUR_BUILD --memory logs/phase6.sqlite3 --radius 18 --frames 12 --depth 2 --budget 21 --settle 45 --min-segments 2 --repeats 3
```

`--use-skills` runs the assisted arm alone. The comparison JSON includes both arms' trial count, target success and replay verification. Both arms share the same restored start and candidate budget. A skill is eligible when the restored room, player and complete platform observations match its recorded start. A two-skill candidate requires the first skill's recorded endpoint to match the second skill's precondition. The whole candidate runs as a speculative save-slot trial, and its observed boundary and endpoint must match before the search accepts it. The trace compares sampled observations and can miss hidden game state.

Passing `--game-version` to live search stores candidate and verification trajectories in SQLite. Its JSONL snapshot defaults to the memory file's basename with a `.jsonl` extension. Set `--trajectory-jsonl` to select another output. Use `--skill-revision` for a changed skill definition during live extraction and `--revision` during offline import. The importer preserves attempt history when re-importing the same definition.

On 2026-11-16, bridge 0.2.3 ran both arms from the room 6b entrance at (2016, -1128), with a shared target of (2057, -1128), radius 18 and a budget of 21 candidates per arm. Ordinary search used seven evaluations. Assisted search used two and selected the newly extracted entrance skill. Both arms landed at (2055, -1128), and each winner matched all three verification replays. The training run used seven evaluations before the comparison. These counts exclude verification replays. The comparison report is in `logs/phase6-live-comparison.json`. SQLite and JSONL each contain 25 trajectories across training and comparison.

The two-skill case used the same entrance and the intermediate landing at (2055, -1128). The continuation landed on a moving ZipMover at (2141, -1152). Its final four grounded samples spanned nine pixels, so a radius of three rejected the stable-landing criterion even though the composition replayed exactly. With radius ten and a budget of 21 candidates per arm, the assisted arm selected both skills in two evaluations. The ordinary arm exhausted its budget without reaching the target. The 120-frame route matched all three independent verification traces, including the observed handoff. Training and verification replays are excluded from the candidate counts. Reports are in `logs/phase6-pair-training.json`, `logs/phase6-pair-comparison.json` and `logs/phase6-pair-comparison-radius10.json`.

