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
egg_qa = _load_module("egg_qa_storage_test", "cogs/egg_qa/storage.py")


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

    def test_transaction_history_is_not_globally_truncated(self):
        for index in range(510):
            points.modify_user_points(index + 1000, 0.1, 99, source="retention_test")
        with points._points_connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM point_transactions").fetchone()[0]
        self.assertGreaterEqual(count, 510)
        self.assertEqual(points.load_points_data()["transactions"], [])
        self.assertGreaterEqual(len(points.load_points_data(include_transactions=True)["transactions"]), 510)


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
        ten_draw_at = "2026-08-20T01:00:00+08:00"
        roles.record_lottery_draw(
            7,
            99,
            results=[{"type": "empty"} for _ in range(10)],
            spent_shells=10,
            refund_shells=0,
            reward_shells=0,
            drawn_at=ten_draw_at,
        )
        self.assertEqual(roles.get_lottery_stats(7, 99)["last_ten_draw_at"], ten_draw_at)


class AppStateSQLiteMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        app_store.APP_STATE_DB_FILE = str(root / "app_state.sqlite3")
        app_store._SCHEMA_READY = False
        red_packets.DATA_FILE = str(root / "red_packets.json")
        submissions.DATA_FILE = str(root / "submissions.json")
        egg_qa.DATA_FILE = str(root / "egg_qa.json")
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

    def test_large_red_packet_is_created_lazily_without_expiry(self):
        packet = red_packets.create_packet(
            guild_id=99,
            channel_id=100,
            sender_id=7,
            sender_name="tester",
            total_amount=1_000_000_000.0,
            count=1_000_000,
            message="large packet",
            admin_free=True,
        )

        self.assertEqual(packet["remaining_count"], 1_000_000)
        self.assertEqual(packet["allocations"], [])
        self.assertEqual(packet["allocation_mode"], "lazy")
        self.assertNotIn("expires_at", packet)
        claim = red_packets.claim_packet(packet["id"], 8)
        self.assertTrue(claim["success"])
        self.assertGreaterEqual(claim["amount"], 0.1)
        self.assertEqual(claim["packet"]["remaining_count"], 999_999)

    def test_lazy_red_packet_pays_exact_total_and_ends_when_empty(self):
        packet = red_packets.create_packet(
            guild_id=99,
            channel_id=100,
            sender_id=7,
            sender_name="tester",
            total_amount=12.3,
            count=20,
            message="until empty",
            admin_free=False,
        )

        claims = [red_packets.claim_packet(packet["id"], user_id) for user_id in range(100, 120)]
        self.assertTrue(all(claim["success"] for claim in claims))
        self.assertEqual(round(sum(claim["amount"] for claim in claims), 1), 12.3)
        finished = red_packets.get_packet(packet["id"])
        self.assertEqual(finished["status"], "empty")
        self.assertEqual(finished["remaining_count"], 0)
        self.assertEqual(finished["remaining_amount"], 0.0)

    def test_active_legacy_timed_red_packet_still_expires(self):
        data = red_packets.load_data()
        data["packets"]["old-active"] = {
            "id": "old-active",
            "sender_id": "7",
            "status": "active",
            "expires_at": "2000-01-01T00:00:00+08:00",
            "remaining_amount": 0.1,
            "remaining_count": 1,
            "allocations": [0.1],
            "claims": {},
        }
        red_packets.save_data(data)

        claim = red_packets.claim_packet("old-active", 8)
        self.assertFalse(claim["success"])
        self.assertEqual(claim["reason"], "expired")
        self.assertEqual(red_packets.expire_due_packets(), [])

    def test_timed_red_packet_has_24_hour_expiry(self):
        packet = red_packets.create_packet(
            guild_id=99,
            channel_id=100,
            sender_id=7,
            sender_name="tester",
            total_amount=10.0,
            count=10,
            message="timed packet",
            admin_free=False,
            timed=True,
        )

        self.assertTrue(packet["timed"])
        lifetime = red_packets.parse_time(packet["expires_at"]) - red_packets.parse_time(
            packet["created_at"]
        )
        self.assertEqual(lifetime.total_seconds(), 24 * 60 * 60)

    def test_red_packet_sender_can_claim_once(self):
        packet = red_packets.create_packet(
            guild_id=99,
            channel_id=100,
            sender_id=7,
            sender_name="tester",
            total_amount=1.0,
            count=2,
            message="sender can claim",
            admin_free=False,
        )

        first = red_packets.claim_packet(packet["id"], 7)
        repeated = red_packets.claim_packet(packet["id"], 7)
        self.assertTrue(first["success"])
        self.assertFalse(repeated["success"])
        self.assertEqual(repeated["reason"], "already_claimed")

    def test_repeated_claim_shows_previous_amount_after_packet_is_empty(self):
        packet = red_packets.create_packet(
            guild_id=99,
            channel_id=100,
            sender_id=7,
            sender_name="tester",
            total_amount=1.0,
            count=1,
            message="empty then repeat",
            admin_free=False,
        )

        first = red_packets.claim_packet(packet["id"], 8)
        repeated = red_packets.claim_packet(packet["id"], 8)
        self.assertTrue(first["success"])
        self.assertEqual(first["packet"]["status"], "empty")
        self.assertFalse(repeated["success"])
        self.assertEqual(repeated["reason"], "already_claimed")
        self.assertEqual(repeated["amount"], first["amount"])

    def test_red_packet_claim_batch_preserves_order_and_uniqueness(self):
        packet = red_packets.create_packet(
            guild_id=99,
            channel_id=100,
            sender_id=7,
            sender_name="tester",
            total_amount=10.0,
            count=10,
            message="batch claims",
            admin_free=False,
        )

        results = red_packets.claim_packets([
            (packet["id"], 8),
            (packet["id"], 8),
            (packet["id"], 9),
        ])
        self.assertTrue(results[0]["success"])
        self.assertFalse(results[1]["success"])
        self.assertEqual(results[1]["reason"], "already_claimed")
        self.assertTrue(results[2]["success"])
        saved = red_packets.get_packet(packet["id"])
        self.assertEqual(saved["remaining_count"], 8)
        self.assertEqual(set(saved["claims"]), {"8", "9"})

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

    def test_list_useful_submissions_filters_by_user_guild_and_status(self):
        data = submissions.load_data()
        data["submissions"] = {
            "liked": {
                "id": "liked",
                "kind": submissions.KIND_RECOMMENDATION,
                "guild_id": "99",
                "status": submissions.STATUS_OPEN,
                "useful_user_ids": ["7"],
                "created_at": "2026-09-02T12:00:00+08:00",
            },
            "not-liked": {
                "id": "not-liked",
                "kind": submissions.KIND_RECOMMENDATION,
                "guild_id": "99",
                "status": submissions.STATUS_OPEN,
                "useful_user_ids": ["8"],
                "created_at": "2026-09-02T13:00:00+08:00",
            },
            "deleted": {
                "id": "deleted",
                "kind": submissions.KIND_RECOMMENDATION,
                "guild_id": "99",
                "status": submissions.STATUS_DELETED,
                "useful_user_ids": ["7"],
                "created_at": "2026-09-02T14:00:00+08:00",
            },
            "other-guild": {
                "id": "other-guild",
                "kind": submissions.KIND_RECOMMENDATION,
                "guild_id": "100",
                "status": submissions.STATUS_OPEN,
                "useful_user_ids": ["7"],
                "created_at": "2026-09-02T15:00:00+08:00",
            },
        }
        submissions.save_data(data)

        rows = submissions.list_useful_submissions(7, 99)
        self.assertEqual([row["id"] for row in rows], ["liked"])

    def test_task_progress_uses_authoritative_module_records(self):
        submissions.grant_comment_reward(guild_id=99, user_id=7, requested_reward=4.5)
        self.assertEqual(
            submissions.get_daily_comment_reward_usage(guild_id=99, user_id=7),
            4.5,
        )
        data = egg_qa.load_data()
        data["questions"]["q1"] = {
            "id": "q1",
            "guild_id": "99",
            "author_id": "8",
            "rewards": {"7": {"user_id": "7", "amount": 3, "date": egg_qa._today()}},
        }
        data["questions"]["q2"] = {
            "id": "q2",
            "guild_id": "99",
            "author_id": "8",
            "rewards": {"7": {"user_id": "7", "amount": 4, "date": egg_qa._today()}},
        }
        data.pop("daily_question_counts", None)
        data.pop("daily_reply_totals", None)
        data["version"] = 2
        egg_qa.save_data(data)
        self.assertEqual(egg_qa.get_daily_reply_reward_total(7, 99), 7)
        self.assertEqual(egg_qa.load_data()["version"], 4)

        question = egg_qa.create_question(author_id=7, guild_id=99, channel_id=10, content="这是一个测试问题")
        self.assertIsNotNone(question)
        self.assertEqual(egg_qa.get_daily_usage(7, 99), 1)
        egg_qa.cancel_question(question["id"])
        self.assertEqual(egg_qa.get_daily_usage(7, 99), 0)

    def test_question_content_rejects_short_and_low_effort_posts(self):
        self.assertIsNotNone(egg_qa.validate_question_content("这是短问题"))
        self.assertIsNotNone(egg_qa.validate_question_content("凑数凑数凑数凑数"))
        self.assertIsNotNone(egg_qa.validate_question_content("哈哈哈哈哈哈哈哈"))
        self.assertIsNone(egg_qa.validate_question_content("大家有哪些好用的耳机推荐？"))
        with self.assertRaises(ValueError):
            egg_qa.create_question(author_id=7, guild_id=99, channel_id=10, content="水水水水水水水")


if __name__ == "__main__":
    unittest.main()
