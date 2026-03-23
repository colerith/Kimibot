import discord
from discord.ext import commands
import json
import os
import datetime

# 相对导入可能在Cog加载时会有问题，建议从项目根目录绝对导入配置
from config import IDS, QUOTA, STYLE

# --- 常量 ---
SPECIFIC_REVIEWER_ID = 1452321798308888776
TIMEOUT_HOURS_ARCHIVE = 6
TIMEOUT_HOURS_REMIND = 3
STRINGS_PATH = os.path.join(os.path.dirname(__file__), 'strings.json')

# --- 文本加载 ---
def load_strings():
    try:
        with open(STRINGS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading strings.json: {e}")
        return {}

STRINGS = load_strings()

# --- 权限检查 ---
def is_reviewer_egg():
    """权限检查装饰器"""
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not ctx.guild:
            await ctx.respond(STRINGS["messages"]["err_not_guild"], ephemeral=True)
            return False

        if ctx.author.id == SPECIFIC_REVIEWER_ID:
            return True

        super_egg_role = ctx.guild.get_role(IDS.get("SUPER_EGG_ROLE_ID", 0))
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True

        await ctx.respond(STRINGS["messages"]["err_not_staff"], ephemeral=True)
        return False
    return commands.check(predicate)

# --- 频道信息解析 ---
def get_ticket_info(channel: discord.TextChannel):
    info = {}
    if not channel.topic: return info
    try:
        parts = channel.topic.split(" | ")
        for part in parts:
            if ": " in part:
                key, value = part.split(": ", 1)
                info[key] = value
    except Exception: pass
    return info

# --- 额度管理 ---
def load_quota_data():
    try:
        with open(QUOTA["QUOTA_FILE_PATH"], 'r') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_reset_date": "2000-01-01", "daily_quota_left": QUOTA["DAILY_TICKET_LIMIT"]}

def save_quota_data(data):
    with open(QUOTA["QUOTA_FILE_PATH"], 'w') as f: json.dump(data, f, indent=4)

# --- 通用归档逻辑 ---
async def execute_archive(bot, interaction, channel, note, is_timeout=True, log_title_override=None):
    """
    执行归档操作的核心逻辑
    """
    info = get_ticket_info(channel)
    ticket_id = info.get("工单ID", "未知")
    creator_id = info.get("创建者ID")
    creator_name = info.get("创建者", "未知用户")
    operator = interaction.user.mention if interaction else "系统自动"

    # 1. 记录日志
    log_channel = bot.get_channel(IDS.get("TICKET_LOG_CHANNEL_ID") or 1419652525249794128)
    if log_channel:
        log_text = STRINGS["messages"]["log_timeout"].format(
            ticket_id=ticket_id, creator_name=creator_name, creator_id=creator_id,
            operator=operator, note=note
        )
        if log_title_override:
            log_text = log_text.replace("超时归档", log_title_override)
        elif not is_timeout: # 手动归档
            log_text = log_text.replace("超时归档", "手动归档")
        await log_channel.send(log_text)

    # 2. 如果是超时，私信通知用户
    if is_timeout and creator_id:
        try:
            user = await bot.fetch_user(int(creator_id))
            await user.send(f"工单 `{ticket_id}` 已超时关闭。\n备注: {note}\n欢迎重新申请~")
        except: pass

    # 3. 移动频道或删除

    archive_cat = channel.guild.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
    if archive_cat:
        new_name = f"超时归档-{ticket_id}-{creator_name}" if is_timeout else f"归档-{ticket_id}-{creator_name}"
        overwrites = {channel.guild.default_role: discord.PermissionOverwrite(read_messages=False)}
        # 保留管理员权限
        spec_user = channel.guild.get_member(SPECIFIC_REVIEWER_ID)
        if spec_user: overwrites[spec_user] = discord.PermissionOverwrite(read_messages=True)

        try:
            await channel.edit(name=new_name, category=archive_cat, overwrites=overwrites, reason=note)
            await channel.send(f"🚫 **已归档**\n原因: {note}")
            if interaction:
                await interaction.response.send_message(f"✅ 已归档频道: {ticket_id}", ephemeral=True)
        except Exception as e:
            if interaction: await interaction.followup.send(f"归档出错: {e}", ephemeral=True)
    else:
        # 如果找不到归档分类，只能删除
        await channel.delete(reason=note)
