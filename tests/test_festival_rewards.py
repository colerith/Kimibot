import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cogs.points import festival, storage


class FestivalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent / ".cache")
        self.addCleanup(temporary.cleanup)
        for module, name, value in [
            (festival, 'CONFIG_FILE', str(Path(temporary.name) / 'festival.json')),
            (storage, 'POINTS_DB_FILE', str(Path(temporary.name) / 'points.db')),
            (storage, 'POINTS_DATA_FILE', str(Path(temporary.name) / 'points.json')),
            (storage, '_POINTS_DB_READY', False),
        ]:
            item = patch.object(module, name, value)
            item.start()
            self.addCleanup(item.stop)

    def configure(self, **overrides):
        values = dict(guild_id=9, name='国庆', start_at='2026-10-01 00:00', end_at='2026-10-08 00:00', multiplier=2)
        values.update(overrides)
        return festival.save_config(**values)

    def test_boundaries_scope_disable_and_persistence(self):
        self.configure()
        self.assertEqual(festival.get_config(9)['name'], '国庆')
        for text, expected in [('2026-09-30 23:59', 3), ('2026-10-01 00:00', 6), ('2026-10-07 23:59', 6), ('2026-10-08 00:00', 3)]:
            self.assertEqual(festival.apply_bonus(9, 3, festival.parse_time(text))[0], expected)
        now = festival.parse_time('2026-10-02')
        self.assertEqual(festival.apply_bonus(10, 3, now)[0], 3)
        self.assertEqual(festival.apply_bonus(9, -3, now)[0], -3)
        self.configure(enabled=False)
        self.assertEqual(festival.apply_bonus(9, 3, now)[0], 3)

    def test_validation(self):
        for value in [float('nan'), float('inf'), 0, 1, 101]:
            with self.assertRaises(ValueError):
                self.configure(multiplier=value)
        with self.assertRaises(ValueError):
            self.configure(end_at='2026-09-01')

    def test_rewards_idempotency_and_signin_penalty(self):
        self.configure(start_at='2020-01-01', end_at='2099-01-01')
        result = storage.grant_monthly_eligible_reward(7, 9, 3, source='submission', idempotency_key='one')
        self.assertEqual(result['amount'], 6)
        self.assertEqual(result['festival_bonus'], 3)
        storage.grant_monthly_eligible_reward(7, 9, 3, source='submission', idempotency_key='one')
        self.assertEqual(storage.get_user_points(7, 9), 6)
        with patch.object(storage, '_pick_random_event', return_value={'id': 'loss', 'delta': -1}), patch.object(storage.random, 'randint', return_value=10):
            result = storage.sign_in_user(7, 9)
        self.assertEqual(result['total_delta'], 3)  # (base 1 + rank 1) * 2 - loss 1
        self.assertEqual(result['festival_bonus'], 2)
        self.assertFalse(storage.sign_in_user(7, 9)['success'])

    def test_monthly_stacking_and_keyword(self):
        self.configure(start_at='2020-01-01', end_at='2099-01-01')
        with patch.object(storage, '_monthly_card_status', return_value={'active': True, 'reward_multiplier': 1.5}):
            result = storage.grant_monthly_eligible_reward(7, 9, 4, source='submission')
        self.assertEqual(result['amount'], 12)
        self.assertEqual(result['monthly_bonus'], 2)
        self.assertEqual(result['festival_bonus'], 6)
        result = storage.reward_daily_kimi_praise(8, 9, 123, min_reward=2, max_reward=2)
        self.assertEqual(result['amount'], 4)

    def test_admin_panel_capacity(self):
        from cogs.roles.views import CommunityPanelManageView
        # View construction validates Discord's five-row component limit.
        import asyncio
        async def construct():
            return CommunityPanelManageView(None, None)
        view = asyncio.run(construct())
        self.assertTrue(any(getattr(item, 'custom_id', '') == 'community_admin_festival' for item in view.children))

