# cogs/manage/punishment_cog.py

import discord
from discord.ext import commands
from discord import Option

from config import IDS, STYLE
from .punishment_db import db
from .punishment_views import ManagementControlView
from ..shared.utils import is_super_egg

# 从 config 获取公示频道 ID
PUBLIC_NOTICE_CHANNEL_ID = IDS.get("PUBLIC_NOTICE_CHANNEL_ID")
LOG_CHANNEL_ID = 1468508677144055818

class PunishmentCog(commands.Cog, name="处罚系统"):
    def __init__(self, bot):
        self.bot = bot
        # 注册持久化视图
        # 在 __init__ 中直接给 ctx 传 None，仅用于注册
        self.bot.add_view(ManagementControlView(None, public_channel_id=PUBLIC_NOTICE_CHANNEL_ID, log_channel_id=LOG_CHANNEL_ID))

    @commands.Cog.listener()
    async def on_ready(self):
        print("[Punishment] Cog loaded.")

    @discord.slash_command(name="处罚", description="打开管理面板 (可上传证据)")
    @is_super_egg()
    async def punishment_panel(self, ctx: discord.ApplicationContext,
            file1: Option(discord.Attachment, "证据1", required=False)=None,
            file2: Option(discord.Attachment, "证据2", required=False)=None,
            file3: Option(discord.Attachment, "证据3", required=False)=None,
            file4: Option(discord.Attachment, "证据4", required=False)=None,
            file5: Option(discord.Attachment, "证据5", required=False)=None,
            file6: Option(discord.Attachment, "证据6", required=False)=None,
            file7: Option(discord.Attachment, "证据7", required=False)=None,
            file8: Option(discord.Attachment, "证据8", required=False)=None,
            file9: Option(discord.Attachment, "证据9", required=False)=None):
        files = [f for f in [file1, file2, file3, file4, file5, file6, file7, file8, file9] if f]
        view = ManagementControlView(
            ctx,
            initial_files=files,
            public_channel_id=PUBLIC_NOTICE_CHANNEL_ID,
            log_channel_id=LOG_CHANNEL_ID
        )
        await ctx.respond(embed=discord.Embed(title="🛡️ 加载中...", color=STYLE["KIMI_YELLOW"]), view=view, ephemeral=True)
        await view.refresh_view(ctx.interaction)

    @discord.slash_command(name="重置处罚", description="清空某用户的违规计数")
    @is_super_egg()
    async def reset_strikes(self, ctx: discord.ApplicationContext, user: Option(discord.User, "选择用户")):
        db.reset_strikes(user.id)
        await ctx.respond(f"✅ 已清空 {user.mention} 的所有违规计数。", ephemeral=True)