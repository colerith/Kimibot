import asyncio
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from cogs.points import storage as points
from cogs.promotion import storage as store
from cogs.promotion import views
from cogs.promotion.cog import PromotionCog
from cogs.promotion.admin import PromotionAdminView, CopyModal, ChannelModal
from cogs.roles import surprise_storage
from test_surprise_lottery import StorageFixture


class PromotionStartupTests(unittest.TestCase):
    def test_extension_setup_without_running_event_loop(self):
        from cogs.promotion import setup
        with self.assertRaises(RuntimeError):
            asyncio.get_running_loop()
        bot = SimpleNamespace(add_cog=Mock(), add_view=Mock())
        setup(bot)
        cog = bot.add_cog.call_args.args[0]
        self.assertIsInstance(cog, PromotionCog)
        self.assertFalse(cog.worker.is_running())
        bot.add_view.assert_not_called()
        cog.cog_unload()


class PromotionFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in [('POINTS_DB_FILE', str(Path(self.tmp.name) / 'points.sqlite3')),
                            ('POINTS_DATA_FILE', str(Path(self.tmp.name) / 'points.json')),
                            ('_POINTS_DB_READY', False)]:
            p = patch.object(points, name, value)
            p.start()
            self.addCleanup(p.stop)
        store.initialize()

    def create(self, user=7, request='one', now=None):
        return store.create(user, 9, request, '使用感想超过三十字。' * 5,
                            ['first.png', 'last.png'], '小蛋', now)


class PromotionStorageTests(PromotionFixture, unittest.TestCase):
    def test_configuration_persists_and_historical_channels_stay_fixed(self):
        old = self.create()
        store.save_settings({'channel_id': 12345, 'application_channel_id': 12345, 'log_channel_id': 67890, 'title': '晋升新文案'})
        points._POINTS_DB_READY = False
        self.assertEqual(store.settings()['title'], '晋升新文案')
        new = self.create(user=8, request='new-channel')
        self.assertEqual(store.get(old['id'])['channel_id'], store.APPLICATION_CHANNEL_ID)
        self.assertEqual(new['channel_id'], 12345)
        store.panel('entry', 1)
        store.panel('entry', 2, channel_id=12345)
        self.assertEqual(store.panel('entry'), 1)
        self.assertEqual(store.panel('entry', channel_id=12345), 2)
        with self.assertRaises(ValueError):
            store.save_settings({'title': 'x' * 257})
        self.assertEqual(store.settings()['title'], '晋升新文案')

    def test_statistics_separate_tests_from_formal_records(self):
        row = self.create()
        store.update(row['id'], status='pending')
        store.decide(row['id'], 1, False, '材料不完整')
        trial = store.create(8, 9, 'trial', '测试感想' * 10, ['a', 'b'], '管理员', is_test=True)
        store.update(trial['id'], status='approved', dm_state='blocked')
        stats = store.statistics(9)
        self.assertEqual(stats['total']['rejected'], 1)
        self.assertEqual(stats['tests']['approved'], 1)
        self.assertEqual(stats['used'], 1)
        self.assertEqual(stats['dm_failed'], 1)

    def test_staff_detection_uses_owner_or_administrator_permission(self):
        member = SimpleNamespace(id=1, bot=False, guild=SimpleNamespace(owner_id=1),
                                 roles=[], guild_permissions=SimpleNamespace(administrator=False))
        self.assertTrue(store.auto_eligible(member))
        member.id = 2
        self.assertFalse(store.auto_eligible(member))
        member.guild_permissions.administrator = True
        self.assertTrue(store.auto_eligible(member))
        member.bot = True
        self.assertFalse(store.auto_eligible(member))

    def test_test_application_ignores_full_quota_and_existing_benefits(self):
        store.activate(7, 9)
        with patch.object(store, '_quota', return_value=100):
            row = store.create(7, 9, 'staff', '测试感想' * 10, ['a', 'b'], '管理员', is_test=True)
        self.assertTrue(row['is_test'])
        self.assertEqual(store.quota(9), 0)
        with self.assertRaises(ValueError):
            store.create(7, 9, 'staff-pending', '测试感想' * 10, ['a', 'b'], '管理员', is_test=True)
        store.update(row['id'], status='pending')
        store.decide(row['id'], 1, True)
        store.complete(row['id'])
        self.assertEqual(points.get_user_points(7, 9), 130)
        second = store.create(7, 9, 'staff-again', '测试感想' * 10, ['a', 'b'], '管理员', is_test=True)
        self.assertNotEqual(row['id'], second['id'])
        self.assertEqual(store.quota(9), 0)
        self.create(user=8, request='ordinary')
        self.assertEqual(store.quota(9), 1)

    def test_backfill_and_daily_are_atomic_once_even_after_restart(self):
        day = datetime(2026, 10, 24, 23, 59, tzinfo=points.TZ_CN)
        with ThreadPoolExecutor(max_workers=4) as executor:
            granted = list(executor.map(lambda _: store.activate(7, 9, day), range(8)))
        self.assertEqual(sum(granted), 1)
        self.assertEqual(points.get_user_points(7, 9), 130)
        points._POINTS_DB_READY = False
        store.settle_daily(day + timedelta(minutes=2))
        self.assertEqual(points.get_user_points(7, 9), 160)
        store.settle_daily(day + timedelta(minutes=3))
        self.assertEqual(points.get_user_points(7, 9), 160)
        store.settle_daily(day + timedelta(days=3))
        self.assertEqual(points.get_user_points(7, 9), 220)
        points.save_points_data(points.load_points_data())
        self.assertFalse(store.activate(7, 9, day + timedelta(days=3)))
        self.assertEqual(store.quote(7, 9, 10), 8)
        self.assertEqual(store.quote(7, 10, 10), 10)

    def test_quota_concurrent_and_beijing_midnight(self):
        before = datetime(2026, 10, 24, 15, 59, tzinfo=timezone.utc)
        with ThreadPoolExecutor(max_workers=8) as executor:
            def attempt(user):
                try:
                    return self.create(user, str(user), before)
                except ValueError:
                    return None
            rows = list(executor.map(attempt, range(105)))
        self.assertEqual(sum(r is not None for r in rows), 100)
        self.assertEqual(store.quota(9, before), 100)
        after = before + timedelta(minutes=1)
        self.assertEqual(store.quota(9, after), 0)
        self.assertEqual(self.create(999, 'tomorrow', after)['batch'], '2026-10-25')

    def test_duplicate_submit_review_and_rejection(self):
        row = self.create()
        self.assertEqual(self.create()['id'], row['id'])
        self.assertEqual(store.quota(9), 1)
        with self.assertRaises(ValueError):
            self.create(request='different')
        store.update(row['id'], status='pending', message_id=123)
        with self.assertRaises(ValueError):
            store.decide(row['id'], 1, False, '  ')
        rejected = store.decide(row['id'], 1, False, '请补充首楼及楼层数。')
        self.assertEqual(rejected['status'], 'rejected')
        self.assertEqual(rejected['reason'], '请补充首楼及楼层数。')
        with self.assertRaises(ValueError):
            store.decide(row['id'], 1, True)
        self.assertEqual(points.get_user_points(7, 9), 0)
        second = self.create(request='retry')
        store.update(second['id'], status='pending')
        store.decide(second['id'], 1, True)
        self.assertEqual(points.get_user_points(7, 9), 0)
        store.complete(second['id'])
        store.complete(second['id'])
        self.assertEqual(points.get_user_points(7, 9), 130)

    def test_reward_failure_rolls_back_application_and_credit(self):
        row = self.create()
        store.update(row['id'], status='pending')
        store.decide(row['id'], 1, True)
        with patch.object(points, '_db_append_transaction', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                store.complete(row['id'])
        self.assertEqual(store.get(row['id'])['status'], 'granting')
        self.assertEqual(points.get_user_points(7, 9), 0)
        store.complete(row['id'])
        self.assertEqual(points.get_user_points(7, 9), 130)

    def test_discounts_apply_only_to_role_spends_and_receipt_once(self):
        store.activate(7, 9)
        for source in ('role_lottery', 'role_redeem'):
            result = points.spend_user_points(7, 10, 9, source=source, operation_id=source)
            self.assertEqual(result['cost'], 8)
            self.assertEqual(points.spend_user_points(7, 10, 9, source=source, operation_id=source), result)
        self.assertEqual(points.spend_user_points(7, 10, 9, source='monthly_card_purchase')['cost'], 10)
        self.assertEqual(points.get_user_points(7, 9), 104)
        self.assertEqual(store.quote(7, 9, 1), 0.8)

    def test_form_validation_before_reserving_quota(self):
        for content, files in [('a ' * 29, ['a', 'b']), ('感想' * 30, ['a'])]:
            with self.assertRaises(ValueError):
                store.create(7, 9, 'bad', content, files, 'name')
        self.assertEqual(store.quota(9), 0)


class PromotionSurpriseTests(StorageFixture, unittest.TestCase):
    def test_surprise_ten_draws_cost_eight_and_receipt_replay(self):
        store.activate(7, 9)
        before = points.get_user_points(7, 9)
        result = surprise_storage.settle_spin(7, 9, 'discount-ten', {1}, draw_count=10)
        self.assertEqual(result['cost'], 8)
        self.assertTrue(all(r['cost'] == 0.8 for r in result['results']))
        self.assertEqual(result['balance'], before - 8)
        self.assertEqual(surprise_storage.settle_spin(7, 9, 'discount-ten', {1}, draw_count=10), result)
        self.assertEqual(points.get_user_points(7, 9), before - 8)


class PromotionUITests(PromotionFixture, unittest.IsolatedAsyncioTestCase):
    async def test_application_card_groups_images_and_keeps_review_actions(self):
        row = self.create()
        row.update(status='pending', content='感想\n-# 小蛋晋升申请 #999 · 北京时间')
        card = views.ApplicationCard(row, ['attachment://first.png', 'attachment://last.png'])
        components = card.to_components()
        self.assertEqual(components[0]['type'], 17)
        galleries = [c for c in components[0]['components'] if c['type'] == 12]
        self.assertEqual(len(galleries), 1)
        self.assertEqual(len(galleries[0]['items']), 2)
        self.assertTrue(card.is_components_v2())
        self.assertTrue(card.is_persistent())
        self.assertEqual([b['custom_id'] for b in components[1]['components']], ['promotion:approve', 'promotion:reject'])
        message = SimpleNamespace(embeds=[], components=components)
        self.assertEqual(views.message_application_id(message), row['id'])
        row.update(status='rejected', reason='请补充首楼截图。')
        rejected = views.ApplicationCard(row, ['attachment://first.png']).to_components()
        self.assertEqual(len(rejected), 1)
        self.assertIn('请补充首楼截图', str(rejected))

    async def test_legacy_card_upgrades_in_place_with_original_attachments(self):
        row = self.create()
        row = store.update(row['id'], status='pending', message_id=123, card_dirty=False)
        message = SimpleNamespace(embeds=[views.application_embed(row)],
            attachments=[SimpleNamespace(filename='first.png'), SimpleNamespace(filename='last.png')], edit=AsyncMock())
        cog = PromotionCog.__new__(PromotionCog)
        cog.bot = SimpleNamespace(get_guild=lambda _: SimpleNamespace())
        cog.channel = AsyncMock(return_value=SimpleNamespace(fetch_message=AsyncMock(return_value=message)))
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        self.assertEqual(views.message_application_id(message), row['id'])
        await cog.process(row)
        kwargs = message.edit.call_args.kwargs
        self.assertEqual(kwargs['embeds'], [])
        self.assertIsNone(kwargs['content'])
        self.assertIn('attachment://last.png', str(kwargs['view'].to_components()))
        self.assertEqual(store.get(row['id'])['layout_version'], 2)
        await cog.process(store.get(row['id']))
        message.edit.assert_awaited_once()

    async def test_ready_registers_views_and_starts_worker_only_once(self):
        bot = SimpleNamespace(add_view=Mock())
        cog = PromotionCog(bot)
        with patch.object(cog.worker, 'is_running', side_effect=[False, True]), patch.object(cog.worker, 'start') as start:
            await cog.on_ready()
            await cog.on_ready()
        self.assertEqual(bot.add_view.call_count, 2)
        start.assert_called_once()
        self.assertTrue(all(view.is_persistent() for view in cog.persistent_views))
        cog.cog_unload()
        self.assertTrue(all(view.is_finished() for view in cog.persistent_views))

    async def test_worker_publishes_panel_before_member_backfill(self):
        guild = SimpleNamespace(id=9, chunked=False, chunk=AsyncMock(side_effect=RuntimeError('chunk timeout')))
        cog = PromotionCog(SimpleNamespace(add_view=Mock()))
        cog.channel = AsyncMock(return_value=SimpleNamespace(guild=guild))
        cog.refresh_panels = AsyncMock()
        cog.report = Mock()
        await cog.worker()
        cog.refresh_panels.assert_awaited_once()
        cog.report.assert_called_once()
        self.assertFalse(cog.backfilled)
        cog.cog_unload()

    async def test_admin_dashboard_edit_forms_and_history_links(self):
        cog = SimpleNamespace(channel=AsyncMock(return_value=SimpleNamespace(guild=SimpleNamespace(id=9))))
        panel = PromotionAdminView(cog, 7, 9)
        embed = await panel.embed()
        self.assertIn('管理控制台', embed.title)
        self.assertEqual(len(CopyModal(panel).children), 5)
        self.assertEqual(len(ChannelModal(panel).children), 3)
        edited = views.entry_embed(12, {'title': '自定义标题', 'requirements': '新的条件说明'})
        self.assertEqual(edited.title, '自定义标题')
        self.assertEqual(edited.fields[1].value, '新的条件说明')
        row = self.create()
        row.update(message_id=987, channel_id=456)
        self.assertTrue(views.jump_view(row).children[0].url.endswith('/456/987'))
        self.assertTrue(views.BottomView(row).children[0].url.endswith('/456/987'))

    async def test_configure_retires_only_old_entry_and_navigation(self):
        cog = PromotionCog.__new__(PromotionCog)
        cog.panel_lock = asyncio.Lock()
        cog.backfilled = True
        entry = SimpleNamespace(edit=AsyncMock())
        bottom = SimpleNamespace(delete=AsyncMock())
        channel = SimpleNamespace(get_partial_message=lambda mid: entry if mid == 11 else bottom)
        cog.channel = AsyncMock(return_value=channel)
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        store.panel('entry', 11)
        store.panel('bottom', 12, channel_id=store.APPLICATION_CHANNEL_ID)
        old = self.create()
        await cog.configure({'channel_id': 456, 'application_channel_id': 789})
        entry.edit.assert_awaited_once()
        bottom.delete.assert_awaited_once()
        self.assertIn('<#456>', entry.edit.call_args.kwargs['content'])
        self.assertEqual(store.get(old['id'])['channel_id'], store.APPLICATION_CHANNEL_ID)
        self.assertFalse(cog.backfilled)

    async def test_refresh_uses_configured_channel_copy_and_old_pending_link(self):
        old = self.create()
        store.update(old['id'], status='pending', message_id=777)
        store.save_settings({'channel_id': 456, 'application_channel_id': 789, 'title': '新的晋升标题'})
        cog = PromotionCog.__new__(PromotionCog)
        cog.panel_lock = asyncio.Lock()
        cog.entry_signature = cog.panel_signature = None
        entry = SimpleNamespace(id=456, guild=SimpleNamespace(id=9), last_message_id=0)
        records = SimpleNamespace(id=789, guild=entry.guild, last_message_id=0)
        sent = []
        async def entry_send(**kwargs):
            sent.append((456, kwargs))
            entry.last_message_id = 1
            return SimpleNamespace(id=1)
        async def records_send(**kwargs):
            sent.append((789, kwargs))
            records.last_message_id = 2
            return SimpleNamespace(id=2)
        entry.send, records.send = entry_send, records_send
        cog.channel = AsyncMock(side_effect=lambda cid: entry if cid == 456 else records)
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        await cog.refresh_panels()
        self.assertEqual(sent[0][0], 456)
        self.assertEqual(sent[1][0], 789)
        self.assertEqual(sent[0][1]['embed'].title, '新的晋升标题')
        self.assertEqual(store.panel('entry', channel_id=456), 1)
        self.assertEqual(store.panel('bottom', channel_id=789), 2)
        self.assertIn(f'/{store.APPLICATION_CHANNEL_ID}/777', sent[1][1]['view'].children[0].url)
        await cog.refresh_panels()
        self.assertEqual(len(sent), 2)

    async def test_public_copy_removes_retired_test_notes_even_when_saved(self):
        embed = views.entry_embed(0, {'notes': '原有说明\n管理员 / 服主自动享有权益；其申请标记为测试记录，不占名额。'})
        text = str(embed.to_dict())
        self.assertNotIn('测试记录不占名额', text)
        self.assertNotIn('管理员 / 服主自动享有权益', text)
        self.assertEqual(embed.fields[2].value, '原有说明')
        self.assertEqual(self.create()['channel_id'], 1563529208943083540)

    async def test_archived_thread_is_reopened_before_sending(self):
        cog = PromotionCog.__new__(PromotionCog)
        thread = Mock(spec=discord.Thread)
        thread.archived, thread.locked = True, False
        thread.edit = AsyncMock()
        cog.channel = AsyncMock(return_value=thread)
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        self.assertIs(await cog.destination(store.APPLICATION_CHANNEL_ID), thread)
        self.assertFalse(thread.edit.call_args.kwargs['archived'])
        thread.locked = True
        with self.assertRaises(ValueError):
            await cog.destination(store.APPLICATION_CHANNEL_ID)
        thread.edit.assert_awaited_once()

    async def test_admin_callbacks_reject_other_users(self):
        panel = PromotionAdminView(SimpleNamespace(), 7, 9)
        interaction = SimpleNamespace(guild_id=9, user=SimpleNamespace(id=8),
                                      response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await panel.interaction_check(interaction))
        interaction.response.send_message.assert_awaited_once()

    async def test_test_approval_does_not_assign_role_or_award_shells(self):
        row = store.create(7, 9, 'test-only', '测试感想' * 10, ['a', 'b'], '管理员', is_test=True)
        store.update(row['id'], status='pending')
        row = store.decide(row['id'], 1, True)
        cog = PromotionCog.__new__(PromotionCog)
        guild = SimpleNamespace(get_member=Mock(side_effect=AssertionError('test must not grant role')))
        cog.bot = SimpleNamespace(get_guild=lambda _: guild)
        # Stop after completing the decision, before unrelated notification delivery.
        cog.channel = AsyncMock(side_effect=RuntimeError('notification offline'))
        cog.bot.get_user = Mock(return_value=SimpleNamespace(send=AsyncMock()))
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        with self.assertRaises(RuntimeError):
            await cog.process(row)
        result = store.get(row['id'])
        self.assertEqual(result['status'], 'approved')
        self.assertEqual(points.get_user_points(7, 9), 0)
        self.assertIn('测试记录', views.application_embed(result).description)
        self.assertIn('测试审批结果', views.result_embed(result).title)

    async def test_form_buttons_and_permissions(self):
        modal = views.PromotionModal()
        payload = modal.to_dict()
        self.assertEqual(modal.uploads.min_values, 2)
        self.assertEqual(modal.thoughts.min_length, 30)
        self.assertIn('components', payload)
        review = views.ReviewView()
        self.assertEqual([b.label for b in review.children], ['通过申请', '驳回申请'])
        interaction = SimpleNamespace(user=SimpleNamespace(id=2), guild=SimpleNamespace(owner_id=1),
                                      response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await review.interaction_check(interaction))
        interaction.user.id = 1
        self.assertTrue(await review.interaction_check(interaction))
        self.assertTrue(views.RejectModal(1).reason.required)

    async def test_failed_role_grant_stays_recoverable_without_credit(self):
        row = self.create()
        store.update(row['id'], status='pending')
        row = store.decide(row['id'], 1, True)
        cog = PromotionCog.__new__(PromotionCog)
        member = SimpleNamespace(roles=[], add_roles=AsyncMock(side_effect=RuntimeError('network')))
        guild = SimpleNamespace(get_member=lambda _: member, get_role=lambda _: SimpleNamespace(id=store.ROLE_ID))
        cog.bot = SimpleNamespace(get_guild=lambda _: guild)
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        with self.assertRaises(RuntimeError):
            await cog.process(row)
        self.assertEqual(store.get(row['id'])['status'], 'granting')
        self.assertEqual(points.get_user_points(7, 9), 0)

    async def test_earliest_navigation_and_cards_fit_limits(self):
        row = self.create()
        row.update(status='pending', message_id=123)
        view = views.BottomView(row)
        self.assertTrue(view.children[0].url.endswith('/123'))
        for embed in (views.entry_embed(100), views.application_embed(row)):
            self.assertLessEqual(len(embed), 6000)
            self.assertTrue(all(len(f.value) <= 1024 for f in embed.fields))

    async def test_approval_delivers_role_logs_and_dm_once(self):
        row = self.create()
        store.update(row['id'], status='pending', message_id=123)
        row = store.decide(row['id'], 1, True)
        cog = PromotionCog.__new__(PromotionCog)
        role = SimpleNamespace(id=store.ROLE_ID)
        member = SimpleNamespace(roles=[], add_roles=AsyncMock(), send=AsyncMock())
        guild = SimpleNamespace(get_member=lambda _: member, get_role=lambda _: role)
        card = SimpleNamespace(embeds=[views.application_embed(row)], edit=AsyncMock())
        log_message = SimpleNamespace(id=456, edit=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=card))
        log_channel = SimpleNamespace(send=AsyncMock(return_value=log_message),
                                      fetch_message=AsyncMock(return_value=log_message))
        cog.bot = SimpleNamespace(get_guild=lambda _: guild, get_user=lambda _: member)
        cog.channel = AsyncMock(side_effect=lambda cid: channel if cid == store.APPLICATION_CHANNEL_ID else log_channel)
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        await cog.process(row)
        completed = store.get(row['id'])
        self.assertEqual(completed['status'], 'approved')
        self.assertEqual(completed['dm_state'], 'sent')
        self.assertEqual(points.get_user_points(7, 9), 130)
        await cog.process(completed)
        member.add_roles.assert_awaited_once()
        member.send.assert_awaited_once()
        log_channel.send.assert_awaited_once()

    async def test_log_failure_does_not_block_rejection_dm(self):
        row = self.create()
        store.update(row['id'], status='pending', card_dirty=False)
        row = store.decide(row['id'], 1, False, '截图未展示首楼，请补充。')
        cog = PromotionCog.__new__(PromotionCog)
        member = SimpleNamespace(send=AsyncMock())
        cog.bot = SimpleNamespace(get_guild=lambda _: SimpleNamespace(), get_user=lambda _: member)
        cog.channel = AsyncMock(side_effect=RuntimeError('log unavailable'))
        async def api(operation, *args, **kwargs):
            return await operation(*args, **kwargs)
        cog.api = api
        with self.assertRaises(RuntimeError):
            await cog.process(row)
        member.send.assert_awaited_once()
        self.assertEqual(store.get(row['id'])['dm_state'], 'sent')
        self.assertEqual(store.get(row['id'])['log_state'], 'pending')
        self.assertIn('截图未展示首楼', member.send.call_args.kwargs['embed'].fields[1].value)

    async def test_shared_lane_serializes_requests(self):
        cog = PromotionCog.__new__(PromotionCog)
        cog.api_lock = asyncio.Lock()
        cog.next_request = 0
        stamps = []
        async def request():
            import time
            stamps.append(time.monotonic())
        await asyncio.gather(cog.api(request), cog.api(request))
        self.assertGreaterEqual(stamps[1] - stamps[0], 0.99)
