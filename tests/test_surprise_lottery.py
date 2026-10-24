import random
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from cogs.points import storage as points
from cogs.roles import storage as roles
from cogs.roles import surprise_storage as store
from cogs.roles import surprise_views as ui


ordinary_role_chance = store.ordinary_role_chance


class StorageFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for module, names in [(points, ['POINTS_DATA_FILE', 'POINTS_DB_FILE']),
                              (roles, ['ROLES_DATA_FILE', 'ROLE_STATE_DB_FILE', 'COLLECTIONS_DATA_FILE',
                                       'LOTTERY_STATS_DATA_FILE', 'REDEEM_OWNERSHIP_DATA_FILE'])]:
            for name in names:
                p = patch.object(module, name, str(root / Path(getattr(module, name)).name))
                p.start()
                self.addCleanup(p.stop)
        for module, name, value in [(points, '_POINTS_DB_READY', False), (roles, '_role_state_ready', False),
                                    (roles, '_role_data_cache', None), (roles, '_role_data_cache_mtime_ns', -1)]:
            p = patch.object(module, name, value)
            p.start()
            self.addCleanup(p.stop)
        chance_patch = patch.object(store, "ordinary_role_chance", return_value=100)
        self.chance_mock = chance_patch.start()
        self.addCleanup(chance_patch.stop)
        roles.save_role_data({})
        points.modify_user_points(7, 20, 9)
        store.update_config(9, settings={"enabled": True, "cost": 1, "duplicate_shards": 1})
        store.update_config(9, role_id=1, entry={"weight": 1, "symbol": "🍒"})


class SurpriseSettlementTests(StorageFixture, unittest.TestCase):
    def test_probability_follows_ordinary_and_ignores_legacy_value(self):
        self.chance_mock.side_effect = ordinary_role_chance
        with points._points_connection() as con:
            store._put(con, "surprise_config", "9", {"enabled": True, "cost": 1,
                       "chance": 99, "duplicate_shards": 1, "roles": {}})
        for weights, expected in [({"role": 2, "shells": 38, "empty": 60}, 2),
                                  ({"role": 1, "shells": 0, "empty": 0}, 100),
                                  ({"role": 0, "shells": 32, "empty": 45}, 100 / 78),
                                  ({"role": 0, "shells": 0, "empty": 0}, 23)]:
            with patch.object(roles, "get_lottery_config", return_value={"outcome_weights": weights}):
                self.assertAlmostEqual(store.get_config(9)["chance"], expected)
        with self.assertRaises(ValueError):
            store.update_config(9, settings={"chance": 50})

    def test_eightieth_spin_guarantees_role_and_replay_does_not_advance(self):
        points.modify_user_points(7, 60, 9)
        self.enterContext(patch.object(store, "miss_refund", return_value=0))
        store.update_config(9, role_id=2, entry={"weight": 1, "symbol": "🍋"})
        self.chance_mock.return_value = 0
        for i in range(79):
            result = store.settle_spin(7, 9, str(i), {1, 2})
            self.assertIsNone(result["winner"])
            self.assertEqual(result["miss_streak"], i + 1)
        points._POINTS_DB_READY = False
        self.assertEqual(store.get_account(7, 9)["miss_streak"], 79)
        result = store.settle_spin(7, 9, "80th", {1, 2})
        self.assertTrue(result["pity_triggered"])
        self.assertEqual(len(set(result["reels"])), 1)
        self.assertEqual(result["pity_remaining"], 80)
        self.assertEqual(store.settle_spin(7, 9, "80th", {1, 2}), result)
        self.assertEqual(store.get_account(7, 9)["draws"], 80)
        self.assertFalse(store.settle_spin(7, 9, "no-money", {1, 2})["success"])
        self.assertEqual(store.get_account(7, 9)["miss_streak"], 0)

    def test_early_duplicate_win_resets_surprise_pity(self):
        store.update_config(9, role_id=2, entry={"weight": 1, "symbol": "🍋"})
        self.chance_mock.return_value = 0
        store.settle_spin(7, 9, "miss", {1, 2})
        self.chance_mock.return_value = 100
        result = store.settle_spin(7, 9, "early", {1}, member_role_ids=[1])
        self.assertTrue(result["duplicate"])
        self.assertFalse(result["pity_triggered"])
        self.assertEqual(result["miss_streak"], 0)
        self.assertEqual(result["shards_gained"], 1)

    def test_batch_pity_refunds_and_idempotency(self):
        store.update_config(9, role_id=2, entry={"weight": 1, "symbol": "🍋"})
        self.chance_mock.return_value = 0
        with points._points_connection() as con:
            store._put(con, "surprise_accounts", "9:7", {"owned": [], "shards": 0, "draws": 77, "miss_streak": 77})
        with patch.object(store, "miss_refund", return_value=0.5):
            batch = store.settle_spin(7, 9, "batch", {1, 2}, draw_count=4)
        self.assertEqual([r["miss_streak"] for r in batch["results"]], [78, 79, 0, 1])
        self.assertTrue(batch["results"][2]["pity_triggered"])
        self.assertEqual(batch["refund"], 1.5)
        self.assertEqual(batch["balance"], 17.5)
        self.assertEqual(store.settle_spin(7, 9, "batch", {1, 2}, draw_count=4), batch)
        self.assertEqual(store.get_account(7, 9)["draws"], 81)
        self.assertEqual(points.get_user_points(7, 9), 17.5)

    def test_ten_draw_duplicates_and_full_cost_check(self):
        batch = store.settle_spin(7, 9, "ten", {1}, draw_count=10)
        self.assertEqual(batch["shards"], 9)
        self.assertEqual(batch["balance"], 10)
        store.update_config(9, settings={"cost": 3})
        self.assertFalse(store.settle_spin(7, 9, "poor", {1}, draw_count=4)["success"])
        self.assertEqual(store.get_account(7, 9)["draws"], 10)

    def test_batch_weights_preserve_symbols_and_reject_conflicts_atomically(self):
        store.set_role_weights(9, [1, 2], 5)
        cfg = store.get_config(9)
        self.assertEqual(cfg["roles"]["1"], {"symbol": "🍒", "weight": 5})
        self.assertEqual(cfg["roles"]["2"], {"symbol": "", "weight": 5})
        roles.save_role_data({"lottery_roles": [3]})
        with self.assertRaises(ValueError):
            store.set_role_weights(9, [1, 3], 9)
        self.assertEqual(store.get_config(9), cfg)

    def test_new_duplicate_and_replay(self):
        first = store.settle_spin(7, 9, "a", {1})
        self.assertEqual(first["reels"], [1, 1, 1])
        self.assertFalse(first["duplicate"])
        self.assertEqual(roles.get_user_collection(7), [1])
        second = store.settle_spin(7, 9, "b", {1})
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["shards"], 1)
        self.assertEqual(store.settle_spin(7, 9, "b", {1}), second)
        self.assertEqual(points.get_user_points(7, 9), 18)
        account = store.get_account(7, 9)
        self.assertEqual(account["draws"], 2)
        self.assertEqual(account["last_result"], second)

    def test_simultaneous_same_request_charges_once(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: store.settle_spin(7, 9, "same", {1}), range(4)))
        self.assertEqual(points.get_user_points(7, 9), 19)
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(store.get_account(7, 9)["draws"], 1)

    def test_insufficient_paused_empty_and_changed_config_do_not_charge(self):
        store.update_config(9, settings={"cost": 30})
        self.assertFalse(store.settle_spin(7, 9, "x", {1})["success"])
        store.update_config(9, settings={"cost": 1, "enabled": False})
        self.assertFalse(store.settle_spin(7, 9, "x", {1})["success"])
        store.update_config(9, settings={"enabled": True})
        self.assertFalse(store.settle_spin(7, 9, "x", set())["success"])
        self.assertFalse(store.settle_spin(7, 9, "x", {1}, expected_config={})["success"])
        self.assertEqual(points.get_user_points(7, 9), 20)
        self.assertEqual(store.get_account(7, 9)["draws"], 0)

    def test_failure_during_commit_rolls_back_balance_and_rewards(self):
        real_put = store._put
        def fail_receipt(con, namespace, key, value):
            if namespace == "surprise_receipts":
                raise RuntimeError("disk failure")
            return real_put(con, namespace, key, value)
        with patch.object(store, "_put", side_effect=fail_receipt), self.assertRaises(RuntimeError):
            store.settle_spin(7, 9, "fail", {1})
        self.assertEqual(points.get_user_points(7, 9), 20)
        self.assertEqual(store.get_account(7, 9)["owned"], [])

    def test_delivery_recovery_and_points_snapshot_preserve_receipt(self):
        with patch.object(roles, "add_many_to_collection", side_effect=RuntimeError("interrupted")):
            result = store.settle_spin(7, 9, "recover", {1})
        self.assertTrue(result["delivery_pending"])
        points.save_points_data(points.load_points_data())
        store.recover_all_rewards()
        self.assertEqual(roles.get_user_collection(7), [1])
        store.settle_spin(7, 9, "recover", {1})
        self.assertEqual(points.get_user_points(7, 9), 19)
        self.assertEqual(store.get_config(9)["chance"], 100)

    def test_existing_roles_count_as_duplicate_and_guilds_are_isolated(self):
        result = store.settle_spin(7, 9, "owned", {1}, member_role_ids=[1])
        self.assertTrue(result["duplicate"])
        self.assertEqual(store.get_account(7, 9)["shards"], 1)
        self.assertEqual(store.get_account(7, 10)["shards"], 0)
        self.assertFalse(store.get_config(10)["enabled"])

    def test_miss_never_has_matching_reels_and_probability_is_overall(self):
        rng = random.Random(1234)
        pool = {1: 1, 2: 3}
        for _ in range(100):
            self.assertNotEqual(len(set(store.roll_reels(pool, 0, rng))), 1)
        wins = [store.roll_reels(pool, 25, rng) for _ in range(12000)]
        winners = [r[0] for r in wins if len(set(r)) == 1]
        self.assertTrue(0.23 < len(winners) / len(wins) < 0.27)
        self.assertTrue(0.72 < winners.count(2) / len(winners) < 0.78)

    def test_invalid_numeric_settings_rejected(self):
        for settings in ({"chance": 101}, {"chance": "nan"}, {"cost": "inf"},
                         {"cost": -1}, {"duplicate_shards": 0.5}):
            with self.assertRaises(ValueError):
                store.update_config(9, settings=settings)
        with self.assertRaises(ValueError):
            store.update_config(9, role_id=1, entry={"weight": "nan"})


class SurpriseViewTests(StorageFixture, unittest.IsolatedAsyncioTestCase):
    async def test_optional_emoji_payload_and_blank_submission(self):
        guild = self.make_guild()
        panel = ui.SurpriseAdminView(SimpleNamespace(guild=guild), 7)
        await panel.prepare()
        panel.refresh = AsyncMock()
        modal = ui.SurpriseRoleModal(panel, guild.get_role(2))
        payload = modal.symbol.to_component_dict()
        self.assertIs(payload["required"], False)
        self.assertEqual(payload["min_length"], 0)
        modal.symbol.value = ""
        interaction = SimpleNamespace(user=SimpleNamespace(id=7), guild_id=9, guild=guild,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        await modal.callback(interaction)
        self.assertEqual(store.get_config(9)["roles"]["2"]["symbol"], "")
        panel.refresh.assert_awaited_once()

    async def test_multi_add_opens_batch_modal_and_keeps_panel(self):
        guild = self.make_guild()
        panel = ui.SurpriseAdminView(SimpleNamespace(guild=guild), 7)
        await panel.prepare()
        picker = next(c for c in panel.children if isinstance(c, ui.SurpriseAdminRolePicker))
        self.assertEqual(picker.max_values, 25)
        interaction = SimpleNamespace(user=SimpleNamespace(id=7), guild_id=9, guild=guild, data={"values": ["2", "3"]},
            response=SimpleNamespace(send_modal=AsyncMock(), defer=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
        await picker.callback(interaction)
        modal = interaction.response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, ui.SurpriseBatchWeightModal)
        modal.weight.value = "7"
        await modal.callback(interaction)
        self.assertEqual(store.get_config(9)["roles"]["2"]["weight"], 7)
        self.assertEqual(store.get_config(9)["roles"]["3"]["weight"], 7)
        self.assertIs(interaction.edit_original_response.await_args.kwargs["view"], panel)
        selected = next(c for c in panel.children if isinstance(c, ui.SurpriseConfiguredPicker))
        self.assertEqual(selected.max_values, 3)
        self.assertEqual({int(o.value) for o in selected.options if o.default}, {2, 3})

    def make_guild(self):
        guild = SimpleNamespace(id=9, roles=[])
        for rid, symbol in [(i, "🍒" if i == 1 else "🍋") for i in range(1, 33)]:
            guild.roles.append(discord.Role(guild=guild, state=SimpleNamespace(), data={
                "id": str(rid), "name": f"role {rid}", "position": rid, "permissions": "0",
                "colors": {"primary_color": 0, "secondary_color": None, "tertiary_color": None},
                "unicode_emoji": symbol, "managed": False}))
        guild.get_role = lambda rid: next((r for r in guild.roles if r.id == rid), None)
        return guild

    async def test_ten_results_paginate_two_draws_without_settling(self):
        guild = self.make_guild()
        batch = store.settle_spin(7, 9, "pages", {1}, draw_count=10)
        view = ui.SurpriseLotteryView(7, guild)
        view.current_result, view.result_cfg = batch, store.get_config(9)
        embeds = view.result_embeds(batch, view.result_cfg)
        self.assertEqual(len(embeds), 9)
        self.assertIn("**10**", embeds[0].description)
        self.assertIn("第 1 抽", embeds[1].title)
        self.assertIn("第 2 抽", embeds[5].title)
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        for _ in range(4):
            await view.result_next.callback(interaction)
        embeds = interaction.response.edit_message.await_args.kwargs["embeds"]
        self.assertIn("第 9 抽", embeds[1].title)
        self.assertIn("第 10 抽", embeds[5].title)
        self.assertTrue(view.result_next.disabled)
        self.assertEqual(store.get_account(7, 9)["draws"], 10)
        self.assertEqual(points.get_user_points(7, 9), 10)

    async def test_mode_buttons_and_admin_rows(self):
        guild = self.make_guild()
        mode = ui.LotteryModeView(7)
        self.assertEqual([c.label for c in mode.children], ["普通抽奖", "惊喜抽奖"])
        admin = ui.SurpriseAdminView(SimpleNamespace(guild=guild, refresh_content=AsyncMock()), 7)
        await admin.prepare()
        for row in range(5):
            self.assertLessEqual(sum(5 if isinstance(c, discord.ui.Select) else 1 for c in admin.children if c.row == row), 5)
        view = ui.SurpriseLotteryView(7, guild)
        await view.prepare()
        self.assertFalse(view.spin.disabled)

    async def test_available_pagination_order_and_pool_exclusion(self):
        guild = self.make_guild()
        roles.save_role_data({"lottery_roles": [2, 3]})
        panel = ui.SurpriseAdminView(SimpleNamespace(guild=guild), 7)
        await panel.prepare()
        picker = next(c for c in panel.children if isinstance(c, ui.SurpriseAdminRolePicker))
        self.assertEqual([int(o.value) for o in picker.options], [rid for rid in range(32, 6, -1) if rid != guild.id])
        self.assertFalse(panel.add_next.disabled)
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())
        await panel.add_next.callback(interaction)
        picker = next(c for c in panel.children if isinstance(c, ui.SurpriseAdminRolePicker))
        self.assertEqual([int(o.value) for o in picker.options], [6, 5, 4])
        self.assertEqual(panel.page, 0)
        self.assertTrue(panel.add_next.disabled)
        await panel.add_previous.callback(interaction)
        self.assertEqual(panel.add_page, 0)

    async def test_both_storage_paths_reject_overlapping_roles(self):
        roles.save_role_data({"lottery_roles": [2]})
        with self.assertRaises(ValueError):
            store.update_config(9, role_id=2, entry={"weight": 1, "symbol": "🍋"})
        with self.assertRaises(ValueError):
            roles.save_role_data({"lottery_roles": [1, 2]})
        from cogs.roles.views import RolePoolManagerView
        panel = RolePoolManagerView(SimpleNamespace(guild=self.make_guild()))
        available = [r.id for r in panel.available_page_roles]
        panel.add_page = 1
        panel.rebuild()
        available += [r.id for r in panel.available_page_roles]
        self.assertNotIn(1, available)
        store.update_config(9, role_id=1, remove=True)
        roles.save_role_data({"lottery_roles": [1, 2]})
        self.assertIn(1, roles.load_role_data()["lottery_roles"])

    async def test_conflicting_icons_block_draw_and_catalog_reports_owned(self):
        guild = self.make_guild()
        store.update_config(9, role_id=2, entry={"weight": 1, "symbol": "🍒"})
        entries, error = ui.playable_pool(guild, store.get_config(9))
        self.assertTrue(error)
        self.assertFalse(entries)
        store.update_config(9, role_id=2, entry={"weight": 1, "symbol": "🍋"})
        store.settle_spin(7, 9, "first", {1})
        embed = await ui.SurpriseCatalogView(7, guild).prepare()
        self.assertEqual(len(embed.fields), 2)
        self.assertIn("已拥有", embed.fields[1].value)

    async def test_spin_displays_result_keeps_buttons_and_snapshot(self):
        guild = self.make_guild()
        view = ui.SurpriseLotteryView(7, guild)
        interaction = SimpleNamespace(id=123, guild_id=9, guild=guild,
            user=SimpleNamespace(id=7, roles=[], add_roles=AsyncMock()),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock())
        with patch("cogs.roles.surprise_views.asyncio.sleep", new=AsyncMock()):
            await view.spin.callback(interaction)
        self.assertFalse(view.busy)
        self.assertFalse(view.spin.disabled)
        self.assertTrue(view.result_prev.disabled)
        self.assertTrue(view.result_next.disabled)
        self.assertIs(interaction.edit_original_response.await_args.kwargs["view"], view)
        embeds = interaction.edit_original_response.await_args.kwargs["embeds"]
        self.assertEqual(len(embeds), 4)
        self.assertIn("获得", embeds[0].description)
        self.assertEqual(store.get_account(7, 9)["last_result"]["symbols"][0][0], "🍒")
        interaction.user.add_roles.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
