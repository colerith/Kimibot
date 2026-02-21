# cogs/manage/punishment_views.py

import discord
from discord import ui
import datetime
import io

from config import IDS, STYLE
from .punishment_db import db
from ..shared.utils import parse_duration

# --- Modal面板 (保持不变) ---
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
        self.view_ref.duration_str = self.children[1].value or "1h"
        await self.view_ref.refresh_view(interaction)


#--- 处罚面板主视图 (常规 View) ---
class ManagementControlView(ui.View):
    def __init__(self, ctx, initial_files=None, public_channel_id=None, log_channel_id=None):
        super().__init__(timeout=900)
        self.ctx = ctx
        self.public_channel_id = public_channel_id
        self.log_channel_id = log_channel_id

        self.attachments = initial_files or []
        # 将附件URL和其他链接分开管理
        self.attachment_urls = {f.url for f in self.attachments}
        self.evidence_links = [f.url for f in self.attachments]

        self.selected_user = None
        self.selected_user_id = None
        self.action_type = None
        self.reason = "违反社区规范"
        self.duration_str = "1h"
        self.update_components()

    def update_components(self):
        can_exec = (self.selected_user_id is not None) and (self.action_type is not None)
        for child in self.children:
            if isinstance(child, ui.Button) and child.custom_id == "btn_execute":
                child.disabled = not can_exec
                child.style = discord.ButtonStyle.danger if can_exec else discord.ButtonStyle.secondary

    async def refresh_view(self, interaction, temp_notify=None):
        self.update_components()
        embed = discord.Embed(title="🛡️ 处罚控制台", color=STYLE["KIMI_YELLOW"])
        # ... (界面显示逻辑不变)
        if self.selected_user:
            info = f"**{self.selected_user.name}**\n`{self.selected_user.id}`"
            embed.set_thumbnail(url=self.selected_user.display_avatar.url)
        elif self.selected_user_id: info = f"ID: `{self.selected_user_id}`"
        else: info = "🔴 **未选择**"
        embed.add_field(name="1. 目标", value=info, inline=True)
        act_map = {"warn": "⚠️ 警告", "mute": "🤐 禁言", "kick": "🚀 踢出", "ban": "🚫 封禁", "unmute": "🎤 解禁", "unban": "🔓 解封"}
        embed.add_field(name="2. 动作", value=act_map.get(self.action_type, "⚪ **未选择**"), inline=True)
        desc = f"> **理由:** {self.reason}\n"
        if self.action_type == "mute": desc += f"> **时长:** `{self.duration_str}`\n"
        # 统计链接时，排除掉已作为附件上传的
        link_only_count = len([link for link in self.evidence_links if link not in self.attachment_urls])
        desc += f"> **证据:** {len(self.attachments)} 个附件, {link_only_count} 个链接"
        if self.selected_user_id:
            current_strikes = db.get_strikes(self.selected_user_id)
            desc += f"\n> **历史违规:** {current_strikes} 次 (本次将+1)"
        embed.add_field(name="配置详情", value=desc, inline=False)
        embed.set_footer(text=temp_notify or "请按顺序选择目标和动作...")
        try:
            if not interaction.response.is_done(): await interaction.response.edit_message(embed=embed, view=self)
            else: await interaction.edit_original_response(embed=embed, view=self)
        except discord.NotFound: pass

    # --- 交互组件 (保持不变) ---
    @ui.user_select(placeholder="👥 选择目标...", row=0, custom_id="sel_user")
    async def cb_user(self, select, interaction):
        await interaction.response.defer()
        self.selected_user = select.values[0]; self.selected_user_id = self.selected_user.id
        await self.refresh_view(interaction)

    @ui.select(placeholder="🔨 选择动作...", row=1, custom_id="sel_act", options=[
        discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
        discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
        discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
        discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
        discord.SelectOption(label="解除禁言", value="unmute", emoji="🎤"),
        discord.SelectOption(label="解除封禁", value="unban", emoji="🔓"),])
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


    # --- 核心执行逻辑 ---
    @ui.button(label="⚡ 确认执行", style=discord.ButtonStyle.danger, row=3, disabled=True, custom_id="btn_execute")
    async def cb_exec(self, _, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # ... (变量准备和 Discord 操作逻辑保持不变)
        tid = self.selected_user_id
        act = self.action_type
        guild = interaction.guild
        member = None
        try:
            member = guild.get_member(tid) or await guild.fetch_member(tid)
        except discord.NotFound: pass

        try:
            # 执行 Discord 操作
            # ... (这部分代码无需修改)
            # --- 以下是各操作的执行部分 ---
            msg_act, color = "", 0x999999
            if act == "warn":
                msg_act, color = "进行警告", 0xFFAA00
                if member: # 尝试私信
                    try:
                        dm_files = [await att.to_file(spoiler=True) for att in self.attachments]
                        dm = discord.Embed(title=f"⚠️ {guild.name} 社区警告", description=f"**理由:** {self.reason}", color=color)
                        if dm_files: dm.set_image(url=f"attachment://{dm_files[0].filename}")
                        await member.send(embed=dm, files=dm_files)
                    except discord.Forbidden: pass
            elif act == "mute":
                msg_act, color = f"禁言 ({self.duration_str})", 0xFF5555
                secs = parse_duration(self.duration_str)
                if secs <= 0: return await interaction.followup.send("❌ 时间格式错误或时长为0", ephemeral=True)
                if member: await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=secs), reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法禁言", ephemeral=True)
            elif act == "kick":
                msg_act, color = "踢出", 0xFF0000
                if member: await member.kick(reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法踢出", ephemeral=True)
            elif act == "ban":
                msg_act, color = "封禁", 0x000000
                await guild.ban(discord.Object(id=tid), reason=self.reason, delete_message_days=0)
            elif act == "unmute":
                msg_act, color = "解禁", 0x55FF55
                if member: await member.timeout(None, reason=self.reason)
                else: return await interaction.followup.send("❌ 找不到该成员，无法解禁", ephemeral=True)
            elif act == "unban":
                msg_act, color = "解封", 0x00AAFF
                await guild.unban(discord.Object(id=tid), reason=self.reason)
            # --- Discord 操作结束 ---

            # 数据库记录
            new_count = db.get_strikes(tid)
            if act in ["warn", "mute", "kick", "ban"]:
                new_count = db.add_strike(tid)

            # 准备文件
            files_to_send = [await att.to_file(spoiler=True) for att in self.attachments]

            # 1. 发送公开公示
            public_msg = None
            public_chan = guild.get_channel(self.public_channel_id) if self.public_channel_id else None
            if public_chan:
                p_embed = discord.Embed(title=f"🚨 社区公告 | {msg_act}", color=color)
                user_obj = member or self.selected_user or await self.ctx.bot.fetch_user(tid)
                p_embed.add_field(name="当事人", value=f"<@{tid}> (`{user_obj.name}`)", inline=True)
                p_embed.add_field(name="累计违规", value=f"**{new_count}** 次", inline=True)
                p_embed.description = f"**理由:**\n{self.reason}"
                p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
                if user_obj and user_obj.display_avatar: p_embed.set_thumbnail(url=user_obj.display_avatar.url)
                public_msg = await public_chan.send(embed=p_embed, files=files_to_send)

            # 2. 发送内部日志 (使用 Container)
            log_chan = guild.get_channel(self.log_channel_id) if self.log_channel_id else None
            # ✅ 新增：准备给 Container 用的文件列表和引用
            container_files, container_file_items = [], []
            for att in self.attachments:
                f_copy = await att.to_file(spoiler=True) # 重新创建 discord.File 对象
                container_files.append(f_copy)
                container_file_items.append(ui.File(media=f"attachment://{f_copy.filename}"))

            if log_chan:
                # 构建 UI 组件
                action_text = ui.TextDisplay(content=f"# {act.upper()}")
                link_button = ui.Button(label="查看公示", url=public_msg.jump_url) if public_msg else ui.Button(label="无公示", disabled=True)

                # 执行人信息
                executor_section = ui.Section(
                    ui.TextDisplay(content="is `EXECUTOR`"),
                    ui.TextDisplay(content=interaction.user.mention),
                    accessory=ui.Thumbnail(media=interaction.user.display_avatar.url)
                )

                # 目标用户信息
                target_user_obj = member or self.selected_user or await self.ctx.bot.fetch_user(tid)
                target_section = ui.Section(
                    ui.TextDisplay(content="is `TARGET`"),
                    ui.TextDisplay(content=target_user_obj.mention),
                    accessory=ui.Thumbnail(media=target_user_obj.display_avatar.url)
                )

                # 理由和外部链接 (如果有)
                details_items = [ui.TextDisplay(content=f"**理由**: {self.reason}")]
                link_only_urls = [link for link in self.evidence_links if link not in self.attachment_urls]
                if link_only_urls:
                    details_items.append(ui.TextDisplay(content="**外部证据链接:**\n" + "\n".join(f"- <{url}>" for url in link_only_urls)))

                # 组装 Container
                log_container = ui.Container(
                    action_text,
                    ui.ActionRow(link_button),
                    ui.Separator(),
                    executor_section,
                    target_section,
                    ui.Separator(),
                    *details_items,
                    ui.Separator(),
                    *container_file_items, # 动态添加所有附件
                    accent_colour=color
                )

                # 使用 LayoutView 发送
                log_view = ui.LayoutView().add_item(log_container)
                await log_chan.send(view=log_view, files=container_files)


            # 3. 反馈与清理
            await interaction.followup.send(f"✅ 执行成功！已发送公示与日志。", ephemeral=True)
            self.clear_items()
            original_msg = await interaction.original_response()
            fin_embed = original_msg.embeds[0]
            fin_embed.color = discord.Color.green(); fin_embed.title = "✅ 处理完毕"
            fin_embed.set_footer(text=f"操作已完成")
            await interaction.edit_original_response(embed=fin_embed, view=self)

        except discord.Forbidden:
            await interaction.followup.send("❌ 权限不足！可能是我或你的身份组权限低于目标用户。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 执行时发生未知错误: {e}", ephemeral=True)
            import traceback; traceback.print_exc()