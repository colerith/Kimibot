# cogs/manage/punishment_views.py

import discord
from discord import ui
import datetime
import io
import re

from config import STYLE
from .punishment_db import db
from ..shared.utils import parse_duration

# --- Modal 面板 (无变化) ---
class IDInputModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="🔍 手动输入用户ID")
        self.view_ref = view_ref
        self.add_item(ui.TextInput(label="用户ID", min_length=15, max_length=20, required=True))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_str = self.children[0].value.strip()
        if not uid_str.isdigit(): return await interaction.followup.send("❌ ID必须是数字", ephemeral=True)
        uid = int(uid_str)
        try:
            user = await interaction.client.fetch_user(uid)
            self.view_ref.selected_user = user; self.view_ref.selected_user_id = uid
            msg = "✅ 已锁定目标"
        except discord.NotFound:
            self.view_ref.selected_user = None; self.view_ref.selected_user_id = uid
            msg = "⚠️ ID已锁定 (未在Discord找到该用户)"
        except Exception as e:
            await interaction.followup.send(f"❌ 查找用户时发生错误: {e}", ephemeral=True)
            return
        self.view_ref.target_ids = [uid]
        await self.view_ref.refresh_view(interaction, temp_notify=msg)

class BatchTargetModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="👥 批量目标")
        self.view_ref = view_ref
        self.add_item(
            ui.InputText(
                label="输入ID或@提及（空格/逗号/换行分隔）",
                style=discord.InputTextStyle.paragraph,
                required=True,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        raw = self.children[0].value.strip()
        ids = []
        seen = set()
        for item in re.findall(r"\d{15,20}", raw):
            uid = int(item)
            if uid in seen:
                continue
            seen.add(uid)
            ids.append(uid)

        if not ids:
            return await interaction.followup.send("❌ 未解析到有效用户ID。", ephemeral=True)

        self.view_ref.selected_user = None
        self.view_ref.selected_user_id = None
        self.view_ref.target_ids = ids
        await self.view_ref.refresh_view(interaction, temp_notify=f"✅ 已载入 {len(ids)} 个批量目标")

class ReasonInputModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📝 处罚详情")
        self.view_ref = view_ref
        self.add_item(ui.InputText(label="理由", style=discord.InputTextStyle.paragraph, required=True, value=view_ref.reason))
        self.add_item(ui.InputText(label="时长 (仅禁言)", placeholder="例如: 10m, 1h, 3d (选填)", required=False, value=view_ref.duration_str))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.view_ref.reason = self.children[0].value
        self.view_ref.duration_str = self.children[1].value or "1h"
        await self.view_ref.refresh_view(interaction)


class StrikeQueryModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="🔎 警告查询")
        self.view_ref = view_ref
        self.add_item(
            ui.InputText(
                label="用户名 / 昵称 / ID / @提及",
                placeholder="例如: 123456789012345678 或 某个用户名",
                required=True,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        query = self.children[0].value.strip()
        member, user_id, error = await self.view_ref.resolve_user_query(interaction, query)
        if error:
            return await interaction.followup.send(f"❌ {error}", ephemeral=True)

        strikes = db.get_strikes(user_id)
        status_text = self.view_ref.get_strike_status_text(strikes)
        display_name = member.display_name if member else f"用户 {user_id}"
        mention_text = member.mention if member else f"`{user_id}`"

        embed = discord.Embed(title="📊 警告状态查询", color=0x66CCFF)
        embed.add_field(name="目标", value=f"{display_name}\n{mention_text}", inline=True)
        embed.add_field(name="当前警告", value=f"**{strikes}/3**", inline=True)
        embed.add_field(name="状态说明", value=status_text, inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

# --- 主视图 ---
class ManagementControlView(ui.View):
    def __init__(self, ctx, initial_files=None, public_channel_id=None, log_channel_id=None, *, timeout=900):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.public_channel_id = public_channel_id
        self.log_channel_id = log_channel_id
        self.attachments = initial_files or []
        self.attachment_urls = {f.url for f in self.attachments}
        self.evidence_links = [f.url for f in self.attachments]
        self.selected_user = None; self.selected_user_id = None
        self.target_ids = []
        self.action_type = None; self.reason = "违反社区规范"; self.duration_str = "1h"
        self.update_components()

    @staticmethod
    def _get_punishment_cog(interaction: discord.Interaction):
        return interaction.client.get_cog("处罚系统") or interaction.client.get_cog("PunishmentCog")

    @staticmethod
    async def _resolve_sendable_channel(guild: discord.Guild, channel_id: int | None):
        if not channel_id:
            return None

        channel = guild.get_thread(channel_id) or guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except discord.HTTPException:
                return None

        if hasattr(channel, "send"):
            return channel
        return None

    @staticmethod
    def _clone_discord_file(src: discord.File):
        try:
            src.fp.seek(0)
        except Exception:
            pass

        data = src.fp.read()

        try:
            src.fp.seek(0)
        except Exception:
            pass

        return discord.File(io.BytesIO(data), filename=src.filename, spoiler=src.spoiler)

    @staticmethod
    def get_strike_status_text(strikes: int):
        if strikes <= 0:
            return "无记录 (下次警告: 禁言 1 天)"
        if strikes == 1:
            return "严重警告 (下次警告: 禁言 7 天)"
        if strikes >= 2:
            return "高危警告 (下次警告: 永久封禁)"
        return "未知异常"

    async def resolve_user_query(self, interaction: discord.Interaction, query: str):
        guild = interaction.guild
        if not guild:
            return None, None, "无法在私信中查询"

        id_matches = re.findall(r"\d{15,20}", query)
        if id_matches:
            target_id = int(id_matches[0])
            member = guild.get_member(target_id)
            if not member:
                try:
                    member = await guild.fetch_member(target_id)
                except discord.NotFound:
                    member = None
                except Exception as e:
                    return None, None, f"查询用户失败: {e}"
            return member, target_id, None

        q = query.lower()
        candidates = []
        for m in guild.members:
            name = (m.name or "").lower()
            display_name = (m.display_name or "").lower()
            nick = (m.nick or "").lower() if hasattr(m, "nick") and m.nick else ""
            if q == name or q == display_name or (nick and q == nick):
                return m, m.id, None
            if q in name or q in display_name or (nick and q in nick):
                candidates.append(m)

        if not candidates:
            return None, None, "未找到匹配用户，请改用 ID 或 @提及"
        if len(candidates) > 1:
            preview = "\n".join([f"- {m.display_name} (`{m.id}`)" for m in candidates[:5]])
            if len(candidates) > 5:
                preview += f"\n- ... 以及其余 {len(candidates) - 5} 人"
            return None, None, f"匹配到多个用户，请使用更精确关键词或ID:\n{preview}"
        m = candidates[0]
        return m, m.id, None

    def update_components(self):
        can_exec = bool(self.target_ids) and self.action_type is not None
        for child in self.children:
            if isinstance(child, ui.Button) and child.custom_id == "btn_execute":
                child.disabled = not can_exec
                child.style = discord.ButtonStyle.danger if can_exec else discord.ButtonStyle.secondary

    async def refresh_view(self, interaction, temp_notify=None):
        self.update_components()
        embed = discord.Embed(title="🛡️ 处罚控制台", color=STYLE["KIMI_YELLOW"])
        if not self.target_ids:
            info = "🔴 **未选择**"
        elif len(self.target_ids) == 1:
            tid = self.target_ids[0]
            if self.selected_user and self.selected_user.id == tid:
                info = f"**{self.selected_user.name}**\n`{tid}`"
                embed.set_thumbnail(url=self.selected_user.display_avatar.url)
            else:
                info = f"ID: `{tid}`"
        else:
            preview_ids = "\n".join([f"`{tid}`" for tid in self.target_ids[:5]])
            if len(self.target_ids) > 5:
                preview_ids += f"\n... 以及其余 {len(self.target_ids) - 5} 人"
            info = f"👥 批量目标: **{len(self.target_ids)}** 人\n{preview_ids}"
        embed.add_field(name="1. 目标", value=info, inline=True)
        act_map = {
            "warn": "⚠️ 警告",
            "unwarn": "✅ 撤销警告",
            "mute": "🤐 禁言",
            "kick": "🚀 踢出",
            "ban": "🚫 封禁",
            "unmute": "🎤 解禁",
            "unban": "🔓 解封",
        }
        embed.add_field(name="2. 动作", value=act_map.get(self.action_type, "⚪ **未选择**"), inline=True)
        desc = f"> **理由:** {self.reason}\n"
        if self.action_type == "mute": desc += f"> **时长:** `{self.duration_str}`\n"
        desc += f"> **证据:** {len(self.attachments)} 个附件"
        channel_id = getattr(interaction, "channel_id", None)
        punish_cog = self._get_punishment_cog(interaction)
        if punish_cog and self.ctx and channel_id:
            session = punish_cog.get_evidence_session(self.ctx.user.id, channel_id)
            if session:
                expire_text = discord.utils.format_dt(session["expires_at"], "R")
                desc += (
                    f"\n> **收集会话:** 进行中 ({expire_text})"
                    f"\n> **待收纳:** {len(session['attachments'])} 个附件"
                )
            else:
                desc += "\n> **收集会话:** 未开启"
        if len(self.target_ids) == 1:
            current_strikes = db.get_strikes(self.target_ids[0])
            if self.action_type == "warn":
                desc += f"\n> **警告累计:** {current_strikes} 次 (本次将+1)"
            elif self.action_type == "unwarn":
                desc += f"\n> **警告累计:** {current_strikes} 次 (本次将-1，最低0)"
            else:
                desc += f"\n> **警告累计:** {current_strikes} 次 (仅警告/撤销警告会变更)"
        elif len(self.target_ids) > 1:
            desc += "\n> **警告累计:** 批量模式下按目标分别计算"
        embed.add_field(name="配置详情", value=desc, inline=False)
        embed.set_footer(text=temp_notify or "请按顺序选择目标和动作...")
        try:
            if not interaction.response.is_done(): await interaction.response.edit_message(embed=embed, view=self)
            else: await interaction.edit_original_response(embed=embed, view=self)
        except discord.NotFound: pass

    # --- 交互组件 (修正) ---
    @ui.user_select(placeholder="👥 选择目标...", row=0, custom_id="sel_user")
    async def cb_user(self, select: ui.UserSelect, interaction: discord.Interaction):
        await interaction.response.defer()
        self.selected_user = select.values[0]
        self.selected_user_id = self.selected_user.id
        self.target_ids = [self.selected_user_id]
        await self.refresh_view(interaction)

    # ✅ 修正: SelectOption 的初始化方式
    @ui.select(
        placeholder="🔨 选择动作...", row=1, custom_id="sel_act",
        options=[
            discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
            discord.SelectOption(label="撤销警告 (Unwarn)", value="unwarn", emoji="✅"),
            discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
            discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
            discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
            discord.SelectOption(label="解除禁言", value="unmute", emoji="🎤"),
            discord.SelectOption(label="解除封禁", value="unban", emoji="🔓")
        ]
    )
    async def cb_act(self, select: ui.Select, interaction: discord.Interaction):
        await interaction.response.defer()
        self.action_type = select.values[0]
        await self.refresh_view(interaction)

    # ✅ 修正: Button 的初始化方式
    @ui.button(label="ID搜人", style=discord.ButtonStyle.secondary, row=2, emoji="🔍", custom_id="btn_id")
    async def cb_id(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(IDInputModal(self))

    @ui.button(label="批量目标", style=discord.ButtonStyle.secondary, row=2, emoji="👥", custom_id="btn_batch_target")
    async def cb_batch_target(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(BatchTargetModal(self))

    @ui.button(label="理由/时长", style=discord.ButtonStyle.primary, row=2, emoji="📝", custom_id="btn_reason")
    async def cb_rsn(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(ReasonInputModal(self))

    @ui.button(label="开始收集", style=discord.ButtonStyle.secondary, row=3, emoji="📥", custom_id="btn_collect_start")
    async def cb_collect_start(self, button: ui.Button, interaction: discord.Interaction):
        punish_cog = self._get_punishment_cog(interaction)
        if not punish_cog:
            return await interaction.response.send_message("❌ 无法找到处罚模块实例。", ephemeral=True)

        expires_at = punish_cog.start_evidence_session(
            interaction.user.id,
            interaction.channel_id,
            duration_seconds=300,
        )
        await interaction.response.defer(ephemeral=True)
        expire_text = discord.utils.format_dt(expires_at, "R")
        await self.refresh_view(interaction, temp_notify=f"📥 已开启证据收集，会话将在 {expire_text} 结束")

    @ui.button(label="完成收集", style=discord.ButtonStyle.success, row=3, emoji="✅", custom_id="btn_collect_finish")
    async def cb_collect_finish(self, button: ui.Button, interaction: discord.Interaction):
        punish_cog = self._get_punishment_cog(interaction)
        if not punish_cog:
            return await interaction.response.send_message("❌ 无法找到处罚模块实例。", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        result = await punish_cog.finish_evidence_session(
            interaction.user.id,
            interaction.channel_id,
            cleanup_channel=interaction.channel,
        )
        if not result:
            await self.refresh_view(interaction, temp_notify="⚠️ 当前没有可提交的证据收集会话")
            return

        collected = result["attachments"]
        added = 0
        for att in collected:
            if not att.url or att.url in self.attachment_urls:
                continue
            self.attachments.append(att)
            self.attachment_urls.add(att.url)
            self.evidence_links.append(att.url)
            added += 1

        deleted = result.get("deleted_messages", 0)
        failed = result.get("failed_deletions", 0)
        notify = f"✅ 已收纳 {added} 个证据附件，并清理 {deleted} 条原消息"
        if failed:
            notify += f"（{failed} 条未能删除）"
        await self.refresh_view(interaction, temp_notify=notify)

    @ui.button(label="跳过证据", style=discord.ButtonStyle.secondary, row=3, emoji="⏭️", custom_id="btn_collect_skip")
    async def cb_collect_skip(self, button: ui.Button, interaction: discord.Interaction):
        punish_cog = self._get_punishment_cog(interaction)
        if punish_cog:
            punish_cog.cancel_evidence_session(interaction.user.id, interaction.channel_id)

        self.attachments = []
        self.attachment_urls = set()
        self.evidence_links = []

        await interaction.response.defer(ephemeral=True)
        await self.refresh_view(interaction, temp_notify="⏭️ 已跳过证据上传，可直接执行处罚")

    @ui.button(label="警告查询", style=discord.ButtonStyle.secondary, row=4, emoji="🔎", custom_id="btn_query_strike")
    async def cb_query_strike(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(StrikeQueryModal(self))

    @ui.button(label="重置警告", style=discord.ButtonStyle.secondary, row=4, emoji="♻️", custom_id="btn_reset_strike")
    async def cb_reset_strike(self, button: ui.Button, interaction: discord.Interaction):
        if not self.target_ids:
            return await interaction.response.send_message("❌ 请先选择目标后再重置。", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        count = 0
        for tid in sorted(set(self.target_ids)):
            db.reset_strikes(tid)
            count += 1

        if count == 1:
            await self.refresh_view(interaction, temp_notify="✅ 已重置该目标的警告累计")
        else:
            await self.refresh_view(interaction, temp_notify=f"✅ 已重置 {count} 个目标的警告累计")

    # --- 执行逻辑 ---
    @ui.button(label="⚡ 确认执行", style=discord.ButtonStyle.danger, row=4, disabled=True, custom_id="btn_execute")
    async def cb_exec(self, button: ui.Button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        act, guild = self.action_type, interaction.guild
        target_ids = sorted(set(self.target_ids))
        if not target_ids:
            return await interaction.followup.send("❌ 请先选择目标。", ephemeral=True)

        punish_cog = self._get_punishment_cog(interaction)
        if not punish_cog:
            return await interaction.followup.send("❌ 无法找到处罚模块实例。", ephemeral=True)

        if len(target_ids) > 1:
            duration_secs = 0
            if act == "mute":
                duration_secs = parse_duration(self.duration_str)
                if duration_secs <= 0:
                    return await interaction.followup.send("❌ 禁言时长无效。", ephemeral=True)

            success = []
            failed = []
            for tid in target_ids:
                result = await punish_cog._apply_single_action(
                    guild=guild,
                    target_id=tid,
                    action=act,
                    reason=self.reason,
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
            act_label = action_map.get(act, act)
            color = color_map.get(act, 0x999999)

            files_for_pub = [await att.to_file(spoiler=True) for att in self.attachments]
            files_for_log = [self._clone_discord_file(f) for f in files_for_pub]

            public_msg = None
            public_chan = await self._resolve_sendable_channel(guild, self.public_channel_id)
            if public_chan and success:
                success_mentions = [f"<@{item['target_id']}>" for item in success]
                display_mentions = "\n".join(success_mentions[:20])
                if len(success_mentions) > 20:
                    display_mentions += f"\n... 以及其余 {len(success_mentions) - 20} 人"

                p_embed = discord.Embed(title=f"🚨 违规公示 | 批量{act_label}", color=color)
                p_embed.add_field(
                    name="目标数量",
                    value=f"成功 **{len(success)}** / 总计 **{len(target_ids)}**",
                    inline=True,
                )
                p_embed.add_field(name="执行人", value=interaction.user.mention, inline=True)
                p_embed.description = f"**理由:**\n{self.reason}\n\n**目标列表:**\n{display_mentions}"
                if act == "mute":
                    p_embed.add_field(name="禁言时长", value=self.duration_str, inline=True)
                if act in {"warn", "unwarn"}:
                    p_embed.add_field(name="累计说明", value="仅警告动作影响累计次数", inline=True)
                p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
                p_embed.timestamp = discord.utils.utcnow()
                public_msg = await public_chan.send(embed=p_embed, files=files_for_pub)

            log_chan = await self._resolve_sendable_channel(guild, self.log_channel_id)
            log_error = None
            if log_chan:
                try:
                    log_embed = discord.Embed(title=f"🛡️ 管理执行日志: BATCH-{act.upper()}", color=color)
                    log_embed.description = f"**理由:** {self.reason}"
                    log_embed.add_field(name="执行人 (Executor)", value=interaction.user.mention, inline=True)
                    log_embed.add_field(
                        name="结果统计",
                        value=f"成功 {len(success)} / 失败 {len(failed)} / 总计 {len(target_ids)}",
                        inline=True,
                    )
                    if act == "mute":
                        log_embed.add_field(name="时长", value=self.duration_str, inline=True)
                    if act == "warn":
                        linked_preview = [
                            f"<@{item['target_id']}>: {item.get('linked_action') or '无'}"
                            for item in success[:10]
                        ]
                        if linked_preview:
                            log_embed.add_field(name="自动处罚结果", value="\n".join(linked_preview), inline=False)

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

                    log_view = ui.View()
                    if public_msg:
                        log_view.add_item(ui.Button(label="查看公示", url=public_msg.jump_url, style=discord.ButtonStyle.link))
                    await log_chan.send(embed=log_embed, view=log_view, files=files_for_log)
                except discord.HTTPException as e:
                    log_error = str(e)
                except Exception as e:
                    log_error = str(e)
            else:
                log_error = f"找不到日志频道/线程: {self.log_channel_id}"

            summary = [
                f"✅ 批量处罚执行完成：**{act_label}**",
                f"- 成功：{len(success)}",
                f"- 失败：{len(failed)}",
                f"- 总计：{len(target_ids)}",
            ]
            if failed:
                fail_lines = [f"`{item['target_id']}`: {item['error']}" for item in failed[:8]]
                summary.append("\n失败示例：\n" + "\n".join(fail_lines))

            if log_error:
                summary.append(f"\n⚠️ 日志发送失败: {log_error}")
            await interaction.followup.send("\n".join(summary), ephemeral=True)
            self.clear_items()
            original_msg = await interaction.original_response()
            fin_embed = original_msg.embeds[0]
            fin_embed.color = discord.Color.green(); fin_embed.title = "✅ 处理完毕"
            return await interaction.edit_original_response(embed=fin_embed, view=self)

        tid = target_ids[0]
        member = None
        try:
            member = guild.get_member(tid) or await guild.fetch_member(tid)
        except discord.NotFound:
            pass

        try:
            # --- Discord 操作 ---
            msg_act, color = "", 0x999999
            linked_action = ""
            if act == "warn":
                if not member:
                    raise ValueError("用户不在服务器内，无法执行警告")

                msg_act, color = "进行警告", 0xFFAA00
                if member:
                    try:
                        dm_files = [await att.to_file(spoiler=True) for att in self.attachments]
                        dm_embed = discord.Embed(title=f"⚠️ {guild.name} 社区警告", description=f"**理由:** {self.reason}", color=color)
                        if dm_files:
                            dm_embed.set_image(url=f"attachment://{dm_files[0].filename}")
                        await member.send(embed=dm_embed, files=dm_files)
                    except (discord.Forbidden, IndexError):
                        pass # 无法私信或无附件

                new_count = db.add_strike(tid)
                try:
                    if new_count == 1:
                        await member.timeout(
                            discord.utils.utcnow() + datetime.timedelta(days=1),
                            reason=self.reason,
                        )
                        linked_action = "禁言 1 天"
                    elif new_count == 2:
                        await member.timeout(
                            discord.utils.utcnow() + datetime.timedelta(days=7),
                            reason=self.reason,
                        )
                        linked_action = "禁言 7 天"
                    elif new_count >= 3:
                        await guild.ban(discord.Object(id=tid), reason=self.reason)
                        linked_action = "永久封禁"
                    else:
                        linked_action = "无"
                except (discord.Forbidden, discord.HTTPException, ValueError) as linked_err:
                    linked_action = f"自动处罚失败: {linked_err}"

            elif act == "unwarn":
                msg_act, color = "撤销警告", 0x66CC99
                new_count = db.remove_strike(tid)
                linked_action = "仅撤销累计，不自动反向解除处罚"

            elif act == "mute":
                msg_act, color = f"禁言 ({self.duration_str})", 0xFF5555
                secs = parse_duration(self.duration_str)
                if secs > 0 and member:
                    await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=secs), reason=self.reason)
                else:
                    raise ValueError("用户不存在或时长无效")
            elif act == "kick":
                msg_act, color = "踢出", 0xFF0000
                if member: await member.kick(reason=self.reason)
                else: raise ValueError("用户不存在")
            elif act == "ban":
                msg_act, color = "封禁", 0x000000
                await guild.ban(discord.Object(id=tid), reason=self.reason)
            elif act == "unmute":
                msg_act, color = "解禁", 0x55FF55
                if member: await member.timeout(None, reason=self.reason)
                else: raise ValueError("用户不存在")
            elif act == "unban":
                msg_act, color = "解封", 0x00AAFF
                await guild.unban(discord.Object(id=tid), reason=self.reason)

            # --- 数据库记录 ---
            if act not in ["warn", "unwarn"]:
                new_count = db.get_strikes(tid)

            # --- 文件准备 ---
            files_for_pub = [await att.to_file(spoiler=True) for att in self.attachments]
            files_for_log = [self._clone_discord_file(f) for f in files_for_pub]

            # --- 1. 发送公开公示 ---
            public_msg, user_obj = None, member or self.selected_user or await self.ctx.bot.fetch_user(tid)
            public_chan = await self._resolve_sendable_channel(guild, self.public_channel_id)
            if public_chan:
                p_embed = discord.Embed(title=f"🚨 违规公示 | {msg_act}", color=color)
                p_embed.add_field(name="违规者", value=f"<@{tid}> (`{user_obj.name}`)", inline=True)
                p_embed.add_field(name="累计违规", value=f"**{new_count}** 次", inline=True)
                if act == "warn" and linked_action:
                    p_embed.add_field(name="自动处罚", value=linked_action, inline=True)
                p_embed.description = f"**理由:**\n{self.reason}"
                p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
                p_embed.timestamp = discord.utils.utcnow()
                if user_obj.display_avatar:
                    p_embed.set_thumbnail(url=user_obj.display_avatar.url)
                public_msg = await public_chan.send(embed=p_embed, files=files_for_pub)

            # --- 2. 发送内部日志 (常规 Embed 样式) ---
            log_chan = await self._resolve_sendable_channel(guild, self.log_channel_id)
            log_error = None
            if log_chan:
                try:
                    log_embed = discord.Embed(title=f"🛡️ 管理执行日志: {act.upper()}", color=color)
                    log_embed.description = f"**理由:** {self.reason}"
                    log_embed.add_field(name="执行人 (Executor)", value=interaction.user.mention, inline=True)
                    log_embed.add_field(name="目标 (Target)", value=user_obj.mention, inline=True)
                    if act == "mute":
                        log_embed.add_field(name="时长", value=self.duration_str, inline=True)
                    if act in {"warn", "unwarn"} and linked_action:
                        log_embed.add_field(name="自动处罚/说明", value=linked_action, inline=False)
                    link_only_urls = [link for link in self.evidence_links if link not in self.attachment_urls]
                    if link_only_urls:
                        log_embed.add_field(name="外部链接", value="\n".join(link_only_urls), inline=False)

                    log_view = ui.View()
                    if public_msg:
                        log_view.add_item(ui.Button(label="查看公示", url=public_msg.jump_url, style=discord.ButtonStyle.link))

                    await log_chan.send(embed=log_embed, view=log_view, files=files_for_log)
                except discord.HTTPException as e:
                    log_error = str(e)
                except Exception as e:
                    log_error = str(e)
            else:
                log_error = f"找不到日志频道/线程: {self.log_channel_id}"

            # --- 3. 反馈与清理 ---
            if log_error:
                await interaction.followup.send(f"✅ 执行成功，但日志发送失败：{log_error}", ephemeral=True)
            else:
                await interaction.followup.send("✅ 执行成功！已发送公示与日志。", ephemeral=True)
            self.clear_items()
            original_msg = await interaction.original_response()
            fin_embed = original_msg.embeds[0]
            fin_embed.color = discord.Color.green(); fin_embed.title = "✅ 处理完毕"
            await interaction.edit_original_response(embed=fin_embed, view=self)

        except (ValueError, discord.Forbidden) as e:
            await interaction.followup.send(f"❌ 操作失败: {e}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 执行时发生未知错误: {e}", ephemeral=True)
            import traceback; traceback.print_exc()
