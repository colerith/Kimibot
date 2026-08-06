import json
import os
import random
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

QUESTION_BANK_FILE = Path(__file__).with_name("question_bank.json")
PREQUIZ_DATA_FILE = "data/prequiz_attempts.json"
TZ_CN = timezone(timedelta(hours=8))
RETRY_COOLDOWN_SECONDS = 5 * 60


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ_CN)
    return dt.astimezone(TZ_CN)


def _load_json_file(path: str | Path, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json_file(path: str | Path, data: Any):
    dirname = os.path.dirname(str(path))
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def load_question_bank() -> dict:
    raw = _load_json_file(QUESTION_BANK_FILE, {"version": 1, "multiple_choice": [], "short_questions": []})
    if not isinstance(raw, dict):
        raw = {}

    multiple_choice = []
    for item in raw.get("multiple_choice", []):
        if not isinstance(item, dict):
            continue
        options = item.get("options", {})
        answer = str(item.get("answer", "")).strip()
        if not isinstance(options, dict) or answer not in options:
            continue
        if len(options) < 2:
            continue
        multiple_choice.append(
            {
                "id": str(item.get("id", f"mc_{len(multiple_choice) + 1}")),
                "question": str(item.get("question", "")).strip(),
                "options": {str(k): str(v) for k, v in options.items()},
                "answer": answer,
            }
        )

    short_questions = []
    for item in raw.get("short_questions", []):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not question or not answer:
            continue
        short_questions.append(
            {
                "id": str(item.get("id", f"short_{len(short_questions) + 1}")),
                "question": question,
                "answer": answer,
            }
        )

    return {"version": int(raw.get("version", 1) or 1), "multiple_choice": multiple_choice, "short_questions": short_questions}


def draw_prequiz_questions() -> dict | None:
    bank = load_question_bank()
    if len(bank["multiple_choice"]) < 5 or not bank["short_questions"]:
        return None
    return {
        "multiple_choice": random.sample(bank["multiple_choice"], 5),
        "short_question": random.choice(bank["short_questions"]),
    }


def load_attempts() -> dict:
    raw = _load_json_file(PREQUIZ_DATA_FILE, {"version": 1, "attempts": {}})
    if not isinstance(raw, dict):
        return {"version": 1, "attempts": {}}
    attempts = raw.get("attempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
    return {"version": 1, "attempts": attempts}


def save_attempts(data: dict):
    _save_json_file(PREQUIZ_DATA_FILE, data)


def get_attempt(user_id: int, guild_id: int | None) -> dict | None:
    data = load_attempts()
    key = f"{guild_id}:{user_id}" if guild_id else str(user_id)
    attempt = data.get("attempts", {}).get(key)
    return attempt if isinstance(attempt, dict) else None


def get_prequiz_access(user_id: int, guild_id: int | None) -> dict:
    attempt = get_attempt(user_id, guild_id)
    if not attempt:
        return {"allowed": True, "reason": "new"}

    if attempt.get("passed") or attempt.get("reward_granted"):
        return {"allowed": False, "reason": "passed", "attempt": attempt}

    last_at = _parse_iso(str(attempt.get("last_attempt_at") or attempt.get("created_at") or ""))
    if not last_at:
        return {"allowed": True, "reason": "cooldown_unknown", "attempt": attempt}

    elapsed = (datetime.now(TZ_CN) - last_at).total_seconds()
    remaining = max(0, RETRY_COOLDOWN_SECONDS - elapsed)
    if remaining > 0:
        return {
            "allowed": False,
            "reason": "cooldown",
            "remaining_seconds": int(math.ceil(remaining)),
            "attempt": attempt,
        }

    return {"allowed": True, "reason": "retry", "attempt": attempt}


def save_attempt(
    *,
    user_id: int,
    guild_id: int,
    passed: bool,
    score: int,
    mc_details: list[dict],
    short_question: dict,
    short_answer: str,
    reward_granted: bool,
):
    data = load_attempts()
    key = f"{guild_id}:{user_id}"
    existing = data.setdefault("attempts", {}).get(key, {})
    if not isinstance(existing, dict):
        existing = {}
    history = existing.get("history", [])
    if not isinstance(history, list):
        history = []

    now = _now_iso()
    attempt_no = int(existing.get("attempt_count", 0) or 0) + 1
    attempt_row = {
        "attempt_no": attempt_no,
        "passed": bool(passed),
        "score": int(score),
        "mc_details": mc_details,
        "short_question_id": short_question.get("id", ""),
        "short_answer": short_answer,
        "short_expected": short_question.get("answer", ""),
        "reward_granted": bool(reward_granted),
        "created_at": now,
    }
    history.append(attempt_row)
    history = history[-20:]

    data["attempts"][key] = {
        "user_id": str(user_id),
        "guild_id": str(guild_id),
        "passed": bool(passed),
        "score": int(score),
        "mc_details": mc_details,
        "short_question_id": short_question.get("id", ""),
        "short_answer": short_answer,
        "short_expected": short_question.get("answer", ""),
        "reward_granted": bool(reward_granted),
        "created_at": existing.get("created_at") or now,
        "last_attempt_at": now,
        "attempt_count": attempt_no,
        "retry_after_seconds": 0 if passed else RETRY_COOLDOWN_SECONDS,
        "history": history,
    }
    save_attempts(data)
