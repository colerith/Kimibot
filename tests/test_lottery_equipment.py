import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from cogs.roles import views
from cogs.roles.surprise_views import equip_latest_surprise


class EquipmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_last_new_win_only(self):
        guild = NS(get_role=lambda rid: NS(id=rid))
        with patch.object(views, 'equip_decoration', new_callable=AsyncMock) as equip:
            await equip_latest_surprise(NS(), guild, {'results': [
                {'winner': 10, 'duplicate': False}, {'winner': 20, 'duplicate': False},
                {'winner': 30, 'duplicate': True}]})
            self.assertEqual(equip.await_count, 1)
            self.assertEqual(equip.call_args.args[2].id, 20)

    async def test_duplicate_does_not_change_outfit(self):
        with patch.object(views, 'equip_decoration', new_callable=AsyncMock) as equip:
            await equip_latest_surprise(NS(), NS(), {'winner': 10, 'duplicate': True})
            equip.assert_not_awaited()

    async def test_both_modes_remove_same_icons_preserve_other_roles(self):
        from cogs.roles import surprise_storage
        member = NS(id=1, roles=[NS(id=n) for n in [10, 20, 30, 40, 50]], remove_roles=AsyncMock())
        data = {'lottery_roles': [10, 40]}
        with patch.object(views, 'load_role_data', return_value=data), \
             patch.object(views, 'get_lottery_role_kind', side_effect=lambda rid, _: views.LOTTERY_KIND_COLOR if rid == 40 else views.LOTTERY_KIND_ICON), \
             patch.object(surprise_storage, 'get_account', return_value={'owned': [20]}), \
             patch.object(surprise_storage, 'get_config', return_value={'roles': {'30': {}}}):
            for kind in ['surprise', 'lottery_icon']:
                removed = await views.remove_all_decorations(member, NS(id=2), keep_role_id=30, exclusive_type=kind, strict=True)
                self.assertEqual([r.id for r in removed], [10, 20])

    async def test_cleanup_failure_prevents_add(self):
        member = NS(add_roles=AsyncMock())
        guild = NS(id=2, fetch_member=AsyncMock(return_value=member))
        with patch.object(views, 'remove_all_decorations', new_callable=AsyncMock, side_effect=RuntimeError('permission')):
            with self.assertRaises(RuntimeError):
                await views.equip_decoration(NS(id=1), guild, NS(id=10), 'surprise', 'test')
        member.add_roles.assert_not_awaited()

    async def test_concurrent_mode_changes_use_fresh_member_serially(self):
        member = NS(add_roles=AsyncMock())
        guild = NS(id=2, fetch_member=AsyncMock(return_value=member))
        events = []
        async def cleanup(*args, **kwargs):
            events.append(kwargs['keep_role_id'])
            await asyncio.sleep(0)
            return []
        async def add(role, **kwargs):
            events.append(-role.id)
        member.add_roles.side_effect = add
        with patch.object(views, 'remove_all_decorations', side_effect=cleanup):
            await asyncio.gather(*(views.equip_decoration(NS(id=1), guild, NS(id=n), kind, 'test')
                                  for n, kind in [(10, 'surprise'), (20, 'lottery_icon')]))
        self.assertEqual(events, [10, -10, 20, -20])
        self.assertEqual(guild.fetch_member.await_count, 2)
