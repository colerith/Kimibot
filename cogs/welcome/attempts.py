"""Persistent Beijing-calendar admission attempt quota."""
from datetime import datetime, timedelta, timezone
import uuid
from cogs.shared import sqlite_store as db

TZ = timezone(timedelta(hours=8))
DAILY_LIMIT = 3


def day_key(at=None):
    return (at or datetime.now(TZ)).astimezone(TZ).date().isoformat()


def reserve(guild_id, user_id, at=None):
    db._ensure_schema()
    day = day_key(at)
    with db._connection() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute('CREATE TABLE IF NOT EXISTS admission_attempts (token TEXT PRIMARY KEY, guild_id INTEGER, user_id INTEGER, day TEXT)')
        used = con.execute('SELECT count(*) FROM admission_attempts WHERE guild_id=? AND user_id=? AND day=?', (guild_id,user_id,day)).fetchone()[0]
        if used >= DAILY_LIMIT:
            return None, used
        token = uuid.uuid4().hex
        con.execute('INSERT INTO admission_attempts VALUES (?,?,?,?)', (token,guild_id,user_id,day))
        return token, used+1


def release(token):
    with db._connection() as con:
        con.execute('DELETE FROM admission_attempts WHERE token=?', (token,))


def used_today(guild_id, user_id, at=None):
    db._ensure_schema()
    with db._connection() as con:
        con.execute('CREATE TABLE IF NOT EXISTS admission_attempts (token TEXT PRIMARY KEY, guild_id INTEGER, user_id INTEGER, day TEXT)')
        return con.execute('SELECT count(*) FROM admission_attempts WHERE guild_id=? AND user_id=? AND day=?',
                           (guild_id, user_id, day_key(at))).fetchone()[0]
