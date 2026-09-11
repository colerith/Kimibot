import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from cogs.entertainment.engine import Entertainment, TZ


class GameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'game.db'
        self.game = Entertainment(self.path, 'qq')
        self.now = datetime(2026, 9, 11, 23, 59, tzinfo=TZ).timestamp()

    def wallet(self, group=1, uid=2, platform='qq'):
        db = self.game.connect()
        try:
            return dict(db.execute('SELECT * FROM wallets WHERE scope=? AND uid=?', (f'{platform}:{group}', str(uid))).fetchone())
        finally:
            db.close()

    def test_concurrent_checkin_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: self.game.handle(1, 2, '奇米签到', n, self.now), range(8)))
        record = self.wallet()
        self.assertEqual(record['streak'], 1)
        self.assertTrue(5 <= record['rice'] <= 15)

    def test_midnight_and_restart(self):
        self.game.handle(1, 2, '签到', 1, self.now)
        before = self.wallet()['rice']
        self.game = Entertainment(self.path, 'qq')
        self.game.handle(1, 2, '签到', 2, self.now)
        self.assertEqual(self.wallet()['rice'], before)
        self.game.handle(1, 2, '签到', 3, self.now+61)
        self.assertEqual(self.wallet()['streak'], 2)
        self.assertGreater(self.wallet()['rice'], before)

    def test_feed_duplicate_and_cooldown(self):
        self.game.handle(1, 2, '签到', 1, self.now)
        before = self.wallet()['rice']
        first = self.game.handle(1, 2, '喂奇米', 2, self.now)
        self.assertEqual(self.game.handle(1, 2, '喂奇米', 2, self.now+100), first)
        self.game.handle(1, 2, '喂奇米', 3, self.now+1)
        self.assertEqual(self.wallet()['rice'], before-3)

    def test_insufficient_and_scope_isolation(self):
        self.game.handle(1, 2, '喂奇米', 1, self.now)
        self.assertEqual(self.wallet()['rice'], 0)
        self.game.handle(2, 2, '签到', 1, self.now)
        self.assertEqual(self.wallet()['rice'], 0)
        self.assertGreater(self.wallet(group=2)['rice'], 0)
        Entertainment(self.path, 'discord').handle(1, 2, '我的饭粒', 1, self.now)
        self.assertEqual(self.wallet(platform='discord')['rice'], 0)

    def test_shared_pet_and_decay(self):
        self.game.handle(1, 2, '摸摸奇米', 1, self.now)
        text = self.game.handle(1, 3, '看看奇米', 2, self.now)
        self.assertIn('成长 1', text)
        text = self.game.handle(1, 3, '看看奇米', 3, self.now+3600*100)
        self.assertIn('饱腹 0/100', text)

    def test_fortune_stable_and_read_only(self):
        first = self.game.handle(1, 2, '今日运势', 1, self.now)
        self.assertEqual(first, Entertainment(self.path, 'qq').handle(1, 2, '今日奇米', 2, self.now))
        self.assertNotEqual(first, self.game.handle(1, 2, '今日奇米', 3, self.now+86400))
        self.assertEqual(self.wallet()['rice'], 0)
