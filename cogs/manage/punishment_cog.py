# cogs/manage/punishment_cog.py

import discord
from discord.ext import commands
from discord import Option

from config import IDS, STYLE
from .punishment_db import db
from .punishment_views import ManagementControlView
from ..shared.utils import is_super_egg

PUBLIC_NOTICE_CHANNEL_ID = IDS.get("PUBLIC_NOTICE_CHANNEL_ID")
LOG_CHANNEL_ID = 1468508677144055818

class PunishmentCog(commands.Cog, name="处罚系统"):
    def __init__(self, bot):
        self.bot = bot
        self.persistent_view = None

    @commands.Cog.listener()
    async def on_ready(self):
        if self.persistent_view is None:
            self.persistent_view = ManagementControlView(
                ctx=None,
                public_channel_id=PUBLIC_NOTICE_CHANNEL_ID,
                log_channel_id=LOG_CHANNEL_ID,
                timeout=None
            )
            self.bot.add_view(self.persistent_view)

        print("[Punishment] Cog loaded and view registered (if persistent).")

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

        # 每次命令创建新的 View 实例
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
