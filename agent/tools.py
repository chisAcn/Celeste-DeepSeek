import asyncio
import time

from agent.protocol import ActionSequence, ExecutionResult


class ToolRegistry:
    """Only these four tools are exposed to the planner runtime."""

    def __init__(self, client):
        self.client = client
        self.trajectory = []
        self.tools = {
            "observe_game": self.observe,
            "execute_actions": self.execute,
            "reset_room": self.reset,
            "get_trajectory": self.history,
        }

    async def invoke(self, name, **arguments):
        if name not in self.tools:
            raise ValueError("unapproved tool")
        return await self.tools[name](**arguments)

    async def observe(self):
        return await self.client.call("get_state")

    async def reset(self):
        return await self.client.call("reset_room")

    async def history(self):
        return self.trajectory[-100:]

    async def execute(self, **arguments):
        return await self._execute("execute_frames", **arguments)

    async def restore_and_execute(self, **arguments):
        return await self._execute("restore_and_execute", **arguments)

    async def _execute(self, method: str, **arguments):
        sequence = ActionSequence.model_validate(arguments)
        result = await self.client.call(method, **sequence.model_dump())
        deadline = time.monotonic() + 20
        while result.get("status") == "running":
            if time.monotonic() >= deadline:
                await self.client.call("stop")
                raise TimeoutError("execution deadline exceeded")
            await asyncio.sleep(0.03)  # status polling, never the game frame clock
            result = await self.client.call("get_execution", execution_id=sequence.execution_id)
        checked = ExecutionResult.model_validate(result)
        self.trajectory.append(checked.model_dump())
        return checked.model_dump()
