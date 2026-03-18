# cogs/manage/punishment_cog.py

import discord
from discord.ext import commands
from discord import Option
import datetime

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

    @discord.message_command(name="📢广告处罚")
    @is_super_egg()
    async def ad_punish_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        if not guild:
            return await ctx.respond("❌ 无法在私信中使用。", ephemeral=True)

        target_id = message.author.id
        member = None
        try:
            member = guild.get_member(target_id) or await guild.fetch_member(target_id)
        except discord.NotFound:
            pass

        reason = "广告行为"
        msg_act = "广告清理"
        color = 0xFF8800

        try:
            if member:
                roles_to_remove = [r for r in member.roles if r != guild.default_role]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason=reason)

            start_of_day = datetime.datetime.now(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            await message.channel.purge(after=start_of_day, check=lambda m: m.author.id == target_id)

            new_count = db.add_strike(target_id)

            public_chan = guild.get_channel(PUBLIC_NOTICE_CHANNEL_ID)
            user_obj = member or message.author
            public_msg = None
            if public_chan:
                p_embed = discord.Embed(title=f"🚨 违规公示 | {msg_act}", color=color)
                p_embed.add_field(name="违规者", value=f"<@{target_id}> (`{user_obj.name}`)", inline=True)
                p_embed.add_field(name="累计违规", value=f"**{new_count}** 次", inline=True)
                p_embed.description = f"**理由:**\n{reason}"
                p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
                p_embed.timestamp = discord.utils.utcnow()
                if user_obj.display_avatar:
                    p_embed.set_thumbnail(url=user_obj.display_avatar.url)
                public_msg = await public_chan.send(embed=p_embed)

            log_chan = guild.get_channel(LOG_CHANNEL_ID)
            if log_chan:
                log_embed = discord.Embed(title="🛡️ 管理执行日志: AD", color=color)
                log_embed.description = f"**理由:** {reason}"
                log_embed.add_field(name="执行人 (Executor)", value=ctx.user.mention, inline=True)
                log_embed.add_field(name="目标 (Target)", value=user_obj.mention, inline=True)
                log_embed.add_field(name="触发消息", value=message.jump_url, inline=False)

                log_view = discord.ui.View()
                if public_msg:
                    log_view.add_item(discord.ui.Button(label="查看公示", url=public_msg.jump_url, style=discord.ButtonStyle.link))

                await log_chan.send(embed=log_embed, view=log_view)

            await ctx.followup.send("✅ 已执行广告处罚并发送公示。", ephemeral=True)

        except discord.Forbidden as e:
            await ctx.followup.send(f"❌ 权限不足: {e}", ephemeral=True)
        except Exception as e:
            await ctx.followup.send(f"❌ 执行失败: {e}", ephemeral=True)
