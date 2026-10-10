"""Provider/account circuit gates; global control always locks first."""
from sqlalchemy import func, select

from app.config import get_settings
from app.services.generation.models import ProviderAttempt
from app.services.generation.recap_models import ProviderAccountControl, RecapProviderAttempt
from app.services.generation.store import Conflict, Held, audit, data, lock_control


def account_alias(provider):
    settings = get_settings()
    alias = {"anthropic": settings.anthropic_account_alias, "elevenlabs": settings.elevenlabs_account_alias}.get(provider)
    if not alias or len(alias) > 64 or not all(c.isalnum() or c in "_-" for c in alias):
        raise Held("provider_account_unconfigured")
    return alias


async def account_control(db, provider, account_key):
    control = await lock_control(db)
    if provider not in ("anthropic", "elevenlabs") or not account_key:
        raise Held("provider_account_unconfigured")
    row = await db.get(ProviderAccountControl, (provider, account_key))
    if row is None:
        row = ProviderAccountControl(provider=provider, account_key=account_key,
            hold="", cooldown_until=0, revision=1, max_concurrency=1)
        db.add(row)
    # Older restores may contain legacy columns. Move atomically, never drop a live hold.
    if provider == "anthropic" and account_key == account_alias("anthropic"):
        if control.provider_hold:
            row.hold = control.provider_hold
            row.revision += 1
        row.cooldown_until = max(row.cooldown_until, control.cooldown_until)
        control.provider_hold, control.cooldown_until = "", 0
    await db.flush()
    return row


async def active_attempts(db, *, provider=None, account_key=None, series_id=None, dispositioned=frozenset()):
    from app.services.generation.models import GenerationOperation
    total = 0
    for model in (ProviderAttempt, RecapProviderAttempt):
        query = select(func.count()).select_from(model).where(model.state.in_(("dispatching", "unknown")))
        if dispositioned and model is RecapProviderAttempt:
            query = query.where(~model.id.in_(dispositioned))
        if provider is not None:
            query = query.where(model.provider == provider, model.account_key == account_key)
        if series_id is not None:
            if model is ProviderAttempt:
                query = query.join(GenerationOperation, GenerationOperation.id == model.operation_id).where(
                    GenerationOperation.series_id == series_id)
            else:
                query = query.where(model.series_id == series_id)
        total += await db.scalar(query)
    return total


async def require_provider_ready(db, provider: str, account_key: str, now: int, *, dispositioned=frozenset()) -> None:
    control = await lock_control(db)
    if get_settings().generation_emergency_pause:
        raise Held("emergency_pause")
    if control.hold:
        raise Held(control.hold)
    row = await account_control(db, provider, account_key)
    allow_accounting = False
    if dispositioned and row.hold == 'accounting_attention':
        unresolved = []
        for model in (ProviderAttempt, RecapProviderAttempt):
            unresolved.extend((await db.scalars(select(model.id).where(model.provider == provider,
                model.account_key == account_key,model.state.in_(('dispatching','unknown','abandoned'))))).all())
        allow_accounting = bool(unresolved) and set(unresolved).issubset(dispositioned)
    if row.hold and not allow_accounting:
        raise Held(row.hold)
    if row.cooldown_until > now:
        raise Held("provider_cooldown")
    if await active_attempts(db, provider=provider, account_key=account_key,dispositioned=dispositioned) >= row.max_concurrency:
        raise Held("concurrency_busy")


async def record_failure(db, provider, account_key, status, now, *, delay=60, accounting_unknown=False):
    row = await account_control(db, provider, account_key)
    if status in (401, 403):
        row.hold = "provider_auth_failed"
    elif status == 429:
        row.cooldown_until = max(row.cooldown_until, now + max(60, min(86400, delay)))
    elif accounting_unknown:
        row.hold = "accounting_attention"
    row.revision += 1


async def reset_provider(db, provider, account_key, expected_revision, actor, reason):
    row = await account_control(db, provider, account_key)
    if row.revision != expected_revision:
        raise Conflict("Provider controls changed. Reload before resetting.")
    for model in (ProviderAttempt, RecapProviderAttempt):
        if await db.scalar(select(model.id).where(model.provider == provider, model.account_key == account_key,
                model.state.in_(("dispatching", "unknown", "abandoned"))).limit(1)):
            raise Held("provider_outcome_unknown")
    before = data(row)
    row.hold, row.cooldown_until = "", 0
    row.revision += 1
    audit(db, actor, "provider_reset", provider + ":" + account_key, reason, before, data(row))
    return data(row)
