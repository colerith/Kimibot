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
    "QUIZ_LOG_CHANNEL_ID": 1452485785939869808
}

# --- 额度配置 ---
QUOTA = {
    "DAILY_TICKET_LIMIT": 100,
    "TIMEZONE": datetime.timezone(datetime.timedelta(hours=8)),
    "QUOTA_FILE_PATH": 'quota_data.json'
}

# --- 身份组抽奖相关配置 ---
LOTTERY = {  
    "LOTTERY_COST": 50, 
    "LOTTERY_REFUND": 20,
    "user_cooldowns": {},
    "COOLDOWN_SECONDS": 30
}

# --- 外观配置 ---
STYLE = {"KIMI_YELLOW": 0xFFD700, "KIMI_FOOTER_TEXT": "请遵守社区规则，一起做个乖饱饱嘛~！"}

globals().update(IDS)
globals().update(QUOTA)
globals().update(STYLE)
globals().update(LOTTERY)
