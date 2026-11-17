"""Execute one action list with frame tracing and print the trajectory.

The bridge records a checkpoint per executed update, which is the only way to
see *where* a plan dies instead of only where it ended up. Useful for measuring
a gap or a spike wall before writing it into a skill or a prompt hint.

    python -m agent.trace_run --actions "right,jump:10;right:25"
    python -m agent.trace_run --actions "right,dash:12" --wait-mover 0:2157
"""
import argparse
import asyncio
import uuid

from agent.client import BridgeClient
from agent.protocol import ActionSequence, FrameAction
from agent.tools import ToolRegistry


def parse_actions(spec):
    actions = []
    for part in spec.split(";"):
        buttons, _, frames = part.partition(":")
        actions.append(FrameAction(buttons=[b for b in buttons.split(",") if b],
                                   frames=int(frames or 1)))
    return actions


async def wait_mover(client, ordinal, target, axis="x"):
    for _ in range(400):
        platforms = (await client.call("get_platforms"))["platforms"]
        movers = {p["ordinal"]: p for p in platforms if p["type"].endswith("ZipMover")}
        if ordinal in movers:
            value = movers[ordinal][axis]
            if (axis == "y" and value <= target) or (axis == "x" and value >= target):
                return value
        await asyncio.sleep(0.03)
    return None


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actions", required=True)
    parser.add_argument("--pre", help="actions to run first, e.g. to walk back to a spot")
    parser.add_argument("--pre-if-x-lt", type=float,
                        help="only run --pre when the player is left of this x")
    parser.add_argument("--wait-mover", metavar="ORDINAL:X")
    parser.add_argument("--wait-mover-y", metavar="ORDINAL:Y")
    parser.add_argument("--settle", type=float, default=0.0,
                        help="seconds to idle before executing")
    args = parser.parse_args()
    sequence = ActionSequence(execution_id=uuid.uuid4().hex, trace_frames=True,
                              actions=parse_actions(args.actions))
    async with BridgeClient(32123, timeout=5) as client:
        registry = ToolRegistry(client)
        if args.pre:
            # A death respawns the player, so wait until input is accepted again.
            for _ in range(60):
                state = await registry.invoke("observe_game")
                playable = (await client.call("get_playability"))["playable"]
                if state["player"] and not state["player"]["dead"] and playable:
                    break
                await asyncio.sleep(0.1)
            player = (await registry.invoke("observe_game"))["player"]
            if args.pre_if_x_lt is None or player["x"] < args.pre_if_x_lt:
                pre = ActionSequence(execution_id=uuid.uuid4().hex,
                                     actions=parse_actions(args.pre))
                await registry.invoke("execute_actions", **pre.model_dump())
                await asyncio.sleep(0.3)
        if args.wait_mover:
            ordinal, target = args.wait_mover.split(":")
            reached = await wait_mover(client, int(ordinal), float(target))
            print(f"mover {ordinal} at x={reached}")
        if args.wait_mover_y:
            ordinal, target = args.wait_mover_y.split(":")
            reached = await wait_mover(client, int(ordinal), float(target), axis="y")
            print(f"mover {ordinal} at y={reached}")
        if args.settle:
            await asyncio.sleep(args.settle)
        before = (await registry.invoke("observe_game"))["player"]
        print(f"before ({before['x']},{before['y']}) dashes={before['dashes']} "
              f"{'ground' if before['on_ground'] else 'air'}")
        result = await registry.invoke("execute_actions", **sequence.model_dump())
        print(f"status={result['status']} frames={result['executed_frames']}")
        for index, checkpoint in enumerate(result["checkpoints"], 1):
            p = checkpoint["player"]
            print(f"  f{index:02d} ({p['x']:7.1f},{p['y']:7.1f}) vx={p['vx']:6.1f} "
                  f"vy={p['vy']:6.1f} {'ground' if p['on_ground'] else 'air':6s} "
                  f"dash={p['dashes']}{' DEAD' if p['dead'] else ''}")
        after = result["after"]["player"]
        print(f"after ({after['x']},{after['y']}) dead={after['dead']} "
              f"room={result['after']['room']['name']}")


if __name__ == "__main__":
    asyncio.run(main())
