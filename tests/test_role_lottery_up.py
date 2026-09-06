import unittest
from types import SimpleNamespace
from unittest.mock import patch
from cogs.roles.lottery_up import active_up_weights, parse_period, UpPoolView, get_up_groups, update_up_group
from cogs.roles.storage import _normalize_role_data
from cogs.roles.views import _pick_available_role


class UpPoolTests(unittest.TestCase):
    def setUp(self):
        self.data = {'lottery_roles': [1, 2], 'lottery_up': {'9': {
            'enabled': True, 'start': 100, 'end': 200, 'multiplier': 3, 'role_ids': [1, 99]}}}

    def test_period_boundaries_and_guild(self):
        self.assertEqual(active_up_weights(self.data, 9, 99), {})
        self.assertEqual(active_up_weights(self.data, 9, 100), {1: 3})
        self.assertEqual(active_up_weights(self.data, 9, 199), {1: 3})
        self.assertEqual(active_up_weights(self.data, 9, 200), {})
        self.assertEqual(active_up_weights(self.data, 8, 150), {})
        self.data['lottery_up']['9']['enabled'] = False
        self.assertEqual(active_up_weights(self.data, 9, 150), {})

    def test_normalization_preserves_schedule(self):
        normalized = _normalize_role_data(self.data)
        self.assertEqual(active_up_weights(normalized, 9, 150), {1: 3})

    def test_multiple_groups_overlap_and_expiry(self):
        legacy = self.data['lottery_up']['9']
        self.data['lottery_up']['9'] = {'groups': [
            dict(legacy, id='a'),
            dict(legacy, id='b', multiplier=5, role_ids=[1, 2], end=170),
            dict(legacy, id='c', multiplier=9, enabled=False),
        ]}
        self.assertEqual(active_up_weights(self.data, 9, 150), {1: 5, 2: 5})
        self.assertEqual(active_up_weights(self.data, 9, 170), {1: 3})
        self.assertEqual(active_up_weights(_normalize_role_data(self.data), 9, 150), {1: 5, 2: 5})

    def test_group_crud_migration_and_stale_panel(self):
        with patch('cogs.roles.lottery_up.load_role_data', side_effect=lambda: self.data), patch('cogs.roles.lottery_up.save_role_data'):
            legacy = get_up_groups(self.data, 9)[0]
            self.assertEqual(legacy['id'], 'legacy')
            update_up_group(9, 'new', cfg=dict(legacy, name='second', role_ids=[2]), creating=True)
            self.assertEqual(len(get_up_groups(self.data, 9)), 2)
            update_up_group(9, 'new', cfg=dict(legacy, name='edited', multiplier=7, role_ids=[2]))
            self.assertEqual(active_up_weights(self.data, 9, 150), {1: 3, 2: 7})
            update_up_group(9, 'legacy', stop=True)
            self.assertEqual(active_up_weights(self.data, 9, 150), {2: 7})
            update_up_group(9, 'new', delete=True)
            self.assertEqual(len(get_up_groups(self.data, 9)), 1)
            self.assertEqual(active_up_weights(self.data, 9, 150), {})
            with self.assertRaises(ValueError):
                update_up_group(9, 'new', cfg=legacy)
            update_up_group(9, 'legacy', delete=True)
            self.assertEqual(get_up_groups(self.data, 9), [])

    def test_validation(self):
        start, end, factor = parse_period('2026-09-06 08:00', '2026-09-06 09:00', '2')
        self.assertEqual(end-start, 3600)
        from datetime import datetime, timezone
        self.assertEqual(datetime.fromtimestamp(start, timezone.utc).hour, 0)
        for value in ['nan', 'inf', '1', '-2', '101']:
            with self.assertRaises(ValueError):
                parse_period('2026-09-06 08:00', '2026-09-06 09:00', value)
        with self.assertRaises(ValueError):
            parse_period('2026-09-06 09:00', '2026-09-06 08:00', '2')

    def test_weighted_role_and_pity(self):
        roles = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
        with patch('cogs.roles.views.random.choices', return_value=[roles[0]]) as choose:
            result = _pick_available_role({'color': {3: roles}}, [1, 3], [99, 1], forced_rarity=3, up_weights={1: 3})
            self.assertEqual(result, (roles[0], 3, 'color'))
            choose.assert_called_once_with(roles, weights=[3, 1.0], k=1)
        with patch('cogs.roles.views.random.choices', return_value=[roles[0]]) as choose:
            _pick_available_role({'color': {3: roles}}, [3], [1], forced_rarity=3)
            choose.assert_called_once_with(roles, weights=[1.0, 1.0], k=1)


class UpPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_pagination_and_independent_drafts(self):
        role = SimpleNamespace(id=1, name='role')
        parent = SimpleNamespace(guild=SimpleNamespace(id=9, roles=[role]))
        groups = [dict(id=str(i), name=f'group {i}', role_ids=[1]) for i in range(30)]
        data = {'lottery_roles': [1], 'lottery_up': {'9': {'groups': groups}}}
        with patch('cogs.roles.lottery_up.load_role_data', return_value=data):
            view = UpPoolView(parent, 7)
            self.assertEqual(view.group_pages, 2)
            view.group_page = 1
            view.rebuild()
            select = next(c for c in view.children if c.row == 3)
            self.assertEqual(len(select.options), 5)
            view.cfg['name'] = 'draft'
            self.assertEqual(groups[0]['name'], 'group 0')
            view.load_group(groups[1])
            self.assertEqual(view.cfg['name'], 'group 1')
            view.load_group()
            view.rebuild()
            self.assertTrue(view.delete_group.disabled)
            for row in range(5):
                width = sum(5 if isinstance(c, __import__('discord').ui.Select) else 1 for c in view.children if c.row == row)
                self.assertLessEqual(width, 5)

    async def test_pagination_preserves_selection(self):
        roles = [SimpleNamespace(id=i, name=str(i)) for i in range(1, 31)]
        parent = SimpleNamespace(guild=SimpleNamespace(id=9, roles=roles))
        with patch('cogs.roles.lottery_up.load_role_data', return_value={'lottery_roles': list(range(1,31))}):
            view = UpPoolView(parent, 7)
            view.selected.add(1)
            view.page = 1
            view.rebuild()
            self.assertEqual(view.selected, {1})
            self.assertEqual(view.pages, 2)
            self.assertTrue(view.next_page.disabled)
            self.assertLessEqual(len(view.children), 25)


if __name__ == '__main__':
    unittest.main()
