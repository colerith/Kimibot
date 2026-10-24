import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from cogs.weekly_invite import storage as store
from cogs.weekly_invite.cog import WeeklyInviteCog, PANEL_FOOTER


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=store.TZ)


def state():
    return dict(enabled=True, pauses=[], title='邀请', copy=store.DEFAULT_COPY,
                invite=None, attempt=None, message_id=None)


class CalendarTests(unittest.TestCase):
    def test_boundaries(self):
        for date, allowed in [('2026-10-26T00:00', True), ('2026-10-30T23:59', True),
                              ('2026-10-31T00:00', False), ('2026-11-01T23:59', False)]:
            self.assertEqual(store.creation_allowed(state(), at(date)), allowed)

    def test_pause_inclusive_and_disabled(self):
        value = state()
        value['pauses'] = store.parse_pauses('2026-10-26 ~ 2026-10-27')
        self.assertFalse(store.creation_allowed(value, at('2026-10-27T23:59')))
        self.assertTrue(store.creation_allowed(value, at('2026-10-28T00:00')))
        value['enabled'] = False
        self.assertFalse(store.creation_allowed(value, at('2026-10-28T00:00')))
        with self.assertRaises(ValueError):
            store.parse_pauses('2026-10-28 ~ 2026-10-27')

    def test_setup_without_running_loop(self):
        from cogs.weekly_invite import setup
        with self.assertRaises(RuntimeError):
            asyncio.get_running_loop()
        bot = SimpleNamespace(add_cog=Mock())
        setup(bot)
        self.assertFalse(bot.add_cog.call_args.args[0].worker.is_running())


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.value = state()
        self.message = SimpleNamespace(id=22, edit=AsyncMock(), delete=AsyncMock())
        self.channel = SimpleNamespace(create_invite=AsyncMock(return_value=SimpleNamespace(code='abc', url='https://discord.gg/abc')),
            send=AsyncMock(return_value=self.message), fetch_message=AsyncMock(return_value=self.message),
            invites=AsyncMock(return_value=[]), get_partial_message=Mock(return_value=self.message))
        self.remote = SimpleNamespace(delete=AsyncMock())
        self.bot = SimpleNamespace(get_channel=Mock(return_value=self.channel), user=SimpleNamespace(id=1),
                                   fetch_invite=AsyncMock(return_value=self.remote))
        self.cog = WeeklyInviteCog(self.bot)
        async def api(fn, *args, **kwargs):
            return await fn(*args, **kwargs)
        self.cog.api = api
        self.patches = [patch.object(store, 'now', return_value=at('2026-10-28T12:00')),
                        patch.object(store, 'load', side_effect=lambda: self.value), patch.object(store, 'save')]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()

    async def test_catchup_restart_no_duplicate(self):
        await self.cog.manage(send=True)
        self.assertEqual(self.channel.create_invite.call_args.kwargs['max_age'], 216000)
        self.assertEqual(self.channel.create_invite.call_args.kwargs['max_uses'], 0)
        self.cog.signature = None
        await self.cog.manage(send=True)
        self.channel.create_invite.assert_awaited_once()
        self.channel.send.assert_awaited_once()

    async def test_pause_does_not_revoke_active_link(self):
        await self.cog.manage(send=True)
        await self.cog.manage(changes={'pauses': [['2026-10-28', '2026-10-30']]})
        self.remote.delete.assert_not_awaited()
        self.assertIsNotNone(self.value['invite'])

    async def test_revoke_stays_disabled(self):
        await self.cog.manage(send=True)
        await self.cog.manage(revoke=True)
        await self.cog.manage(changes={'title': '更新'})
        self.assertFalse(self.value['enabled'])
        self.remote.delete.assert_awaited_once()
        self.message.delete.assert_awaited_once()
        self.channel.create_invite.assert_awaited_once()

    async def test_unknown_creation_recovered(self):
        self.value['attempt'] = dict(started=at('2026-10-28T11:59').isoformat(),
                                    expires=at('2026-10-31T00:00').isoformat(), week='2026-10-26')
        self.channel.invites.return_value = [SimpleNamespace(inviter=self.bot.user,
            created_at=at('2026-10-28T11:59'), expires_at=at('2026-10-31T00:00'), code='old', url='https://discord.gg/old')]
        await self.cog.manage(send=True)
        self.channel.create_invite.assert_not_awaited()
        self.assertEqual(self.value['invite']['code'], 'old')

    async def test_uncertain_recovery_failure_does_not_create(self):
        self.value['attempt'] = {'started': 'unknown'}
        self.channel.invites.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            await self.cog.manage(send=True)
        self.channel.create_invite.assert_not_awaited()

    async def test_pause_blocks_manual_creation(self):
        self.value['pauses'] = [['2026-10-28', '2026-10-30']]
        await self.cog.manage(send=True)
        self.channel.create_invite.assert_not_awaited()
        self.channel.send.assert_awaited_once()

    async def test_interrupted_panel_send_recovers_message(self):
        self.value['panel_attempt'] = at('2026-10-28T11:59').isoformat()
        self.message.author = self.bot.user
        self.message.embeds = [SimpleNamespace(footer=SimpleNamespace(text=PANEL_FOOTER))]
        async def history(**kwargs):
            yield self.message
        self.channel.history = history
        await self.cog.manage(send=True)
        self.channel.send.assert_not_awaited()
        self.assertEqual(self.value['message_id'], self.message.id)
        self.assertIsNone(self.value['panel_attempt'])

    async def test_management_components_serialize(self):
        from cogs.weekly_invite.views import InviteAdminView, InviteCopyModal, PausesModal
        panel = InviteAdminView(self.cog, 1, 2)
        panel.state = self.value
        self.assertTrue(panel.to_components())
        self.assertTrue(InviteCopyModal(panel).to_dict())
        self.assertTrue(PausesModal(panel).to_dict())
