"""Explicit setup and read-only release diagnostics; never forces generation."""
import argparse
import asyncio
import json
import os
import time

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db.engine import dispose_engine, get_sessionmaker
from app.services.generation.models import LeagueSeason
from app.services.recap_monitor.collect import collect, owner
from app.services.recap_monitor.evidence import publication_proof
from app.services.recap_monitor.models import RecapMonitorAlert, RecapMonitorState
from app.services.recap_monitor.runner import Config
from app.services.recap_monitor.state import MONITOR, initialize


async def email_ready(config, maker):
    from email.utils import parseaddr
    recipient = await owner(maker, config)
    key = os.environ.get('RESEND_API_KEY', '')
    sender = os.environ.get('RECAP_MONITOR_FROM_EMAIL', '')
    address = parseaddr(sender)[1]
    if not key or not address or '@' not in address or '\n' in sender or '\r' in sender:
        raise ValueError('monitor_email_configuration_missing')
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.get('https://api.resend.com/domains', headers={
            'Authorization': 'Bearer ' + key, 'User-Agent': 'public-dynasty-recap-monitor/1.0'})
        response.raise_for_status()
        domains = response.json().get('data', [])
    if not any(d.get('name') == address.rsplit('@', 1)[1] and d.get('status') == 'verified' for d in domains):
        raise ValueError('monitor_sender_not_verified')
    return dict(sender_domain_verified=True, existing_owner_recipient_verified=bool(recipient.email), email_sent=False)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('initialize', 'status', 'dry-run', 'verify-email', 'verify-publications'))
    parser.add_argument('--season', type=int)
    parser.add_argument('--week', type=int)
    args = parser.parse_args()
    config, maker = Config.load(), get_sessionmaker()
    if args.command == 'initialize':
        # Setup may create monitor state only, never a job, approval or alert.
        await email_ready(config, maker)
        await initialize(maker, config.scope, config.start_at)
        print(json.dumps(dict(initialized=True, scope=config.scope, start_at=config.start_at)))
    elif args.command == 'verify-email':
        print(json.dumps(await email_ready(config, maker)))
    elif args.command == 'status':
        async with maker() as db:
            row = await db.get(RecapMonitorState, MONITOR)
            alerts = (await db.scalars(select(RecapMonitorAlert).where(RecapMonitorAlert.scope_digest == config.scope))).all()
            print(json.dumps(dict(configured=bool(row and row.scope_digest == config.scope),
                scope=config.scope, next_check_at=row.next_check_at if row else None,
                heartbeat_at=row.heartbeat_at if row else None, last_started_at=row.last_started_at if row else None,
                last_finished_at=row.last_finished_at if row else None,
                observations=json.loads(row.state_json) if row else {},
                alerts=[dict(state=a.state, error=a.error) for a in alerts])))
    elif args.command == 'dry-run':
        async with maker() as db:
            row = await db.get(RecapMonitorState, MONITOR)
            previous = json.loads(row.state_json).get('observations', {}) if row else {}
        values = await collect(config, maker, get_settings().cache_dir, int(time.time()), previous)
        print(json.dumps(dict(observations=values, recovery_executed=False, email_sent=False)))
    else:
        if not args.season or not args.week:
            parser.error('verify-publications requires explicit --season and --week')
        await owner(maker, config)
        values = []
        async with maker() as db:
            for series_id in config.series_ids:
                seasons = (await db.scalars(select(LeagueSeason).where(LeagueSeason.series_id == series_id,
                    LeagueSeason.season == args.season, LeagueSeason.verified_at > 0))).all()
                if len(seasons) != 1:
                    raise ValueError('verified_league_series_mapping_required')
                season = seasons[0]
                proof = await publication_proof(db, get_settings().cache_dir, season.league_id, args.season, args.week)
                values.append(dict(series_id=series_id, season=args.season, week=args.week, proof=proof))
        print(json.dumps(values))
        if not all(v['proof'] for v in values):
            raise ValueError('monitor_publication_proof_incomplete')


if __name__ == '__main__':
    async def run():
        try:
            await main()
        finally:
            await dispose_engine()
    asyncio.run(run())
