import datetime
import importlib.util
import unittest
from pathlib import Path


def _load_ticket_utils():
    path = Path(__file__).parents[1] / "cogs/tickets/utils.py"
    spec = importlib.util.spec_from_file_location("ticket_utils_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


ticket_utils = _load_ticket_utils()
ARCHIVE_KIND_APPROVED = ticket_utils.ARCHIVE_KIND_APPROVED
ARCHIVE_KIND_REJECTED = ticket_utils.ARCHIVE_KIND_REJECTED
ARCHIVE_KIND_TIMEOUT = ticket_utils.ARCHIVE_KIND_TIMEOUT
ApprovedTicketArchiveView = ticket_utils.ApprovedTicketArchiveView
build_ticket_archive_embed = ticket_utils.build_ticket_archive_embed


class TicketArchiveRecordTests(unittest.TestCase):
    def _build(self, archive_kind: str):
        opened_at = datetime.datetime(2026, 8, 23, 9, 30, tzinfo=datetime.timezone.utc)
        closed_at = datetime.datetime(2026, 8, 23, 10, 45, tzinfo=datetime.timezone.utc)
        return build_ticket_archive_embed(
            ticket_id="123456",
            creator_id="99887766",
            creator_name="测试用户",
            reason="测试归档原因",
            opened_at=opened_at,
            closed_at=closed_at,
            archive_kind=archive_kind,
            operator="审核员",
        )

    def test_archive_record_contains_required_fields(self):
        embed = self._build(ARCHIVE_KIND_APPROVED)
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["📌 归档原因"], "测试归档原因")
        self.assertIn("123456", fields["🧾 工单编号"])
        self.assertIn("99887766", fields["🆔 用户 DC ID"])
        self.assertEqual(fields["👤 用户名"], "测试用户")
        self.assertIn("<t:", fields["⏱️ 工单开启时间"])
        self.assertIn("<t:", fields["🔒 工单关闭时间"])
        self.assertEqual(fields["🐧 QQ 号码"], "`尚未录入`")

    def test_archive_reasons_use_distinct_colors(self):
        colors = {
            self._build(ARCHIVE_KIND_APPROVED).color.value,
            self._build(ARCHIVE_KIND_TIMEOUT).color.value,
            self._build(ARCHIVE_KIND_REJECTED).color.value,
        }
        self.assertEqual(len(colors), 3)
        timeout_fields = {field.name for field in self._build(ARCHIVE_KIND_TIMEOUT).fields}
        self.assertNotIn("🐧 QQ 号码", timeout_fields)

    def test_approved_record_view_has_persistent_qq_button(self):
        view = ApprovedTicketArchiveView()
        self.assertIsNone(view.timeout)
        self.assertEqual(view.children[0].custom_id, "ticket_archive_record_qq")


if __name__ == "__main__":
    unittest.main()
