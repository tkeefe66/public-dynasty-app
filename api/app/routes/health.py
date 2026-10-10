from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get('/api/health/restore-gate')
def restore_gate():
    from app.services.generation.recovery import external_restore_gate
    return external_restore_gate()
