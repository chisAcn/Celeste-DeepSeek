"""Convert CelesteTAS ExportGameInfo dumps to aligned training examples."""
import argparse
import json
import math
import re
from pathlib import Path

from agent.tas_training import BUTTONS

HEADER = "Line\tInputs\tFrames\tTime\tPosition\tSpeed\tState\tStatuses\tRoom\tEntities"


def vector(text):
    x, y = map(float, text.split(","))
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("non-finite vector")
    return [x, y]


def examples(path):
    with path.open(encoding="utf-8-sig") as source:
        if source.readline().rstrip("\r\n") != HEADER:
            raise ValueError(f"{path}: expected ExportGameInfo header")
        previous = None
        for line in source:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 9:
                previous = None
                continue
            room = next((field[1:-1] for field in fields[8:]
                         if re.fullmatch(r"\[[^\[\]]+\]", field)), None)
            if room is None:
                previous = None
                continue
            state = {"frame": int(fields[2]), "room": room, "position": vector(fields[4]),
                     "speed": vector(fields[5]), "state": fields[6]}
            _, _, inputs = fields[1].partition("/")
            duration, *tokens = [field.strip() for field in inputs.split(",")]
            supported = duration.isdecimal() and all(token in BUTTONS for token in tokens)
            if (supported and previous and state["frame"] == previous["frame"] + 1
                    and room == previous["room"]):
                yield {"source": path.name, "observation": previous,
                       "action": {"buttons": sorted({BUTTONS[token] for token in tokens}), "frames": 1},
                       "next_observation": state}
            previous = state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/interop-training/transitions.jsonl"))
    args = parser.parse_args()
    try:
        rows = list(examples(args.dump))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if not rows:
        parser.error("no adjacent supported gameplay frames")
    if args.output.resolve() == args.dump.resolve():
        parser.error("output must differ from the source dump")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row) + "\n")
    print(f"{len(rows)} transitions from {len({row['observation']['room'] for row in rows})} rooms")


if __name__ == "__main__":
    main()
