import pytz
import os
import datetime


# --- 身份组和频道ID配置 ---
IDS = {
    "SUPER_EGG_ROLE_ID": 1417724603253395526,
    "SERVER_OWNER_ID": 1353777207042113576,
    "WISH_CHANNEL_ID": 1417577014096957554,
    "VERIFICATION_ROLE_ID": 1417722528574738513,
    "HATCHED_ROLE_ID": 1417722389718110249,
    "TICKET_PANEL_CHANNEL_ID": 1417572579304013885,
    "FIRST_REVIEW_CHANNEL_ID":
    1418598526765629550,  # 注意：你的代码里叫 Category，但功能上是作为父频道的
    "SECOND_REVIEW_CHANNEL_ID": 1419599094988537856,  # 我已在 tickets.py 中适配了这个用法
    "ARCHIVE_CHANNEL_ID": 1418602649305092211,  # 同上
    "TICKET_LOG_CHANNEL_ID": 1419652525249794128
}

# --- 额度配置 ---
QUOTA = {
    "DAILY_TICKET_LIMIT": 60,
    "TIMEZONE": datetime.timezone(datetime.timedelta(hours=8)),
    "QUOTA_FILE_PATH": 'quota_data.json'
}

# --- 外观配置 ---
STYLE = {"KIMI_YELLOW": 0xFFD700, "KIMI_FOOTER_TEXT": "请遵守社区规则，一起做个乖饱饱嘛~！"}

# --- Bot Token ---
# Bot Token 已移至环境变量管理，使用 Replit Secrets 中的 DISCORD_TOKEN
