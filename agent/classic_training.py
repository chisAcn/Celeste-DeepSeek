"""Train a separate action prior from PICO-8 Celeste Classic routes."""
import argparse
import hashlib
import json
import re
from collections import Counter
from itertools import groupby
from pathlib import Path

from agent.tas_training import action_key, metrics, train

BUTTONS = ("left", "right", "up", "down", "jump", "dash")


def read_masks(path):
    payload = path.read_text(encoding="utf-8-sig").strip()
    if payload.startswith("["):
        _, separator, payload = payload.partition("]")
        if not separator:
            raise ValueError("incomplete Classic TAS header")
    payload = payload.strip().removesuffix(",")
    if not re.fullmatch(r"\d+(?:\s*,\s*\d+)*", payload):
        raise ValueError("invalid input sequence")
    masks = bytes(int(mask) for mask in payload.split(","))
    if max(masks) >= 1 << len(BUTTONS):
        raise ValueError("input uses unsupported controller bits")
    return masks


def route_examples(masks, source, split):
    previous = None
    for mask, segment in groupby(masks):
        action = action_key(button for bit, button in enumerate(BUTTONS) if mask & (1 << bit))
        frames = sum(1 for _ in segment)
        while frames:
            duration = min(frames, 120)
            yield {"source": source, "split": split, "previous": previous,
                   "action": action, "frames": duration}
            previous = action
            frames -= duration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/tas-training-classic"))
    parser.add_argument("--holdout-games", nargs="+", default=["classic", "classic2"])
    args = parser.parse_args()
    holdouts = set(args.holdout_games)
    paths = [path.relative_to(args.source) for path in args.source.rglob("*.tas")]
    paths.sort(key=lambda path: (path.parts[0] not in holdouts, path.as_posix()))
    splits = {"train": [], "holdout": []}
    seen = set()
    files, skipped = {}, {}
    for path in paths:
        name = path.as_posix()
        try:
            masks = read_masks(args.source / path)
        except (OSError, ValueError) as error:
            skipped[name] = str(error)
            continue
        digest = hashlib.sha256(masks).hexdigest()
        if digest in seen:
            skipped[name] = "duplicate decoded inputs"
            continue
        seen.add(digest)
        split = "holdout" if path.parts[0] in holdouts else "train"
        records = list(route_examples(masks, name, split))
        splits[split].extend(records)
        files[name] = {"split": split, "frames": len(masks), "segments": len(records),
                       "input_sha256": digest}
    present = {Path(name).parts[0] for name in files if files[name]["split"] == "holdout"}
    if present != holdouts or not splits["train"]:
        parser.error("training data or requested holdout games are missing")
    model = train(splits["train"])
    totals = {
        split: {"routes": sum(file["split"] == split for file in files.values()),
                "segments": len(rows), "frames": sum(row["frames"] for row in rows)}
        for split, rows in splits.items()
    }
    report = {"domain": "pico8-celeste-classic", "holdout_games": sorted(holdouts),
              "totals": totals, "holdout_metrics": metrics(model, splits["holdout"]),
              "skipped_counts": dict(Counter(skipped.values())), "files": files, "skipped": skipped}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "action-prior.json").write_text(model.model_dump_json(indent=2), encoding="utf-8")
    (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (args.output / "actions.jsonl").open("w", encoding="utf-8") as output:
        for rows in splits.values():
            for row in rows:
                output.write(json.dumps(row) + "\n")
    print(json.dumps({key: report[key] for key in ("totals", "holdout_metrics", "skipped_counts")}, indent=2))


if __name__ == "__main__":
    main()
