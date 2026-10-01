"""Writer client boundary: a key alone cannot authorize paid generation."""
from __future__ import annotations

import asyncio

from anthropic.types import Message


class UnmanagedGenerationError(RuntimeError):
    pass


class DeniedClient:
    def close(self):
        """No resources are opened by an unauthorized client."""

    @property
    def messages(self):
        return self

    def create(self, **request):
        raise UnmanagedGenerationError(
            "Paid generation requires an authorized admin job. "
            "Submit it through the app; a standalone provider key is insufficient."
        )


class ManagedClient:
    """Synchronous writers bridge to their durable gateway on the worker loop."""
    def __init__(self, gateway, operation_id, generation, loop, max_tokens):
        self.gateway = gateway
        self.operation_id = operation_id
        self.generation = generation
        self.loop = loop
        self.max_tokens = max_tokens
        self.stage = 0
        self.last_response = None
        self.feedback = None

    @property
    def messages(self):
        return self

    def create(self, **request):
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            raise RuntimeError("Run synchronous writers in a worker thread, not the gateway event loop")
        request["max_tokens"] = min(request["max_tokens"], self.max_tokens)
        if self.feedback and self.last_response:
            request["messages"] = [*request["messages"],
                {"role": "assistant", "content": self.last_response["content"]},
                {"role": "user", "content": "Correct only these validation failures using the original facts: "
                    + "; ".join(self.feedback)}]
        stage = self.stage + 1
        future = asyncio.run_coroutine_threadsafe(
            self.gateway.invoke(self.operation_id, self.generation, stage, request), self.loop)
        response = future.result()
        self.stage = stage
        self.last_response = response
        return Message.model_validate(response)
