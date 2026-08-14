# cogs/roles/cog.py

import asyncio

import discord
from discord.ext import commands, tasks
from discord import SlashCommandGroup

from .views import (
    CommunityPanelManageView,
    RoleClaimView,
    build_community_manage_embed,
    NotificationEntranceView,
    refresh_role_panel,
)
from cogs.shared.utils import is_super_egg
from .storage import load_role_data, get_collection_reward_role_ids, reconcile_cached_member_ownership

class RolesCog(commands.Cog):
    """负责自助身份组领取、通知订阅和相关管理命令。"""

    def __init__(self, bot):
        self.bot = bot
        self.role_panel_auto_refreshed = False
        self.ownership_scanner_started = False

    @commands.Cog.listener()
    async def on_ready(self):
        # 注册持久化视图，这样机器人重启后按钮也能继续工作
        self.bot.add_view(RoleClaimView())
        self.bot.add_view(NotificationEntranceView())
        print("[Roles] Cog loaded and persistent views registered.")
        if not self.role_panel_auto_refreshed:
            self.role_panel_auto_refreshed = True
            self.bot.loop.create_task(self._refresh_saved_role_panel())
        if not self.ownership_scanner_started:
            self.ownership_scanner_started = True
            self.cached_ownership_reconcile.start()

    def cog_unload(self):
        self.cached_ownership_reconcile.cancel()

    @tasks.loop(hours=6)
    async def cached_ownership_reconcile(self):
        """Silently import pre-existing collectible roles from the member cache."""
        try:
            role_data = await asyncio.to_thread(load_role_data)
        except Exception:
            return
        relevant_ids = (
            set(role_data.get("lottery_roles", []))
            | set(role_data.get("redeem_roles", []))
            | set(get_collection_reward_role_ids(role_data))
        )
        if not relevant_ids:
            return

        member_roles: dict[int, set[int]] = {}
        scanned = 0
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                matched = {role.id for role in member.roles if role.id in relevant_ids}
                if matched:
                    member_roles.setdefault(member.id, set()).update(matched)
                scanned += 1
                if scanned % 250 == 0:
                    # Pure cache work, but yield regularly so other bot events stay responsive.
                    await asyncio.sleep(0)

        if member_roles:
            try:
                await asyncio.to_thread(reconcile_cached_member_ownership, member_roles, role_data)
            except Exception:
                # This maintenance pass is intentionally silent and will retry next cycle.
                return

    @cached_ownership_reconcile.before_loop
    async def before_cached_ownership_reconcile(self):
        await self.bot.wait_until_ready()

    async def _refresh_saved_role_panel(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            if await refresh_role_panel(guild, avatar_url):
                print(f"[Roles] refreshed saved role panel names in guild {guild.id}.")
                return

    # --- 命令组定义 ---
    community_group = SlashCommandGroup("社区面板", "管理小蛋报到与社区蛋壳面板")

    @community_group.command(name="管理", description="打开社区面板管理台")
    @is_super_egg()
    async def manage_community_panel(self, ctx: discord.ApplicationContext):
        try:
            await ctx.defer(ephemeral=True)
        except discord.NotFound:
            return
        embed = build_community_manage_embed(ctx.guild)
        view = CommunityPanelManageView(ctx, self.bot)
        try:
            await ctx.followup.send(embed=embed, view=view, ephemeral=True)
        except discord.NotFound:
            return
