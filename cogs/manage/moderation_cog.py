# cogs/manage/moderation_cog.py

import discord
from discord.ext import commands
from discord import Option
import asyncio

from .moderation_views import AnnouncementModal
from ..shared.utils import is_super_egg, parse_duration

class ModerationCog(commands.Cog, name="通用管理"):
    """包含日常服务器管理命令，如清屏、慢速模式等。"""

    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="发布公告", description="奇米大王的特别广播时间到惹！(会弹出编辑器哦)")
    @is_super_egg()
    async def publish_announcement(self, ctx: discord.ApplicationContext, 
        channel: discord.TextChannel, 
        mention_role: Option(discord.Role, "要@的身份组", required=False) = None,  # pyright: ignore[reportInvalidTypeForm]
        image1: Option(discord.Attachment, "图片附件1", required=False) = None,  # type: ignore
        image2: Option(discord.Attachment, "图片附件2", required=False) = None, # type: ignore
        image3: Option(discord.Attachment, "图片附件3", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image4: Option(discord.Attachment, "图片附件4", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image5: Option(discord.Attachment, "图片附件5", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image6: Option(discord.Attachment, "图片附件6", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image7: Option(discord.Attachment, "图片附件7", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image8: Option(discord.Attachment, "图片附件8", required=False) = None, # pyright: ignore[reportInvalidTypeForm]
        image9: Option(discord.Attachment, "图片附件9", required=False) = None # pyright: ignore[reportInvalidTypeForm]
    ):
        attachments = [img for img in [image1, image2, image3, image4, image5, image6, image7, image8, image9] if img]
        modal = AnnouncementModal(channel, mention_role, attachments)
        await ctx.send_modal(modal)

    @discord.slash_command(name="清空消息", description="本大王来帮你打扫卫生惹！可以定时清理唷~")
    @is_super_egg()
    async def clear_messages(self, ctx: discord.ApplicationContext,
        channel: Option(discord.TextChannel, "目标频道"),
        amount: Option(int, "要删除的消息数量"),
        schedule: Option(str, "延迟执行 (例如: 10s, 5m, 1h)", required=False) = None
    ):
        await ctx.defer(ephemeral=True)
        if schedule:
            delay = parse_duration(schedule)
            if delay > 0:
                await ctx.followup.send(f"收到唷呐！本大王已经把小闹钟定好惹，{delay}秒后开始大扫除！🕰️✨", ephemeral=True)
                await asyncio.sleep(delay)
                deleted_messages = await channel.purge(limit=amount)
                await channel.send(f"咻~！✨ 本大王施展惹清洁魔法，赶跑了 {len(deleted_messages)} 条坏蛋消息！", delete_after=10)
            else:
                await ctx.followup.send("呜...这个时间格式本大王看不懂捏！要用's', 'm', 'h'结尾才可以嘛！", ephemeral=True)
        else:
            deleted_messages = await channel.purge(limit=amount)
            await ctx.followup.send(f"咻~！✨ 本大王施展惹清洁魔法，赶跑了 {len(deleted_messages)} 条坏蛋消息！", ephemeral=True)

    @discord.slash_command(name="慢速模式", description="让大家冷静一点，优雅地聊天嘛~")
    @is_super_egg()
    async def slowmode(self, ctx: discord.ApplicationContext,
        seconds: Option(int, "冷却秒数 (设为0以关闭)")
    ):
        if not (0 <= seconds <= 21600):
            return await ctx.respond("秒数必须在 0 到 21600 (6小时) 之间！", ephemeral=True)

        # 确保 ctx.channel 是可以修改的对象
        if not hasattr(ctx.channel, 'edit'):
             return await ctx.respond("这个命令不能用在当前频道类型哦！", ephemeral=True)

        await ctx.channel.edit(slowmode_delay=seconds)

        if seconds > 0:
            await ctx.respond(f"大家冷静一点捏~本大王开启了 **{seconds}秒** 慢速魔法！🐢")
        else:
            await ctx.respond("好惹！封印解除！大家可以尽情地聊天惹！冲鸭！🚀")