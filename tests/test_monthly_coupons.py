import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from concurrent.futures import ThreadPoolExecutor

from cogs.points import storage as points
from cogs.roles import storage as roles
from cogs.roles import coupons


class MonthlyCouponTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for module, names in [(points, ['POINTS_DATA_FILE', 'POINTS_DB_FILE']), (roles, ['ROLES_DATA_FILE', 'ROLE_STATE_DB_FILE', 'COLLECTIONS_DATA_FILE', 'LOTTERY_STATS_DATA_FILE', 'REDEEM_OWNERSHIP_DATA_FILE'])]:
            for name in names:
                patcher = patch.object(module, name, str(root / Path(getattr(module, name)).name))
                patcher.start(); self.addCleanup(patcher.stop)
        for module, name, value in [(points, '_POINTS_DB_READY', False), (roles, '_role_state_ready', False), (roles, '_role_data_cache', None), (roles, '_role_data_cache_mtime_ns', -1)]:
            patcher = patch.object(module, name, value); patcher.start(); self.addCleanup(patcher.stop)
        roles.save_role_data({'lottery_roles': [1, 2, 3], 'redeem_roles': [4], 'lottery_role_meta': {'1': {'rarity': 2}, '2': {'rarity': 2}, '3': {'rarity': 3}}})

    def seed(self, coupons_count=2):
        data = points.load_points_data()
        data['users']['9:7'] = {'shells': 100, 'monthly_two_star_coupons': coupons_count}
        points.save_points_data(data)

    def test_historical_backfill_deduplicates_sources_and_restart(self):
        data = points.load_points_data()
        purchase = dict(purchase_id='p1', purchased_at='2026-01-01T00:00:00+08:00', starts_at='2026-01-01T00:00:00+08:00', expires_at='2026-02-01T00:00:00+08:00')
        data['users']['9:7'] = {'shells': 100, 'monthly_card_ever_purchased': True, 'monthly_card_periods': [purchase], 'monthly_card_purchases': [purchase]}
        data['monthly_card_purchases'] = [dict(purchase, user_id='7', guild_id='9'), dict(purchase, purchase_id='p2', user_id='7', guild_id='9')]
        data['transactions'] = [dict(time=purchase['purchased_at'], user_id='7', guild_id='9', amount=-30, balance=100, source='monthly_card_purchase', reason='purchase_id=p1'), dict(time='2026-03-01', user_id='7', guild_id='9', amount=-30, balance=100, source='monthly_card_purchase', reason='purchase_id=p3')]
        points.save_points_data(data)
        report = points.backfill_monthly_coupons()
        self.assertEqual(report['coupons'], 3)
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 3)
        points._POINTS_DB_READY = False
        self.assertTrue(points.backfill_monthly_coupons()['already_done'])
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 3)

    def test_purchase_grants_exactly_one_and_failure_grants_none(self):
        self.seed(0)
        result = points.purchase_monthly_card(7, 9)
        self.assertTrue(result['success'])
        self.assertEqual(result['coupon_granted'], 1)
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 1)
        self.assertTrue(points.purchase_monthly_card(7, 9)["success"])
        self.assertEqual(points.get_monthly_coupon_record(7, 9)["balance"], 2)
        points.modify_user_points(7, -10000, 9)
        self.assertFalse(points.purchase_monthly_card(7, 9)['success'])
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 2)

    def test_role_claim_idempotency_and_fallback(self):
        self.seed()
        result = coupons.redeem_coupon(7, 9, 'r1', 1, [1,2,3,4])
        self.assertTrue(result['success'])
        self.assertIn(1, roles.get_user_collection(7))
        self.assertTrue(coupons.redeem_coupon(7, 9, 'r1', 1, [1,2,3,4])['duplicate'])
        self.assertFalse(coupons.redeem_coupon(7, 9, 'bad', 4, [1,2,3,4])['success'])
        self.assertFalse(coupons.redeem_coupon(7, 9, 'bad', 0, [1,2,3,4])['success'])
        roles.add_to_collection(7, 2)
        before = points.get_user_points(7, 9)
        self.assertTrue(coupons.redeem_coupon(7, 9, 'cash', 0, [1,2,3,4])['success'])
        self.assertEqual(points.get_user_points(7, 9), before + 10)
        coupons.redeem_coupon(7, 9, 'cash', 0, [1,2,3,4])
        self.assertEqual(points.get_user_points(7, 9), before + 10)
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 0)

    def test_delivery_recovers_after_interruption(self):
        self.seed(1)
        with patch.object(roles, 'add_to_collection', side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):
                coupons.redeem_coupon(7, 9, 'recover', 1, [1,2])
        coupons.initialize_monthly_coupons()
        self.assertIn(1, roles.get_user_collection(7))
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 0)

    def test_concurrent_views_cannot_double_spend_or_duplicate_role(self):
        self.seed(1)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda key: coupons.redeem_coupon(7, 9, key, 1, [1,2]), ['a', 'b']))
        self.assertEqual(sum(r['success'] for r in results), 1)
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 0)

    def test_empty_pool_keeps_coupon(self):
        self.seed(1)
        self.assertFalse(coupons.redeem_coupon(7, 9, 'empty', 0, [])['success'])
        self.assertEqual(points.get_monthly_coupon_record(7, 9)['balance'], 1)

    def test_redeem_roles_survive_collection_config_and_complete_group(self):
        data = roles.load_role_data()
        data['collection_config'] = {'groups': [{'id': 'g', 'name': 'mixed', 'role_ids': [1,4], 'reward_shells': 5}]}
        roles.save_role_data(data)
        self.assertEqual(roles.get_collection_config()['groups'][0]['role_ids'], [1,4])
        with patch.object(roles, 'load_collection_reward_claims', return_value={}), patch.object(roles, '_save_collection_reward_claims'):
            rewards = roles.claim_completed_collection_rewards(7, [1,4])
        self.assertEqual([r['id'] for r in rewards], ['g'])


class CouponFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_required_and_reselection_clears_confirmation(self):
        guild = SimpleNamespace(get_role=lambda rid: SimpleNamespace(name=str(rid), position=rid))
        panel = coupons.CouponView(guild, 7, {'balance': 1}, {1,2}, {1,2})
        interaction = SimpleNamespace(response=SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock()))
        await panel.finish.callback(interaction)
        interaction.response.send_message.assert_awaited_once()
        select = next(c for c in panel.children if isinstance(c, coupons.CouponSelect))
        select._interaction = SimpleNamespace(data={})
        select._selected_values = ['1']
        await select.callback(interaction)
        self.assertTrue(panel.finish.disabled)
        await panel.confirm.callback(interaction)
        self.assertEqual(panel.confirmed, 1)
        self.assertFalse(panel.finish.disabled)
        select = next(c for c in panel.children if isinstance(c, coupons.CouponSelect))
        select._interaction = SimpleNamespace(data={})
        select._selected_values = ['2']
        await select.callback(interaction)
        self.assertIsNone(panel.confirmed)
        self.assertTrue(panel.finish.disabled)


class RedeemCategoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_category_and_config_show_all_pages(self):
        import discord
        from cogs.roles.views import RolePoolManagerView, RedeemManagerView, RedeemConfigSelect, CollectionAdminView
        guild = SimpleNamespace(id=999, roles=[], members=[])
        guild.roles = [discord.Role(guild=guild, state=SimpleNamespace(), data={
            'id': str(i), 'name': str(i), 'position': i, 'permissions': '0',
            'colors': {'primary_color': 0, 'secondary_color': None, 'tertiary_color': None},
            'color': 0, 'hoist': False, 'managed': False, 'mentionable': False}) for i in range(1,31)]
        guild.get_role = lambda rid: next((r for r in guild.roles if r.id == rid), None)
        parent = SimpleNamespace(guild=guild)
        data = {'redeem_roles': list(range(1,31)), 'lottery_roles': []}
        with patch('cogs.roles.views.load_role_data', return_value=data):
            panel = RolePoolManagerView(parent, 'redeem')
            self.assertEqual(panel.pool_type, 'redeem')
            self.assertTrue(any(getattr(c, 'action', '') == 'redeem_config' for c in panel.children))
            for row in range(5):
                width = sum(5 if isinstance(c, discord.ui.Select) else 1 for c in panel.children if c.row == row)
                self.assertLessEqual(width, 5)
            config = RedeemManagerView(parent, guild)
            self.assertEqual(config.total_pages, 2)
            config.page = 1
            config.refresh_items()
            select = next(c for c in config.children if isinstance(c, RedeemConfigSelect))
            self.assertEqual(len(select.options), 5)
            self.assertEqual({int(o.value) for o in select.options}, {1,2,3,4,5})
