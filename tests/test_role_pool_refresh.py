import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import discord
from cogs.roles.views import RolePoolManagerView, RolePoolAddSelect, RolePoolBrowseButton


class RolePoolRefreshTests(unittest.IsolatedAsyncioTestCase):
    def role(self, rid, name=None, managed=False):
        return discord.Role(guild=self.guild, state=SimpleNamespace(), data={
            'id': str(rid), 'name': name or f'role {rid}', 'position': rid,
            'permissions': '0', 'colors': {'primary_color': 0, 'secondary_color': None, 'tertiary_color': None}, 'color': 0, 'hoist': False, 'managed': managed, 'mentionable': False})

    async def asyncSetUp(self):
        self.guild = SimpleNamespace(id=1000, roles=[], members=[])
        self.guild.roles = [self.role(i) for i in range(1, 31)]
        self.parent = SimpleNamespace(guild=self.guild)
        self.data = {'lottery_roles': [], 'redeem_roles': [2]}
        self.loader = patch('cogs.roles.views.load_role_data', side_effect=lambda: self.data)
        self.loader.start()
        self.addCleanup(self.loader.stop)

    async def test_search_pagination_and_exclusions(self):
        self.guild.roles += [self.role(1000), self.role(1001, managed=True)]
        panel = RolePoolManagerView(self.parent)
        self.assertEqual(panel.add_pages, 2)
        panel.add_page = 1
        panel.rebuild()
        self.assertEqual(len(panel.available_page_roles), 4)
        self.assertNotIn(2, [r.id for r in panel.available_page_roles])
        panel.add_query = 'role 30'
        panel.rebuild()
        self.assertEqual([r.id for r in panel.available_page_roles], [30])
        panel.add_query = '29'
        panel.rebuild()
        self.assertEqual([r.id for r in panel.available_page_roles], [29])
        panel.add_query = 'missing'
        panel.rebuild()
        self.assertFalse(any(isinstance(c, RolePoolAddSelect) for c in panel.children))

    async def test_refresh_then_add_role_missing_from_cache(self):
        panel = RolePoolManagerView(self.parent)
        new_role = self.role(99, 'new role')
        self.guild.fetch_roles = AsyncMock(return_value=[*self.guild.roles, new_role])
        interaction = SimpleNamespace(guild=self.guild, data={'values': ['99']},
            response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True, edit_message=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
        refresh = next(c for c in panel.children if isinstance(c, RolePoolBrowseButton) and c.action == 'refresh')
        await refresh.callback(interaction)
        self.assertIn(new_role, panel.available_page_roles)
        picker = next(c for c in panel.children if isinstance(c, RolePoolAddSelect))
        with patch('cogs.roles.views.save_role_data') as save:
            await picker.callback(interaction)
            save.assert_called_once()
        self.assertIn(99, self.data['lottery_roles'])
        self.assertIn(new_role, panel.page_roles)
        self.assertNotIn(new_role, panel.available_page_roles)
        for row in range(5):
            width = sum(5 if isinstance(c, discord.ui.Select) else 1 for c in panel.children if c.row == row)
            self.assertLessEqual(width, 5)

