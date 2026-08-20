import json
import os
import threading
from datetime import date, datetime, timedelta

from cogs.shared.sqlite_store import load_json_namespace, save_json_namespace


REPORT_DATA_FILE = "data/server_daily_reports.json"
_REPORT_DATA_LOCK = threading.RLock()
_EVENT_KEYS = ("joins", "leaves", "newbie_gains", "hatched_gains")


def _empty_data() -> dict:
    return {"version": 1, "guilds": {}}


def _empty_guild() -> dict:
    return {
        "tracking_started_date": "",
        "initial_catchup_repaired": False,
        "days": {},
        "reports": {},
        "member_snapshot": {
            "captured_at": "",
            "newbie_ids": [],
            "hatched_ids": [],
        },
    }


def _normalize_ids(values) -> list[str]:
    return sorted({str(value) for value in values or [] if str(value).isdigit()}, key=int)


def _normalize_day(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {key: _normalize_ids(raw.get(key, [])) for key in _EVENT_KEYS}


def _load_unlocked() -> dict:
    raw = load_json_namespace(
        "server_daily_reports", legacy_file=REPORT_DATA_FILE, default=_empty_data()
    )
    return raw if isinstance(raw, dict) else _empty_data()


def _save_unlocked(data: dict) -> None:
    save_json_namespace("server_daily_reports", data)


def _guild_record(data: dict, guild_id: int) -> dict:
    guilds = data.setdefault("guilds", {})
    record = guilds.setdefault(str(guild_id), _empty_guild())
    for key, default in _empty_guild().items():
        record.setdefault(key, default)
    return record


def initialize_and_reconcile(
    guild_id: int,
    *,
    today: str,
    captured_at: str,
    joined_members: list[tuple[int, str]],
    newbie_ids: list[int],
    hatched_ids: list[int],
) -> None:
    """Initialize tracking and reconcile cache state after a restart.

    Joined dates are exact Discord timestamps. Role changes while the bot was
    offline have no timestamp, so newly observed gains are attributed to the
    most recently completed day when the prior snapshot predates today.
    """
    with _REPORT_DATA_LOCK:
        data = _load_unlocked()
        record = _guild_record(data, guild_id)
        today_date = date.fromisoformat(today)
        # The first report is for the day before the feature starts.  Starting
        # at ``today`` would make the initial catch-up scan skip yesterday.
        first_report_date = today_date - timedelta(days=1)
        had_tracking_start = bool(record.get("tracking_started_date"))
        if not had_tracking_start:
            record["tracking_started_date"] = first_report_date.isoformat()
            record["initial_catchup_repaired"] = True

        try:
            tracking_start = date.fromisoformat(record["tracking_started_date"])
        except (TypeError, ValueError):
            tracking_start = first_report_date
            record["tracking_started_date"] = tracking_start.isoformat()
            record["initial_catchup_repaired"] = True
        # Migrate data created by the old implementation, which started at the
        # installation day and therefore permanently excluded the day before.
        if had_tracking_start and not record.get("initial_catchup_repaired"):
            tracking_start -= timedelta(days=1)
            record["tracking_started_date"] = tracking_start.isoformat()
            record["initial_catchup_repaired"] = True
        if tracking_start > first_report_date:
            tracking_start = first_report_date
            record["tracking_started_date"] = tracking_start.isoformat()
        for user_id, joined_date_raw in joined_members:
            try:
                joined_date = date.fromisoformat(joined_date_raw)
            except (TypeError, ValueError):
                continue
            if tracking_start <= joined_date <= today_date:
                day = record.setdefault("days", {}).setdefault(joined_date.isoformat(), _normalize_day({}))
                day["joins"] = _normalize_ids([*day.get("joins", []), user_id])

        snapshot = record.get("member_snapshot", {})
        old_newbie = set(_normalize_ids(snapshot.get("newbie_ids", [])))
        old_hatched = set(_normalize_ids(snapshot.get("hatched_ids", [])))
        current_newbie = set(_normalize_ids(newbie_ids))
        current_hatched = set(_normalize_ids(hatched_ids))
        previous_capture = str(snapshot.get("captured_at", "") or "")

        if previous_capture:
            try:
                previous_date = datetime.fromisoformat(previous_capture).date()
            except ValueError:
                previous_date = today_date
            gain_date = today_date - timedelta(days=1) if previous_date < today_date else today_date
            gain_date = max(gain_date, tracking_start)
            day = record.setdefault("days", {}).setdefault(gain_date.isoformat(), _normalize_day({}))
            day["newbie_gains"] = _normalize_ids([*day.get("newbie_gains", []), *(current_newbie - old_newbie)])
            day["hatched_gains"] = _normalize_ids([*day.get("hatched_gains", []), *(current_hatched - old_hatched)])

        record["member_snapshot"] = {
            "captured_at": captured_at,
            "newbie_ids": _normalize_ids(current_newbie),
            "hatched_ids": _normalize_ids(current_hatched),
        }
        _save_unlocked(data)


def record_member_join(guild_id: int, user_id: int, event_date: str) -> None:
    _record_event(guild_id, event_date, "joins", user_id)


def record_member_leave(guild_id: int, user_id: int, event_date: str) -> None:
    with _REPORT_DATA_LOCK:
        data = _load_unlocked()
        record = _guild_record(data, guild_id)
        day = record.setdefault("days", {}).setdefault(event_date, _normalize_day({}))
        day["leaves"] = _normalize_ids([*day.get("leaves", []), user_id])
        snapshot = record.setdefault("member_snapshot", {})
        snapshot["newbie_ids"] = [value for value in _normalize_ids(snapshot.get("newbie_ids", [])) if value != str(user_id)]
        snapshot["hatched_ids"] = [value for value in _normalize_ids(snapshot.get("hatched_ids", [])) if value != str(user_id)]
        _save_unlocked(data)


def record_role_update(
    guild_id: int,
    user_id: int,
    event_date: str,
    *,
    has_newbie: bool,
    had_newbie: bool,
    has_hatched: bool,
    had_hatched: bool,
) -> None:
    with _REPORT_DATA_LOCK:
        data = _load_unlocked()
        record = _guild_record(data, guild_id)
        day = record.setdefault("days", {}).setdefault(event_date, _normalize_day({}))
        if has_newbie and not had_newbie:
            day["newbie_gains"] = _normalize_ids([*day.get("newbie_gains", []), user_id])
        if has_hatched and not had_hatched:
            day["hatched_gains"] = _normalize_ids([*day.get("hatched_gains", []), user_id])

        snapshot = record.setdefault("member_snapshot", {})
        for key, enabled in (("newbie_ids", has_newbie), ("hatched_ids", has_hatched)):
            values = set(_normalize_ids(snapshot.get(key, [])))
            if enabled:
                values.add(str(user_id))
            else:
                values.discard(str(user_id))
            snapshot[key] = _normalize_ids(values)
        _save_unlocked(data)


def _record_event(guild_id: int, event_date: str, event_key: str, user_id: int) -> None:
    if event_key not in _EVENT_KEYS:
        raise ValueError(f"unsupported report event: {event_key}")
    with _REPORT_DATA_LOCK:
        data = _load_unlocked()
        record = _guild_record(data, guild_id)
        day = record.setdefault("days", {}).setdefault(event_date, _normalize_day({}))
        day[event_key] = _normalize_ids([*day.get(event_key, []), user_id])
        _save_unlocked(data)


def get_missing_report_dates(guild_id: int, through_date: str) -> list[str]:
    with _REPORT_DATA_LOCK:
        data = _load_unlocked()
        record = _guild_record(data, guild_id)
        start_raw = str(record.get("tracking_started_date", "") or "")
        if not start_raw:
            return []
        try:
            current = date.fromisoformat(start_raw)
            end = date.fromisoformat(through_date)
        except ValueError:
            return []
        reports = record.get("reports", {})
        missing = []
        while current <= end:
            key = current.isoformat()
            if not isinstance(reports.get(key), dict) or not reports[key].get("message_id"):
                missing.append(key)
            current += timedelta(days=1)
        return missing


def get_day_stats(guild_id: int, report_date: str) -> dict:
    with _REPORT_DATA_LOCK:
        data = _load_unlocked()
        record = _guild_record(data, guild_id)
        return _normalize_day(record.get("days", {}).get(report_date, {}))


def mark_report_sent(guild_id: int, report_date: str, message_id: int, sent_at: str) -> None:
    with _REPORT_DATA_LOCK:
        data = _load_unlocked()
        record = _guild_record(data, guild_id)
        record.setdefault("reports", {})[report_date] = {
            "message_id": str(message_id),
            "sent_at": sent_at,
        }
        _save_unlocked(data)
