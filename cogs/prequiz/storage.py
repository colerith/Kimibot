import json
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

QUESTION_BANK_FILE = Path(__file__).with_name("question_bank.json")
PREQUIZ_DATA_FILE = "data/prequiz_attempts.json"
TZ_CN = timezone(timedelta(hours=8))


def _now_iso() -> str:
    return datetime.now(TZ_CN).isoformat(timespec="seconds")


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
    data.setdefault("attempts", {})[key] = {
        "user_id": str(user_id),
        "guild_id": str(guild_id),
        "passed": bool(passed),
        "score": int(score),
        "mc_details": mc_details,
        "short_question_id": short_question.get("id", ""),
        "short_answer": short_answer,
        "short_expected": short_question.get("answer", ""),
        "reward_granted": bool(reward_granted),
        "created_at": _now_iso(),
    }
    save_attempts(data)
