# cogs/manage/punishment_cog.py

import os
import re
import datetime
import discord
from discord.ext import commands
from discord import Option
import redis.asyncio as redis

from config import IDS, STYLE
from .punishment_db import db
from .punishment_views import ManagementControlView
from ..shared.utils import is_super_egg, parse_duration

PUBLIC_NOTICE_CHANNEL_ID = IDS.get("PUBLIC_NOTICE_CHANNEL_ID")
LOG_CHANNEL_ID = IDS.get("LOG_CHANNEL_ID", 1468508677144055818)

# Redis 配置（可用环境变量覆盖）
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
AD_MESSAGE_TTL_SECONDS = int(os.getenv("AD_MESSAGE_TTL_SECONDS", "86400"))


class PunishmentCog(commands.Cog, name="处罚系统"):
    def __init__(self, bot):
        self.bot = bot
        self.persistent_view = None
        self.redis_client = None
        self.redis_ready = False

    def _redis_key(self, guild_id: int, user_id: int) -> str:
        return f"ad_msgs:{guild_id}:{user_id}"

    async def _init_redis(self):
        if self.redis_client is not None:
            return

        try:
            self.redis_client = redis.from_url(REDIS_URL, decode_responses=True)
            await self.redis_client.ping()
            self.redis_ready = True
            print(f"[Punishment] Redis connected: {REDIS_URL}")
        except Exception as e:
            self.redis_client = None
            self.redis_ready = False
            print(f"[Punishment] Redis unavailable, ad cleanup tracking disabled: {e}")

    async def _track_user_message(self, message: discord.Message):
        if not self.redis_ready or not self.redis_client:
            return
        if not message.guild:
            return
        if message.author.bot:
            return

        key = self._redis_key(message.guild.id, message.author.id)
        value = f"{message.channel.id}:{message.id}"

        try:
            pipe = self.redis_client.pipeline()
            pipe.rpush(key, value)
            pipe.expire(key, AD_MESSAGE_TTL_SECONDS)
            await pipe.execute()
        except Exception as e:
            # 记录失败但不影响主流程
            print(f"[Punishment] Redis track message failed: {e}")

    async def _delete_tracked_messages(self, guild: discord.Guild, user_id: int, reason: str):
        if not self.redis_ready or not self.redis_client:
            return 0, 0, 0

        key = self._redis_key(guild.id, user_id)
        try:
            raw_items = await self.redis_client.lrange(key, 0, -1)
        except Exception as e:
            print(f"[Punishment] Redis read failed: {e}")
            return 0, 0, 0

        deleted_count = 0
        attempted_count = 0
        seen = set()

        for raw in raw_items:
            try:
                channel_id_str, message_id_str = raw.split(":", 1)
                channel_id = int(channel_id_str)
                message_id = int(message_id_str)
            except Exception:
                continue

            pair = (channel_id, message_id)
            if pair in seen:
                continue
            seen.add(pair)
            attempted_count += 1

            channel = guild.get_channel(channel_id)
            if channel is None and hasattr(guild, "get_thread"):
                channel = guild.get_thread(channel_id)
            if channel is None:
                channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue

            try:
                target_msg = await channel.fetch_message(message_id)
                await target_msg.delete(reason=reason)
                deleted_count += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
                continue

        # 处罚执行后，立即清空此用户追踪记录，避免重复删除
        try:
            await self.redis_client.delete(key)
        except Exception:
            pass

        return deleted_count, attempted_count, len(raw_items)

    @staticmethod
    def _parse_user_ids(raw_text: str | None):
        if not raw_text:
            return []

        # 支持: 纯ID、@提及、逗号/空格/换行混合输入
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

    async def _apply_single_action(self, guild: discord.Guild, target_id: int, action: str, reason: str, duration_secs: int):
        member = None
        ad_stats = (0, 0, 0)

        try:
            member = guild.get_member(target_id) or await guild.fetch_member(target_id)
        except discord.NotFound:
            member = None

        try:
            if action == "warn":
                if member:
                    try:
                        dm_embed = discord.Embed(
                            title=f"⚠️ {guild.name} 社区警告",
                            description=f"**理由:** {reason}",
                            color=0xFFAA00
                        )
                        await member.send(embed=dm_embed)
                    except discord.Forbidden:
                        pass

            elif action == "mute":
                if not member:
                    raise ValueError("用户不在服务器内，无法禁言")
                await member.timeout(
                    discord.utils.utcnow() + datetime.timedelta(seconds=duration_secs),
                    reason=reason
                )

            elif action == "ad":
                if not member:
                    raise ValueError("用户不在服务器内，无法执行广告处罚")
                roles_to_remove = [r for r in member.roles if r != guild.default_role]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove, reason=reason)
                ad_stats = await self._delete_tracked_messages(
                    guild=guild,
                    user_id=target_id,
                    reason=reason
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
            if action in {"warn", "mute", "ad", "kick", "ban"}:
                strike = db.add_strike(target_id)

            return {
                "ok": True,
                "target_id": target_id,
                "member": member,
                "strike": strike,
                "ad_stats": ad_stats
            }

        except (discord.Forbidden, discord.HTTPException, ValueError) as e:
            return {
                "ok": False,
                "target_id": target_id,
                "member": member,
                "error": str(e),
                "ad_stats": ad_stats
            }

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

        await self._init_redis()
        print("[Punishment] Cog loaded and view registered (if persistent).")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._track_user_message(message)

    def cog_unload(self):
        if self.redis_client is not None:
            try:
                self.bot.loop.create_task(self.redis_client.aclose())
            except Exception:
                pass

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

    @discord.slash_command(name="批量处罚", description="一次对多个用户执行同一种处罚")
    @is_super_egg()
    async def batch_punishment(
        self,
        ctx: discord.ApplicationContext,
        action: Option(
            str,
            "处罚动作",
            choices=["warn", "mute", "ad", "kick", "ban", "unmute", "unban"]
        ),
        reason: Option(str, "处罚理由", required=False) = "违反社区规范",
        duration: Option(str, "禁言时长(仅 mute 生效，如 10m/1h/3d)", required=False) = "1h",
        id_text: Option(str, "输入多个ID或@提及（空格/逗号/换行分隔）", required=False) = None,
        user1: Option(discord.User, "选择用户1", required=False) = None,
        user2: Option(discord.User, "选择用户2", required=False) = None,
        user3: Option(discord.User, "选择用户3", required=False) = None,
        user4: Option(discord.User, "选择用户4", required=False) = None,
        user5: Option(discord.User, "选择用户5", required=False) = None
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
                ephemeral=True
            )

        duration_secs = 0
        if action == "mute":
            duration_secs = parse_duration(duration or "")
            if duration_secs <= 0:
                return await ctx.followup.send(
                    "❌ 禁言时长无效，请使用如 `10m` / `1h` / `3d`。",
                    ephemeral=True
                )

        sorted_targets = sorted(target_ids)
        success = []
        failed = []
        total_deleted = 0
        total_attempted = 0
        total_tracked = 0

        for target_id in sorted_targets:
            result = await self._apply_single_action(
                guild=guild,
                target_id=target_id,
                action=action,
                reason=reason,
                duration_secs=duration_secs
            )

            if result["ok"]:
                success.append(result)
                deleted_count, attempted_count, tracked_count = result["ad_stats"]
                total_deleted += deleted_count
                total_attempted += attempted_count
                total_tracked += tracked_count
            else:
                failed.append(result)

        action_map = {
            "warn": "⚠️ 警告",
            "mute": "🤐 禁言",
            "ad": "📢 广告清理",
            "kick": "🚀 踢出",
            "ban": "🚫 封禁",
            "unmute": "🎤 解除禁言",
            "unban": "🔓 解封"
        }
        color_map = {
            "warn": 0xFFAA00,
            "mute": 0xFF5555,
            "ad": 0xFF8800,
            "kick": 0xFF0000,
            "ban": 0x000000,
            "unmute": 0x55FF55,
            "unban": 0x00AAFF
        }
        act_label = action_map.get(action, action)
        color = color_map.get(action, 0x999999)

        # 公开公示（仅对成功目标）
        public_msg = None
        public_chan = guild.get_channel(PUBLIC_NOTICE_CHANNEL_ID)
        if public_chan and success:
            success_mentions = [f"<@{item['target_id']}>" for item in success]
            display_mentions = "\n".join(success_mentions[:20])
            if len(success_mentions) > 20:
                display_mentions += f"\n... 以及其余 {len(success_mentions) - 20} 人"

            p_embed = discord.Embed(title=f"🚨 违规公示 | 批量{act_label}", color=color)
            p_embed.add_field(name="目标数量", value=f"成功 **{len(success)}** / 总计 **{len(sorted_targets)}**", inline=True)
            p_embed.add_field(name="执行人", value=ctx.user.mention, inline=True)
            p_embed.description = f"**理由:**\n{reason}\n\n**目标列表:**\n{display_mentions}"
            if action == "mute":
                p_embed.add_field(name="禁言时长", value=duration, inline=True)
            p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
            p_embed.timestamp = discord.utils.utcnow()
            public_msg = await public_chan.send(embed=p_embed)

        # 内部日志
        log_chan = guild.get_channel(LOG_CHANNEL_ID)
        if log_chan:
            log_embed = discord.Embed(title=f"🛡️ 管理执行日志: BATCH-{action.upper()}", color=color)
            log_embed.description = f"**理由:** {reason}"
            log_embed.add_field(name="执行人 (Executor)", value=ctx.user.mention, inline=True)
            log_embed.add_field(
                name="结果统计",
                value=f"成功 {len(success)} / 失败 {len(failed)} / 总计 {len(sorted_targets)}",
                inline=True
            )
            if action == "mute":
                log_embed.add_field(name="时长", value=duration, inline=True)
            if action == "ad":
                log_embed.add_field(
                    name="广告清理统计",
                    value=(
                        f"已删 {total_deleted} 条 / 命中 {total_attempted} 条 / "
                        f"缓存记录 {total_tracked} 条\n"
                        f"Redis状态: {'可用' if self.redis_ready else '不可用'}"
                    ),
                    inline=False
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
                log_view.add_item(discord.ui.Button(label="查看公示", url=public_msg.jump_url, style=discord.ButtonStyle.link))

            await log_chan.send(embed=log_embed, view=log_view)

        # 命令回执
        summary = [
            f"✅ 批量处罚执行完成：**{act_label}**",
            f"- 成功：{len(success)}",
            f"- 失败：{len(failed)}",
            f"- 总计：{len(sorted_targets)}"
        ]
        if action == "ad":
            summary.append(
                f"- 广告清理：已删 {total_deleted} 条 / 命中 {total_attempted} 条 / 缓存记录 {total_tracked} 条"
            )

        if failed:
            fail_lines = [f"`{item['target_id']}`: {item['error']}" for item in failed[:8]]
            summary.append("\n失败示例：\n" + "\n".join(fail_lines))

        await ctx.followup.send("\n".join(summary), ephemeral=True)

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

            deleted_count, attempted_count, tracked_count = await self._delete_tracked_messages(
                guild=guild,
                user_id=target_id,
                reason=reason
            )

            # 兜底：确保触发处罚的这条消息也尝试删除
            try:
                await message.delete(reason=reason)
                deleted_count += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

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
                log_embed.add_field(
                    name="清理结果",
                    value=(
                        f"已删 {deleted_count} 条 / 命中 {attempted_count} 条 / "
                        f"缓存记录 {tracked_count} 条\n"
                        f"Redis状态: {'可用' if self.redis_ready else '不可用'}"
                    ),
                    inline=False
                )

                log_view = discord.ui.View()
                if public_msg:
                    log_view.add_item(discord.ui.Button(label="查看公示", url=public_msg.jump_url, style=discord.ButtonStyle.link))

                await log_chan.send(embed=log_embed, view=log_view)

            await ctx.followup.send(
                "✅ 已执行广告处罚并发送公示。\n"
                f"🧹 清理统计：已删 {deleted_count} 条 / 命中 {attempted_count} 条 / 缓存记录 {tracked_count} 条。",
                ephemeral=True
            )

        except discord.Forbidden as e:
            await ctx.followup.send(f"❌ 权限不足: {e}", ephemeral=True)
        except Exception as e:
            await ctx.followup.send(f"❌ 执行失败: {e}", ephemeral=True)
