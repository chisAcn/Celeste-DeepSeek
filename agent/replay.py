"""Bounded input replay. Checkpoints are execution boundaries, not save states."""
import argparse
import asyncio
import json
import math
import uuid
from pathlib import Path

from pydantic import Field

from agent.client import BridgeClient
from agent.protocol import (
    ActionSequence,
    ExecutionResult,
    FrameAction,
    GameState,
    Schema,
)
from agent.tools import ToolRegistry


class Recording(Schema):
    versions: dict[str, str]
    initial: GameState
    sequences: list[ActionSequence] = Field(default_factory=list)
    results: list[ExecutionResult] = Field(default_factory=list)

    def export(self, path: str):
        Path(path).write_text(self.model_dump_json() + "\n", encoding="utf-8")


async def record(client, sequences, versions):
    reset = await client.call("reset_room")
    if reset.get("requested") is True:
        async with asyncio.timeout(8):
            first_frame = None
            while True:
                initial = GameState.model_validate(await client.call("get_state"))
                if first_frame is None:
                    first_frame = initial.frame
                player = initial.player
                playable = (await client.call("get_playability"))["playable"] if (
                    versions.get("playability") == "true") else True
                if (initial.frame > first_frame and player and player.on_ground
                        and not player.dead and not initial.room.completed and playable):
                    break
                await asyncio.sleep(0.05)
    else:
        initial = GameState.model_validate(reset)
    recording = Recording(versions=versions, initial=initial)
    for sequence in sequences:
        seq = sequence.model_copy(update={"execution_id": str(uuid.uuid4())})
        result = ExecutionResult.model_validate(await ToolRegistry(client).execute(**seq.model_dump()))
        recording.sequences.append(seq)
        recording.results.append(result)
        if result.status == "interrupted" or result.after.room.completed:
            break
    return recording


def compare(reference: Recording, actual: Recording, tolerance: float = 1e-6):
    if tolerance < 0:
        raise ValueError("negative tolerance")
    errors = []
    maximum_position = maximum_velocity = 0.0
    if reference.versions != actual.versions:
        errors.append("versions")
    if len(reference.results) != len(actual.results):
        errors.append("length")
    states = [(reference.initial, actual.initial)] + [
        (a.after, b.after) for a, b in zip(reference.results, actual.results)]
    for index, (a, b) in enumerate(states):
        mismatch = a.room != b.room or (a.player is None) != (b.player is None)
        if a.player and b.player:
            p, q = a.player, b.player
            position = math.hypot(p.x-q.x, p.y-q.y)
            velocity = math.hypot(p.vx-q.vx, p.vy-q.vy)
            maximum_position = max(maximum_position, position)
            maximum_velocity = max(maximum_velocity, velocity)
            mismatch |= position > tolerance or velocity > tolerance
            mismatch |= any(getattr(p, k) != getattr(q, k) for k in
                            ("dead", "on_ground", "dashes", "stamina"))
        mismatch |= a.frame-reference.initial.frame != b.frame-actual.initial.frame
        if index:
            left, right = reference.results[index-1], actual.results[index-1]
            mismatch |= (left.status, left.executed_frames) != (right.status, right.executed_frames)
        if mismatch:
            errors.append(f"checkpoint:{index}")
    return {"matches": not errors, "first_mismatch": next(iter(errors), None),
            "max_position_error": maximum_position, "max_velocity_error": maximum_velocity,
            "scope": "sampled execution boundaries; not proof of full determinism"}


async def replay(client, reference):
    actual = await record(client, reference.sequences, reference.versions)
    report = compare(reference, actual)
    first_frame_mismatch = None
    traced = False
    for index, (left, right) in enumerate(zip(reference.results, actual.results)):
        if not reference.sequences[index].trace_frames:
            continue
        traced = True
        if (len(left.checkpoints) != left.executed_frames or
                len(right.checkpoints) != right.executed_frames or
                len(left.checkpoints) != len(right.checkpoints)):
            first_frame_mismatch = {"execution": index, "reason": "checkpoint count"}
            break
        for frame, (a, b) in enumerate(zip(left.checkpoints, right.checkpoints), 1):
            if reference.sequences[index].trace_platforms:
                samples = (a.platform_sample, b.platform_sample)
                if any(s is None or s.total != len(s.platforms) for s in samples):
                    first_frame_mismatch = {"execution": index, "frame": frame,
                                            "reason": "missing or truncated platform telemetry"}
                    break
                if samples[0] != samples[1]:
                    first_frame_mismatch = {"execution": index, "frame": frame,
                                            "reason": "platform state"}
                    break
            if (a.player, a.room, a.frame - left.before.frame) != (
                    b.player, b.room, b.frame - right.before.frame):
                first_frame_mismatch = {"execution": index, "frame": frame}
                break
        if first_frame_mismatch:
            break
    if traced:
        report["first_frame_mismatch"] = first_frame_mismatch
        report["matches"] &= first_frame_mismatch is None
        report["scope"] = "observed state at each executed update, including requested platforms"
    return actual, report


async def live_smoke(output: Path, trials: int, trace_platforms: bool = False):
    async with BridgeClient(timeout=3) as client:
        bridge = await client.call("ping")
        if bridge.get("backend") != "everest-realtime":
            raise RuntimeError("expected the Everest game bridge")
        if trace_platforms and not bridge.get("platform_telemetry"):
            raise RuntimeError("the running bridge does not support platform telemetry")
        state = GameState.model_validate(await client.call("get_state"))
        if not state.room.name or not state.player:
            raise RuntimeError("enter a playable room before starting the replay")
        versions = {"protocol": state.protocol_version, "backend": bridge["backend"],
                    "game": bridge.get("game_version", "unknown"),
                    "mod": bridge.get("mod_version", "unknown"),
                    "playability": str(bool(bridge.get("playability"))).lower()}
        sequence = ActionSequence(execution_id="live-smoke",
                                  trace_frames=bool(bridge.get("frame_checkpoints")),
                                  trace_platforms=trace_platforms, actions=[
            FrameAction(buttons=["up", "right", "dash"], frames=8),
        ])
        reference = await record(client, [sequence], versions)
        runs = [reference]
        reports = []
        for _ in range(trials):
            if runs[-1].results[-1].after.room.name != reference.initial.room.name:
                break
            actual, report = await replay(client, reference)
            runs.append(actual)
            reports.append(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(run.model_dump_json() + "\n" for run in runs), encoding="utf-8")
    baseline = reference.results[-1]
    before, after = baseline.before.player, baseline.after.player
    movement_observed = bool(before and after and (before.x, before.y) != (after.x, after.y))
    dash_consumed = bool(before and after and after.dashes < before.dashes)
    passed = (movement_observed and dash_consumed and len(reports) == trials
              and all(report["matches"] for report in reports)
              and all(run.results[-1].status == "completed" and
                      run.results[-1].executed_frames == 8 for run in runs))
    report = {"passed": passed, "room": reference.initial.room.name,
              "requested_replays": trials, "comparisons": reports, "versions": versions,
              "movement_observed": movement_observed, "dash_consumed": dash_consumed}
    output.with_suffix(".report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Repeat a short input from an Everest room reset")
    parser.add_argument("--output", type=Path, default=Path("logs/live-replay.jsonl"))
    parser.add_argument("--trials", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--trace-platforms", action="store_true")
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(live_smoke(args.output, args.trials, args.trace_platforms)) else 1)

