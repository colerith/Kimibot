import importlib.util
import tempfile
import unittest
from pathlib import Path

from cogs.shared import sqlite_store as app_store


def _load_storage():
    path = Path(__file__).parents[1] / "cogs/wish_pool/storage.py"
    spec = importlib.util.spec_from_file_location("wish_pool_storage_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


wish_storage = _load_storage()


class WishPoolStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app_store.APP_STATE_DB_FILE = str(Path(self.temp_dir.name) / "app_state.sqlite3")
        app_store._SCHEMA_READY = False

    def tearDown(self):
        app_store._SCHEMA_READY = False
        self.temp_dir.cleanup()

    def test_general_and_phone_entries_remain_separate(self):
        general = wish_storage.create_entry(
            guild_id=1,
            author_id=10,
            author_name="General User",
            kind="wish",
            subject="社区愿望",
            content="希望增加一个社区功能",
            scope="general",
            category="社区建设",
        )
        phone = wish_storage.create_entry(
            guild_id=1,
            author_id=20,
            author_name="Phone User",
            kind="bug",
            subject="手机 Bug",
            content="这里出现了一个问题",
        )
        wish_storage.bind_entry_message(general["id"], channel_id=100, message_id=101)
        wish_storage.bind_entry_message(phone["id"], channel_id=200, message_id=201)

        self.assertEqual(wish_storage.find_entry_by_message_id(101)["scope"], "general")
        self.assertEqual(wish_storage.find_entry_by_message_id(201)["scope"], "phone")

    def test_rejection_reason_is_saved_and_cleared_by_new_status(self):
        entry = wish_storage.create_entry(
            guild_id=1,
            author_id=10,
            author_name="Tester",
            kind="wish",
            subject="测试",
            content="测试愿望内容",
        )
        rejected = wish_storage.set_entry_status(entry["id"], "rejected", reason="目前不符合规划")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["status_reason"], "目前不符合规划")

        accepted = wish_storage.set_entry_status(entry["id"], "accepted")
        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(accepted["status_reason"], "")


if __name__ == "__main__":
    unittest.main()
