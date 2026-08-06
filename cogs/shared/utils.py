import discord
from discord.ext import commands
import datetime
import math
from config import IDS, STYLE, SERVER_OWNER_ID

# 常量定义
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))
KIMI_FOOTER_TEXT = "请遵守社区规则，一起做个乖饱饱嘛~！"

# 检查权限：超级小蛋
def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if ctx.author.id == SERVER_OWNER_ID:
            return True

        if not isinstance(ctx.author, discord.Member) or not hasattr(ctx.author, 'roles'):
             await ctx.respond("呜...无法识别你的身份组信息！", ephemeral=True)
             return False

        super_egg_role = ctx.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True

        await ctx.respond("🚫 只有【超级小蛋】才能使用此魔法哦！", ephemeral=True)
        return False
    return commands.check(predicate)


def has_verification_role(member: discord.Member) -> bool:
    """是否已拥有新兵蛋子或正式成员身份。"""
    if not isinstance(member, discord.Member) or not hasattr(member, "roles"):
        return False

    verified_role_ids = {
        int(IDS.get("VERIFICATION_ROLE_ID", 0) or 0),
        int(IDS.get("HATCHED_ROLE_ID", 0) or 0),
    }
    return any(role.id in verified_role_ids for role in member.roles)


def get_account_wait_status(member: discord.Member, guild_id: int | None) -> dict:
    """根据账号注册时间和加速卡计算正式答题剩余等待期。"""
    from cogs.points.storage import get_acceleration_status

    accel = get_acceleration_status(member.id, guild_id)
    now = discord.utils.utcnow()
    account_age = now - member.created_at
    account_age_seconds = max(0, account_age.total_seconds())
    account_age_days_float = account_age_seconds / 86400
    required_days = int(accel.get("required_wait_days", 30))
    remaining_seconds = max(0, required_days * 86400 - account_age_seconds)
    remaining_days = int(math.ceil(remaining_seconds / 86400)) if remaining_seconds > 0 else 0

    return {
        **accel,
        "account_age_days": int(account_age_days_float),
        "account_age_days_float": account_age_days_float,
        "remaining_wait_days": remaining_days,
        "eligible": remaining_days <= 0,
    }

# 时间解析
def parse_duration(duration_str: str) -> int:
    try:
        unit = duration_str[-1].lower()
        value = int(duration_str[:-1])
        if unit == 's': return value
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 3600
        elif unit == 'd': return value * 86400
    except (ValueError, IndexError):
        return 0
    return 0

# 进度条生成
def generate_progress_bar(percent: float, length: int = 15) -> str:
    filled_length = int(length * percent // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return bar
