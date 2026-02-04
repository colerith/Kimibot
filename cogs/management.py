# cogs/management.py

import discord
from discord import SlashCommandGroup, Option, ui
from discord.ext import commands
import datetime
from config import IDS, STYLE, SERVER_OWNER_ID

# --- 辅助常量 ---
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

# 权限检查
def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not isinstance(ctx.author, discord.Member): return False

        # 即使配置未加载也允许 Owner 使用方便调试
        if ctx.author.id == SERVER_OWNER_ID: return True

        super_egg_role_id = IDS.get("SUPER_EGG_ROLE_ID")
        if not super_egg_role_id:
             await ctx.respond("❌ 配置缺失: SUPER_EGG_ROLE_ID", ephemeral=True)
             return False

        role = ctx.guild.get_role(super_egg_role_id)
        if role and role in ctx.author.roles: return True

        await ctx.respond("🚫 只有【超级小蛋】才能使用此魔法哦！", ephemeral=True)
        return False
    return commands.check(predicate)

def parse_duration(duration_str: str) -> int:
    try:
        if not duration_str: return 0
        s = duration_str.strip().lower()
        if len(s) < 2: return 0
        unit = s[-1]
        val_str = s[:-1]
        if not val_str.isdigit(): return 0
        val = int(val_str)

        if unit == 's': return val
        elif unit == 'm': return val * 60
        elif unit == 'h': return val * 3600
        elif unit == 'd': return val * 86400
    except: return 0
    return 0

# ======================================================
# Modal 组件
# ======================================================

# 1. ID 输入 (备用)
class IDInputModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="🔍 手动输入用户ID")
        self.view_ref = view_ref
        self.add_item(ui.InputText(
            label="用户ID", placeholder="18位数字ID",
            min_length=15, max_length=20, required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_str = self.children[0].value.strip()
        if not uid_str.isdigit():
            return await interaction.followup.send("❌ ID必须是数字", ephemeral=True)

        uid = int(uid_str)
        try:
            # 尝试获取用户对象用于显示头像
            user = await interaction.client.fetch_user(uid)
            self.view_ref.selected_user = user
            self.view_ref.selected_user_id = uid
            msg = "✅ 已锁定目标用户"
        except:
            self.view_ref.selected_user = None
            self.view_ref.selected_user_id = uid
            msg = "⚠️ 未找到用户详细信息，但ID已锁定"

        await self.view_ref.refresh_view(interaction, temp_notify=msg)

# 2. 证据管理 (追加文本链接)
class EvidenceAppendModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📸 追加证据链接")
        self.view_ref = view_ref
        self.add_item(ui.InputText(
            label="额外证据链接 (每行一个)",
            placeholder="https://...",
            style=discord.InputTextStyle.paragraph,
            required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        content = self.children[0].value.strip()
        added_count = 0
        for line in content.split('\n'):
            if line.strip():
                self.view_ref.evidence_links.append(line.strip())
                added_count += 1

        await self.view_ref.refresh_view(interaction, temp_notify=f"✅ 已追加 {added_count} 条证据")

# 3. 理由填写
class ReasonInputModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📝 处罚详情")
        self.view_ref = view_ref
        self.add_item(ui.InputText(
            label="详细理由", style=discord.InputTextStyle.paragraph,
            required=True, max_length=500, value=view_ref.reason
        ))
        self.add_item(ui.InputText(
            label="时长 (仅禁言生效)", placeholder="10m, 1h, 1d",
            required=False, max_length=10, value=view_ref.duration_str
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.view_ref.reason = self.children[0].value
        if self.children[1].value:
            self.view_ref.duration_str = self.children[1].value
        await self.view_ref.refresh_view(interaction)

# ======================================================
# 核心视图
# ======================================================

class ManagementControlView(ui.View):
    def __init__(self, ctx, initial_files=None):
        super().__init__(timeout=900)
        self.ctx = ctx

        # --- 状态数据 ---
        self.selected_user = None       # discord.User / Member
        self.selected_user_id = None    # int
        self.action_type = None         # str
        self.reason = "违反社区规范"
        self.duration_str = "1h"

        # 证据列表 (包含上传的附件URL)
        self.evidence_links = []
        if initial_files:
            for attachment in initial_files:
                if attachment:
                    self.evidence_links.append(attachment.url)

        # 初始化组件状态
        self.update_components()

    def update_components(self):
        """根据当前状态开关按钮"""
        can_exec = (self.selected_user_id is not None) and (self.action_type is not None)

        # 遍历子组件设置状态
        for child in self.children:
            if isinstance(child, ui.Button):
                if child.custom_id == "btn_execute":
                    child.disabled = not can_exec
                    child.style = discord.ButtonStyle.danger if can_exec else discord.ButtonStyle.secondary
                elif child.custom_id == "btn_reason":
                    child.disabled = (self.action_type is None)

    async def refresh_view(self, interaction: discord.Interaction, temp_notify=None):
        self.update_components()

        # --- 第一部分: 状态展示 (Embed) ---
        embed = discord.Embed(title="🛡️ 社区管理控制台", color=STYLE["KIMI_YELLOW"])
        embed.set_thumbnail(url=self.ctx.me.display_avatar.url)

        # 1. 目标区块
        if self.selected_user:
            u_name = f"{self.selected_user.name}"
            u_mention = self.selected_user.mention
            u_id = self.selected_user.id
            u_avatar = self.selected_user.display_avatar.url

            val_text = f"**用户:** {u_mention}\n**账号:** `{u_name}`\n**ID:** `{u_id}`"
            embed.set_image(url=u_avatar) # 显示大图确认身份
        elif self.selected_user_id:
            val_text = f"⚙️ **ID模式:** `{self.selected_user_id}`\n(未获取到详细资料)"
        else:
            val_text = "🔴 **[请点击下方选择用户]**"

        embed.add_field(name="1. 目标用户 (Target)", value=val_text, inline=True)

        # 2. 动作区块
        act_map = {
            "warn": "⚠️ 警告", "mute": "🤐 禁言", "kick": "🚀 踢出", "ban": "🚫 封禁",
            "unmute": "🎤 解禁", "unban": "🔓 解封"
        }
        act_text = act_map.get(self.action_type, "⚪ **[请选择动作]**")
        embed.add_field(name="2. 执行动作 (Action)", value=act_text, inline=True)

        # 3. 详情配置
        embed.add_field(name="\u200b", value="**📝 配置详情:**", inline=False)

        detail_desc = f"> **理由:** {self.reason}\n"
        if self.action_type == "mute":
            detail_desc += f"> **时长:** `{self.duration_str}`\n"

        if self.evidence_links:
            detail_desc += f"> **证据:** 已包含 {len(self.evidence_links)} 个文件/链接"
        else:
            detail_desc += "> **证据:** 暂无"

        embed.add_field(name="\u200b", value=detail_desc, inline=False)

        # 底部状态栏
        if temp_notify:
            embed.set_footer(text=f"🔔 {temp_notify}")
        else:
            embed.set_footer(text="等待操作指令...")

        # 更新消息
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    # --- 第二部分: 交互组件 (View) ---

    # Row 0: 选人 (核心入口)
    @ui.user_select(placeholder="👥 点击此处选择目标用户...", row=0, min_values=1, max_values=1, custom_id="sel_user")
    async def callback_user_select(self, select, interaction):
        user = select.values[0]
        self.selected_user = user
        self.selected_user_id = user.id
        await self.refresh_view(interaction)

    # Row 1: 选动作
    @ui.select(placeholder="🔨 选择处理方式...", row=1, custom_id="sel_action", options=[
        discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
        discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
        discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
        discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
        discord.SelectOption(label="解除禁言", value="unmute", emoji="🎤"),
        discord.SelectOption(label="解除封禁", value="unban", emoji="🔓"),
    ])
    async def callback_action_select(self, select, interaction):
        self.action_type = select.values[0]
        # 只要不是mute，时长字段其实没意义，但保留显示无妨
        await self.refresh_view(interaction)

    # Row 2: 功能按钮
    @ui.button(label="ID搜人", style=discord.ButtonStyle.secondary, row=2, emoji="🔍", custom_id="btn_id")
    async def callback_btn_id(self, _, interaction):
        await interaction.response.send_modal(IDInputModal(self))

    @ui.button(label="追加证据", style=discord.ButtonStyle.secondary, row=2, emoji="📎", custom_id="btn_ev")
    async def callback_btn_ev(self, _, interaction):
        await interaction.response.send_modal(EvidenceAppendModal(self))

    @ui.button(label="理由/时长", style=discord.ButtonStyle.primary, row=2, emoji="📝", custom_id="btn_reason")
    async def callback_btn_reason(self, _, interaction):
        await interaction.response.send_modal(ReasonInputModal(self))

    # Row 3: 执行
    @ui.button(label="⚡ 确认执行", style=discord.ButtonStyle.danger, row=3, disabled=True, custom_id="btn_execute")
    async def callback_btn_execute(self, _, interaction):
        await interaction.response.defer()

        # 提取数据
        tid = self.selected_user_id
        act = self.action_type
        rsn = self.reason
        guild = interaction.guild

        target_member = guild.get_member(tid)

        # 基础检查
        if act in ["warn", "mute", "kick"] and not target_member:
            return await interaction.followup.send("❌ 目标用户不在服务器内，无法执行该操作。", ephemeral=True)

        # 准备日志 Embed
        log_embed = discord.Embed(title=f"🛡️ 执行报告: {act.upper()}", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        log_embed.description = f"**对象:** <@{tid}>\n**执行者:** {interaction.user.mention}\n**理由:** {rsn}"

        # 整理证据展示
        if self.evidence_links:
            links_str = "\n".join([f"• [证据链接 {i+1}]({link})" for i, link in enumerate(self.evidence_links)])
            log_embed.add_field(name="📎 相关证据", value=links_str, inline=False)
            # 尝试把第一张图作为日志的主图
            first_img = next((x for x in self.evidence_links if any(ext in x.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])), None)
            if first_img:
                log_embed.set_image(url=first_img)

        try:
            status_msg = "执行完毕。"

            if act == "warn":
                try:
                    dm = discord.Embed(title=f"⚠️ {guild.name} 警告通知", description=rsn, color=0xFFAA00)
                    if self.evidence_links:
                         dm.set_image(url=self.evidence_links[0]) # 给用户看第一张证据
                    await target_member.send(embed=dm)
                    status_msg = "✅ 警告私信发送成功。"
                except:
                    status_msg = "⚠️ 警告已记录 (用户关闭了私信)。"

            elif act == "mute":
                secs = parse_duration(self.duration_str)
                if secs <= 0: return await interaction.followup.send("❌ 时长格式错误 (例如: 10m, 1h)", ephemeral=True)

                until = discord.utils.utcnow() + datetime.timedelta(seconds=secs)
                await target_member.timeout(until, reason=rsn)
                status_msg = f"🤐 禁言成功 ({self.duration_str})。"
                log_embed.add_field(name="禁言时长", value=self.duration_str)

            elif act == "kick":
                await target_member.kick(reason=rsn)
                status_msg = "🚀 踢出成功。"

            elif act == "ban":
                await guild.ban(discord.Object(id=tid), reason=rsn)
                status_msg = "🚫 封禁成功。"

            elif act == "unmute":
                await target_member.timeout(None, reason=rsn)
                status_msg = "🎤 解除禁言成功。"

            elif act == "unban":
                await guild.unban(discord.Object(id=tid), reason=rsn)
                status_msg = "🔓 解除封禁成功。"

            # 反馈结果
            await interaction.followup.send(content=status_msg, embed=log_embed, ephemeral=True)

            # 结束面板
            self.clear_items()
            final_embed = interaction.message.embeds[0]
            final_embed.color = discord.Color.green()
            final_embed.title = "✅ 处理完成"
            final_embed.description = f"**操作对象:** <@{tid}>\n**结果:** {status_msg}"
            final_embed.set_footer(text=f"执行人: {interaction.user.display_name}")
            await interaction.edit_original_response(embed=final_embed, view=self)

        except discord.Forbidden:
            await interaction.followup.send("❌ 权限不足！我也许无法处罚这个身份比我高的人。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 执行出错: {e}", ephemeral=True)


# ======================================================
# Cog 注册
# ======================================================
class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="处罚", description="打开管理面板 (可直接上传证据)")
    @is_super_egg()
    async def punishment_panel(
        self,
        ctx: discord.ApplicationContext,
        evidence_file: Option(discord.Attachment, "上传证据截图/文件", required=False),
        evidence_file2: Option(discord.Attachment, "上传更多证据(可选)", required=False)
    ):
        # 收集所有上传的附件
        files = []
        if evidence_file: files.append(evidence_file)
        if evidence_file2: files.append(evidence_file2)

        # 初始化面板
        view = ManagementControlView(ctx, initial_files=files)

        # 初始加载占位
        embed = discord.Embed(title="🛡️ 面板加载中...", color=STYLE["KIMI_YELLOW"])

        await ctx.respond(embed=embed, view=view, ephemeral=True)

        # 立即刷新显示内容
        await view.refresh_view(ctx.interaction)

def setup(bot):
    bot.add_cog(Management(bot))
