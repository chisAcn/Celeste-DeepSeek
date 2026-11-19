"""Replay one room section of a CelesteTAS file through the live bridge.

The .tas format holds a whole chapter. A section is a run of ``frames,KEYS``
rows between two ``#lvl_<room>`` headers. Because the bridge caps a single
execution at 600 frames / 64 actions / 120 frames per action, short sections
(most 1A rooms) go through in one call, which keeps input gapless: splitting
into two calls would insert unheld frames at the seam and desync the route.

Keys the bridge cannot express are held as no input rather than dropped, so the
frame count stays aligned with the original recording.

``Z``/``V`` are crouch dashes. CelesteTAS holds ``down`` and presses ``dash`` on
the first frame she can actually crouch -- in the room-8 reference she is still
airborne when the block opens, lands ten frames later, and dashes on the next
frame. The bridge has no such condition, so ``duck_lead`` holds ``down`` alone
for that many frames before adding the dash press, keeping the total frame count
identical. A dash read on the block's first frame while airborne becomes a
down-diagonal dash, which is what a lead of 0 still does.
"""
import argparse
import asyncio
import json
import uuid
from pathlib import Path

from agent.client import BridgeClient
from agent.protocol import ActionSequence, FrameAction, GameState
from agent.tas_training import BUTTONS
from agent.tools import ToolRegistry

MAX_FRAMES_PER_CALL = 600
MAX_ACTIONS_PER_CALL = 64
MAX_FRAMES_PER_ACTION = 120

# CelesteTAS special inputs. Z/V are "crouch dash": down and dash on the same
# frame, which is the closest the bridge can express without a duck lead-in.
SPECIAL_KEYS = {"Z": ["down", "dash"], "V": ["down", "dash"]}

DEFAULT_DUCK_LEAD = 0


def split_crouch(buttons, frames, lead):
    """Hold down for `lead` frames, then add dash -- frame count is conserved."""
    limit = min(lead, frames - 1)
    if limit <= 0:
        return [(buttons, frames)]
    return [([button for button in buttons if button != "dash"], limit),
            (buttons, frames - limit)]


def load_section(path, room, *, duck_lead=DEFAULT_DUCK_LEAD):
    """Return [(buttons, frames)] for one room, in file order."""
    rows, unknown, current = [], set(), None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("#lvl_"):
            current = line.removeprefix("#lvl_").strip()
            continue
        if not line or line.startswith("#") or current != room:
            continue
        fields = [field.strip() for field in line.split("#", 1)[0].split(",")]
        if not fields[0].isdigit():
            continue  # console/load/commands: not input
        frames = int(fields[0])
        if not 1 <= frames <= MAX_FRAMES_PER_ACTION:
            raise ValueError(f"{path.name}: {frames} frames on one row is out of bounds")
        buttons, crouch = [], False
        for token in fields[1:]:
            if token in BUTTONS:
                pressed = [BUTTONS[token]]
            elif token in SPECIAL_KEYS:
                pressed = SPECIAL_KEYS[token]
                crouch = True
                unknown.add(f"{token}({' + '.join(pressed)})")
            else:
                unknown.add(token)
                pressed = []  # unrepresentable: held as neutral, frames preserved
            for button in pressed:
                if button not in buttons:
                    buttons.append(button)
        if crouch:
            rows.extend(split_crouch(buttons, frames, duck_lead))
        else:
            rows.append((buttons, frames))
    if not rows:
        raise ValueError(f"{path.name}: no rows under #lvl_{room}")
    return rows, unknown


def to_actions(rows):
    """Split rows into bridge-legal calls without reordering or merging."""
    calls, current, frames = [], [], 0
    for buttons, count in rows:
        if current and (len(current) >= MAX_ACTIONS_PER_CALL
                        or frames + count > MAX_FRAMES_PER_CALL):
            calls.append(current)
            current, frames = [], 0
        current.append(FrameAction(buttons=buttons, frames=count))
        frames += count
    if current:
        calls.append(current)
    return calls


async def replay_room(client, room, rows, *, reset=False, settle=0.4):
    registry = ToolRegistry(client)
    if reset:
        await registry.invoke("reset_room")
        await asyncio.sleep(settle)
        for _ in range(40):
            state = GameState.model_validate(await registry.invoke("observe_game"))
            if ((await client.call("get_playability"))["playable"]
                    and state.player and state.player.on_ground):
                break
            await asyncio.sleep(0.1)
    before = GameState.model_validate(await registry.invoke("observe_game"))
    if before.room.name != room:
        raise SystemExit(f"expected to stand in {room}, found {before.room.name!r}")
    steps, ended = [], "completed"
    for call in to_actions(rows):
        sequence = ActionSequence(execution_id=str(uuid.uuid4()), actions=call)
        result = await registry.invoke("execute_actions", **sequence.model_dump())
        steps.append({"frames": result["executed_frames"], "status": result["status"],
                      "end": [result["after"]["player"]["x"],
                              result["after"]["player"]["y"]]
                      if result["after"]["player"] else None,
                      "room": result["after"]["room"]["name"],
                      "dead": bool(result["after"]["player"] and
                                   result["after"]["player"]["dead"])})
        after = result["after"]
        if after["player"] and after["player"]["dead"]:
            ended = "died"
            break
        if after["room"]["name"] != room or after["room"]["completed"]:
            ended = "exit"
            break
        if result["status"] != "completed":
            ended = result["status"]
            break
    final = GameState.model_validate(await registry.invoke("observe_game"))
    return {"room": room, "ended": ended, "steps": steps,
            "start_position": [before.player.x, before.player.y] if before.player else None,
            "final_room": final.room.name,
            "final_position": [final.player.x, final.player.y] if final.player else None,
            "final_dead": bool(final.player and final.player.dead)}


async def main():
    parser = argparse.ArgumentParser(description="Replay one .tas room section")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--room", required=True)
    parser.add_argument("--reset", action="store_true", help="reset the room first")
    parser.add_argument("--duck-lead", type=int, default=DEFAULT_DUCK_LEAD,
                        help="frames of down held before a Z/V dash press")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows, unknown = load_section(args.file, args.room, duck_lead=args.duck_lead)
    calls = to_actions(rows)
    summary = {"room": args.room, "rows": len(rows), "calls": len(calls),
               "frames": sum(count for _, count in rows),
               "duck_lead": args.duck_lead,
               "unknown_keys_held_neutral": sorted(unknown)}
    if args.dry_run:
        print(json.dumps({**summary, "actions_per_call": [len(c) for c in calls]}, indent=2))
        return
    async with BridgeClient(timeout=5) as client:
        summary.update(await replay_room(client, args.room, rows, reset=args.reset))
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
