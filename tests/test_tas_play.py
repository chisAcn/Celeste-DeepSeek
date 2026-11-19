import asyncio
from pathlib import Path

import pytest

from agent.client import BridgeClient
from agent.main import wait_playable
from agent.mock import MockBridge
from agent.tas_play import (
    MAX_FRAMES_PER_CALL,
    load_section,
    split_crouch,
    to_actions,
)

TAS = Path(__file__).resolve().parents[1] / "data" / "1A-through-6b.tas"


def test_section_keeps_frames_and_order():
    rows, unknown = load_section(TAS, "6b")
    assert sum(frames for _, frames in rows) == 150
    assert rows[0] == (["right"], 1)
    assert rows[1] == (["up", "dash"], 15)
    assert unknown == {"Z(down + dash)"}


def test_crouch_dash_expands_to_down_and_dash():
    # "4,Z" is a crouch dash: the bridge has no Z button, so it becomes down+dash.
    rows, _ = load_section(TAS, "6b")
    assert (["down", "dash"], 4) in rows


def test_crouch_dash_can_wait_out_a_duck_lead():
    # With a lead the dash press waits, but the row still spans the same frames.
    plain, _ = load_section(TAS, "6b")
    led, _ = load_section(TAS, "6b", duck_lead=3)
    assert (["down"], 3) in led
    assert (["down", "dash"], 1) in led
    assert sum(frames for _, frames in led) == sum(frames for _, frames in plain)


def test_duck_lead_keeps_the_other_buttons_and_leaves_one_dash_frame():
    rows = [(["right", "down", "dash"], 2)]
    assert split_crouch(rows[0][0], 2, 5) == [(["right", "down"], 1),
                                              (["right", "down", "dash"], 1)]
    assert split_crouch(rows[0][0], 1, 5) == [(["right", "down", "dash"], 1)]
    assert split_crouch(rows[0][0], 14, 0) == [(["right", "down", "dash"], 14)]


def test_section_is_one_gapless_call():
    rows, _ = load_section(TAS, "6b")
    calls = to_actions(rows)
    assert len(calls) == 1
    assert sum(action.frames for action in calls[0]) == 150


def test_chunking_respects_the_bridge_budget():
    rows = [([], 120)] * 20
    calls = to_actions(rows)
    assert all(sum(action.frames for action in call) <= MAX_FRAMES_PER_CALL for call in calls)
    assert sum(len(call) for call in calls) == 20


def test_unknown_room_is_rejected():
    with pytest.raises(ValueError, match="no rows"):
        load_section(TAS, "not-a-room")


def test_wait_playable_returns_false_when_frozen():
    async def scenario():
        mock = MockBridge()
        mock.paused = True
        server = await asyncio.start_server(mock.handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1]) as client:
            assert await wait_playable(client, timeout=0.2) is False
            mock.paused = False
            assert await wait_playable(client, timeout=0.2) is True
    asyncio.run(scenario())
