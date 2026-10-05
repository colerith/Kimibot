import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.roles import storage, views


class LegendaryTicketViewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for name, value in {
            "ROLE_STATE_DB_FILE": str(root / "roles.sqlite3"),
            "COLLECTIONS_DATA_FILE": str(root / "collections.json"),
            "REDEEM_OWNERSHIP_DATA_FILE": str(root / "redeem.json"),
            "LOTTERY_STATS_DATA_FILE": str(root / "stats.json"),
            "_role_state_ready": False,
        }.items():
            self.enterContext(patch.object(storage, name, value))
        self.roles = {rid: SimpleNamespace(id=rid, mention=f"<@&{rid}>") for rid in range(1, 8)}
        self.guild = SimpleNamespace(id=99, get_role=self.roles.get)
        self.user = SimpleNamespace(id=7, add_roles=AsyncMock())
        self.enterContext(patch.object(views, "_LOTTERY_USER_LOCKS", {}))
        self.enterContext(patch.object(views, "load_role_data", return_value={}))
        self.enterContext(patch.object(views, "_legendary_ticket_pool", return_value=list(self.roles)))
        self.enterContext(patch.object(views, "_settle_collection_rewards", return_value=[]))
        self.enterContext(patch.object(views, "remove_all_decorations", new=AsyncMock()))
        self.enterContext(patch.object(views, "get_lottery_role_kind", return_value=storage.LOTTERY_KIND_COLOR))
        storage.record_lottery_draw(
            7, 99, results=[{"type": "role", "rarity": storage.RARITY_LEGENDARY, "dupe": True}] * 12,
            spent_shells=12, refund_shells=0, reward_shells=0, drawn_at="2026-10-05",
        )
        self.month = views.datetime.now(views.BEIJING_TZ).strftime("%Y-%m")

    def interaction(self):
        return SimpleNamespace(
            user=self.user, response=SimpleNamespace(defer=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()),
        )

    def panel(self):
        return views.LegendaryTicketUseView(
            self.guild, 7, storage.get_legendary_ticket_status(7, 99, self.month), 7,
        )

    async def test_use_one_retains_remaining_and_allows_next_use(self):
        panel = self.panel()
        interaction = self.interaction()
        await panel.use_ticket.callback(interaction)
        result = interaction.edit_original_response.call_args.kwargs
        self.assertIn("剩余券：**3**", result["embed"].description)
        next_panel = result["view"]
        self.assertFalse(next_panel.use_ticket.disabled)
        self.assertNotEqual(panel.request_id, next_panel.request_id)
        await next_panel.use_ticket.callback(self.interaction())
        status = storage.get_legendary_ticket_status(7, 99, self.month)
        self.assertEqual(status["balance"], 2)
        self.assertEqual(status["used_this_month"], 2)

    async def test_simultaneous_clicks_on_same_panel_only_consume_one(self):
        panel = self.panel()
        first, second = self.interaction(), self.interaction()
        await asyncio.gather(panel.use_ticket.callback(first), panel.use_ticket.callback(second))
        status = storage.get_legendary_ticket_status(7, 99, self.month)
        self.assertEqual(status["balance"], 3)
        self.assertEqual(status["used_this_month"], 1)
        self.user.add_roles.assert_awaited_once()
        second.edit_original_response.assert_not_awaited()
        second.followup.send.assert_awaited_once()

    async def test_monthly_limit_disables_button_but_preserves_ticket(self):
        panel = self.panel()
        for _ in range(3):
            interaction = self.interaction()
            await panel.use_ticket.callback(interaction)
            panel = interaction.edit_original_response.call_args.kwargs["view"]
        self.assertTrue(panel.use_ticket.disabled)
        self.assertEqual(panel.status["balance"], 1)
        self.assertIn("未使用的券会继续保留", panel.availability_notice())

    async def test_retry_after_display_failure_does_not_consume_another_ticket(self):
        panel = self.panel()
        failed = self.interaction()
        failed.edit_original_response.side_effect = RuntimeError("display unavailable")
        with self.assertRaises(RuntimeError):
            await panel.use_ticket.callback(failed)
        retry = self.interaction()
        await panel.use_ticket.callback(retry)
        self.assertEqual(storage.get_legendary_ticket_status(7, 99, self.month)["balance"], 3)
        self.assertFalse(retry.edit_original_response.call_args.kwargs["view"].use_ticket.disabled)


if __name__ == "__main__":
    unittest.main()
