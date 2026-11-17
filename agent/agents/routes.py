"""The route book on disk: what a session learned, minus the session.

Replay only paid off inside one process. A route learned in the run that cleared
room 7 died when that run exited, so the next run asked the model the same
question again and got a different answer. The book is evidence -- start
position, buttons, landing -- and evidence is worth keeping.

Two files exist and they are not the same thing:

``logs/routes.json``
    What this machine has learned or replayed. Written at the end of a session,
    replaced atomically, and never committed: it grows hits and misses, which
    belong to the machine, not the repo.

``agent/agents/seed-routes.json``
    Routes derived from a live clear and checked in, so a fresh checkout can
    replay a known room before it has ever run. It is read only when the
    learned book is missing; once a session saves, the learned book wins and
    carries the seed forward. Resolved next to this module, not next to the
    working directory, so the seed does not depend on where the run started.

A bad row costs one route, not the run. Losing the book to a truncated write
would be the more expensive failure, so rows that do not validate are counted
and skipped rather than raising.
"""

import json
import tempfile
from pathlib import Path

from agent.agents.skills import Replay, SkillBook

SCHEMA_VERSION = 1
LEARNED = Path("logs/routes.json")
SEED = Path(__file__).with_name("seed-routes.json")


def save_book(book: SkillBook, path: Path = LEARNED) -> Path:
    """Write the book atomically: a killed session must not truncate it.

    One route per line inside the envelope, because this file is read by humans
    when a route stops matching, and a re-indented diff hides which route moved.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ",\n".join("  " + json.dumps(entry.to_dict(), ensure_ascii=False)
                      for entry in book.entries)
    if rows:
        text = '{\n "schema_version": %d,\n "routes": [\n%s\n ]\n}\n' % (SCHEMA_VERSION, rows)
    else:
        text = '{\n "schema_version": %d,\n "routes": []\n}\n' % SCHEMA_VERSION
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name, suffix=".tmp", delete=False)
    try:
        with handle as output:
            output.write(text)
        Path(handle.name).replace(path)
    finally:
        Path(handle.name).unlink(missing_ok=True)
    return path


def load_book(path: Path, *, book: SkillBook | None = None) -> tuple[SkillBook, int]:
    """Read a book off disk; returns the book and how many rows were dropped."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError(f"{path} is not a route book")
    book = book if book is not None else SkillBook()
    skipped = 0
    for row in rows:
        try:
            entry = Replay.from_dict(row)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        # A route that already left rotation stays out: replaying it again
        # would only rediscover that it does not fit this room any more.
        if entry.streak >= book.max_streak:
            skipped += 1
            continue
        book.add(entry)  # the same route twice is one route, not a loss
    return book, skipped


def open_book(path: Path = LEARNED, *, seed: Path = SEED,
              book: SkillBook | None = None) -> tuple[SkillBook, str, int]:
    """The book to plan from, and where it came from.

    The learned file is the source of truth once it exists. The seed is a
    starting point for a checkout that has never run, not a second book to
    merge: merging would resurrect routes the learned book has since demoted.

    A learned book that will not parse is put aside before the next save can
    replace it, and the seed takes its place. A hand-edited typo should cost
    the routes in the file, not the file itself.
    """
    book = book if book is not None else SkillBook()
    target = Path(path)
    if target.exists():
        try:
            loaded, skipped = load_book(target, book=book)
            return loaded, "learned", skipped
        except (OSError, ValueError):
            _set_aside(target)
    seed_path = Path(seed)
    if seed_path.exists() and seed_path != target:
        try:
            loaded, skipped = load_book(seed_path, book=book)
            return loaded, "seed", skipped
        except (OSError, ValueError):
            pass
    return book, "empty", 0


def _set_aside(path: Path) -> Path | None:
    """Keep unparseable bytes next to the book instead of overwriting them."""
    try:
        return path.replace(path.with_suffix(path.suffix + ".broken"))
    except OSError:
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Inspect a route book.")
    parser.add_argument("path", type=Path, nargs="?", default=LEARNED)
    args = parser.parse_args()
    if not args.path.exists():
        raise SystemExit(f"no route book at {args.path}")
    book, skipped = load_book(args.path)
    for entry in book.entries:
        print(f"{entry.room:>4}  ({entry.x:>8.1f},{entry.y:>8.1f})  "
              f"{entry.frames:>4}f  hits={entry.hits} misses={entry.misses}  "
              f"{entry.name}")
    print(f"{len(book)} routes, {skipped} dropped")


if __name__ == "__main__":
    main()
