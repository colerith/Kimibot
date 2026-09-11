"""Version 1 local SQLite mailbox, shared with Kimibot (no network listener)."""
import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager


def parse_ticket(comment):
    # Label required: never mistake a six-digit QQ number for a ticket number.
    hits = re.findall(r"(?:工单(?:编号|号|ID)?\s*[:：#]?\s*|#)([1-9][0-9]{5})(?![0-9])", comment, re.I)
    return hits[0] if len(hits) == 1 else None


class Mailbox:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, gid INTEGER NOT NULL, qq INTEGER NOT NULL, ticket TEXT NOT NULL, requested REAL NOT NULL, joined REAL, revision INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '', next_try REAL NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS archives (message INTEGER PRIMARY KEY, ticket TEXT NOT NULL, approved INTEGER NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS archives_ticket ON archives(ticket)")
            db.execute("CREATE TABLE IF NOT EXISTS joins (gid INTEGER, qq INTEGER, observed REAL, PRIMARY KEY(gid,qq))")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, gid, qq, ticket, flag, timestamp):
        key = hashlib.sha256(f"{gid}:{qq}:{flag}".encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO requests(id,gid,qq,ticket,requested) VALUES(?,?,?,?,?)", (key, gid, qq, ticket, timestamp))
            joined = db.execute('SELECT observed FROM joins WHERE gid=? AND qq=?', (gid, qq)).fetchone()
        if joined and timestamp <= joined['observed'] <= timestamp + 7*86400:
            self.joined(gid, qq, joined['observed'])

    def joined(self, gid, qq, timestamp):
        with self.connect() as db:
            db.execute('INSERT INTO joins VALUES(?,?,?) ON CONFLICT(gid,qq) DO UPDATE SET observed=MAX(observed,excluded.observed)', (gid, qq, timestamp))
            # A delayed notice cannot confirm a newer request; ambiguous claims stay manual.
            rows = db.execute("SELECT * FROM requests WHERE gid=? AND qq=? AND requested<=? AND requested>=? ORDER BY requested DESC", (gid, qq, timestamp, timestamp-7*86400)).fetchall()
            if rows and len({r['ticket'] for r in rows}) == 1:
                db.execute("UPDATE requests SET joined=?, revision=revision+1, state=CASE WHEN state='conflict' THEN state ELSE 'pending' END, next_try=0 WHERE id=? AND joined IS NULL", (timestamp, rows[0]['id']))

    def pending(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests WHERE state='pending' AND next_try<=? ORDER BY requested LIMIT 20", (time.time(),))]

    def result(self, row, state, note):
        with self.connect() as db:
            # A joining notice received during Discord editing must be processed afterwards.
            db.execute("UPDATE requests SET state=?,note=?,next_try=? WHERE id=? AND revision=?", (state, note, time.time()+60, row['id'], row['revision']))

    def index(self, message, ticket, approved):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO archives VALUES(?,?,?)", (message, ticket, int(approved)))

    def matches(self, ticket):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM archives WHERE ticket=?", (ticket,))]


if __name__ == '__main__':
    import sys
    box = Mailbox(sys.argv[1])
    with box.connect() as db:
        for row in db.execute("SELECT ticket,gid,qq,state,note FROM requests ORDER BY requested DESC LIMIT 30"):
            print(json.dumps(dict(row), ensure_ascii=False))
