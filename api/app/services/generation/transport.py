"""The only paid network boundary. HTTP transport has no implicit retries."""
import asyncio
import os
from dataclasses import dataclass

import httpx

from app.services.generation.store import Held


@dataclass(frozen=True)
class Receipt:
    status: int
    body: str
    headers: dict[str, str]


class AnthropicTransport:
    def check_ready(self):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise Held("provider_key_missing")

    async def send(self, request: dict) -> Receipt:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise Held("provider_key_missing")
        # A dedicated transport makes retry behavior independent of SDK defaults.
        async with asyncio.timeout(330), httpx.AsyncClient(timeout=300,
                transport=httpx.AsyncHTTPTransport(retries=0)) as client:
            response = await client.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"}, json=request)
            headers = {k: response.headers[k] for k in ("request-id", "retry-after")
                       if k in response.headers}
            return Receipt(response.status_code, response.text, headers)
