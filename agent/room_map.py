"""Print the current room as a coordinate-labelled map plus collidable objects.

    python -m agent.room_map
    python -m agent.room_map --objects
"""
import argparse
import asyncio

from agent.client import BridgeClient


def ruler(width, left):
    tens = "".join(str((left + x) // 10 % 10) for x in range(width))
    ones = "".join(str((left + x) % 10) for x in range(width))
    return tens, ones


async def main(args):
    async with BridgeClient(32123, timeout=20) as c:
        tiles = await c.call("get_tiles", whole_room=True)
        room = await c.call("get_room_structure")
        player = await c.call("get_player")
        collide = await c.call("get_collision", limit=args.limit) if args.objects else None

    region = tiles["region"]
    rows = tiles["rows"]
    cols = tiles["width"]
    x0 = region["x"] // 8
    y0 = region["y"] // 8
    tens, ones = ruler(cols, x0)

    print(f"room {tiles['room']}  world {region['x']},{region['y']} "
          f"{region['width']}x{region['height']}  tiles {cols}x{len(rows)}")
    print(f"player {player['position']}  state {player['state']}  "
          f"dashes {player['dashes']}/{player['max_dashes']}  ground {player['on_ground']}")
    print()
    print("     " + tens)
    print("     " + ones)
    for i, row in enumerate(rows):
        world_y = (y0 + i) * 8
        print(f"{world_y:6d} {row}")
    print()
    print("legend:", ", ".join(f"{k}={v}" for k, v in tiles["legend"].items()))

    if collide:
        print("\ncollidable objects")
        for o in collide.get("objects") or []:
            box = o.get("collider") or {}
            b = box.get("bounds")
            span = (f"{b['x']},{b['y']} {b['width']}x{b['height']}"
                    if b else box.get("type"))
            print(f"  {o['type']:26s} {o['kind']:10s} {span}")
        print("coverage:", collide.get("coverage"))

    print("\nneighbours")
    for n in room["neighbours"]:
        print(f"  {n['side']:5s} {n['room']:4s} {n['bounds']}")
    print("spawns:")
    for s in room["spawns"]:
        print(f"  {s['x']},{s['y']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", action="store_true")
    parser.add_argument("--limit", type=int, default=200)
    asyncio.run(main(parser.parse_args()))
