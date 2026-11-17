"""Run one action segment and report where it left the player.

Turns the bridge into a REPL for routing: execute, look, adjust. Deaths respawn
at the room's start point, so a failed probe costs about a second.

    python -m agent.step --actions "right:26"
    python -m agent.step --actions "right,jump:26" --wait-mover-x-le 0:2100
    python -m agent.step --actions "right:30" --probe
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


async def mover(client, ordinal):
    platforms = (await client.call("get_platforms"))["platforms"]
    for p in platforms:
        if p["type"].endswith("ZipMover") and p["ordinal"] == ordinal:
            return p
    return None


async def wait_mover(client, ordinal, axis, op, target, limit=600):
    """Poll until the mover satisfies `value <op> target`, return the reading."""
    for _ in range(limit):
        p = await mover(client, ordinal)
        if p is not None:
            value = p[axis]
            if (op == "le" and value <= target) or (op == "ge" and value >= target):
                return value
        await asyncio.sleep(0.02)
    return None


def brief(player):
    pos = player.get("position")
    if not pos:
        return f"<no player entity; keys={sorted(player)[:6]}>"
    speed = player.get("speed") or {}
    return (f"({pos['x']:7.1f},{pos['y']:7.1f}) "
            f"vx={speed.get('x', 0):6.1f} vy={speed.get('y', 0):6.1f} "
            f"dash={player['dashes']} "
            f"{'ground' if player['on_ground'] else 'air':6s} {player['state']}"
            f"{' DEAD' if player['dead'] else ''}")


async def wait_stable(client, ordinal, limit=80):
    """Wait until the mover's x stops changing: jumping while it is still
    travelling inherits its speed and overshoots the arc."""
    previous, same = None, 0
    for _ in range(limit):
        p = await mover(client, ordinal)
        x = p["x"] if p else None
        if x is not None and x == previous:
            same += 1
            if same >= 2:
                return x
        else:
            same = 0
        previous = x
        await asyncio.sleep(0.02)
    return previous


async def wait_lift(client, limit_value, limit=120):
    """Wait until the platform-carried speed decays. Jumping while lift_speed is
    still large adds it to the jump and throws the arc into the spikes."""
    best = None
    for _ in range(limit):
        p = await client.call("get_player", internals=True)
        lift = (p.get("lift_speed") or {}).get("x", 0)
        speed = (p.get("speed") or {}).get("x", 0)
        best = (lift, speed)
        if abs(lift) <= limit_value and abs(speed) <= 5 and p.get("on_ground"):
            return best
        await asyncio.sleep(0.02)
    return best


async def main(args):
    async with BridgeClient(32123, timeout=20) as client:
        registry = ToolRegistry(client)
        for _ in range(80):
            state = await registry.invoke("observe_game")
            playable = (await client.call("get_playability"))["playable"]
            if state["player"] and not state["player"]["dead"] and playable:
                break
            await asyncio.sleep(0.1)

        before = await client.call("get_player")
        print("before", brief(before))

        if args.wait_mover_x_le is not None:
            ordinal, target = args.wait_mover_x_le.split(":")
            print(f"  mover {ordinal} x -> <= {target}: got",
                  await wait_mover(client, int(ordinal), "x", "le", float(target)))
        if args.wait_mover_x_ge is not None:
            ordinal, target = args.wait_mover_x_ge.split(":")
            print(f"  mover {ordinal} x -> >= {target}: got",
                  await wait_mover(client, int(ordinal), "x", "ge", float(target)))
        if args.stable is not None:
            print(f"  mover {args.stable} stable at x=",
                  await wait_stable(client, args.stable))
        if args.wait_lift is not None:
            print("  lift settled (lift,speed)=", await wait_lift(client, args.wait_lift))
        if args.wait_mover_y_ge is not None:
            ordinal, target = args.wait_mover_y_ge.split(":")
            print(f"  mover {ordinal} y -> >= {target}: got",
                  await wait_mover(client, int(ordinal), "y", "ge", float(target)))
        if args.wait_mover_y_le is not None:
            ordinal, target = args.wait_mover_y_le.split(":")
            print(f"  mover {ordinal} y -> <= {target}: got",
                  await wait_mover(client, int(ordinal), "y", "le", float(target)))

        if args.actions:
            sequence = ActionSequence(execution_id=uuid.uuid4().hex,
                                      trace_frames=bool(args.trace),
                                      actions=parse_actions(args.actions))
            result = await registry.invoke("execute_actions", **sequence.model_dump())
            print(f"status={result['status']} frames={result['executed_frames']}")
            if args.trace:
                for index, cp in enumerate(result["checkpoints"], 1):
                    p = cp["player"]
                    print(f"  f{index:02d} ({p['x']:7.1f},{p['y']:7.1f}) "
                          f"vx={p['vx']:6.1f} vy={p['vy']:6.1f} "
                          f"{'ground' if p['on_ground'] else 'air':6s} "
                          f"dash={p['dashes']}{' DEAD' if p['dead'] else ''}")

        await asyncio.sleep(args.settle)
        # A death removes the player entity, so wait for the respawn before
        # reporting; otherwise the payload has no position to show.
        for _ in range(80):
            after = await client.call("get_player")
            if after.get("position") and not after.get("dead"):
                break
            await asyncio.sleep(0.1)
        print("after ", brief(after))
        if not after.get("position") or after.get("dead"):
            return
        for ordinal in (0, 1):
            p = await mover(client, ordinal)
            if p:
                print(f"  mover{ordinal} ({p['x']},{p['y']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actions", default="")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--wait-mover-x-le", dest="wait_mover_x_le")
    parser.add_argument("--wait-mover-x-ge", dest="wait_mover_x_ge")
    parser.add_argument("--wait-mover-y-ge", dest="wait_mover_y_ge")
    parser.add_argument("--wait-mover-y-le", dest="wait_mover_y_le")
    parser.add_argument("--stable", type=int, help="wait until this mover stops moving")
    parser.add_argument("--wait-lift", type=float, dest="wait_lift",
                        help="wait until |lift_speed.x| drops below this")
    parser.add_argument("--settle", type=float, default=0.35)
    asyncio.run(main(parser.parse_args()))
