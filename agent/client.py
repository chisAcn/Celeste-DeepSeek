import asyncio
import json
import uuid

from agent.protocol import Request


class BridgeClient:
    def __init__(self, port=32123, timeout=5):
        self.port, self.timeout = port, timeout
        self.lock = asyncio.Lock()

    async def __aenter__(self):
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", self.port, limit=8 * 1024 * 1024), self.timeout)
        return self

    async def __aexit__(self, *args):
        self.writer.close()
        await self.writer.wait_closed()

    async def call(self, method, **params):
        async with self.lock:
            req = Request(id=str(uuid.uuid4()), method=method, params=params)
            try:
                self.writer.write((req.model_dump_json() + "\n").encode())
                await asyncio.wait_for(self.writer.drain(), self.timeout)
                raw = await asyncio.wait_for(self.reader.readline(), self.timeout)
            except BaseException:
                self.writer.close()  # ambiguous: the request may still be running
                raise
            if not raw:
                self.writer.close()
                raise ConnectionError("bridge disconnected; execution outcome unknown")
            try:
                response = json.loads(raw)
            except ValueError:
                self.writer.close()
                raise
            if response.get("id") != req.id or response.get("protocol_version") != "1.0":
                self.writer.close()  # a mismatched answer cannot be trusted
                raise ValueError("invalid response envelope")
            if "error" in response:
                # A well-formed error reply means the stream is still in sync, so
                # an optional probe like get_platforms must not kill the session.
                raise RuntimeError(response["error"])
            return response["result"]
