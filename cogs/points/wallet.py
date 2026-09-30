"""Read-only wallet reporting; viewing a report never grants rewards."""
from datetime import datetime, timedelta
import math

from . import storage
from .festival import get_config, parse_time


def festival_bonus(row):
    for item in str(row.get('reason', '')).split(';'):
        if item.startswith('festival_bonus='):
            try:
                value = float(item.partition('=')[2])
                return max(0.0, value) if math.isfinite(value) else 0.0
            except ValueError:
                return 0.0
    return 0.0


def totals(rows):
    income = round(sum(max(0, row['amount']) for row in rows), 1)
    expense = round(sum(max(0, -row['amount']) for row in rows), 1)
    return dict(income=income, expense=expense, net=round(income-expense, 1),
                festival_bonus=round(sum(festival_bonus(row) for row in rows), 1))


def get_report(user_id, guild_id, now=None):
    now = now or datetime.now(storage.TZ_CN)
    now = now.replace(tzinfo=storage.TZ_CN) if now.tzinfo is None else now.astimezone(storage.TZ_CN)
    today = now.date()
    week = today - timedelta(days=today.weekday())
    month = today.replace(day=1)
    seven = today - timedelta(days=6)
    earliest = min(week, month, seven)
    storage._ensure_points_db()
    with storage._points_connection() as connection:
        connection.execute('BEGIN')
        record, _ = storage._db_get_user(connection, user_id, guild_id)
        monthly = storage._monthly_card_status(record, storage._db_monthly_config(connection), now)
        # Include a timezone margin, then compare parsed timestamps in Beijing time.
        raw = connection.execute(
            'SELECT id, time, amount, source, reason FROM point_transactions '
            'WHERE guild_id=? AND user_id=? AND time>=? ORDER BY id DESC',
            (str(guild_id), str(user_id), (earliest-timedelta(days=1)).isoformat()),
        ).fetchall()
        has_events = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kimi_daily_events'").fetchone()
        played = bool(has_events and connection.execute(
            "SELECT 1 FROM kimi_daily_events WHERE guild_id=? AND user_id=? AND action='fortune' AND day=?",
            (guild_id, user_id, today.isoformat()),
        ).fetchone())
    rows = []
    for row in raw:
        moment = storage._parse_iso_datetime(row['time'])
        if moment and earliest <= moment.date() <= today and moment <= now:
            rows.append({**dict(row), 'moment': moment, 'day': moment.date().isoformat()})
    rows.sort(key=lambda row: (row['moment'], row['id']), reverse=True)
    fortune_text = None
    if played:
        from cogs.entertainment.engine import fortune
        fortune_text = fortune(f'discord:{guild_id}', str(user_id), today.isoformat())
    festival = get_config(guild_id)
    if not (festival.get('enabled') and parse_time(festival['start_at']) <= now < parse_time(festival['end_at'])):
        festival = None
    return dict(today=today, balance=storage._round_shells(record.get('shells', 0)),
                streak=int(record.get('streak_days', 0)), monthly=monthly,
                messages=int(record.get('daily_msg_count', 0)) if record.get('daily_msg_date') == today.isoformat() else 0,
                fortune=fortune_text, festival=festival, rows=[row for row in rows if row['day'] >= seven.isoformat()],
                today_totals=totals([row for row in rows if row['day'] == today.isoformat()]),
                week=totals([row for row in rows if row['day'] >= week.isoformat()]),
                month=totals([row for row in rows if row['day'] >= month.isoformat()]))
