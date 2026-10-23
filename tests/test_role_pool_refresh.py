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



class LotteryConfigNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from cogs.roles import views
        self.views = views
        self.guild = SimpleNamespace(id=1000, roles=[])
        self.guild.roles = [discord.Role(guild=self.guild, state=SimpleNamespace(), data={
            "id": str(i), "name": f"role {100-i}", "position": i, "permissions": "0",
            "colors": {"primary_color": 0, "secondary_color": None, "tertiary_color": None},
            "color": 0, "hoist": False, "managed": False, "mentionable": False,
        }) for i in range(1, 31)]
        self.guild.get_role = lambda rid: next((r for r in self.guild.roles if r.id == rid), None)
        self.parent = SimpleNamespace(guild=self.guild, refresh_content=AsyncMock())
        self.data = {"lottery_roles": list(range(1, 31))}
        self.cfg = {"groups": [{"id": "group", "role_ids": [1, 30, 2]}], "full_reward": {}}
        for name, value in (("load_role_data", self.data), ("get_collection_config", self.cfg),
                            ("get_collectible_role_ids", list(range(1, 31)))):
            patcher = patch(f"cogs.roles.views.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.interaction = SimpleNamespace(guild=self.guild, user=SimpleNamespace(id=42),
            response=SimpleNamespace(edit_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: False),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    async def test_all_hub_children_return_to_hub(self):
        hub = self.views.LotteryConfigHubView(self.parent)
        for label in ("稀有度与类型", "图鉴与收集奖励", "限时 UP 池"):
            button = next(c for c in hub.children if c.label == label)
            with patch("cogs.roles.lottery_up.load_role_data", return_value=self.data):
                await button.callback(self.interaction)
                child = self.interaction.response.edit_message.await_args.kwargs["view"]
                back = next(c for c in child.children if "返回" in getattr(c, "label", ""))
                await back.callback(self.interaction)
            self.assertIs(self.interaction.response.edit_message.await_args.kwargs["view"], hub)
        self.parent.refresh_content.assert_not_awaited()

    async def test_lists_follow_server_order_across_pages(self):
        panel = self.views.LotteryRarityConfigView(self.parent, self.guild)
        self.assertEqual([int(o.value) for o in panel.all_options], list(range(30, 0, -1)))
        collection = self.views.CollectionAdminView(self.parent)
        collection.selected_id = "group"
        collection.rebuild()
        self.assertEqual(collection.current_page_ids, list(range(30, 5, -1)))
        collection.page = 1
        collection.rebuild()
        self.assertEqual(collection.current_page_ids, [5, 4, 3, 2, 1])
        embed = self.views._collection_admin_embed(self.guild, "group")
        self.assertEqual(embed.fields[1].value, "<@&30>\n<@&2>\n<@&1>")

    async def test_apply_retains_page_and_selection_and_refreshes_metadata(self):
        panel = self.views.LotteryRarityConfigView(self.parent, self.guild)
        panel.page = 1
        panel.selected_role_ids = [3, 2]
        panel.selected_rarity = self.views.RARITY_RARE
        panel.selected_kind = self.views.LOTTERY_KIND_ICON
        panel._build()
        button = next(c for c in panel.children if isinstance(c, self.views.LotteryRarityApplyButton))
        with patch("cogs.roles.views.set_lottery_role_rarity", return_value=True), patch("cogs.roles.views.set_lottery_role_kind", return_value=True), patch("cogs.roles.views.get_lottery_role_rarity", return_value=panel.selected_rarity), patch("cogs.roles.views.get_lottery_role_kind", return_value=panel.selected_kind):
            await button.callback(self.interaction)
        self.assertIs(self.interaction.edit_original_response.await_args.kwargs["view"], panel)
        self.assertEqual(panel.page, 1)
        select = next(c for c in panel.children if isinstance(c, self.views.LotteryRarityRoleSelect))
        self.assertEqual([int(o.value) for o in select.options if o.default], [3, 2])
        self.assertIn(self.views._rarity_label(panel.selected_rarity), select.options[0].description)
        self.parent.refresh_content.assert_not_awaited()
