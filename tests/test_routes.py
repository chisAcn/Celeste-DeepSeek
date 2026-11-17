import json

from agent.agents.routes import SEED, load_book, open_book, save_book
from agent.agents.skills import Replay, SkillBook
from agent.protocol import FrameAction, GameState


def state(x=100.0, y=-1000.0, *, room="7", dashes=1, on_ground=True):
    return GameState.model_validate({
        "frame": 1000,
        "player": {"x": x, "y": y, "vx": 0.0, "vy": 0.0, "on_ground": on_ground,
                   "dashes": dashes, "stamina": 110, "dead": False},
        "room": {"name": room, "completed": False},
    })


def route(x=100.0, y=-1000.0, *, name="hop", room="7", end=(180.0, -1000.0)):
    return Replay(name=name, room=room, x=x, y=y, dashes=1,
                  actions=[FrameAction(buttons=["right"], frames=12),
                           FrameAction(buttons=["right", "jump"], frames=8)],
                  end_x=end[0], end_y=end[1], hits=3, misses=1)


def write(tmp_path, rows, name="routes.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"schema_version": 1, "routes": rows}), encoding="utf-8")
    return path


def test_a_saved_book_reloads_into_the_same_routes(tmp_path):
    book = SkillBook()
    book.add(route())
    path = save_book(book, tmp_path / "routes.json")

    loaded, skipped = load_book(path)

    assert skipped == 0 and len(loaded) == 1
    entry = loaded.entries[0]
    assert entry.name == "hop" and entry.room == "7"
    assert (entry.x, entry.y) == (100.0, -1000.0)
    assert (entry.end_x, entry.end_y) == (180.0, -1000.0)
    assert [action.model_dump() for action in entry.actions] == \
           [{"buttons": ["right"], "frames": 12},
            {"buttons": ["right", "jump"], "frames": 8}]
    assert (entry.hits, entry.misses) == (3, 1)


def test_the_reloaded_route_still_matches_its_start(tmp_path):
    book = SkillBook()
    book.add(route())
    loaded, _ = load_book(save_book(book, tmp_path / "routes.json"))

    assert loaded.match(state(x=100.5, y=-999.5)) is not None
    assert loaded.match(state(x=104.0)) is None


def test_the_reloaded_route_keeps_its_origin_and_its_dashes(tmp_path):
    book = SkillBook()
    entry = route()
    entry.origin = "live"
    book.add(entry)
    loaded, _ = load_book(save_book(book, tmp_path / "routes.json"))

    assert loaded.entries[0].origin == "live"
    assert loaded.match(state(dashes=0)) is None


def test_a_route_that_left_rotation_does_not_come_back(tmp_path):
    book = SkillBook(max_streak=2)
    demoted = route()
    demoted.streak = 2
    book.add(demoted)
    path = save_book(book, tmp_path / "routes.json")

    loaded, skipped = load_book(path)

    assert len(loaded) == 0 and skipped == 1
    assert path.exists()  # the evidence is not deleted, only out of rotation


def test_a_truncated_row_costs_one_route_and_not_the_book(tmp_path):
    good = route().to_dict()
    path = write(tmp_path, [good, {"name": "broken", "room": "7", "start": [1.0]}])

    loaded, skipped = load_book(path)

    assert len(loaded) == 1 and skipped == 1


def test_a_row_with_a_bad_button_is_skipped_not_replayed(tmp_path):
    bad = route().to_dict()
    bad["actions"] = [{"buttons": ["sideways"], "frames": 4}]
    path = write(tmp_path, [bad])

    loaded, skipped = load_book(path)

    assert len(loaded) == 0 and skipped == 1


def test_an_unreadable_book_is_put_aside_and_the_seed_takes_over(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text("{ not json", encoding="utf-8")

    book, origin, _ = open_book(path, seed=SEED)

    assert origin == "seed" and len(book) == 3
    assert not path.exists()
    assert (tmp_path / "routes.json.broken").read_text(encoding="utf-8") == "{ not json"


def test_an_unreadable_book_without_a_seed_starts_empty(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text("[]", encoding="utf-8")  # valid JSON, not a route book

    book, origin, skipped = open_book(path, seed=tmp_path / "absent.json")

    assert (len(book), origin, skipped) == (0, "empty", 0)
    assert (tmp_path / "routes.json.broken").exists()


def test_the_seed_is_used_only_before_the_first_save(tmp_path):
    path = tmp_path / "routes.json"

    seeded, origin, _ = open_book(path, seed=SEED)
    assert origin == "seed" and len(seeded) == 3

    save_book(SkillBook(), path)  # a session that learned nothing still owns the file
    empty, origin, _ = open_book(path, seed=SEED)
    assert origin == "learned" and len(empty) == 0


def test_without_a_seed_the_book_starts_empty(tmp_path):
    book, origin, skipped = open_book(tmp_path / "routes.json",
                                      seed=tmp_path / "absent.json")

    assert (len(book), origin, skipped) == (0, "empty", 0)


def test_the_seed_route_through_room_seven_chains_end_to_start():
    book, skipped = load_book(SEED)

    assert skipped == 0 and len(book) == 3
    ordered = book.entries
    assert [entry.name for entry in ordered] == ["7-spawn-to-e2", "7-e2-to-e3",
                                                 "7-e3-to-room-8"]
    for here, there in zip(ordered, ordered[1:]):
        assert abs(here.end_x - there.x) <= 2.0
        assert abs(here.end_y - there.y) <= 2.0
    assert all(entry.origin == "live" for entry in ordered)


def test_the_seed_route_is_replayable_from_the_spawn_tile():
    book, _ = load_book(SEED)
    first = book.entries[0]

    assert book.match(state(x=2600.0, y=-1480.0)) is first
    assert first.frames == 60
    assert book.match(state(x=2600.0, y=-1480.0, room="7a")) is None


def test_save_creates_the_directory_it_writes_into(tmp_path):
    path = save_book(SkillBook(), tmp_path / "nested" / "deeper" / "routes.json")

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["routes"] == []


def test_a_promoted_route_gets_a_name_no_other_route_carries():
    from agent.agents.messages import StepOutcome, StepReport, TraceRow

    book = SkillBook()
    book.add(route(x=300.0, name="learned-2"))
    report = StepReport(status="SUCCEEDED", execution_id="probe", start=state(),
                        end=state(x=180.0),
                        actions=[FrameAction(buttons=["right"], frames=12)],
                        trace=[TraceRow(frame=0, x=100.0, y=-1000.0)])

    promoted = book.note(StepOutcome(verdict="LANDED", report=report,
                                     actions=list(report.actions),
                                     settled=report.end))

    assert promoted == "learned-3"
    assert len({entry.name for entry in book.entries}) == len(book)
