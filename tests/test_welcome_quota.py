import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from cogs.shared import sqlite_store as db
from cogs.welcome import attempts

class DailyQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.pathpatch=patch.object(db,'APP_STATE_DB_FILE',str(Path(self.tmp.name)/'state.db'))
        self.readypatch=patch.object(db,'_SCHEMA_READY',False)
        self.pathpatch.start(); self.readypatch.start()
        self.day=datetime(2026,10,25,23,59,tzinfo=attempts.TZ)
    def tearDown(self):
        self.readypatch.stop(); self.pathpatch.stop(); self.tmp.cleanup()
    def test_concurrent_limit_persistence_and_refund(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:attempts.reserve(1,2,self.day),range(6)))
        tokens=[token for token,count in results if token]
        self.assertEqual(len(tokens),3)
        self.assertEqual(attempts.used_today(1,2,self.day),3)
        db._SCHEMA_READY=False
        self.assertIsNone(attempts.reserve(1,2,self.day)[0])
        attempts.release(tokens[0]); attempts.release(tokens[0])
        self.assertEqual(attempts.used_today(1,2,self.day),2)
        self.assertIsNotNone(attempts.reserve(1,2,self.day)[0])
    def test_beijing_midnight_and_user_isolation(self):
        for _ in range(3): attempts.reserve(1,2,self.day)
        midnight=datetime(2026,10,26,0,0,tzinfo=attempts.TZ)
        self.assertEqual(attempts.used_today(1,2,midnight),0)
        self.assertEqual(attempts.reserve(1,2,midnight)[1],1)
        self.assertEqual(attempts.reserve(1,3,self.day)[1],1)
        self.assertEqual(attempts.reserve(9,2,self.day)[1],1)

    def test_remaining_and_explicit_refresh_time(self):
        self.assertIn('3/3', attempts.quota_text(1,2,at=self.day))
        for _ in range(3): attempts.reserve(1,2,self.day)
        text = attempts.quota_text(1,2,at=self.day)
        self.assertIn('0/3', text)
        self.assertIn('2026-10-26 00:00（北京时间）', text)
        self.assertIn('不占次数', attempts.quota_text(1,2,test_mode=True,at=self.day))
