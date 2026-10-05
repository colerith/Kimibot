import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from cogs.red_packets import storage
from cogs.red_packets.cog import RedPacketCog, build_packet_completion_text


class RedPacketCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.packet = {
            "id": "test", "status": "active", "created_at": "2026-10-05T10:00:00+08:00",
            "remaining_count": 3, "remaining_amount": 5.5,
            "allocations": [2.5, 2.5, 0.5], "claims": {},
        }

    async def test_batch_announces_once_and_replies_to_packet(self):
        data = {"packets": {"test": self.packet}}
        with patch.object(storage, "load_data", return_value=data), patch.object(storage, "save_data"), patch.object(storage, "now_iso", return_value="2026-10-05T11:02:03+08:00"):
            results = storage.claim_packets([("test", 1), ("test", 2), ("test", 3), ("test", 4), ("test", 2)])
        cog = RedPacketCog(Mock())
        cog._send_claim_result = AsyncMock()
        cog._schedule_packet_refresh = Mock()
        message = SimpleNamespace(reply=AsyncMock())
        interaction = SimpleNamespace(message=message)
        for result in results:
            await cog._process_claim(interaction, "test", result)
        message.reply.assert_awaited_once()
        text = message.reply.call_args.args[0]
        self.assertIn("1小时2分3秒", text)
        self.assertIn("<@2>", text)
        self.assertIn("**2.5** 蛋壳", text)
        mentions = message.reply.call_args.kwargs["allowed_mentions"]
        self.assertFalse(mentions.replied_user)
        self.assertTrue(mentions.users)

    def test_duration_under_second_and_over_day(self):
        packet = copy.deepcopy(self.packet)
        packet["claims"] = {"9": {"amount": 5, "claimed_at": packet["created_at"]}}
        self.assertIn("不到1秒", build_packet_completion_text(packet))
        packet["claims"]["9"]["claimed_at"] = "2026-10-07T10:00:01+08:00"
        self.assertIn("2天1秒", build_packet_completion_text(packet))


if __name__ == "__main__":
    unittest.main()
