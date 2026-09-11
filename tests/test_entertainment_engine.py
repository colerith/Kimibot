import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from cogs.entertainment.engine import Entertainment, TZ
from cogs.entertainment.flavor import PET_STORIES, FORTUNE_STORIES
from cogs.points import storage as points


class GameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'game.db'
        self.game = Entertainment(self.path, 'qq')
        for name, value in [('POINTS_DB_FILE', str(Path(self.tmp.name) / 'points.db')),
                            ('POINTS_DATA_FILE', str(Path(self.tmp.name) / 'points.json')),
                            ('_POINTS_DB_READY', False)]:
            patcher = patch.object(points, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
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
        self.assertIsNone(Entertainment(self.path, 'discord').handle(1, 2, '我的饭粒', 1, self.now))

    def test_flavor_banks(self):
        self.assertGreaterEqual(len(set(PET_STORIES)), 50)
        self.assertGreaterEqual(len(set(FORTUNE_STORIES)), 50)

    def test_daily_event_concurrent_aliases_restart_and_midnight(self):
        game = Entertainment(self.path, 'discord')
        with patch.object(points.random, 'choice', return_value=1), patch.object(points.random, 'randint', return_value=100):
            with ThreadPoolExecutor(max_workers=8) as pool:
                replies = list(pool.map(lambda n: game.handle(1, 2, '今日运势' if n % 2 else '今日奇米', n, self.now), range(8)))
            self.assertEqual(len(set(replies)), 1)
            self.assertEqual(points.get_user_points(2, 1), 10)
            game = Entertainment(self.path, 'discord')
            self.assertEqual(game.handle(1, 2, '奇米运势', 20, self.now), replies[0])
            game.handle(1, 2, '群宠', 21, self.now)
            game.handle(1, 2, '看看奇米', 22, self.now)
            self.assertEqual(points.get_user_points(2, 1), 20)
            game.handle(1, 2, '今日运势', 23, self.now+61)
            self.assertEqual(points.get_user_points(2, 1), 30)
            game.handle(2, 2, '今日运势', 24, self.now)
            game.handle(1, 3, '今日运势', 25, self.now)
            self.assertEqual(points.get_user_points(2, 2), 10)
            self.assertEqual(points.get_user_points(3, 1), 10)

    def test_penalty_clamps_and_cannot_retry_after_topup(self):
        game = Entertainment(self.path, 'discord')
        points.modify_user_points(2, 0.3, 1)
        with patch.object(points.random, 'choice', return_value=-1), patch.object(points.random, 'randint', return_value=100):
            first = game.handle(1, 2, '今日运势', 1, self.now)
        self.assertIn('实际：-0.3', first)
        self.assertIn('余额不足', first)
        self.assertEqual(points.get_user_points(2, 1), 0)
        points.modify_user_points(2, 5, 1)
        self.assertEqual(game.handle(1, 2, '今日运势', 2, self.now), first)
        self.assertEqual(points.get_user_points(2, 1), 5)

    def test_daily_event_minimum_and_zero_balance(self):
        with patch.object(points.random, 'choice', return_value=-1), patch.object(points.random, 'randint', return_value=1):
            result = points.settle_kimi_daily_event(2, 1, 'status', '2026-09-11')
        self.assertEqual(result, {'requested': -0.1, 'actual': 0, 'balance': 0})
        with patch.object(points.random, 'choice', return_value=1), patch.object(points.random, 'randint', return_value=1):
            result = points.settle_kimi_daily_event(2, 1, 'fortune', '2026-09-11')
        self.assertEqual(result, {'requested': 0.1, 'actual': 0.1, 'balance': 0.1})

    def test_daily_event_rollback_and_game_failure_retry(self):
        game = Entertainment(self.path, 'discord')
        with patch.object(points.random, 'choice', return_value=1), patch.object(points.random, 'randint', return_value=50):
            with patch.object(points, '_db_put_user', side_effect=RuntimeError('write failed')):
                with self.assertRaises(RuntimeError):
                    game.handle(1, 2, '今日运势', 1, self.now)
            self.assertEqual(points.get_user_points(2, 1), 0)
            original = game.daily_event
            def fail_after_settlement(*args):
                original(*args)
                raise RuntimeError('game failed')
            with patch.object(game, 'daily_event', side_effect=fail_after_settlement):
                with self.assertRaises(RuntimeError):
                    game.handle(1, 2, '今日运势', 1, self.now)
            self.assertEqual(points.get_user_points(2, 1), 5)
            game.handle(1, 2, '今日运势', 1, self.now)
            self.assertEqual(points.get_user_points(2, 1), 5)

    def test_discord_shell_feed_concurrent_and_restart(self):
        game = Entertainment(self.path, 'discord')
        points.modify_user_points(2, 10.1, 1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda n: game.handle(1, 2, '喂奇米', 123, self.now), range(8)))
        self.assertEqual(len(set(replies)), 1)
        self.assertEqual(points.get_user_points(2, 1), 7.1)
        game = Entertainment(self.path, 'discord')
        self.assertEqual(game.handle(1, 2, '喂奇米', 123, self.now+100), replies[0])
        self.assertIn('秒后', game.handle(1, 2, '喂奇米', 124, self.now+1))
        self.assertEqual(points.get_user_points(2, 1), 7.1)
        self.assertEqual(self.wallet(platform='discord')['rice'], 0)

    def test_discord_insufficient_full_and_no_checkin(self):
        game = Entertainment(self.path, 'discord')
        self.assertIsNone(game.handle(1, 2, '奇米签到', 1, self.now))
        points.modify_user_points(2, 2.9, 1)
        self.assertIn('不够', game.handle(1, 2, '喂奇米', 2, self.now))
        self.assertEqual(points.get_user_points(2, 1), 2.9)
        points.modify_user_points(2, 10, 1)
        db = game.connect()
        with db:
            db.execute("UPDATE pets SET hunger=100 WHERE scope='discord:1'")
        db.close()
        self.assertIn('不扣费', game.handle(1, 2, '喂奇米', 3, self.now))
        self.assertEqual(points.get_user_points(2, 1), 12.9)
        self.assertIn('不够', game.handle(2, 2, '喂奇米', 4, self.now))

    def test_shell_receipt_survives_game_transaction_failure(self):
        game = Entertainment(self.path, 'discord')
        points.modify_user_points(2, 10, 1)
        original = game.apply
        def fail_after_payment(*args):
            original(*args)
            raise RuntimeError('simulated game write failure')
        with patch.object(game, 'apply', side_effect=fail_after_payment):
            with self.assertRaises(RuntimeError):
                game.handle(1, 2, '喂奇米', 77, self.now)
        self.assertEqual(points.get_user_points(2, 1), 7)
        game.handle(1, 2, '喂奇米', 77, self.now)
        self.assertEqual(points.get_user_points(2, 1), 7)
        self.assertEqual(self.wallet(platform='discord')['fed'], self.now)

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
