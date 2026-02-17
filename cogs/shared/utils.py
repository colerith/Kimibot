import discord
from discord.ext import commands
import datetime
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
