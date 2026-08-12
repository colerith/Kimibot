# config.py
import pytz
import os
import datetime

TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

# --- 身份组和频道ID配置 ---
IDS = {
    "SUPER_EGG_ROLE_ID": 1417724603253395526,
    "SERVER_OWNER_ID": 1353777207042113576,
    "WISH_CHANNEL_ID": 1417577014096957554,
    "VERIFICATION_ROLE_ID": 1417722528574738513,
    "HATCHED_ROLE_ID": 1417722389718110249,
    "TICKET_PANEL_CHANNEL_ID": 1417572579304013885,
    "FIRST_REVIEW_CHANNEL_ID": 1418598526765629550,
    "FIRST_REVIEW_EXTRA_CHANNEL_ID": 1467855113786884271,
    "SECOND_REVIEW_CHANNEL_ID": 1419599094988537856,
    "ARCHIVE_CHANNEL_ID": 1418602649305092211,
    "TICKET_LOG_CHANNEL_ID": 1419652525249794128,
    "PUBLIC_NOTICE_CHANNEL_ID":1417573350598770739 ,
    "LOG_CHANNEL_ID": 1468508677144055818,
    "QUIZ_CHANNEL_ID": 1467034060026286090,
    "QUIZ_LOG_CHANNEL_ID": 1452485785939869808,
    "BOOST_THANKS_CHANNEL_ID": 1417575247128821791,
    "AUTO_AD_PUNISH_CHANNEL_ID": 1534797738414182462
}

# --- 额度配置 ---
QUOTA = {
    "DAILY_TICKET_LIMIT": 50,
    "TIMEZONE": datetime.timezone(datetime.timedelta(hours=8)),
    "QUOTA_FILE_PATH": 'quota_data.json'
}

# --- 身份组抽奖相关配置 ---
LOTTERY = {  
    "LOTTERY_COST": 1.0,
    "LOTTERY_FIVE_COST": 5.0,
    "LOTTERY_TEN_COST": 10.0,
    "LOTTERY_REFUND": 1.0,
    "user_cooldowns": {},
    "COOLDOWN_SECONDS": 30
}

POINTS = {
    "POINTS_SIGN_REWARD": 1.0,
    "POINTS_DAILY_MSG_CAP": 100,
    "POINTS_POST_REWARD": 5.0,
    "POINTS_DAILY_POST_CAP": 15.0,
    "POINTS_PER_MSG_MIN": 0,
    "POINTS_PER_MSG_MAX": 0,
    "POINTS_MSG_COOLDOWN": 30,
    "PRAISE_KIMI_CHANNEL_ID": 1450480250210484357,
    "PRAISE_KIMI_TRIGGER": "赞美奇米蛋！",
    "PRAISE_KIMI_REWARD_WEIGHTS": [90, 70, 52, 36, 24, 15, 9, 4, 1],
}

SHELLS = {
    "SIGN_BASE_REWARD": 1.0,
    "SIGN_TOP_RANK_LIMIT": 10,
    "SIGN_TOP_RANK_MIN": 0.1,
    "SIGN_TOP_RANK_MAX": 1.9,
    "RANDOM_EVENT_MIN": 0.1,
    "RANDOM_EVENT_MAX": 1.9,
    "FORUM_REWARD_CHANNEL_IDS": [1467159077422371017, 1417576703487770636],
    "FORUM_REWARD_DAILY_POST_LIMIT": 3,
    "FORUM_REWARD_AMOUNT": 5.0,
    "BOOST_REWARD_AMOUNT": 10.0,
    "PRE_QUIZ_CHANNEL_ID": 1417568378889175071,
    "PRE_QUIZ_REWARD": 5.0,
    "ACCOUNT_BASE_WAIT_DAYS": 30,
    "ACCOUNT_MIN_WAIT_DAYS": 5,
    "ACCELERATION_CARD_TIERS": [
        {"id": "day_1", "label": "减1天", "days": 1, "cost": 2.0},
        {"id": "day_5", "label": "减5天", "days": 5, "cost": 8.0},
        {"id": "day_10", "label": "减10天", "days": 10, "cost": 15.0},
    ],
    "ACCELERATION_CARD_MAX_DAYS": 25,
    "ROLE_LOTTERY_SINGLE_COST": 1.0,
    "ROLE_LOTTERY_FIVE_COST": 5.0,
    "ROLE_LOTTERY_TEN_COST": 10.0,
    "RED_PACKET_EXPIRE_HOURS": 24,
}

SUBMISSIONS = {
    "CHANNEL_IDS": {
        "repo_sfw": 1441437806617563156,
        "repo_nsfw": 1417576370451513495,
        "bug": 1417577014096957554,
        "recommendation": 1536024803587137536,
    },
    "REWARD_RANGES": {
        "base_repo": (0.5, 2.0),
        "base_bug": (0.8, 2.5),
        "base_recommendation": (1.0, 3.0),
        "reply_repo": (0.3, 1.5),
        "reply_bug": (0.5, 2.0),
    },
    "DELETE_PENALTY_RATE": 0.5,
}

EGG_QA = {
    "BOTTOM_PANEL_CHANNEL_ID": 1536931285300154408,
}

SUBMISSION_USEFUL_TIERS = [
    {"count": 3, "reward": 1.0},
    {"count": 10, "reward": 3.0},
    {"count": 30, "reward": 8.0},
    {"count": 50, "reward": 15.0},
]

# --- 外观配置 ---
STYLE = {"KIMI_YELLOW": 0xFFD700, "KIMI_FOOTER_TEXT": "请遵守社区规则，一起做个乖饱饱嘛~！"}

globals().update(IDS)
globals().update(QUOTA)
globals().update(STYLE)
globals().update(LOTTERY)
globals().update(POINTS)
globals().update(SHELLS)
globals().update(SUBMISSIONS)
globals().update(EGG_QA)
