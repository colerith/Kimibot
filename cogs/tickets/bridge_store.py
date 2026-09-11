"""Version 1 local SQLite mailbox, shared with Kimibot (no network listener)."""
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager


def parse_ticket(comment):
    hits = set(re.findall(r"(?<!\d)[0-9]{6}(?!\d)", unicodedata.normalize('NFKC', comment)))
    return next(iter(hits)) if len(hits) == 1 else None


class Mailbox:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, gid INTEGER NOT NULL, qq INTEGER NOT NULL, ticket TEXT NOT NULL, requested REAL NOT NULL, joined REAL, revision INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT '', next_try REAL NOT NULL DEFAULT 0)")
            db.execute("CREATE TABLE IF NOT EXISTS archives (message INTEGER PRIMARY KEY, ticket TEXT NOT NULL, approved INTEGER NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS archives_ticket ON archives(ticket)")
            db.execute("CREATE TABLE IF NOT EXISTS joins (gid INTEGER, qq INTEGER, observed REAL, PRIMARY KEY(gid,qq))")
            columns = {r['name'] for r in db.execute('PRAGMA table_info(requests)')}
            for name, declaration in {
                'flag': "TEXT NOT NULL DEFAULT ''", 'bot_id': 'INTEGER NOT NULL DEFAULT 0',
                'verified': 'REAL NOT NULL DEFAULT 0', 'admission': "TEXT NOT NULL DEFAULT 'waiting'",
                'attempts': 'INTEGER NOT NULL DEFAULT 0', 'admit_after': 'REAL NOT NULL DEFAULT 0',
            }.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE requests ADD COLUMN {name} {declaration}')
            db.execute('CREATE TABLE IF NOT EXISTS claims (ticket TEXT PRIMARY KEY, qq INTEGER NOT NULL)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, gid, qq, ticket, flag, timestamp, bot_id=0, can_approve=True):
        key = hashlib.sha256(f"{gid}:{qq}:{flag}".encode()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO requests(id,gid,qq,ticket,requested,flag,bot_id) VALUES(?,?,?,?,?,?,?)", (key, gid, qq, ticket, timestamp, flag if can_approve else '', bot_id))
            joined = db.execute('SELECT observed FROM joins WHERE gid=? AND qq=?', (gid, qq)).fetchone()
        if joined and timestamp <= joined['observed'] <= timestamp + 7*86400:
            self.joined(gid, qq, joined['observed'])

    def joined(self, gid, qq, timestamp):
        with self.connect() as db:
            db.execute('INSERT INTO joins VALUES(?,?,?) ON CONFLICT(gid,qq) DO UPDATE SET observed=MAX(observed,excluded.observed)', (gid, qq, timestamp))
            # A delayed notice cannot confirm a newer request; ambiguous claims stay manual.
            rows = db.execute("SELECT * FROM requests WHERE gid=? AND qq=? AND requested<=? AND requested>=? ORDER BY requested DESC", (gid, qq, timestamp, timestamp-7*86400)).fetchall()
            if rows and len({r['ticket'] for r in rows}) == 1:
                db.execute("UPDATE requests SET joined=?, admission='joined', revision=revision+1, state=CASE WHEN state='conflict' THEN state ELSE 'pending' END, next_try=0 WHERE gid=? AND qq=? AND ticket=? AND requested<=? AND requested>=? AND joined IS NULL", (timestamp, gid, qq, rows[0]['ticket'], timestamp, timestamp-7*86400))

    def pending(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests WHERE (state='pending' OR (state='done' AND admission IN ('waiting','running') AND flag!='' AND joined IS NULL AND attempts<3 AND requested>?)) AND next_try<=? ORDER BY next_try,requested LIMIT 20", (time.time()-7*86400, time.time()))]

    def result(self, row, state, note):
        with self.connect() as db:
            # A joining notice received during Discord editing must be processed afterwards.
            valid = state in ('ready', 'done')
            db.execute("UPDATE requests SET state=?,note=?,next_try=?,verified=? WHERE id=? AND revision=?", ('pending' if state == 'ready' else state, note, time.time()+60, time.time() if valid else 0, row['id'], row['revision']))

    def reserve(self, ticket, qq):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO claims VALUES(?,?)', (ticket, qq))
            return db.execute('SELECT qq FROM claims WHERE ticket=?', (ticket,)).fetchone()['qq'] == qq

    def observed_candidates(self, bot_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests WHERE bot_id=? AND joined IS NULL AND requested>?", (bot_id, time.time()-7*86400))]

    def approval_candidates(self, bot_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM requests WHERE bot_id=? AND joined IS NULL AND state!='conflict' AND flag!='' AND verified>? AND admission IN ('waiting','running') AND attempts<3 AND admit_after<=? AND requested>? LIMIT 20", (bot_id, time.time()-90, time.time(), time.time()-7*86400))]

    def start_approval(self, row):
        with self.connect() as db:
            result = db.execute("UPDATE requests SET admission='running', attempts=attempts+1,admit_after=? WHERE id=? AND joined IS NULL AND revision=? AND verified>? AND admission IN ('waiting','running') AND attempts<3 AND admit_after<=?", (time.time()+60, row['id'], row['revision'], time.time()-90, time.time()))
            return result.rowcount == 1

    def finish_approval(self, row, success):
        with self.connect() as db:
            db.execute("UPDATE requests SET admission=CASE WHEN ? THEN 'approved' WHEN attempts>=3 THEN 'manual' ELSE 'waiting' END WHERE id=? AND joined IS NULL AND admission='running'", (success, row['id']))

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
        for row in db.execute("SELECT ticket,gid,qq,state,admission,attempts,note FROM requests ORDER BY requested DESC LIMIT 30"):
            print(json.dumps(dict(row), ensure_ascii=False))
