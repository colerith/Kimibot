import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from cogs.points import storage, festival
from cogs.points.wallet import get_report, totals
from cogs.roles.wallet_view import WalletView, WalletFilter, build_wallet_embed, FORTUNE_CHANNEL
from cogs.entertainment.engine import Entertainment, fortune


class WalletTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for module, name, value in [
            (storage, 'POINTS_DB_FILE', str(root/'points.db')),
            (storage, 'POINTS_DATA_FILE', str(root/'points.json')),
            (storage, '_POINTS_DB_READY', False),
            (festival, 'CONFIG_FILE', str(root/'festival.json')),
        ]:
            item = patch.object(module, name, value)
            item.start()
            self.addCleanup(item.stop)
        self.now = datetime(2026, 10, 1, 12, tzinfo=storage.TZ_CN)
        self.user = SimpleNamespace(id=7, display_name='小蛋', display_avatar=SimpleNamespace(url='https://example.com/avatar.png'))

    def credit(self, timestamp, amount, guild=9, uid=7, source='test', reason=''):
        with patch.object(storage, '_now_iso', return_value=timestamp):
            storage.modify_user_points(uid, amount, guild, source=source, reason=reason)

    def test_beijing_boundaries_week_month_and_isolation(self):
        self.credit('2026-09-24T12:00:00+08:00', 50)
        self.credit('2026-09-25T12:00:00+08:00', 10)
        self.credit('2026-09-28T12:00:00+08:00', 20)
        self.credit('2026-09-30T15:59:59+00:00', -3)
        self.credit('2026-09-30T16:00:00+00:00', 4, reason='festival_bonus=2')
        self.credit('2026-10-01T11:00:00+08:00', -2)
        self.credit('2026-10-01T11:00:00+08:00', 99, uid=8)
        self.credit('2026-10-01T11:00:00+08:00', 99, guild=10)
        report = get_report(7, 9, self.now)
        self.assertEqual(report['balance'], 79)
        self.assertEqual(report['today_totals'], dict(income=4, expense=2, net=2, festival_bonus=2))
        self.assertEqual(report['week']['net'], 19)
        self.assertEqual(report['month']['net'], 2)
        self.assertEqual(totals(report['rows'])['net'], 29)
        self.assertEqual(len(report['rows']), 5)

    def test_no_fortune_does_not_roll_or_write(self):
        report = get_report(7, 9, self.now)
        self.assertIsNone(report['fortune'])
        self.assertEqual(report['balance'], 0)
        self.assertEqual(report['rows'], [])
        embed = build_wallet_embed(self.user, report)
        self.assertIn(FORTUNE_CHANNEL, embed.fields[0].value)
        self.assertIn('/奇米 运势', embed.fields[0].value)
        with storage._points_connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM point_transactions').fetchone()[0], 0)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='kimi_daily_events'").fetchone())

    def test_fortune_matches_command_and_refresh_never_settles(self):
        game = Entertainment(Path(self.temp.name)/'game.db', 'discord')
        with patch.object(storage, '_now_iso', return_value=self.now.isoformat()):
            reply = game.handle(9, 7, '今日运势', 123, self.now.timestamp())
        expected = fortune('discord:9', '7', '2026-10-01')
        self.assertTrue(reply.startswith(expected))
        with patch.object(storage, 'settle_kimi_daily_event', side_effect=AssertionError('must not settle')):
            report = get_report(7, 9, self.now)
            second = get_report(7, 9, self.now)
        self.assertEqual(report['fortune'], expected)
        self.assertEqual(report['balance'], second['balance'])
        self.assertIsNone(get_report(7, 9, self.now+timedelta(days=1))['fortune'])
        self.assertIsNone(get_report(8, 9, self.now)['fortune'])

    def test_bonus_is_in_balance_once_and_in_statement(self):
        festival.save_config(9, '国庆', '2020-01-01', '2099-01-01', 2)
        with patch.object(storage, '_now_iso', return_value=self.now.isoformat()):
            storage.grant_monthly_eligible_reward(7, 9, 4, source='submission_recommendation')
        report = get_report(7, 9, self.now)
        self.assertEqual(report['balance'], 8)
        self.assertEqual(report['today_totals']['income'], 8)
        self.assertEqual(report['today_totals']['festival_bonus'], 4)
        embed = build_wallet_embed(self.user, report)
        self.assertIn('活动收益 **×2**', embed.description)
        self.assertTrue(any('含节日 +4' in field.value for field in embed.fields))

    def test_filter_pagination_privacy_and_discord_limits(self):
        for i in range(20):
            self.credit(f'2026-10-01T10:{i:02}:00+08:00', 1)
        report = get_report(7, 9, self.now)

        async def run():
            view = WalletView(self.user, 9)
            with patch('cogs.roles.wallet_view.get_report', return_value=report):
                embed = await view.prepare()
                self.assertTrue(view.previous.disabled)
                self.assertFalse(view.next_page.disabled)
                selector = next(item for item in view.children if isinstance(item, WalletFilter))
                self.assertEqual(len(selector.options), 10)
                view.page = 99
                await view.prepare()
                self.assertEqual(view.page, 2)
                self.assertTrue(view.next_page.disabled)
                view.mode = 'fortune'
                embed = await view.prepare()
                self.assertTrue(view.next_page.disabled)
                self.assertEqual(len(embed.fields), 3)
                self.assertTrue(embed.fields[-2].name.startswith('📊 本周'))
                self.assertTrue(embed.fields[-1].name.startswith('🗓️ 本月'))
                other = SimpleNamespace(user=SimpleNamespace(id=8), response=SimpleNamespace(send_message=AsyncMock()))
                self.assertFalse(await view.interaction_check(other))
                self.assertTrue(other.response.send_message.call_args.kwargs['ephemeral'])
            for mode in ('overview', 'today', 'seven', 'fortune', '2026-09-30'):
                embed = build_wallet_embed(self.user, report, mode)
                self.assertLess(len(embed), 6000)
                self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
