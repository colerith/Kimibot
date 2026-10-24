import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from cogs.roles import views, surprise_storage

class WardrobeTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_categories_and_refresh_preserve_page(self):
        roles = [NS(id=n, name=f'女王蛋{n}', position=n) for n in range(1, 28)]
        panel = views.RoleSelectionView(roles, page=1)
        member = NS(id=7, roles=[roles[0]])
        guild = NS(id=9, fetch_member=AsyncMock(return_value=member))
        interaction = NS(user=NS(id=7), guild=guild, edit_original_response=AsyncMock())
        with patch.object(views, 'load_role_data', return_value={'lottery_roles': [1, 2]}), \
             patch.object(views, 'get_lottery_role_kind', side_effect=lambda rid, data: views.LOTTERY_KIND_COLOR if rid == 1 else views.LOTTERY_KIND_ICON), \
             patch.object(surprise_storage, 'get_account', return_value={'owned': [3]}), \
             patch.object(surprise_storage, 'get_config', return_value={'roles': {'3': {}}}):
            await panel.refresh(interaction)
            self.assertEqual(panel.page, 1)
            self.assertEqual(panel.categories[1], ('🎨', '颜色'))
            self.assertEqual(panel.categories[2], ('🏷️', '图标'))
            self.assertEqual(panel.categories[3], ('🎰', '惊喜抽奖'))
            options = {int(o.value): o for o in panel.children[0].options}
            self.assertEqual(str(options[1].emoji), '✅')
            self.assertEqual(str(options[2].emoji), '🏷️')
            member.roles = []
            await panel.refresh(interaction)
            options = {int(o.value): o for o in panel.children[0].options}
            self.assertEqual(str(options[1].emoji), '🎨')
            self.assertIn('没有佩戴', interaction.edit_original_response.call_args.kwargs['embed'].description)

    async def test_names_no_longer_guess_emoji(self):
        select = views.RoleClaimSelect([NS(id=1, name='暮色私语'), NS(id=2, name='女王蛋')],
            categories={1: ('🎨', '颜色'), 2: ('🎰', '惊喜抽奖')})
        self.assertEqual([str(o.emoji) for o in select.options], ['🎨', '🎰'])
