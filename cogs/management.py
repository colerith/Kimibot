# cogs/management.py

import discord
from discord import SlashCommandGroup, Option, ui
from discord.ext import commands
import datetime
import io
from config import IDS, STYLE

# --- 辅助常量与函数 ---
KIMI_FOOTER_TEXT = "请遵守社区规则，一起做个乖饱饱嘛~！"
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

# 简单的权限检查装饰器
def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not isinstance(ctx.author, discord.Member) or not hasattr(ctx.author, 'roles'):
             await ctx.respond("呜...无法识别你的身份组信息！", ephemeral=True)
             return False

        # 从配置中获取管理员 ID
        super_egg_role_id = IDS.get("SUPER_EGG_ROLE_ID")
        if not super_egg_role_id:
             # 如果配置没加载成功，为了安全先拒绝
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
        unit = duration_str[-1].lower()
        value = int(duration_str[:-1])
        if unit == 's': return value
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 3600
        elif unit == 'd': return value * 86400
    except (ValueError, IndexError):
        return 0
    return 0

# --- 通用 Modal 组件 ---
# 用于处理各种弹窗输入，保持在主 View 逻辑之外
class CommonModal(ui.Modal):
    def __init__(self, title, input_fields, callback_func):
        super().__init__(title=title)
        self.callback_func = callback_func
        self.fields_map = input_fields # 记录字段名和组件对象的映射

        # 动态添加组件到 Modal
        for key, item in input_fields.items():
            self.add_item(item)

    async def callback(self, interaction: discord.Interaction):
        # 1. 立即 Defer，防止因为处理时间过长导致 Modal 报错
        await interaction.response.defer(ephemeral=True)

        data = {}
        # 遍历我们定义的字段表来提取数据
        for key, item in self.fields_map.items():
            # 普通文本框
            if isinstance(item, ui.InputText):
                data[key] = item.value

            # Label 包裹的组件 (如下拉框、文件上传)
            elif isinstance(item, ui.Label):
                comp = item.component

                # 下拉框 (Select)
                if hasattr(comp, "values"):
                    data[key] = comp.values

                # 文件上传 (FileUpload)
                elif isinstance(comp, ui.FileUpload):
                    # Pycord Modal 中的文件上传数据获取方式
                    # 通常需要检查该组件的 uploaded_attachments 属性
                     data[key] = comp.uploaded_attachments

                # 其他情况
                elif hasattr(comp, "value"):
                    data[key] = comp.value

        # 如果上述方式没取到文件（有时 Pycord 行为略有不同），兜底检查一遍 children
        for child in self.children:
            if isinstance(child, ui.Label) and isinstance(child.component, ui.FileUpload):
                # 如果这个组件对应我们需要的 key
                for k, v in self.fields_map.items():
                     if v == child:
                         current_attachments = child.component.uploaded_attachments
                         if current_attachments:
                             data[k] = current_attachments

        # 调用外部传入的回调函数处理业务逻辑
        if self.callback_func:
            await self.callback_func(data, interaction)

# --- 特殊 Modal: ID 输入 ---
class IDInputModal(discord.ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="🔍 手动输入用户ID")
        self.view_ref = view_ref
        self.add_item(discord.ui.InputText(
            label="用户ID",
            placeholder="请输入一串数字ID...",
            min_length=15, max_length=20, required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        # defer 更新
        await interaction.response.defer(ephemeral=True)

        user_id_str = self.children[0].value.strip()
        if not user_id_str.isdigit():
            return await interaction.followup.send("❌ ID必须是纯数字唷！", ephemeral=True)

        user_id = int(user_id_str)
        try:
            # 尝试获取用户对象以便显示头像和名称
            user = await interaction.client.fetch_user(user_id)
            self.view_ref.selected_user = user
            self.view_ref.selected_user_id = user_id
            await self.view_ref.update_panel(interaction) # 刷新主面板
        except discord.NotFound:
            # 找不到用户对象，但也记录 ID（比如已经退服的人）
            self.view_ref.selected_user = None
            self.view_ref.selected_user_id = user_id
            await self.view_ref.update_panel(interaction, override_desc=f"⚠️ 未在Discord找到该用户资料，但已选定ID: {user_id}")
        except Exception as e:
            await interaction.followup.send(f"出错惹: {e}", ephemeral=True)

# --- 特殊 Modal: 理由输入 ---
class ReasonInputModal(discord.ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📝 填写/修改处罚理由")
        self.view_ref = view_ref
        # 预填入当前的理由
        self.add_item(discord.ui.InputText(
            label="处罚理由",
            placeholder="请输入详细的理由...",
            style=discord.InputTextStyle.paragraph,
            required=True,
            value=view_ref.reason
        ))
        # 如果是禁言，额外显示时间输入框
        if view_ref.action_type == "mute":
             self.add_item(discord.ui.InputText(
                label="禁言时间 (仅禁言模式有效)",
                placeholder="例如: 10m, 1h, 1d",
                min_length=2, max_length=10, required=False,
                value=str(view_ref.duration_str) if view_ref.duration_str else ""
            ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        self.view_ref.reason = self.children[0].value
        if self.view_ref.action_type == "mute" and len(self.children) > 1:
            self.view_ref.duration_str = self.children[1].value

        await self.view_ref.update_panel(interaction) # 刷新主面板

# ======================================================
# 核心视图：全能管理面板 (Container)
# ======================================================
class ManagementControlView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=900) # 15分钟超时
        self.ctx = ctx

        # --- 面板状态数据 ---
        self.selected_user = None       # Discord User 对象
        self.selected_user_id = None    # int ID
        self.action_type = None         # str: warn, mute, etc.
        self.reason = "违反社区规范"      # str
        self.duration_str = "1h"        # str

        # 证据缓存: list[discord.File]
        # 注意: discord.File 读取过一次后指针会到末尾，需要seek(0)
        self.evidence_files = []

        # 初始化按钮状态
        self.refresh_buttons_state()

    def refresh_buttons_state(self):
        """根据当前选中的数据，决定哪些按钮可用"""
        # 能否执行：必须有目标ID + 动作类型
        can_execute = (self.selected_user_id is not None) and (self.action_type is not None)

        for child in self.children:
            # 执行按钮
            if isinstance(child, discord.ui.Button) and child.custom_id == "btn_execute":
                child.disabled = not can_execute
                child.style = discord.ButtonStyle.danger if can_execute else discord.ButtonStyle.secondary

            # 理由按钮：必须先选动作
            if isinstance(child, discord.ui.Button) and child.custom_id == "btn_reason":
                child.disabled = (self.action_type is None)

    async def update_panel(self, interaction: discord.Interaction, override_desc=None):
        """核心方法：在原地刷新整个面板的消息内容"""

        # 1. 刷新按钮状态
        self.refresh_buttons_state()

        # 2. 构建新的 Embed
        user_text = "❓ 未选择"
        if self.selected_user:
            user_text = f"{self.selected_user.mention} \n`{self.selected_user.name}`"
        elif self.selected_user_id:
            user_text = f"⚙️ ID: `{self.selected_user_id}` (未找到对象)"

        action_map = {
            "warn": "⚠️ 警告 (Warn)",
            "mute": "🤐 禁言 (Mute)",
            "kick": "🚀 踢出 (Kick)",
            "ban": "🚫 封禁 (Ban)",
            "unwarn": "🛁 解除警告",
            "unmute": "🎤 解除禁言",
            "unban": "🔓 解除封禁"
        }
        act_text = action_map.get(self.action_type, "❓ 未选择")

        embed = discord.Embed(title="🛡️ 社区管理控制台", color=STYLE["KIMI_YELLOW"])
        embed.description = override_desc if override_desc else "请配置以下选项，确认无误后点击【⚡ 执行处罚】。"

        # 构建信息概览表格
        embed.add_field(name="1. 目标用户", value=user_text, inline=True)
        embed.add_field(name="2. 处罚动作", value=act_text, inline=True)

        details_text = f"**📜 理由:** {self.reason}\n"
        if self.action_type == "mute":
            details_text += f"**⏳ 时长:** `{self.duration_str}`\n"

        if self.evidence_files:
            details_text += f"**📎 附件:** 已暂存 {len(self.evidence_files)} 张证据"
        else:
            details_text += "**📎 附件:** 无"

        embed.add_field(name="3. 执行详情", value=details_text, inline=False)

        if self.selected_user:
            embed.set_thumbnail(url=self.selected_user.display_avatar.url)
        embed.set_footer(text=KIMI_FOOTER_TEXT)

        # 3. 编辑消息
        # 兼容处理：检查 interaction 是否已经被回应过
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            print(f"Panel update failed: {e}")

    # --- 交互组件事件 ---

    # Row 0: 用户选择器
    @discord.ui.user_select(placeholder="👥 点击这里快速选择服务器成员...", row=0, min_values=1, max_values=1)
    async def select_user(self, select: discord.ui.Select, interaction: discord.Interaction):
        user = select.values[0] # 获取选中的 Member/User 对象
        self.selected_user = user
        self.selected_user_id = user.id
        await self.update_panel(interaction)

    # Row 1: 动作选择器
    @discord.ui.select(placeholder="🔨 请选择一种处理方式...", row=1, options=[
        discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️", description="发送私信警告"),
        discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐", description="开启超时模式"),
        discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀", description="移出服务器"),
        discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫", description="永久封禁"),
        discord.SelectOption(label="解除禁言 (Unmute)", value="unmute", emoji="🎤"),
        discord.SelectOption(label="解除封禁 (Unban)", value="unban", emoji="🔓"),
    ])
    async def select_action(self, select: discord.ui.Select, interaction: discord.Interaction):
        self.action_type = select.values[0]
        # 重置一些默认值提醒
        if self.action_type == "mute" and self.duration_str == "":
            self.duration_str = "1h"
        await self.update_panel(interaction)

    # Row 2: 功能按钮组
    @discord.ui.button(label="ID搜索", style=discord.ButtonStyle.secondary, row=2, emoji="🔍")
    async def btn_manual_id(self, button, interaction):
        await interaction.response.send_modal(IDInputModal(self))

    @discord.ui.button(label="补充证据", style=discord.ButtonStyle.primary, row=2, emoji="📸")
    async def btn_add_evidence(self, button, interaction: discord.Interaction):
        # 构造 Modal 内容
        fields = {
            "upload": ui.Label(
                text="上传证据图 (单次最多5张)",
                component=ui.FileUpload(
                    custom_id="ev_upload_comp",
                    max_values=5,
                    required=True, # 必须传才能提交
                ),
            ),
        }

        # 内部回调：处理上传的文件
        async def on_upload_submit(data, interact):
            attachments = data.get("upload")

            if not attachments:
                return await interact.followup.send("❌ 没有检测到文件上传捏。", ephemeral=True)

            count = 0
            for att in attachments:
                try:
                    # 将 Attachment 转回 File 对象缓存
                    f = await att.to_file()
                    self.evidence_files.append(f)
                    count += 1
                except Exception as e:
                    print(f"File convert error: {e}")

            await self.update_panel(interact, override_desc=f"✅ 成功添加了 {count} 张新证据！当前共 {len(self.evidence_files)} 张。")

        await interaction.response.send_modal(
            CommonModal("📸 上传证据", fields, on_upload_submit)
        )

    @discord.ui.button(label="撰写理由", style=discord.ButtonStyle.secondary, row=2, emoji="📝", custom_id="btn_reason")
    async def btn_reason(self, button, interaction):
        await interaction.response.send_modal(ReasonInputModal(self))

    # Row 3: 执行按钮 (单独一行，显眼)
    @discord.ui.button(label="执行处罚", style=discord.ButtonStyle.danger, row=3, disabled=True, custom_id="btn_execute", emoji="⚡")
    async def btn_execute(self, button, interaction):
        # 再次推迟交互，因为执行可能需要时间
        await interaction.response.defer()

        # --- 准备执行数据 ---
        target_id = self.selected_user_id
        action = self.action_type
        reason = self.reason
        guild = interaction.guild
        op_user = interaction.user

        # --- 处理文件流 ---
        # File 对象一旦被读取（比如上传到了临时服务器），指针可能会偏。
        # 发送前我们尝试重置它们。
        final_files = []
        for f in self.evidence_files:
            try:
                if hasattr(f.fp, 'seek'):
                    f.fp.seek(0)
                final_files.append(f)
            except:
                pass # 忽略坏文件

        # --- 获取目标成员对象 ---
        target_member = guild.get_member(target_id)

        # 针对需要成员在场才能执行的操作进行检查
        if action in ["warn", "mute", "kick"] and not target_member:
             return await interaction.followup.send(f"❌ 目标用户 (ID: {target_id}) 当前不在服务器内，无法执行 警告/禁言/踢出！", ephemeral=True)

        # 获取 User 对象只为了显示名字 (fetch fallback)
        target_user_display = self.selected_user or (target_member)
        if not target_user_display:
            try:
                target_user_display = await self.bot.fetch_user(target_id)
            except:
                pass # 实在找不到就算了

        name_display = f"{target_user_display.name} (ID: {target_id})" if target_user_display else f"ID: {target_id}"

        # --- 构造日志 Embed ---
        log_embed = discord.Embed(title=f"🛡️ 管理操作执行: {action.upper()}", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        log_embed.add_field(name="执行对象", value=name_display, inline=False)
        log_embed.add_field(name="执行理由", value=reason, inline=False)
        log_embed.add_field(name="操作人", value=op_user.mention, inline=False)
        if target_user_display and target_user_display.avatar:
            log_embed.set_thumbnail(url=target_user_display.avatar.url)

        status_msg = ""

        try:
            # --- 实际执行逻辑 ---
            if action == "warn":
                # 警告通常只是私信 + 记录
                try:
                    dm_embed = discord.Embed(title=f"⚠️ 来自 {guild.name} 的警告", description=f"**理由:** {reason}", color=0xFFAA00)
                    dm_embed.set_footer(text="请注意你的言行哦。")
                    await target_member.send(embed=dm_embed)
                    status_msg = "✅ 已私信发送警告。"
                except discord.Forbidden:
                    status_msg = "⚠️ 警告已记录，但无法私信用户（对方关闭了私信）。"

            elif action == "mute":
                seconds = parse_duration(self.duration_str)
                if seconds <= 0:
                    return await interaction.followup.send("❌ 禁言时间格式错误！", ephemeral=True)

                until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
                await target_member.timeout(until, reason=reason)
                log_embed.add_field(name="禁言时长", value=self.duration_str, inline=False)
                status_msg = f"🤐 已禁言 {self.duration_str}。"

            elif action == "kick":
                await target_member.kick(reason=reason)
                status_msg = "🚀 用户已被踢出。"

            elif action == "ban":
                # Ban 可以接受 User 对象或 ID
                user_to_ban = target_member or discord.Object(id=target_id)
                await guild.ban(user_to_ban, reason=reason)
                status_msg = "🚫 用户已被封禁。"

            elif action == "unban":
                user_to_unban = discord.Object(id=target_id)
                await guild.unban(user_to_unban, reason=reason)
                status_msg = "🔓 用户已解封。"

            elif action == "unmute":
                await target_member.timeout(None, reason=reason)
                status_msg = "🎤 用户已解除禁言。"

            # --- 发送结果 ---
            # 1. 在面板下方显示结果（Ephemeral）
            await interaction.followup.send(f"**执行成功！** {status_msg}", embed=log_embed, files=final_files, ephemeral=True)

            # 2. (可选) 如果配置了日志频道，可以在这里发送一份公开记录
            # log_channel = guild.get_channel(IDS["TICKET_LOG_CHANNEL_ID"])
            # if log_channel: await log_channel.send(embed=log_embed)

            # 3. 锁定面板，防止重复点击
            for child in self.children:
                child.disabled = True

            embed = interaction.message.embeds[0]
            embed.color = 0x00FF00 # 绿色表示完成
            embed.title = "🛡️ 社区管理控制台 (已执行)"
            embed.set_footer(text=f"操作已由 {op_user.display_name} 完成")

            await interaction.edit_original_response(embed=embed, view=self)

        except discord.Forbidden:
            await interaction.followup.send("❌ **权限不足！** 我无法对该用户执行此操作（可能是因为他的身份组比我高）。", ephemeral=True)
        except Exception as e:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"❌ **执行过程中发生错误**: {e}", ephemeral=True)

# ======================================================
# Cog 定义
# ======================================================
class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="处罚", description="呼出全能管理面板，对不乖的饱饱进行处罚！")
    @is_super_egg()
    async def punishment_panel(self, ctx: discord.ApplicationContext):
        # 初始 Embed
        embed = discord.Embed(
            title="🛡️ 社区管理控制台 (初始化中...)",
            description="正在加载组件，请稍候...",
            color=STYLE["KIMI_YELLOW"]
        )
        embed.set_footer(text=KIMI_FOOTER_TEXT)

        # 初始化 View
        view = ManagementControlView(ctx)

        # 发送消息并立即刷新一次面板以显示默认状态
        resp = await ctx.respond(embed=embed, view=view, ephemeral=True)

        # 获取 Interaction 对象来第一次刷新内容
        if isinstance(resp, discord.Interaction):
            # 这里的 resp 实际上是 interaction 上下文
            # 但我们需要的是一个能调用 edit 或 followup 的上下文
            # 在 pycord 中 ctx.respond 返回的是 Interaction 或 WebhookMessage
            # 我们直接手动调用 view 的 update 逻辑来初始化内容
            await view.update_panel(ctx.interaction, override_desc="请使用下方的组件来配置处罚选项。\n• 先选人，再选动作。\n• 点击【📸 补充证据】可上传截图保留。")

def setup(bot):
    bot.add_cog(Management(bot))

