"""Read-only liveness for the independent Railway controller watchdog."""
import os

from app.config import get_settings
from app.services.recap_monitor.models import RecapMonitorState
from app.services.recap_monitor.runner import Config
from app.services.recap_monitor.state import MONITOR


async def health(db, now):
    reason = ""
    row = await db.get(RecapMonitorState, MONITOR)
    if not get_settings().recap_monitor_enabled:
        reason = "monitor_disabled"
    elif not row:
        reason = "monitor_state_missing"
    else:
        try:
            matches = row.scope_digest == Config.load().scope
        except ValueError:
            matches = False
        if not matches:
            reason = "monitor_configuration_invalid"
        elif not row.heartbeat_at or now - row.heartbeat_at > 300:
            reason = "monitor_heartbeat_stale"
        elif row.last_started_at > row.last_finished_at and now - row.last_started_at > 300:
            reason = "monitor_cycle_stalled"
        elif row.next_check_at < now - 600:
            reason = "monitor_check_overdue"
        elif not os.getenv("RESEND_API_KEY") or not os.getenv("RECAP_MONITOR_FROM_EMAIL"):
            reason = "monitor_email_configuration_missing"
    return {"healthy": not reason, "reason": reason, "checked_at": now,
            "heartbeat_at": row.heartbeat_at if row else 0}
