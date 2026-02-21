# cogs/manage/punishment_views.py

import discord
from discord import ui
import datetime

from config import IDS, STYLE
from .punishment_db import db
from ..shared.utils import parse_duration

# ---Modal面板---

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
            self.view_ref.selected_user = user
            self.view_ref.selected_user_id = uid
            msg = "✅ 已锁定目标"
        except discord.NotFound:
            self.view_ref.selected_user = None
            self.view_ref.selected_user_id = uid
            msg = "⚠️ ID已锁定 (未在Discord找到该用户)"
        except Exception as e:
            await interaction.followup.send(f"❌ 查找用户时发生错误: {e}", ephemeral=True)
            return

        await self.view_ref.refresh_view(interaction, temp_notify=msg)


class EvidenceAppendModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📸 追加证据链接")
        self.view_ref = view_ref
        self.add_item(ui.InputText(
            label="链接 (每行一个)", style=discord.InputTextStyle.paragraph, required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_links = [line.strip() for line in self.children[0].value.strip().split('\n') if line.strip()]
        self.view_ref.evidence_links.extend(new_links)
        await self.view_ref.refresh_view(interaction, temp_notify=f"✅ 已追加 {len(new_links)} 条证据")

class ReasonInputModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📝 处罚详情")
        self.view_ref = view_ref
        self.add_item(ui.InputText(label="理由", style=discord.InputTextStyle.paragraph, required=True, value=view_ref.reason))
        self.add_item(ui.InputText(label="时长 (仅禁言)", placeholder="例如: 10m, 1h, 3d (选填)", required=False, value=view_ref.duration_str))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.view_ref.reason = self.children[0].value
        self.view_ref.duration_str = self.children[1].value or "1h" # 如果为空，给个默认值
        await self.view_ref.refresh_view(interaction)

#---处罚面板主视图---

class ManagementControlView(ui.View):
    # ✅ 修正: 在 __init__ 中添加接收参数
    def __init__(self, ctx, initial_files=None, public_channel_id=None, log_channel_id=None):
        super().__init__(timeout=900)
        self.ctx = ctx
        # ✅ 修正: 保存频道ID到实例属性
        self.public_channel_id = public_channel_id
        self.log_channel_id = log_channel_id

        self.selected_user = None
        self.selected_user_id = None
        self.action_type = None
        self.reason = "违反社区规范"
        self.duration_str = "1h"
        self.evidence_links = [f.url for f in initial_files if f] if initial_files else []
        self.update_components()

    def update_components(self):
        # 允许在没有选择用户的情况下填写理由
        can_exec = (self.selected_user_id is not None) and (self.action_type is not None)

        for child in self.children:
            if isinstance(child, ui.Button):
                if child.custom_id == "btn_execute":
                    child.disabled = not can_exec
                    child.style = discord.ButtonStyle.danger if can_exec else discord.ButtonStyle.secondary

    async def refresh_view(self, interaction, temp_notify=None):
        self.update_components()
        embed = discord.Embed(title="🛡️ 处罚控制台", color=STYLE["KIMI_YELLOW"])

        # 目标显示
        if self.selected_user:
            info = f"**{self.selected_user.name}**\n`{self.selected_user.id}`"
            embed.set_thumbnail(url=self.selected_user.display_avatar.url)
        elif self.selected_user_id:
            info = f"ID: `{self.selected_user_id}`"
        else:
            info = "🔴 **未选择**"
        embed.add_field(name="1. 目标", value=info, inline=True)

        # 动作显示
        act_map = {"warn": "⚠️ 警告", "mute": "🤐 禁言", "kick": "🚀 踢出", "ban": "🚫 封禁", "unmute": "🎤 解禁", "unban": "🔓 解封"}
        embed.add_field(name="2. 动作", value=act_map.get(self.action_type, "⚪ **未选择**"), inline=True)

        # 详情
        desc = f"> **理由:** {self.reason}\n"
        if self.action_type == "mute": desc += f"> **时长:** `{self.duration_str}`\n"
        desc += f"> **证据:** {len(self.evidence_links)} 条"

        if self.selected_user_id:
            current_strikes = db.get_strikes(self.selected_user_id)
            desc += f"\n> **历史违规:** {current_strikes} 次 (本次将+1)"

        embed.add_field(name="配置详情", value=desc, inline=False)
        embed.set_footer(text=temp_notify or "请按顺序选择目标和动作...")

        try:
            if interaction.response.is_done(): await interaction.edit_original_response(embed=embed, view=self)
            else: await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            pass

    # --- 交互 ---
    @ui.user_select(placeholder="👥 选择目标...", row=0, custom_id="sel_user")
    async def cb_user(self, select, interaction):
        await interaction.response.defer()
        self.selected_user = select.values[0]
        self.selected_user_id = self.selected_user.id
        await self.refresh_view(interaction)

    @ui.select(placeholder="🔨 选择动作...", row=1, custom_id="sel_act", options=[
        discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
        discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
        discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
        discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
        discord.SelectOption(label="解除禁言", value="unmute", emoji="🎤"),
        discord.SelectOption(label="解除封禁", value="unban", emoji="🔓"),
    ])
    async def cb_act(self, select, interaction):
        await interaction.response.defer()
        self.action_type = select.values[0]
        await self.refresh_view(interaction)

    @ui.button(label="ID搜人", style=discord.ButtonStyle.secondary, row=2, emoji="🔍", custom_id="btn_id")
    async def cb_id(self, _, interaction): await interaction.response.send_modal(IDInputModal(self))

    @ui.button(label="追加证据", style=discord.ButtonStyle.secondary, row=2, emoji="📎", custom_id="btn_ev")
    async def cb_ev(self, _, interaction): await interaction.response.send_modal(EvidenceAppendModal(self))

    @ui.button(label="理由/时长", style=discord.ButtonStyle.primary, row=2, emoji="📝", custom_id="btn_reason")
    async def cb_rsn(self, _, interaction): await interaction.response.send_modal(ReasonInputModal(self))

    @ui.button(label="⚡ 确认执行", style=discord.ButtonStyle.danger, row=3, disabled=True, custom_id="btn_execute")
    async def cb_exec(self, _, interaction):
        await interaction.response.defer(ephemeral=True)

        tid = self.selected_user_id
        act = self.action_type
        guild = interaction.guild
        member = guild.get_member(tid) or (await guild.fetch_member(tid) if tid else None)

        try:
            msg_act = ""
            if act == "warn":
                msg_act = "进行警告"
                if member:
                    try:
                        dm = discord.Embed(title=f"⚠️ {guild.name} 警告", description=self.reason, color=0xFFAA00)
                        if self.evidence_links: dm.set_image(url=self.evidence_links[0])
                        await member.send(embed=dm)
                    except discord.Forbidden: pass # 用户可能关闭了私信
            elif act == "mute":
                secs = parse_duration(self.duration_str)
                if secs <= 0: return await interaction.followup.send("❌ 时间格式错误或时长为0", ephemeral=True)
                if member: await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=secs), reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法禁言", ephemeral=True)
                msg_act = f"禁言 ({self.duration_str})"
            elif act == "kick":
                if member: await member.kick(reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法踢出", ephemeral=True)
                msg_act = "踢出"
            elif act == "ban":
                await guild.ban(discord.Object(id=tid), reason=self.reason, delete_message_days=0)
                msg_act = "封禁"
            elif act == "unmute":
                if member: await member.timeout(None, reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法解禁", ephemeral=True)
                msg_act = "解禁"
            elif act == "unban":
                await guild.unban(discord.Object(id=tid), reason=self.reason)
                msg_act = "解封"

            new_count = db.get_strikes(tid)
            if act in ["warn", "mute", "kick", "ban"]: new_count = db.add_strike(tid)

            # ✅ 修正: 使用 self.public_channel_id 和 self.log_channel_id
            public_chan = guild.get_channel(self.public_channel_id) if self.public_channel_id else None
            if public_chan:
                color_map = {"warn": 0xFFAA00, "mute": 0xFF5555, "kick": 0xFF0000, "ban": 0x000000, "unmute": 0x55FF55, "unban": 0x00AAFF}
                p_embed = discord.Embed(title=f"🚨 违规公示 | {msg_act}", color=color_map.get(act, 0x999999))

                user_obj = member or self.selected_user or (await self.ctx.bot.fetch_user(tid))
                user_name = user_obj.name if user_obj else f"ID: {tid}"

                p_embed.add_field(name="违规者", value=f"<@{tid}>\n(`{user_name}`)", inline=True)
                p_embed.add_field(name="累计违规", value=f"**{new_count}** 次", inline=True)
                p_embed.description = f"**处罚理由:**\n{self.reason}"
                p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
                p_embed.timestamp = discord.utils.utcnow()
                if user_obj and user_obj.display_avatar: p_embed.set_thumbnail(url=user_obj.display_avatar.url)
                await public_chan.send(embed=p_embed)

            log_chan = guild.get_channel(self.log_channel_id) if self.log_channel_id else None
            if log_chan:
                l_embed = discord.Embed(title=f"🛡️ 管理执行: {act.upper()}", color=STYLE["KIMI_YELLOW"])
                l_embed.description = f"**对象:** <@{tid}> (`{tid}`)\n**执行人:** {interaction.user.mention}\n**理由:** {self.reason}"
                l_embed.add_field(name="累计违规", value=str(new_count))
                if act == "mute": l_embed.add_field(name="时长", value=self.duration_str)

                if self.evidence_links:
                    l_embed.add_field(name="📎 证据链", value="\n".join([f"<{x}>" for x in self.evidence_links]), inline=False)
                    first_img = next((x for x in self.evidence_links if any(ext in x.lower() for ext in ['.png', '.jpg','.jpeg','.webp'])), None)
                    if first_img: l_embed.set_image(url=first_img)

                l_embed.timestamp = discord.utils.utcnow()
                await log_chan.send(embed=l_embed)

            await interaction.followup.send(f"✅ 执行成功！\n- 已记录违规次数: {new_count}\n- 已发送公示与日志", ephemeral=True)
            self.clear_items()

            original_msg = await interaction.original_response()
            fin_embed = original_msg.embeds[0]
            fin_embed.color = discord.Color.green()
            fin_embed.title = "✅ 处理完毕"
            fin_embed.set_footer(text=f"操作已完成 @ {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
            await interaction.edit_original_response(embed=fin_embed, view=self)

        except discord.Forbidden:
            await interaction.followup.send("❌ 权限不足！可能是我或你的身份组权限低于目标用户。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 执行时发生未知错误: {e}", ephemeral=True)
            # 在控制台打印详细错误
            import traceback
            traceback.print_exc()