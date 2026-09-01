import importlib.util
import unittest
from pathlib import Path


def _load_submission_storage():
    path = Path(__file__).parents[1] / "cogs/submissions/storage.py"
    spec = importlib.util.spec_from_file_location("submission_quality_storage_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


storage = _load_submission_storage()


class SubmissionQualityTests(unittest.TestCase):
    def test_attachment_lookup_ignores_temporary_cdn_signature(self):
        data = storage._empty_data()
        data["submissions"]["123"] = {
            "id": "123",
            "attachments": [
                "https://cdn.discordapp.com/attachments/10/20/example.png?ex=old&is=old"
            ],
        }
        original_load = storage.load_data
        storage.load_data = lambda: data
        try:
            record = storage.find_by_attachment_urls([
                "https://cdn.discordapp.com/attachments/10/20/example.png?ex=new&is=new"
            ])
            self.assertIsNotNone(record)
            self.assertEqual(record["id"], "123")
        finally:
            storage.load_data = original_load

    def test_manual_reply_reward_is_optional_and_validated(self):
        self.assertIsNone(storage.parse_manual_reply_reward(""))
        self.assertEqual(storage.parse_manual_reply_reward("2.5"), 2.5)
        with self.assertRaises(ValueError):
            storage.parse_manual_reply_reward("-1")
        with self.assertRaises(ValueError):
            storage.parse_manual_reply_reward("2.55")
        with self.assertRaises(ValueError):
            storage.parse_manual_reply_reward("101")

    def test_content_requires_fifteen_meaningful_characters(self):
        result = storage.validate_submission_content("太短了，没写清楚")

        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "too_short")
        self.assertEqual(result["minimum"], 15)

    def test_content_rejects_repeated_water_text(self):
        result = storage.validate_submission_content("嘎哒" * 30)

        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "repetitive")

    def test_content_accepts_descriptive_text(self):
        result = storage.validate_submission_content(
            "这个预设适合日常剧情使用，人物反应自然，建议补充安装说明。"
        )

        self.assertTrue(result["valid"])

    def test_withdrawal_is_idempotent_and_blocks_today(self):
        data = storage._empty_data()
        original_load = storage.load_data
        original_save = storage.save_data
        storage.load_data = lambda: data
        storage.save_data = lambda updated: None
        try:
            results = []
            for index in range(1, 4):
                submission_id = str(index)
                data["submissions"][submission_id] = {
                    "id": submission_id,
                    "guild_id": "100",
                    "author_id": "200",
                    "status": storage.STATUS_OPEN,
                    "base_reward": 1.5,
                    "extra_reward": 0.5,
                }
                results.append(
                    storage.record_meaningless_withdrawal(
                        submission_id,
                        moderator_id=300,
                        reason="重复字符灌水",
                    )
                )

            self.assertEqual([item["count"] for item in results], [1, 2, 3])
            self.assertEqual([item["should_warn"] for item in results], [False, False, True])
            self.assertEqual(results[-1]["penalty"], 2.0)
            self.assertEqual(
                results[-1]["record"]["moderation"]["withdrawal_reason"],
                "重复字符灌水",
            )

            duplicate = storage.record_meaningless_withdrawal("3", moderator_id=300)
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(duplicate["count"], 3)

            status = storage.can_create_submission(
                guild_id=100,
                author_id=200,
                kind=storage.KIND_REPO,
            )
            self.assertFalse(status["allowed"])
            self.assertTrue(status["blocked"])

            storage.mark_meaningless_warning_issued(guild_id=100, user_id=200, warning_count=1)
            warning_status = storage.get_meaningless_submission_status(guild_id=100, user_id=200)
            self.assertEqual(warning_status["warning_count"], 1)
        finally:
            storage.load_data = original_load
            storage.save_data = original_save


if __name__ == "__main__":
    unittest.main()
