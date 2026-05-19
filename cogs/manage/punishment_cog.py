# cogs/manage/punishment_cog.py

import datetime
import re

import discord
from discord import Option
from discord.ext import commands

from config import IDS, STYLE
from .punishment_db import db
from .punishment_views import ManagementControlView
from ..shared.utils import is_super_egg, parse_duration

PUBLIC_NOTICE_CHANNEL_ID = IDS.get("PUBLIC_NOTICE_CHANNEL_ID")
LOG_CHANNEL_ID = IDS.get("LOG_CHANNEL_ID", 1468508677144055818)


class PunishmentCog(commands.Cog, name="处罚系统"):
    def __init__(self, bot):
        self.bot = bot
        self.persistent_view = None

    @staticmethod
    def _parse_user_ids(raw_text: str | None):
        if not raw_text:
            return []

        matches = re.findall(r"\d{15,20}", raw_text)
        seen = set()
        ordered_ids = []
        for item in matches:
            uid = int(item)
            if uid in seen:
                continue
            seen.add(uid)
            ordered_ids.append(uid)
        return ordered_ids

    async def _apply_single_action(
        self,
        guild: discord.Guild,
        target_id: int,
        action: str,
        reason: str,
        duration_secs: int,
    ):
        member = None

        try:
            member = guild.get_member(target_id) or await guild.fetch_member(target_id)
        except discord.NotFound:
            member = None

        try:
            if action == "warn":
                if not member:
                    raise ValueError("用户不在服务器内，无法执行警告")

                if member:
                    try:
                        dm_embed = discord.Embed(
                            title=f"⚠️ {guild.name} 社区警告",
                            description=f"**理由:** {reason}",
                            color=0xFFAA00,
                        )
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        pass

                strike = db.add_strike(target_id)
                linked_action = "无"
                try:
                    if strike == 1:
                        await member.timeout(
                            discord.utils.utcnow() + datetime.timedelta(days=1),
                            reason=reason,
                        )
                        linked_action = "禁言 1 天"
                    elif strike == 2:
                        await member.timeout(
                            discord.utils.utcnow() + datetime.timedelta(days=7),
                            reason=reason,
                        )
                        linked_action = "禁言 7 天"
                    elif strike >= 3:
                        await guild.ban(discord.Object(id=target_id), reason=reason)
                        linked_action = "永久封禁"
                except (discord.Forbidden, discord.HTTPException, ValueError) as linked_err:
                    linked_action = f"自动处罚失败: {linked_err}"

                return {
                    "ok": True,
                    "target_id": target_id,
                    "member": member,
                    "strike": strike,
                    "linked_action": linked_action,
                }

            elif action == "unwarn":
                strike = db.remove_strike(target_id)
                return {
                    "ok": True,
                    "target_id": target_id,
                    "member": member,
                    "strike": strike,
                    "linked_action": "仅撤销累计，不自动反向解除处罚",
                }

            elif action == "mute":
                if not member:
                    raise ValueError("用户不在服务器内，无法禁言")
                await member.timeout(
                    discord.utils.utcnow() + datetime.timedelta(seconds=duration_secs),
                    reason=reason,
                )

            elif action == "kick":
                if not member:
                    raise ValueError("用户不在服务器内，无法踢出")
                await member.kick(reason=reason)

            elif action == "ban":
                await guild.ban(discord.Object(id=target_id), reason=reason)

            elif action == "unmute":
                if not member:
                    raise ValueError("用户不在服务器内，无法解除禁言")
                await member.timeout(None, reason=reason)

            elif action == "unban":
                await guild.unban(discord.Object(id=target_id), reason=reason)

            else:
                raise ValueError("不支持的处罚动作")

            strike = db.get_strikes(target_id)

            return {
                "ok": True,
                "target_id": target_id,
                "member": member,
                "strike": strike,
                "linked_action": "",
            }

        except (discord.Forbidden, discord.HTTPException, ValueError) as e:
            return {
                "ok": False,
                "target_id": target_id,
                "member": member,
                "error": str(e),
            }

    @commands.Cog.listener()
    async def on_ready(self):
        if self.persistent_view is None:
            self.persistent_view = ManagementControlView(
                ctx=None,
                public_channel_id=PUBLIC_NOTICE_CHANNEL_ID,
                log_channel_id=LOG_CHANNEL_ID,
                timeout=None,
            )
            self.bot.add_view(self.persistent_view)

        print("[Punishment] Cog loaded and view registered (if persistent).")

    @discord.slash_command(name="处罚", description="打开管理面板 (可上传证据)")
    @is_super_egg()
    async def punishment_panel(
        self,
        ctx: discord.ApplicationContext,
        file1: Option(discord.Attachment, "证据1", required=False) = None,
        file2: Option(discord.Attachment, "证据2", required=False) = None,
        file3: Option(discord.Attachment, "证据3", required=False) = None,
        file4: Option(discord.Attachment, "证据4", required=False) = None,
        file5: Option(discord.Attachment, "证据5", required=False) = None,
        file6: Option(discord.Attachment, "证据6", required=False) = None,
        file7: Option(discord.Attachment, "证据7", required=False) = None,
        file8: Option(discord.Attachment, "证据8", required=False) = None,
        file9: Option(discord.Attachment, "证据9", required=False) = None,
    ):
        files = [f for f in [file1, file2, file3, file4, file5, file6, file7, file8, file9] if f]

        view = ManagementControlView(
            ctx,
            initial_files=files,
            public_channel_id=PUBLIC_NOTICE_CHANNEL_ID,
            log_channel_id=LOG_CHANNEL_ID,
        )
        await ctx.respond(
            embed=discord.Embed(title="🛡️ 加载中...", color=STYLE["KIMI_YELLOW"]),
            view=view,
            ephemeral=True,
        )
        await view.refresh_view(ctx.interaction)

    @discord.slash_command(name="批量处罚", description="一次对多个用户执行同一种处罚")
    @is_super_egg()
    async def batch_punishment(
        self,
        ctx: discord.ApplicationContext,
        action: Option(
            str,
            "处罚动作",
            choices=["warn", "unwarn", "mute", "kick", "ban", "unmute", "unban"],
        ),
        reason: Option(str, "处罚理由", required=False) = "违反社区规范",
        duration: Option(str, "禁言时长(仅 mute 生效，如 10m/1h/3d)", required=False) = "1h",
        id_text: Option(str, "输入多个ID或@提及（空格/逗号/换行分隔）", required=False) = None,
        user1: Option(discord.User, "选择用户1", required=False) = None,
        user2: Option(discord.User, "选择用户2", required=False) = None,
        user3: Option(discord.User, "选择用户3", required=False) = None,
        user4: Option(discord.User, "选择用户4", required=False) = None,
        user5: Option(discord.User, "选择用户5", required=False) = None,
    ):
        await ctx.defer(ephemeral=True)
        guild = ctx.guild
        if not guild:
            return await ctx.followup.send("❌ 无法在私信中使用。", ephemeral=True)

        target_ids = {u.id for u in [user1, user2, user3, user4, user5] if u}
        target_ids.update(self._parse_user_ids(id_text))

        if not target_ids:
            return await ctx.followup.send(
                "❌ 请至少提供一个目标（用户选择器或ID文本）。",
                ephemeral=True,
            )

        duration_secs = 0
        if action == "mute":
            duration_secs = parse_duration(duration or "")
            if duration_secs <= 0:
                return await ctx.followup.send(
                    "❌ 禁言时长无效，请使用如 `10m` / `1h` / `3d`。",
                    ephemeral=True,
                )

        sorted_targets = sorted(target_ids)
        success = []
        failed = []

        for target_id in sorted_targets:
            result = await self._apply_single_action(
                guild=guild,
                target_id=target_id,
                action=action,
                reason=reason,
                duration_secs=duration_secs,
            )

            if result["ok"]:
                success.append(result)
            else:
                failed.append(result)

        action_map = {
            "warn": "⚠️ 警告",
            "unwarn": "✅ 撤销警告",
            "mute": "🤐 禁言",
            "kick": "🚀 踢出",
            "ban": "🚫 封禁",
            "unmute": "🎤 解除禁言",
            "unban": "🔓 解封",
        }
        color_map = {
            "warn": 0xFFAA00,
            "unwarn": 0x66CC99,
            "mute": 0xFF5555,
            "kick": 0xFF0000,
            "ban": 0x000000,
            "unmute": 0x55FF55,
            "unban": 0x00AAFF,
        }
        act_label = action_map.get(action, action)
        color = color_map.get(action, 0x999999)

        public_msg = None
        public_chan = guild.get_channel(PUBLIC_NOTICE_CHANNEL_ID)
        if public_chan and success:
            success_mentions = [f"<@{item['target_id']}>" for item in success]
            display_mentions = "\n".join(success_mentions[:20])
            if len(success_mentions) > 20:
                display_mentions += f"\n... 以及其余 {len(success_mentions) - 20} 人"

            p_embed = discord.Embed(title=f"🚨 违规公示 | 批量{act_label}", color=color)
            p_embed.add_field(
                name="目标数量",
                value=f"成功 **{len(success)}** / 总计 **{len(sorted_targets)}**",
                inline=True,
            )
            p_embed.add_field(name="执行人", value=ctx.user.mention, inline=True)
            p_embed.description = f"**理由:**\n{reason}\n\n**目标列表:**\n{display_mentions}"
            if action == "mute":
                p_embed.add_field(name="禁言时长", value=duration, inline=True)
            if action in {"warn", "unwarn"}:
                p_embed.add_field(
                    name="累计说明",
                    value="仅警告动作影响累计次数",
                    inline=True,
                )
            p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
            p_embed.timestamp = discord.utils.utcnow()
            public_msg = await public_chan.send(embed=p_embed)

        log_chan = guild.get_channel(LOG_CHANNEL_ID)
        if log_chan:
            log_embed = discord.Embed(title=f"🛡️ 管理执行日志: BATCH-{action.upper()}", color=color)
            log_embed.description = f"**理由:** {reason}"
            log_embed.add_field(name="执行人 (Executor)", value=ctx.user.mention, inline=True)
            log_embed.add_field(
                name="结果统计",
                value=f"成功 {len(success)} / 失败 {len(failed)} / 总计 {len(sorted_targets)}",
                inline=True,
            )
            if action == "mute":
                log_embed.add_field(name="时长", value=duration, inline=True)
            if action == "warn":
                linked_preview = [
                    f"<@{item['target_id']}>: {item.get('linked_action') or '无'}"
                    for item in success[:10]
                ]
                if linked_preview:
                    log_embed.add_field(
                        name="自动处罚结果",
                        value="\n".join(linked_preview),
                        inline=False,
                    )

            success_list = [f"<@{item['target_id']}>" for item in success]
            failed_list = [f"`{item['target_id']}`: {item['error']}" for item in failed]

            if success_list:
                text = "\n".join(success_list[:20])
                if len(success_list) > 20:
                    text += f"\n... 以及其余 {len(success_list) - 20} 人"
                log_embed.add_field(name="成功目标", value=text, inline=False)

            if failed_list:
                text = "\n".join(failed_list[:10])
                if len(failed_list) > 10:
                    text += f"\n... 以及其余 {len(failed_list) - 10} 条失败"
                log_embed.add_field(name="失败详情", value=text, inline=False)

            log_view = discord.ui.View()
            if public_msg:
                log_view.add_item(
                    discord.ui.Button(
                        label="查看公示",
                        url=public_msg.jump_url,
                        style=discord.ButtonStyle.link,
                    )
                )

            await log_chan.send(embed=log_embed, view=log_view)

        summary = [
            f"✅ 批量处罚执行完成：**{act_label}**",
            f"- 成功：{len(success)}",
            f"- 失败：{len(failed)}",
            f"- 总计：{len(sorted_targets)}",
        ]

        if failed:
            fail_lines = [f"`{item['target_id']}`: {item['error']}" for item in failed[:8]]
            summary.append("\n失败示例：\n" + "\n".join(fail_lines))

        await ctx.followup.send("\n".join(summary), ephemeral=True)

    @discord.slash_command(name="重置处罚", description="清空某用户的违规计数")
    @is_super_egg()
    async def reset_strikes(
        self,
        ctx: discord.ApplicationContext,
        user: Option(discord.User, "选择用户"),
    ):
        db.reset_strikes(user.id)
        await ctx.respond(f"✅ 已清空 {user.mention} 的所有违规计数。", ephemeral=True)
