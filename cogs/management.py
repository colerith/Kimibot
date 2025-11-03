import discord
from discord import SlashCommandGroup
from discord.ext import commands
import datetime
from config import IDS, QUOTA, STYLE

KIMI_FOOTER_TEXT = "请遵守社区规则，一起做个乖饱饱嘛~！"

# --- 权限检查魔法 ---
# 这个检查函数确保只有“超级小蛋”才能使用这些管理命令
def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        # 确保 ctx.author 不是 None 并且有 roles 属性
        if not isinstance(ctx.author, discord.Member) or not hasattr(ctx.author, 'roles'):
             await ctx.respond("呜...无法识别你的身份组信息！", ephemeral=True)
             return False
        
        super_egg_role = ctx.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True
        
        await ctx.respond("呜...这个是【超级小蛋】专属嘟魔法，你还不能用捏！QAQ", ephemeral=True)
        return False
    return commands.check(predicate)

# --- 时间转换小工具 ---
# 用于解析像 "10m", "1h", "7d" 这样的时间字符串
def parse_duration(duration_str: str) -> int:
    """将时间字符串 (e.g., '1d', '2h', '30m') 转换为秒数。"""
    try:
        unit = duration_str[-1].lower()
        value = int(duration_str[:-1])
        if unit == 's': return value
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 3600
        elif unit == 'd': return value * 86400
    except (ValueError, IndexError):
        # 如果格式不正确（例如 "abc" 或空字符串），返回0
        return 0
    return 0

# --- 管理命令的 Cog ---
class Management(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    # 创建一个名为 "管理 (mod)" 的斜杠命令组
    mod = SlashCommandGroup("管理", "对不乖的饱饱进行一些小小的惩罚~", checks=[is_super_egg()])

    @mod.command(name="禁言", description="让某个小调皮暂时安静一下下！")
    async def mute(self, ctx: discord.ApplicationContext, user: discord.Member, duration: str, reason: str = "没有理由，但本大王觉得需要！"):
        """
        禁言用户指定的时间。
        duration: 时间字符串，如 "10s", "5m", "1h", "3d"
        """
        seconds = parse_duration(duration)
        if seconds <= 0 or seconds > 2419200: # 2419200 秒 = 28 天
            await ctx.respond("时间格式不对或者太长惹！要用 's', 'm', 'h', 'd' 结尾，并且不能超过28天唷！", ephemeral=True)
            return
        
        delta = datetime.timedelta(seconds=seconds)
        until = discord.utils.utcnow() + delta
        
        try:
            await user.timeout(until, reason=reason)
            embed = discord.Embed(title="🤫 小调皮要安静一下下唷~", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
            embed.add_field(name="处罚对象", value=user.mention, inline=False)
            embed.add_field(name="处罚期限", value=duration, inline=False)
            embed.add_field(name="处罚理由", value=reason, inline=False)
            embed.add_field(name="操作员", value=ctx.author.mention, inline=False)
            embed.add_field(name="解除时间", value=f"<t:{int(until.timestamp())}:R>", inline=False)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="用户ID", value=user.id, inline=False)
            embed.set_footer(text=KIMI_FOOTER_TEXT)
            await ctx.respond(embed=embed)
        except discord.Forbidden:
            await ctx.respond("呜哇！本大王没有足够的权限来禁言这个用户！QAQ", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"发生了一个未知错误: {e}", ephemeral=True)

    @mod.command(name="警告", description="对用户发出爱心警告！")
    async def warn(self, ctx: discord.ApplicationContext, user: discord.Member, reason: str):
        """对用户发出一次公开警告。"""
        embed = discord.Embed(title="⚠️ 注意注意！本大王的爱心警告来惹！", description=f"给 {user.mention} 的警告！", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.add_field(name="警告理由", value=reason, inline=False)
        embed.add_field(name="操作员", value=ctx.author.mention, inline=False)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="用户ID", value=user.id, inline=False)
        embed.set_footer(text="再这样本大王就要生气惹！哼！")
        await ctx.respond(embed=embed)

    @mod.command(name="解除禁言", description="大发慈悲地让饱饱重新说话！")
    async def unmute(self, ctx: discord.ApplicationContext, user: discord.Member):
        """手动解除用户的禁言状态。"""
        try:
            await user.timeout(None, reason=f"由 {ctx.author.name} 解除")
            await ctx.respond(f"好惹好惹，看在饱饱这么可爱嘟份上，本大王就大发慈悲地让 {user.mention} 重新说话吧！要乖乖嘟唷~！🎤")
        except discord.Forbidden:
            await ctx.respond("呜哇！本大王没有足够的权限来操作这个用户！QAQ", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"发生了一个未知错误: {e}", ephemeral=True)


    @mod.command(name="踢出", description="把不乖的饱饱暂时发射出去！")
    async def kick(self, ctx: discord.ApplicationContext, user: discord.Member, reason: str = "这里不欢迎不听话的饱饱哦！"):
        """从服务器踢出成员。"""
        try:
            await user.kick(reason=reason)
            embed = discord.Embed(title="🚀 坏饱饱，发射！", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
            embed.add_field(name="处罚对象", value=user.display_name, inline=False)
            embed.add_field(name="处罚理由", value=reason, inline=False)
            embed.add_field(name="操作员", value=ctx.author.mention, inline=False)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="用户ID", value=user.id, inline=False)
            embed.set_footer(text="暂时冷静一下，想回来要先变乖唷！")
            await ctx.respond(embed=embed)
        except discord.Forbidden:
            await ctx.respond(f"呜哇！本大王没有权限把 {user.mention} 发射出去！QAQ", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"发生了一个未知错误: {e}", ephemeral=True)


    @mod.command(name="封禁", description="哼！不许再回来惹！")
    async def ban(self, ctx: discord.ApplicationContext, user: discord.Member, reason: str = "惹本大王生气嘟后果很严重！"):
        """封禁服务器成员。"""
        try:
            await user.ban(reason=reason)
            embed = discord.Embed(title="🚫 哼！不许再回来惹！", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
            embed.add_field(name="处罚对象", value=user.display_name, inline=False)
            embed.add_field(name="处罚理由", value=reason, inline=False)
            embed.add_field(name="操作员", value=ctx.author.mention, inline=False)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="用户ID", value=user.id, inline=False)
            embed.set_footer(text="社区的大门已经对你永久关闭惹！")
            await ctx.respond(embed=embed)
        except discord.Forbidden:
            await ctx.respond(f"呜哇！本大王没有权限封禁 {user.mention}！QAQ", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"发生了一个未知错误: {e}", ephemeral=True)

    
    @mod.command(name="解除封禁", description="本大王心软惹...再给一次机会吧！")
    async def unban(self, ctx: discord.ApplicationContext, user_id: str):
        """通过用户ID解除封禁。"""
        try:
            user = await self.bot.fetch_user(int(user_id))
            await ctx.guild.unban(user, reason=f"由 {ctx.author.name} 解除")
            await ctx.respond(f"本大王心软惹…好吧好吧，再给 {user.name} 一次机会，要好好珍惜唷呐！💖")
        except discord.NotFound:
            await ctx.respond("咦？找不到这个饱饱，是不是ID写错惹？", ephemeral=True)
        except ValueError:
            await ctx.respond("呜...用户ID应该是一串数字才对呀！", ephemeral=True)
        except discord.Forbidden:
            await ctx.respond("呜哇！本大王没有权限解除封禁！QAQ", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"呜...出错了惹: {e}", ephemeral=True)

# 这是一个固定的函数，用于让你的主文件(main.py)能够加载这个Cog
def setup(bot):
    bot.add_cog(Management(bot))