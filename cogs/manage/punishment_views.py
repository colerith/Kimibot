# cogs/manage/punishment_views.py

import discord
from discord import ui
import datetime
import io

from config import IDS, STYLE
from .punishment_db import db
from ..shared.utils import parse_duration

# --- Modal 面板 ---

class IDInputModal(ui.Modal, title="🔍 手动输入用户ID"):
    target_id_ui = ui.Label(
        text="用户ID",
        component=ui.TextInput(min_length=15, max_length=20, required=True),
    )

    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_str = self.target_id_ui.component.value.strip()
        if not uid_str.isdigit():
            return await interaction.followup.send("❌ ID必须是数字", ephemeral=True)

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


class EvidenceAppendModal(ui.Modal, title="📸 追加证据链接"):
    links_ui = ui.Label(
        text="链接 (每行一个)",
        component=ui.TextInput(style=discord.TextStyle.paragraph, required=True),
    )

    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        new_links = [line.strip() for line in self.links_ui.component.value.strip().split('\n') if line.strip()]
        self.view_ref.evidence_links.extend(new_links)
        await self.view_ref.refresh_view(interaction, temp_notify=f"✅ 已追加 {len(new_links)} 条证据")


class ReasonInputModal(ui.Modal, title="📝 处罚详情"):
    reason_ui = ui.Label(
        text="理由",
        component=ui.TextInput(style=discord.TextStyle.paragraph, required=True),
    )
    duration_ui = ui.Label(
        text="时长 (仅禁言)",
        component=ui.TextInput(placeholder="例如: 10m, 1h, 3d (选填)", required=False),
    )

    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref
        # 初始化输入框的值
        self.reason_ui.component.default_value = view_ref.reason
        self.duration_ui.component.default_value = view_ref.duration_str

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.view_ref.reason = self.reason_ui.component.value
        self.view_ref.duration_str = self.duration_ui.component.value or "1h"
        await self.view_ref.refresh_view(interaction)


# --- 处罚面板主视图 ---

class ManagementControlView(ui.LayoutView):
    def __init__(self, ctx, initial_files=None, public_channel_id=None, log_channel_id=None):
        super().__init__(timeout=900)
        self.ctx = ctx
        self.public_channel_id = public_channel_id
        self.log_channel_id = log_channel_id

        self.attachments = initial_files or []
        self.evidence_links = [f.url for f in self.attachments]

        self.selected_user = None
        self.selected_user_id = None
        self.action_type = None
        self.reason = "违反社区规范"
        self.duration_str = "1h"

        # --- 定义组件 ---
        self.user_select = ui.UserSelect(placeholder="👥 选择目标...", custom_id="sel_user")
        self.user_select.callback = self.cb_user

        self.action_select = ui.Select(
            placeholder="🔨 选择动作...",
            custom_id="sel_act",
            options=[
                discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
                discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
                discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
                discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
                discord.SelectOption(label="解除禁言", value="unmute", emoji="🎤"),
                discord.SelectOption(label="解除封禁", value="unban", emoji="🔓"),
            ]
        )
        self.action_select.callback = self.cb_act

        self.id_button = ui.Button(label="ID搜人", style=discord.ButtonStyle.secondary, emoji="🔍", custom_id="btn_id")
        self.id_button.callback = self.cb_id

        self.evidence_button = ui.Button(label="追加证据", style=discord.ButtonStyle.secondary, emoji="📎", custom_id="btn_ev")
        self.evidence_button.callback = self.cb_ev

        self.reason_button = ui.Button(label="理由/时长", style=discord.ButtonStyle.primary, emoji="📝", custom_id="btn_reason")
        self.reason_button.callback = self.cb_rsn

        self.execute_button = ui.Button(label="⚡ 确认执行", style=discord.ButtonStyle.danger, disabled=True, custom_id="btn_execute")
        self.execute_button.callback = self.cb_exec

        self.build_layout()

    def build_layout(self):
        """构建视图布局"""
        self.clear_items()
        container = ui.Container(
            ui.ActionRow(self.user_select),
            ui.ActionRow(self.action_select),
            ui.ActionRow(self.id_button, self.evidence_button, self.reason_button),
            ui.ActionRow(self.execute_button),
        )
        self.add_item(container)

    def update_components(self):
        can_exec = (self.selected_user_id is not None) and (self.action_type is not None)
        self.execute_button.disabled = not can_exec
        self.execute_button.style = discord.ButtonStyle.danger if can_exec else discord.ButtonStyle.secondary

    async def refresh_view(self, interaction, temp_notify=None):
        self.update_components()
        embed = discord.Embed(title="🛡️ 处罚控制台", color=STYLE["KIMI_YELLOW"])
        if self.selected_user:
            info = f"**{self.selected_user.name}**\n`{self.selected_user.id}`"
            embed.set_thumbnail(url=self.selected_user.display_avatar.url)
        elif self.selected_user_id:
            info = f"ID: `{self.selected_user_id}`"
        else:
            info = "🔴 **未选择**"
        embed.add_field(name="1. 目标", value=info, inline=True)

        act_map = {"warn": "⚠️ 警告", "mute": "🤐 禁言", "kick": "🚀 踢出", "ban": "🚫 封禁", "unmute": "🎤 解禁", "unban": "🔓 解封"}
        embed.add_field(name="2. 动作", value=act_map.get(self.action_type, "⚪ **未选择**"), inline=True)

        desc = f"> **理由:** {self.reason}\n"
        if self.action_type == "mute": desc += f"> **时长:** `{self.duration_str}`\n"
        desc += f"> **证据:** {len(self.attachments)} 个附件, {len(self.evidence_links) - len(self.attachments)} 个链接"

        if self.selected_user_id:
            current_strikes = db.get_strikes(self.selected_user_id)
            desc += f"\n> **历史违规:** {current_strikes} 次 (本次处罚后将+1)"
        embed.add_field(name="配置详情", value=desc, inline=False)
        embed.set_footer(text=temp_notify or "请按顺序选择目标和动作...")

        try:
            # 始终使用 followup 或 edit_original_response 来更新，避免 is_done 错误
            await interaction.edit_original_response(embed=embed, view=self)
        except (discord.NotFound, discord.InteractionResponded):
            try:
                await interaction.followup.send(embed=embed, view=self, ephemeral=True)
            except: # 如果连 followup 都失败，则忽略
                pass


    # --- 交互回调 ---
    async def cb_user(self, interaction):
        self.selected_user = interaction.values[0]
        self.selected_user_id = self.selected_user.id
        await interaction.response.defer()
        await self.refresh_view(interaction)

    async def cb_act(self, interaction):
        self.action_type = interaction.values[0]
        await interaction.response.defer()
        await self.refresh_view(interaction)

    async def cb_id(self, interaction): await interaction.response.send_modal(IDInputModal(self))
    async def cb_ev(self, interaction): await interaction.response.send_modal(EvidenceAppendModal(self))
    async def cb_rsn(self, interaction): await interaction.response.send_modal(ReasonInputModal(self))

    async def cb_exec(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        tid = self.selected_user_id
        act = self.action_type
        guild = interaction.guild
        member = None
        try:
            member = guild.get_member(tid) or await guild.fetch_member(tid)
        except discord.NotFound:
            pass

        try:
            # (Discord 操作逻辑, 与之前相同)
            msg_act = ""
            if act == "warn": msg_act = "进行警告"; # dm 逻辑省略...
            elif act == "mute":
                secs = parse_duration(self.duration_str)
                if secs <= 0: return await interaction.followup.send("❌ 时间格式错误或时长为0", ephemeral=True)
                if member: await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=secs), reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法禁言", ephemeral=True)
                msg_act = f"禁言 ({self.duration_str})"
            elif act == "kick": # ...
                if member: await member.kick(reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法踢出", ephemeral=True)
                msg_act = "踢出"
            elif act == "ban":
                await guild.ban(discord.Object(id=tid), reason=self.reason, delete_message_days=0)
                msg_act = "封禁"
            elif act == "unmute": # ...
                if member: await member.timeout(None, reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法解禁", ephemeral=True)
                msg_act = "解禁"
            elif act == "unban": #...
                await guild.unban(discord.Object(id=tid), reason=self.reason)
                msg_act = "解封"

            new_count = db.get_strikes(tid)
            if act in ["warn", "mute", "kick", "ban"]: new_count = db.add_strike(tid)

            files_to_send_pub = [await att.to_file() for att in self.attachments]

            public_message = None
            public_chan = guild.get_channel(self.public_channel_id)
            if public_chan:
                color_map = {"warn": 0xFFAA00, "mute": 0xFF5555, "kick": 0xFF0000, "ban": 0x000000}
                p_embed = discord.Embed(title=f"🚨 违规公示 | {msg_act}", color=color_map.get(act, 0x999999))
                p_embed.description = f"**处罚理由:**\n{self.reason}"
                user_obj = member or self.selected_user or await self.ctx.bot.fetch_user(tid)
                p_embed.add_field(name="违规者", value=f"<@{tid}>\n(`{user_obj.name}`)", inline=False)
                p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
                p_embed.timestamp = discord.utils.utcnow()
                public_message = await public_chan.send(embed=p_embed, files=files_to_send_pub)

            # --- ✅ 全新日志逻辑 ---
            log_chan = guild.get_channel(self.log_channel_id)
            if log_chan:
                # 准备执行者和目标的用户对象
                executor_user = interaction.user
                target_user = member or self.selected_user or await self.ctx.bot.fetch_user(tid)

                action_text = f"#{msg_act}" if act != "warn" else f"#{self.reason}"

                # 创建 Container 布局
                log_container = ui.Container(
                    ui.TextDisplay(content=action_text),
                    # 如果有公示消息，则显示跳转按钮
                    ui.ActionRow(
                        ui.Button(label="查看公示", url=public_message.jump_url)
                    ) if public_message else ui.TextDisplay(content="*本次操作无公开公示*"),
                    ui.Separator(),

                    # 执行人信息
                    ui.Section(
                        ui.TextDisplay(content="is `EXECUTOR`"),
                        ui.TextDisplay(content=f"{executor_user.mention}"),
                        accessory=ui.Thumbnail(media=executor_user.display_avatar.url)
                    ),

                    # 目标信息
                    ui.Section(
                        ui.TextDisplay(content="is `TARGET`"),
                        ui.TextDisplay(content=f"{target_user.mention}"),
                        accessory=ui.Thumbnail(media=target_user.display_avatar.url)
                    ),
                    accent_colour=discord.Color.dark_grey()
                )

                await log_chan.send(view=ui.LayoutView(log_container))


            await interaction.followup.send(f"✅ 执行成功！\n- 已记录违规次数: {new_count}\n- 已发送公示与日志", ephemeral=True)
            self.stop() 

            original_msg = await interaction.original_response()
            fin_embed = original_msg.embeds[0]
            fin_embed.color = discord.Color.green()
            fin_embed.title = "✅ 处理完毕"
            await original_msg.edit(embed=fin_embed, view=None) # 移除视图

        except discord.Forbidden:
            await interaction.followup.send("❌ 权限不足！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 执行时出错: {e}", ephemeral=True)
            import traceback
            traceback.print_exc()