from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecapMonitorState(Base):
    __tablename__ = 'recap_monitor_state'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope_digest: Mapped[str] = mapped_column(String)
    next_check_at: Mapped[int] = mapped_column(BigInteger)
    lease_token: Mapped[str] = mapped_column(String, default='')
    lease_until: Mapped[int] = mapped_column(BigInteger, default=0)
    state_json: Mapped[str] = mapped_column(String, default='{}')
    last_started_at: Mapped[int] = mapped_column(BigInteger, default=0)
    last_finished_at: Mapped[int] = mapped_column(BigInteger, default=0)
    heartbeat_at: Mapped[int] = mapped_column(BigInteger, default=0)


class RecapMonitorAlert(Base):
    __tablename__ = 'recap_monitor_alerts'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    scope_digest: Mapped[str] = mapped_column(String)
    recipient_digest: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default='pending')
    payload_json: Mapped[str] = mapped_column(String)
    first_attempt_at: Mapped[int] = mapped_column(BigInteger, default=0)
    next_attempt_at: Mapped[int] = mapped_column(BigInteger, default=0)
    lease_until: Mapped[int] = mapped_column(BigInteger, default=0)
    provider_id: Mapped[str] = mapped_column(String, default='')
    error: Mapped[str] = mapped_column(String, default='')
