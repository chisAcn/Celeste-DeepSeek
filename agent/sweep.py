"""Run several action sequences from one savestate and compare where they end.

Routing a room is a search over timings, not a single decode: "dash two frames
later" changes where a spring throws you. Each candidate runs through
restore_and_execute, so every attempt starts from the same savestate and no
execution is still in flight when the next one begins. Deaths are recorded,
not fatal.

    python -m agent.sweep --save \
        --actions "right:24;right,jump:21;right:14;right,dash:10;right:41" \
        --actions "right:24;right,jump:21;right:18;right,dash:10;right:37"
"""
import argparse
import asyncio
import uuid

from agent.client import BridgeClient
from agent.step import parse_actions


async def run(client, spec, settle, trace):
    execution_id = uuid.uuid4().hex
    actions = [{"buttons": a.buttons, "frames": a.frames} for a in parse_actions(spec)]
    result = await client.call("restore_and_execute", execution_id=execution_id,
                               actions=actions, trace_frames=trace)
    deadline = asyncio.get_event_loop().time() + 20
    while result.get("status") == "running":
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"execution {execution_id} never finished")
        await asyncio.sleep(0.03)
        result = await client.call("get_execution", execution_id=execution_id)
    points = [c["player"] for c in result.get("checkpoints") or []]
    # A landing is only visible after the arc finishes, so watch until the run
    # either dies or comes to rest instead of sampling once.
    after = await client.call("get_player")
    for _ in range(int(settle * 20)):
        if after.get("dead") or not after.get("position"):
            break
        if after.get("on_ground"):
            break
        await asyncio.sleep(0.05)
        after = await client.call("get_player")
    ys = [p["y"] for p in points if p.get("y") is not None]
    xs = [p["x"] for p in points if p.get("x") is not None]
    return {
        "frames": result.get("executed_frames"),
        "peak_y": min(ys) if ys else None,
        "max_x": max(xs) if xs else None,
        "end": after.get("position"),
        "dead": after.get("dead"),
    }


async def main(args):
    async with BridgeClient(32123, timeout=25) as client:
        if args.save:
            await client.call("save_state")
            print("savestate written")
        for spec in args.actions:
            row = await run(client, spec, args.settle, args.trace)
            flag = "DEAD" if row["dead"] else "alive"
            print(f"  peak_y={row['peak_y']} max_x={row['max_x']} "
                  f"end={row['end']} {flag}")
            print(f"    {spec}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actions", action="append", default=[])
    parser.add_argument("--save", action="store_true", help="write a savestate first")
    parser.add_argument("--settle", type=float, default=0.4)
    parser.add_argument("--trace", action="store_true",
                        help="record per-frame checkpoints (limits a run to 120 frames)")
    asyncio.run(main(parser.parse_args()))
