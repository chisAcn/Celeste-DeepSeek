"""Validate Speedrun Tool restore and first input on an installed bridge."""
import argparse
import asyncio
import json
import uuid
from pathlib import Path

from agent.client import BridgeClient
from agent.tools import ToolRegistry


def observed(state):
    return {key: value for key, value in state.items() if key != "frame"}


def trace(result):
    return [observed(result["before"]), *(observed(s) for s in result["checkpoints"])]


async def probe(mode):
    async with BridgeClient() as client:
        capabilities = await client.call("ping")
        if not capabilities.get("restore_and_execute"):
            raise RuntimeError("install bridge 0.2.2 and restart Celeste")
        if capabilities.get("tas_active"):
            raise RuntimeError("stop Studio playback before the Speedrun Tool test")
        tools = ToolRegistry(client)

        async def execute(buttons, frames, restore=False):
            method = tools.restore_and_execute if restore else tools.execute
            return await method(execution_id=str(uuid.uuid4()), trace_frames=True,
                                trace_platforms=mode == "platform",
                                actions=[{"buttons": buttons, "frames": frames}])

        if mode == "airborne":
            state = await client.call("get_state")
            player = state["player"]
            if (not player or player["dead"] or not player["on_ground"]
                    or player["dashes"] < 1 or not (await client.call("get_playability"))["playable"]):
                raise RuntimeError(f"room {state['room']['name']}: start on solid ground with a dash")
            launch = await execute(["up", "dash"], 5)
            player = launch["after"]["player"]
            if (launch["status"] != "completed" or not player or player["on_ground"]
                    or player["dead"]):
                raise RuntimeError("upward dash did not produce a playable airborne state")
        if not (await client.call("save_state"))["accepted"]:
            raise RuntimeError("Speedrun Tool rejected the save")
        try:
            frames = 8 if mode == "airborne" else 45
            baseline, *repeats = [await execute([], frames, restore=True) for _ in range(4)]
            alternate = await execute(["left"], frames, restore=True) if mode == "airborne" else None
            initial = baseline["before"]
            comparisons = [trace(baseline) == trace(run) for run in repeats]
            all_runs = [baseline, *repeats]
            complete = all(r["status"] == "completed" and len(r["checkpoints"]) == frames
                           for r in all_runs)
            if mode == "airborne":
                p = initial["player"]
                exercised = bool(p and not p["on_ground"] and not p["dead"] and
                                 observed(alternate["before"]) == observed(initial) and
                                 trace(alternate) != trace(baseline))
            else:
                samples = [state["platform_sample"] for state in trace(baseline)]
                exercised = (all(s and s["total"] == len(s["platforms"]) for s in samples)
                             and any(s != samples[0] for s in samples[1:]))
            return {"passed": complete and exercised and all(comparisons), "mode": mode,
                    "same_trace": comparisons, "exercised": exercised,
                    "baseline": baseline, "repeats": repeats, "alternate": alternate}
        finally:
            async with BridgeClient() as cleanup:
                try:
                    await cleanup.call("load_state")
                finally:
                    await cleanup.call("clear_state")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["airborne", "platform"])
    parser.add_argument("--output", type=Path, default=Path("logs/live-atomic-restore.json"))
    args = parser.parse_args()
    report = asyncio.run(probe(args.mode))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print({key: report[key] for key in ("passed", "mode", "same_trace", "exercised")})
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
