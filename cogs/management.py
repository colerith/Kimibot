# cogs/management.py

import discord
from discord import SlashCommandGroup, Option, ui
from discord.ext import commands
import datetime
import io
from config import IDS, STYLE

# --- 辅助常量 ---
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

# 简单的权限检查装饰器
def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not isinstance(ctx.author, discord.Member):
             await ctx.respond("呜...无法识别你的身份信息！", ephemeral=True)
             return False

        # 从配置中获取管理员 ID
        super_egg_role_id = IDS.get("SUPER_EGG_ROLE_ID")
        if not super_egg_role_id:
             await ctx.respond("系统配置加载异常(ID缺失)，请联系开发者。", ephemeral=True)
             return False

        super_egg_role = ctx.guild.get_role(super_egg_role_id)
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True
        await ctx.respond("呜...这个是【超级小蛋】专属嘟魔法，你还不能用捏！QAQ", ephemeral=True)
        return False
    return commands.check(predicate)

def parse_duration(duration_str: str) -> int:
    try:
        if not duration_str: return 0
        unit = duration_str[-1].lower()
        value = int(duration_str[:-1])
        if unit == 's': return value
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 3600
        elif unit == 'd': return value * 86400
    except (ValueError, IndexError):
        return 0
    return 0

# ======================================================
# 新版 Modal 组件 (完全复刻 Label + Component 结构)
# ======================================================

# 1. ID 输入弹窗
class IDInputModal(ui.Modal, title="🔍 手动输入用户ID"):
    # 使用 Label 包裹 TextInput
    id_ui = ui.Label(
        text="用户ID",
        component=ui.TextInput(
            label="请输入一串数字ID...", # 注意：在Label结构下，TextInput自身的label属性可能不显示，主要靠Label text
            placeholder="例如: 123456789012345678",
            min_length=15, max_length=20, required=True
        )
    )

    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # 仅仅defer，不发消息，靠view刷新

        user_id_str = self.id_ui.component.value.strip()
        if not user_id_str.isdigit():
            await interaction.followup.send("❌ ID必须是纯数字唷！", ephemeral=True)
            return

        user_id = int(user_id_str)
        try:
            user = await interaction.client.fetch_user(user_id)
            self.view_ref.selected_user = user
            self.view_ref.selected_user_id = user_id
            # 刷新父视图
            await self.view_ref.refresh_view(interaction)
        except discord.NotFound:
            self.view_ref.selected_user = None
            self.view_ref.selected_user_id = user_id
            await self.view_ref.refresh_view(interaction, temp_notify=f"⚠️ 未找到用户，但已锁定ID: {user_id}")
        except Exception as e:
            await interaction.followup.send(f"出错惹: {e}", ephemeral=True)

# 2. 证据上传弹窗
class EvidenceUploadModal(ui.Modal, title="📸 上传证据"):
    upload_ui = ui.Label(
        text="请上传截图 (最多9张)",
        component=ui.FileUpload(
            custom_id="ev_upload_comp",
            max_values=9,
            required=True,
        )
    )

    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        attachments = self.upload_ui.component.uploaded_attachments
        if not attachments:
            return await interaction.followup.send("❌ 未检测到文件。", ephemeral=True)

        count = 0
        for att in attachments:
            try:
                # 转换为 File 对象并缓存到 View 中
                f = await att.to_file()
                self.view_ref.evidence_files.append(f)
                count += 1
            except Exception as e:
                print(f"File error: {e}")

        await self.view_ref.refresh_view(interaction, temp_notify=f"✅ 成功添加 {count} 张证据！当前共 {len(self.view_ref.evidence_files)} 张。")

# 3. 理由填写弹窗
class ReasonInputModal(ui.Modal, title="📝 处罚理由"):
    reason_ui = ui.Label(
        text="详细理由",
        component=ui.TextInput(
            style=discord.InputTextStyle.paragraph,
            placeholder="请输入违规详情...",
            required=True,
            max_length=500
        )
    )

    duration_ui = ui.Label(
        text="时长 (仅禁言模式生效)",
        description="格式: 10m, 1h, 1d",
        component=ui.TextInput(
            style=discord.InputTextStyle.short,
            required=False,
            max_length=10,
            placeholder="留空默认1h"
        )
    )

    def __init__(self, view_ref):
        super().__init__()
        self.view_ref = view_ref
        # 预填默认值
        self.reason_ui.component.default_value = view_ref.reason
        if view_ref.duration_str:
            self.duration_ui.component.default_value = view_ref.duration_str

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        self.view_ref.reason = self.reason_ui.component.value
        dur = self.duration_ui.component.value
        if dur:
            self.view_ref.duration_str = dur

        await self.view_ref.refresh_view(interaction)

# ======================================================
# 核心视图：ManagementControlView (LayoutView 重构版)
# ======================================================

class ManagementControlView(ui.LayoutView):
    def __init__(self, ctx):
        super().__init__(timeout=900)
        self.ctx = ctx

        # --- 内部状态 ---
        self.selected_user = None       # Discord User
        self.selected_user_id = None    # Int ID
        self.action_type = None         # Str
        self.reason = "违反社区规范"
        self.duration_str = "1h"
        self.evidence_files = []        # List[discord.File]

        # --- 预定义组件 (Interactive Components) ---
        # 1. 动作类型选择
        self.sel_action = ui.Select(
            placeholder="🔨 选择处理方式...",
            options=[
                discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
                discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
                discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
                discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
                discord.SelectOption(label="解除禁言 (Unmute)", value="unmute", emoji="🎤"),
                discord.SelectOption(label="解除封禁 (Unban)", value="unban", emoji="🔓"),
            ],
            custom_id="sel_action"
        )
        self.sel_action.callback = self.on_action_select

        # 2. 用户选择 (UserSelect)
        self.sel_user = ui.UserSelect(
            placeholder="👥 点击选择目标成员...",
            min_values=1, max_values=1,
            custom_id="sel_user"
        )
        self.sel_user.callback = self.on_user_select

        # 3. 功能按钮
        self.btn_id_search = ui.Button(label="ID模式", style=discord.ButtonStyle.secondary, emoji="🔍")
        self.btn_id_search.callback = self.on_btn_id_click

        self.btn_evidence = ui.Button(label="传证", style=discord.ButtonStyle.primary, emoji="📸")
        self.btn_evidence.callback = self.on_btn_evidence_click

        self.btn_reason = ui.Button(label="写理由", style=discord.ButtonStyle.secondary, emoji="📝")
        self.btn_reason.callback = self.on_btn_reason_click

        # 4. 执行按钮 (初始禁用)
        self.btn_execute = ui.Button(label="⚡ 执行处罚", style=discord.ButtonStyle.danger, disabled=True, row=4)
        self.btn_execute.callback = self.on_btn_execute_click

        # 初次构建界面
        self.build_layout()

    # --- 布局构建方法 ---
    def build_layout(self, notification=None):
        self.clear_items() # 清空当前容器

        # 1. 顶部状态栏 Section
        # 根据是否有选中用户显示不同内容
        if self.selected_user:
            user_display = f"**目标:** {self.selected_user.mention} (`{self.selected_user.id}`)"
            avatar_url = self.selected_user.display_avatar.url
        elif self.selected_user_id:
            user_display = f"**目标ID:** `{self.selected_user_id}` (离线/未知)"
            avatar_url = None # 或者放个默认图
        else:
            user_display = "**目标:** ❓ 未选择"
            avatar_url = None

        # 2. 动作详情 Section
        action_map = {"warn": "⚠️ 警告", "mute": "🤐 禁言", "kick": "🚀 踢出", "ban": "🚫 封禁", "unwarn": "🛁 解警", "unmute": "🎤 解禁", "unban": "🔓 解封"}
        act_str = action_map.get(self.action_type, "❓ 未选择")

        detail_lines = [f"**动作:** {act_str}"]
        if self.action_type == "mute":
            detail_lines.append(f"**时长:** `{self.duration_str}`")
        detail_lines.append(f"**理由:** {self.reason}")
        if self.evidence_files:
            detail_lines.append(f"**证据:** 已存 {len(self.evidence_files)} 张")

        detail_content = "\n".join(detail_lines)

        # 3. 如果有临时通知
        notify_section = None
        if notification:
            notify_section = ui.Section(
                ui.TextDisplay(content=f"🔔 {notification}"),
                accessory=None
            )

        # 4. 更新按钮状态
        can_exec = (self.selected_user_id is not None) and (self.action_type is not None)
        self.btn_execute.disabled = not can_exec
        self.btn_reason.disabled = (self.action_type is None)

        # --- 组装 Container ---
        container_items = []

        # Header Section
        container_items.append(
            ui.Section(
                ui.TextDisplay(content="### 🛡️ 社区管理控制台"),
                ui.TextDisplay(content=user_display),
                accessory=ui.Thumbnail(media=avatar_url) if avatar_url else None
            )
        )

        # Details Section
        container_items.append(
            ui.Section(
                ui.TextDisplay(content=detail_content),
                # 这里可以放个装饰性按钮或者Icon作为Accessory，这里暂空
            )
        )

        if notify_section:
            container_items.append(notify_section)

        container_items.append(ui.Separator())

        # Action Rows
        container_items.append(ui.ActionRow(self.sel_user))
        container_items.append(ui.ActionRow(self.sel_action))
        container_items.append(ui.ActionRow(self.btn_id_search, self.btn_evidence, self.btn_reason))
        container_items.append(ui.Separator())
        container_items.append(ui.ActionRow(self.btn_execute))

        # Config Container
        container = ui.Container(
            *container_items,
            accent_colour=discord.Color.from_rgb(255, 223, 0) # Kimi Yellow
        )

        self.add_item(container)

    # --- 刷新逻辑 ---
    async def refresh_view(self, interaction: discord.Interaction = None, temp_notify=None):
        """重新构建布局并更新消息"""
        self.build_layout(notification=temp_notify)

        if interaction:
            if not interaction.response.is_done():
                await interaction.response.edit_message(view=self)
            else:
                await interaction.edit_original_response(view=self)

    # --- 回调函数 ---

    async def on_user_select(self, interaction: discord.Interaction):
        # UserSelect values 是一个列表
        if not self.sel_user.values: return
        user = self.sel_user.values[0]
        self.selected_user = user
        self.selected_user_id = user.id
        await self.refresh_view(interaction)

    async def on_action_select(self, interaction: discord.Interaction):
        if not self.sel_action.values: return
        self.action_type = self.sel_action.values[0]
        if self.action_type == "mute" and not self.duration_str:
            self.duration_str = "1h"
        await self.refresh_view(interaction)

    async def on_btn_id_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(IDInputModal(self))

    async def on_btn_evidence_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EvidenceUploadModal(self))

    async def on_btn_reason_click(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ReasonInputModal(self))

    async def on_btn_execute_click(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # 数据准备
        target_id = self.selected_user_id
        action = self.action_type
        reason = self.reason
        guild = interaction.guild
        op_user = interaction.user

        # 文件指针重置
        final_files = []
        for f in self.evidence_files:
            try:
                if hasattr(f.fp, 'seek'): f.fp.seek(0)
                final_files.append(f)
            except: pass

        target_member = guild.get_member(target_id)
        if action in ["warn", "mute", "kick"] and not target_member:
             return await interaction.followup.send(f"❌ 目标不在服内，无法执行 {action}！", ephemeral=True)

        # 执行逻辑
        status_msg = ""
        log_embed = discord.Embed(title=f"🛡️ 执行报告: {action.upper()}", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        log_embed.description = f"**对象:** <@{target_id}> ({target_id})\n**操作人:** {op_user.mention}\n**理由:** {reason}"

        try:
            if action == "warn":
                try:
                    dm = discord.Embed(title=f"⚠️ {guild.name} 警告通知", description=f"**理由:** {reason}", color=0xFFAA00)
                    await target_member.send(embed=dm)
                    status_msg = "✅ 已私信警告。"
                except: status_msg = "⚠️ 警告已记录 (由于隐私设置未能私信)。"

            elif action == "mute":
                secs = parse_duration(self.duration_str)
                if secs <= 0: return await interaction.followup.send("❌ 时间格式错误", ephemeral=True)
                until = discord.utils.utcnow() + datetime.timedelta(seconds=secs)
                await target_member.timeout(until, reason=reason)
                status_msg = f"🤐 已禁言 {self.duration_str}。"
                log_embed.add_field(name="时长", value=self.duration_str)

            elif action == "kick":
                await target_member.kick(reason=reason)
                status_msg = "🚀 已踢出。"

            elif action == "ban":
                await guild.ban(discord.Object(id=target_id), reason=reason)
                status_msg = "🚫 已封禁。"

            elif action == "unmute":
                await target_member.timeout(None, reason=reason)
                status_msg = "🎤 已解除禁言。"

            elif action == "unban":
                await guild.unban(discord.Object(id=target_id), reason=reason)
                status_msg = "🔓 已解除封禁。"

            # 结果反馈
            await interaction.followup.send(f"{status_msg}", embed=log_embed, files=final_files, ephemeral=True)

            # 锁定面板
            self.clear_items()
            end_container = ui.Container(
                ui.Section(
                    ui.TextDisplay(content=f"### ✅ 操作已完成"),
                    ui.TextDisplay(content=f"由 {op_user.display_name} 执行于 {datetime.datetime.now().strftime('%H:%M')}"),
                ),
                accent_colour=discord.Color.green()
            )
            self.add_item(end_container)
            await interaction.edit_original_response(view=self)

        except discord.Forbidden:
            await interaction.followup.send("❌ 权限不足 (对方身份组可能更高)！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 遇到错误: {e}", ephemeral=True)


# ======================================================
# Cog 定义
# ======================================================
class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="处罚", description="打开全能管理面板")
    @is_super_egg()
    async def punishment_panel(self, ctx: discord.ApplicationContext):
        view = ManagementControlView(ctx)
        await ctx.respond(view=view, ephemeral=True)

def setup(bot):
    bot.add_cog(Management(bot))