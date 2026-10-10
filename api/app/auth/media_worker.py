"""Dedicated service principal. Identity and capabilities are server-owned."""
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.config import get_settings


@dataclass(frozen=True)
class MediaWorkerPrincipal:
    worker_id: str
    capabilities: frozenset[str]


def is_media_credential(token):
    saved = get_settings().media_worker_token
    return bool(saved and secrets.compare_digest(saved, token))


async def require_media_worker(request: Request):
    settings = get_settings()
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    if len(settings.media_worker_token) < 32 or not is_media_credential(token):
        raise HTTPException(403, "Dedicated media worker credential required")
    from app.services.recap_video.workflow import MEDIA_KINDS
    capabilities = frozenset(settings.media_worker_capabilities.split(","))
    if not capabilities or not capabilities <= MEDIA_KINDS:
        raise HTTPException(503, "Media worker capabilities are not configured")
    return MediaWorkerPrincipal(settings.media_worker_id, capabilities)
