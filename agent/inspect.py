"""Query the bridge's information layer.

Examples:
    python -m agent.inspect --what player
    python -m agent.inspect --what player --internals
    python -m agent.inspect --what level,room --json
    python -m agent.inspect --what tiles
    python -m agent.inspect --what entities --fields --limit 40
"""
import argparse
import asyncio
import json

from agent.client import BridgeClient

TOPICS = (
    "player", "level", "room", "entities", "collision", "tiles", "menu", "save",
)


def request_for(topic, args):
    if topic == "player":
        return "get_player", {"internals": args.internals}
    if topic == "level":
        return "get_level", {}
    if topic == "room":
        return "get_room_structure", {}
    if topic == "entities":
        return "get_entities", {
            "fields": args.fields, "limit": args.limit, "whole_room": True}
    if topic == "collision":
        return "get_collision", {"limit": args.limit}
    if topic == "tiles":
        return "get_tiles", {"whole_room": True}
    if topic == "menu":
        return "get_menu", {}
    return "get_save", {}


def print_tiles(payload):
    print(f"room {payload['room']}  region {payload['region']}")
    for row in payload["rows"]:
        print(row)
    print("legend:", ", ".join(f"{k}={v}" for k, v in payload["legend"].items()))


async def main(args):
    topics = [t.strip() for t in args.what.split(",") if t.strip()]
    unknown = [t for t in topics if t not in TOPICS]
    if unknown:
        raise SystemExit(f"unknown topic(s): {', '.join(unknown)}; pick from {', '.join(TOPICS)}")
    async with BridgeClient(32123, timeout=12) as client:
        for topic in topics:
            method, params = request_for(topic, args)
            result = await client.call(method, **params)
            if topic == "tiles" and not args.json:
                print_tiles(result)
                continue
            if args.json:
                print(json.dumps({topic: result}, ensure_ascii=False, indent=1))
                continue
            print(f"=== {topic} ===")
            print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--what", default="player",
                        help=f"comma separated: {', '.join(TOPICS)}")
    parser.add_argument("--internals", action="store_true",
                        help="include raw private fields and physics constants")
    parser.add_argument("--fields", action="store_true",
                        help="reflect every entity's own simple fields")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--json", action="store_true", help="machine readable output")
    asyncio.run(main(parser.parse_args()))
