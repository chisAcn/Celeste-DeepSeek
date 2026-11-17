"""Train a bridge-compatible action prior from chapter-level Celeste TAS files."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from agent.protocol import FrameAction, Schema

BUTTONS = {
    "L": "left", "R": "right", "U": "up", "D": "down",
    "J": "jump", "K": "jump", "X": "dash", "C": "dash", "G": "grab", "H": "grab",
}


def action_key(buttons):
    return ",".join(sorted(buttons))


def parse_route(path, *, content=None):
    """Read gameplay blocks, keeping barriers where commands or inputs are unsupported."""
    rows = []
    repeats = []
    room = None
    skipped = 0
    if content is None:
        content = path.read_bytes()
    for number, raw in enumerate(content.decode("utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#lvl_"):
            room = line.removeprefix("#lvl_").strip()
            rows.append(None)
            continue
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split("#", 1)[0].split(",")]
        command = fields[0].lower().split(maxsplit=1)
        command = command[0] if command else ""
        if command in {"read", "play"}:
            raise ValueError(f"{path.name}:{number}: flatten {command} in Celeste Studio first")
        if command == "repeat" and len(fields) == 2 and fields[1].isdigit() and 1 <= int(fields[1]) <= 1000:
            repeats.append((len(rows), int(fields[1]), room))
            continue
        if command == "endrepeat" and repeats:
            start, count, start_room = repeats.pop()
            if room != start_room or (len(rows) - start) * count > 100_000:
                raise ValueError(f"{path.name}:{number}: unsupported Repeat block")
            rows.extend(rows[start:] * (count - 1))
            continue
        if command in {"repeat", "endrepeat"}:
            raise ValueError(f"{path.name}:{number}: malformed Repeat")
        if room is None:
            continue
        if not fields[0].isdigit() or not 1 <= int(fields[0]) <= 120 or any(
                token not in BUTTONS for token in fields[1:]):
            skipped += 1
            rows.append(None)
            continue
        rows.append((room, number, action_key({BUTTONS[token] for token in fields[1:]}), int(fields[0])))
    if repeats:
        raise ValueError(f"{path.name}: unterminated Repeat")
    return rows, skipped


def examples(path, rows, split):
    previous = None
    for row in rows:
        if row is None:
            previous = None
            continue
        room, line, action, frames = row
        yield {"split": split, "source": path.name, "room": room, "line": line,
               "previous": previous, "action": action, "frames": frames}
        previous = action


class ActionPrior(Schema):
    schema_version: int = 1
    counts: dict[str, int]
    transitions: dict[str, dict[str, int]]
    durations: dict[str, int]

    def rank(self, previous=None):
        local = self.transitions.get(previous, {})
        total = sum(self.counts.values())
        return sorted(self.counts, key=lambda action: (
            -(local.get(action, 0) + 8 * self.counts[action] / total), action))

    def suggest(self, previous, dashes, limit=5):
        suggestions = []
        for action in self.rank(previous):
            buttons = action.split(",") if action else []
            if "dash" in buttons and dashes == 0:
                continue
            suggestions.append(FrameAction(buttons=buttons, frames=self.durations[action]))
            if len(suggestions) == limit:
                break
        return suggestions


def train(rows):
    counts = Counter()
    transitions = defaultdict(Counter)
    durations = defaultdict(Counter)
    for row in rows:
        action = row["action"]
        counts[action] += 1
        durations[action][row["frames"]] += 1
        if row["previous"] is not None:
            transitions[row["previous"]][action] += 1
    if not counts:
        raise ValueError("no supported training actions")
    return ActionPrior(counts=dict(counts), transitions=dict(transitions),
                       durations={action: min(histogram, key=lambda n: (-histogram[n], n))
                                  for action, histogram in durations.items()})


def metrics(model, rows):
    if not rows:
        raise ValueError("no supported holdout actions")
    ranked = {previous: model.rank(previous) for previous in {row["previous"] for row in rows}}
    baseline = model.rank()
    return {f"top_{k}": {
        "transition": sum(row["action"] in ranked[row["previous"]][:k] for row in rows) / len(rows),
        "frequency": sum(row["action"] in baseline[:k] for row in rows) / len(rows),
    } for k in (1, 3, 5)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/tas-training"))
    parser.add_argument("--train", nargs="+", default=["1A.tas", "1B.tas"])
    parser.add_argument("--holdout", nargs="+", default=["2A.tas"])
    args = parser.parse_args()
    files, splits = {}, {"train": [], "holdout": []}
    hashes = set()
    for split, names in (("train", args.train), ("holdout", args.holdout)):
        for filename in names:
            if Path(filename).name != filename or not filename.lower().endswith(".tas"):
                parser.error(f"expected a chapter .tas filename: {filename}")
            path = args.source / filename
            try:
                content = path.read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                if digest in hashes:
                    parser.error(f"duplicate route across selected files: {filename}")
                hashes.add(digest)
                rows, skipped = parse_route(path, content=content)
            except (OSError, ValueError) as error:
                parser.error(str(error))
            records = list(examples(path, rows, split))
            if not records:
                parser.error(f"no supported gameplay actions in {filename}")
            splits[split].extend(records)
            files[filename] = {"split": split, "segments": len(records),
                               "frames": sum(row["frames"] for row in records), "skipped_rows": skipped,
                               "sha256": digest}
    model = train(splits["train"])
    report = {"files": files,
              "holdout_metrics": metrics(model, splits["holdout"])}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "action-prior.json").write_text(model.model_dump_json(indent=2), encoding="utf-8")
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (args.output / "actions.jsonl").open("w", encoding="utf-8") as output:
        for records in splits.values():
            for row in records:
                output.write(json.dumps(row) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
