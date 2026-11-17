import asyncio
import json

import pytest

from agent.client import BridgeClient
from agent.mock import MockBridge
from agent.tools import ToolRegistry


def test_malformed_request():
    async def check():
        server = await asyncio.start_server(MockBridge().handle, "127.0.0.1", 0)
        async with server:
            reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
            writer.write(b'not-json\n')
            await writer.drain()
            reply = json.loads(await reader.readline())
            assert reply["error"]["code"] == -32602
            assert reply["id"] is None
            writer.close()
            await writer.wait_closed()
    asyncio.run(check())


@pytest.mark.parametrize("disconnect", [False, True])
def test_timeout_disconnect(disconnect):
    async def check():
        async def handle(reader, writer):
            await reader.readline()
            if disconnect:
                writer.close()
            else:
                await reader.read()
                writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        async with server, BridgeClient(server.sockets[0].getsockname()[1], timeout=0.1) as client:
            with pytest.raises(ConnectionError if disconnect else TimeoutError):
                await client.call("get_state")
            assert client.writer.is_closing()
    asyncio.run(check())


def test_tool_polling():
    class Client:
        def __init__(self):
            self.calls = []

        async def call(self, method, **params):
            self.calls.append(method)
            if method == "execute_frames":
                return {"status": "running"}
            from agent.protocol import GameState
            return {"execution_id": "x", "status": "interrupted", "executed_frames": 2,
                    "before": GameState().model_dump(), "after": GameState(frame=2).model_dump()}
    async def check():
        client = Client()
        tools = ToolRegistry(client)
        result = await tools.invoke("execute_actions", execution_id="x", actions=[{"buttons": [], "frames": 10}])
        assert result["executed_frames"] == 2
        assert client.calls == ["execute_frames", "get_execution"]
        assert len(await tools.invoke("get_trajectory")) == 1
        with pytest.raises(ValueError):
            await tools.invoke("shell")
    asyncio.run(check())
