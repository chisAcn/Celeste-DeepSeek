import asyncio

from agent.mock import MockBridge
from agent.protocol import ActionSequence, FrameAction, Request
from agent.replay import compare, record, replay
from agent.search import astar


class Local:
    def __init__(self):
        self.bridge = MockBridge()

    async def call(self, method, **params):
        return self.bridge.dispatch(Request(id="test", method=method, params=params))


def test_replay_and_divergence():
    async def scenario():
        client = Local()
        seq = ActionSequence(execution_id="a", trace_frames=True,
                             actions=[FrameAction(buttons=["right"], frames=30)])
        reference = await record(client, [seq], {"game": "mock"})
        actual, report = await replay(client, reference)
        assert report["matches"]
        assert len(actual.results[0].checkpoints) == 30
        assert actual.results[0].checkpoints[3].player.x == 4
        actual.results[0].after.player.x += 1
        assert compare(reference, actual)["first_mismatch"] == "checkpoint:1"
    asyncio.run(scenario())


def test_routing():
    graph = {"a": [("b", 2), ("c", 1)], "c": [("b", 0.5)], "b": []}
    assert astar("a", "b", graph.__getitem__) == ["a", "c", "b"]
