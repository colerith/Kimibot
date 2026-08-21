import concurrent.futures
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from cogs.shared import sqlite_store as app_store


def _load_module(name: str, relative_path: str):
    path = Path(__file__).parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


points = _load_module("points_storage_test", "cogs/points/storage.py")
roles = _load_module("roles_storage_test", "cogs/roles/storage.py")
red_packets = _load_module("red_packets_storage_test", "cogs/red_packets/storage.py")
submissions = _load_module("submissions_storage_test", "cogs/submissions/storage.py")


class PointsSQLiteMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        points.POINTS_DATA_FILE = str(root / "user_points.json")
        points.POINTS_DB_FILE = str(root / "user_points.sqlite3")
        points._POINTS_DB_READY = False
        legacy = points._empty_points_data()
        legacy["users"]["99:1"] = {"shells": 12.5, "streak_days": 3}
        Path(points.POINTS_DATA_FILE).write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self):
        points._POINTS_DB_READY = False
        self.temp_dir.cleanup()

    def test_json_migrates_once_and_keeps_backup(self):
        self.assertEqual(points.get_user_points(1, 99), 12.5)
        self.assertTrue(Path(f"{points.POINTS_DATA_FILE}.pre_sqlite.bak").exists())
        points.modify_user_points(1, 2.0, 99, source="test")
        self.assertEqual(points.get_user_points(1, 99), 14.5)

        points._POINTS_DB_READY = False
        self.assertEqual(points.get_user_points(1, 99), 14.5)

    def test_concurrent_signins_are_unique_and_ranked(self):
        user_ids = list(range(100, 150))
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(lambda uid: points.sign_in_user(uid, 99, 1.0), user_ids))

        self.assertTrue(all(result["success"] for result in results))
        self.assertEqual(sorted(result["rank"] for result in results), list(range(1, 51)))
        self.assertEqual(points.get_daily_signin_summary(99)["count"], 50)
        self.assertEqual(points.get_daily_activity_stats(99, points._today())["signin_users"], 50)
        repeated = points.sign_in_user(user_ids[0], 99, 1.0)
        self.assertFalse(repeated["success"])
        self.assertGreater(repeated["rank"], 0)

    def test_idempotent_reward_uses_indexed_lookup(self):
        first = points.grant_monthly_eligible_reward(
            1, 99, 3.0, source="test_reward", idempotency_key="same-event"
        )
        second = points.grant_monthly_eligible_reward(
            1, 99, 3.0, source="test_reward", idempotency_key="same-event"
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(points.get_user_points(1, 99), 15.5)

    def test_atomic_spend_never_overdraws(self):
        spent = points.spend_user_points(1, 10.0, 99, source="test_spend")
        rejected = points.spend_user_points(1, 10.0, 99, source="test_spend")
        self.assertTrue(spent["success"])
        self.assertFalse(rejected["success"])
        self.assertEqual(points.get_user_points(1, 99), 2.5)

    def test_legacy_snapshot_writer_remains_compatible(self):
        result = points.claim_daily_task_bonus(1, 99, "basic", 10.0)
        self.assertTrue(result["success"])
        self.assertEqual(points.get_user_points(1, 99), 22.5)
        snapshot = points.get_user_daily_snapshot(1, 99)
        self.assertEqual(snapshot["users"]["99:1"]["shells"], 22.5)

    def test_monthly_card_uses_indexed_candidate_marker(self):
        points.update_monthly_card_config(
            price=1.0, duration_days=3, daily_reward=2.0, reward_multiplier=1.5
        )
        purchase = points.purchase_monthly_card(1, 99)
        self.assertTrue(purchase["success"])
        self.assertEqual(purchase["daily_reward"], 2.0)
        settlement = points.settle_monthly_card_daily_rewards()
        self.assertEqual(settlement["rewarded_users"], 0)


class RoleStateSQLiteMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        roles.COLLECTIONS_DATA_FILE = str(root / "collections.json")
        roles.REDEEM_OWNERSHIP_DATA_FILE = str(root / "redeem.json")
        roles.LOTTERY_STATS_DATA_FILE = str(root / "stats.json")
        roles.ROLE_STATE_DB_FILE = str(root / "role_state.sqlite3")
        roles._role_state_ready = False
        Path(roles.COLLECTIONS_DATA_FILE).write_text('{"7":[101]}', encoding="utf-8")
        Path(roles.REDEEM_OWNERSHIP_DATA_FILE).write_text("{}", encoding="utf-8")
        Path(roles.LOTTERY_STATS_DATA_FILE).write_text("{}", encoding="utf-8")

    def tearDown(self):
        roles._role_state_ready = False
        self.temp_dir.cleanup()

    def test_collection_batch_and_lottery_stats_are_targeted(self):
        self.assertEqual(roles.get_user_collection(7), [101])
        self.assertEqual(roles.add_many_to_collection(7, [102, 103, 102]), [101, 102, 103])
        result = roles.record_lottery_draw(
            7,
            99,
            results=[{"type": "empty"}, {"type": "shells"}],
            spent_shells=2,
            refund_shells=0,
            reward_shells=0.5,
            drawn_at="2026-08-20T00:00:00+08:00",
        )
        self.assertEqual(result["total_draws"], 2)
        self.assertEqual(roles.get_lottery_stats(7, 99)["shell_hits"], 1)


class AppStateSQLiteMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        app_store.APP_STATE_DB_FILE = str(root / "app_state.sqlite3")
        app_store._SCHEMA_READY = False
        red_packets.DATA_FILE = str(root / "red_packets.json")
        submissions.DATA_FILE = str(root / "submissions.json")
        Path(red_packets.DATA_FILE).write_text(
            json.dumps({"version": 1, "packets": {"legacy": {"id": "legacy"}}}),
            encoding="utf-8",
        )

    def tearDown(self):
        app_store._SCHEMA_READY = False
        self.temp_dir.cleanup()

    def test_namespace_migration_is_one_time_and_backed_up(self):
        migrated = red_packets.load_data()
        self.assertIn("legacy", migrated["packets"])
        self.assertTrue(Path(f"{red_packets.DATA_FILE}.pre_sqlite.bak").exists())
        migrated["packets"]["new"] = {"id": "new"}
        red_packets.save_data(migrated)
        Path(red_packets.DATA_FILE).write_text("{}", encoding="utf-8")
        self.assertIn("new", red_packets.load_data()["packets"])

    def test_submission_notification_subscription_is_owned_and_persistent(self):
        record, created = submissions.create_submission_once(
            guild_id=99,
            author_id=7,
            author_name="tester",
            kind=submissions.KIND_RECOMMENDATION,
            fields={"target": "测试投稿", "content": "正文"},
            base_reward=1.0,
            request_id="notification-test",
        )
        self.assertTrue(created)
        self.assertTrue(submissions.submission_notifications_enabled(record))
        self.assertIsNone(submissions.set_submission_notifications(record["id"], 8, False))
        updated = submissions.set_submission_notifications(record["id"], 7, False)
        self.assertIsNotNone(updated)
        self.assertFalse(submissions.submission_notifications_enabled(updated))
        self.assertFalse(
            submissions.submission_notifications_enabled(submissions.get_submission(record["id"]))
        )
        self.assertTrue(submissions.submission_notifications_enabled({"id": "legacy"}))


if __name__ == "__main__":
    unittest.main()
