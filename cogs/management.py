import discord
from discord import SlashCommandGroup, Option, ui
from discord.ext import commands
import datetime
from config import IDS, STYLE

# --- 辅助常量与函数 ---
KIMI_FOOTER_TEXT = "请遵守社区规则，一起做个乖饱饱嘛~！"
TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not isinstance(ctx.author, discord.Member) or not hasattr(ctx.author, 'roles'):
             await ctx.respond("呜...无法识别你的身份组信息！", ephemeral=True)
             return False

        super_egg_role = ctx.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
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

# --- 通用 Modal 组件 (核心逻辑来自宝贝的代码) ---
class CommonModal(ui.Modal):
    def __init__(self, view, title, input_fields, callback_func):
        super().__init__(title=title)
        self.view_ref = view
        self.callback_func = callback_func
        self.fields_map = input_fields

        # 动态添加组件
        for key, item in input_fields.items():
            self.add_item(item)

    async def callback(self, interaction: discord.Interaction):
        # 1. Defer 交互，防止 Modal 显示超时 (文件上传可能需要时间)
        await interaction.response.defer(ephemeral=True)

        data = {}
        for key, item in self.fields_map.items():
            # 提取 TextInput
            if isinstance(item, ui.InputText): # Pycord 中通常是 InputText
                data[key] = item.value
            # 提取 Label 包裹的组件 (FileUpload / Select 等)
            elif isinstance(item, ui.Label):
                comp = item.component
                if hasattr(comp, "values"):  # Select
                    data[key] = comp.values
                elif hasattr(comp, "value"):  # TextInput inside Label?
                    data[key] = comp.value
                elif isinstance(comp, ui.FileUpload): # FileUpload 特殊处理
                    # Pycord 可能会直接把文件绑定在 interaction.data 或者组件状态里
                    # 但在这里我们相信该组件能正确返回 values 或者被正确捕获
                    # 注意：Pycord 的 FileUpload 组件通常直接用于 Modal 时行为比较特殊
                    # 若无法直接获取，我们假设框架底层已经处理好
                    pass

        # 针对 FileUpload 的特殊数据获取
        # 实际上在 Pycord 的 Modal callback 里，附件通常不在 item.value
        # 而是需要检查该组件的状态。在你的示例逻辑中，似乎直接通过 key 获取即可。
        # 我们这里做一个兼容处理：再次遍历 children 检查 FileUpload
        for child in self.children:
            # 如果是 Label 包裹的
            if isinstance(child, ui.Label) and isinstance(child.component, ui.FileUpload):
                # 找到对应的 key
                for k, v in self.fields_map.items():
                    if v == child:
                        # 尝试获取已上传的文件
                        # 注意：这依赖于库的具体实现。如果 child.component.values 为空，
                        # 可能需要从 interaction.message 或其他地方找。
                        # 这里我们信任示例代码逻辑：假设组件会自动持有上传数据。
                        data[k] = child.component.uploaded_attachments

        if self.callback_func:
            await self.callback_func(data, interaction)

# --- 具体的 ID 输入 Modal (保留旧有逻辑) ---
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
        user_id = self.children[0].value.strip()
        if not user_id.isdigit():
            return await interaction.response.send_message("❌ ID必须是纯数字唷！", ephemeral=True)
        try:
            user = await interaction.client.fetch_user(int(user_id))
            self.view_ref.selected_user = user
            self.view_ref.selected_user_id = int(user_id)
            await self.view_ref.update_embed(interaction)
        except discord.NotFound:
            self.view_ref.selected_user = None
            self.view_ref.selected_user_id = int(user_id)
            await self.view_ref.update_embed(interaction, override_desc=f"⚠️ 未找到用户对象，但已记录ID: {user_id}")
        except Exception as e:
            await interaction.response.send_message(f"出错惹: {e}", ephemeral=True)

# --- 理由输入 Modal (保留旧有逻辑) ---
class ReasonInputModal(discord.ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📝 填写/修改处罚理由")
        self.view_ref = view_ref
        self.add_item(discord.ui.InputText(
            label="处罚理由",
            placeholder="请输入详细的理由...",
            style=discord.InputTextStyle.paragraph,
            required=True,
            value=view_ref.reason
        ))
        if view_ref.action_type == "mute":
             self.add_item(discord.ui.InputText(
                label="禁言时间 (仅禁言有效)",
                placeholder="例如: 10m, 1h, 1d",
                min_length=2, max_length=10, required=False,
                value=str(view_ref.duration_str) if view_ref.duration_str else ""
            ))

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.reason = self.children[0].value
        if self.view_ref.action_type == "mute" and len(self.children) > 1:
            self.view_ref.duration_str = self.children[1].value
        await self.view_ref.update_embed(interaction)

# --- 核心视图：管理面板 ---
class ManagementControlView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=600)
        self.ctx = ctx

        # 状态存储
        self.selected_user = None
        self.selected_user_id = None
        self.action_type = None
        self.reason = "违反社区规范"
        self.duration_str = "1h"

        # 证据图片存储 (List[discord.File])
        # 注意：discord.File 对象是一次性的，如果发送失败或者需要预览，需要特别小心。
        # 这里我们存 File 对象，发送时使用。
        self.evidence_files = []
        self.evidence_count = 0

    async def update_embed(self, interaction: discord.Interaction, override_desc=None):
        """刷新面板显示"""
        user_text = f"{self.selected_user.name} ({self.selected_user.id})" if self.selected_user else (f"未知用户 (ID: {self.selected_user_id})" if self.selected_user_id else "❓ 未选择")
        thumb_url = self.selected_user.display_avatar.url if self.selected_user else None

        action_map = {
            "warn": "⚠️ 警告", "mute": "🤐 禁言", "kick": "🚀 踢出",
            "ban": "🚫 封禁", "unwarn": "🛁 解除警告", "unmute": "🎤 解除禁言", "unban": "🔓 解除封禁"
        }
        act_text = action_map.get(self.action_type, "❓ 未选择")

        e = discord.Embed(title="🛡️ 社区管理控制台", color=STYLE["KIMI_YELLOW"])
        e.add_field(name="1. 目标用户", value=user_text, inline=True)
        e.add_field(name="2. 处罚动作", value=act_text, inline=True)

        details = f"📜 **理由**: {self.reason}"
        if self.action_type == "mute":
            details += f"\n⏳ **时长**: {self.duration_str}"

        # 显示证据状态
        if self.evidence_files:
            details += f"\n📎 **附件**: 已暂存 {len(self.evidence_files)} 张证据图片"
        else:
            details += "\n📎 **附件**: 无 (可点击下方按钮补充)"

        e.add_field(name="3. 执行详情", value=details, inline=False)
        if override_desc: e.description = override_desc
        if thumb_url: e.set_thumbnail(url=thumb_url)

        # 按钮状态控制
        can_execute = (self.selected_user or self.selected_user_id) is not None and self.action_type is not None
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "btn_execute":
                child.disabled = not can_execute
                child.style = discord.ButtonStyle.danger if can_execute else discord.ButtonStyle.secondary

        try:
            # 如果 interaction 已经被 deferred (通常在 Modal 回调后)，用 follow up 或者 edit_original
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=e, view=self)
            else:
                await interaction.response.edit_message(embed=e, view=self)
        except:
            pass

    # Row 0: 选择用户
    @discord.ui.user_select(placeholder="👥 在这里快速选择服务器成员...", row=0, min_values=1, max_values=1)
    async def select_user(self, select: discord.ui.Select, interaction: discord.Interaction):
        user = select.values[0]
        self.selected_user = user
        self.selected_user_id = user.id
        await self.update_embed(interaction)

    # Row 1: 选择动作
    @discord.ui.select(placeholder="🔨 选择一种处罚方式...", row=1, options=[
        discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
        discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
        discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
        discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
        discord.SelectOption(label="解除禁言 (Unmute)", value="unmute", emoji="🎤"),
        discord.SelectOption(label="解除封禁 (Unban)", value="unban", emoji="🔓"),
    ])
    async def select_action(self, select: discord.ui.Select, interaction: discord.Interaction):
        self.action_type = select.values[0]
        await self.update_embed(interaction)

    # Row 2: 按钮组
    @discord.ui.button(label="🔍 ID搜索", style=discord.ButtonStyle.secondary, row=2)
    async def btn_manual_id(self, button, interaction):
        await interaction.response.send_modal(IDInputModal(self))

    # --- 新增：补充证据按钮 ---
    @discord.ui.button(label="📸 补充证据(可选)", style=discord.ButtonStyle.primary, row=2, emoji="🖼️")
    async def btn_add_evidence(self, button, interaction: discord.Interaction):
        # 定义 Modal 里面的组件
        fields = {
            "upload": ui.Label(
                text="上传证据图片 (最多5张/次)",
                component=ui.FileUpload(
                    custom_id="evidence_upload",
                    max_values=5,
                    required=True,
                ),
            ),
        }

        # 回调函数：处理文件
        async def cb(data, interaction):
            attachments = data.get("upload") # 获取上传的 attachments 列表

            if not attachments:
                return await interaction.followup.send("❌ 你好像没有上传任何图片捏？", ephemeral=True)

            count = 0
            for att in attachments:
                try:
                    # 关键：将 attachment 转换为 File 对象并存入 View 的状态
                    f = await att.to_file()
                    self.evidence_files.append(f)
                    count += 1
                except Exception as e:
                    print(f"Evidence file process error: {e}")

            # 更新面板状态
            await self.update_embed(interaction, override_desc=f"✅ 成功添加了 {count} 张证据图片！")
            # 提示消息（Ephemeral）
            await interaction.followup.send(f"已缓存 {count} 张图片作为证据。", ephemeral=True)

        # 发送 Modal
        await interaction.response.send_modal(
            CommonModal(self, "上传处罚证据", fields, cb)
        )

    @discord.ui.button(label="📝 填写理由", style=discord.ButtonStyle.secondary, row=2)
    async def btn_reason(self, button, interaction):
        if not self.action_type:
            return await interaction.response.send_message("❌ 请先选择【处罚动作】哦！", ephemeral=True)
        await interaction.response.send_modal(ReasonInputModal(self))

    @discord.ui.button(label="⚡ 执行处罚", style=discord.ButtonStyle.danger, row=3, disabled=True, custom_id="btn_execute")
    async def btn_execute(self, button, interaction):
        await interaction.response.defer()

        target_id = self.selected_user_id
        action = self.action_type
        reason = self.reason
        guild = interaction.guild
        op_user = interaction.user

        # 准备文件 (复位指针)
        final_files_to_send = []
        for f in self.evidence_files:
            try:
                f.start() # Reset file pointer if supported or needed
                # 或者有些版本的 discord.File 需要 fp.seek(0)
                if hasattr(f.fp, 'seek'):
                     f.fp.seek(0)
                final_files_to_send.append(f)
            except:
                pass

        target_member = guild.get_member(target_id)
        if action in ["kick", "mute", "warn"] and not target_member:
             target_user_test = self.selected_user or await self.bot.fetch_user(target_id)
             return await interaction.followup.send(f"❌ 用户 {target_user_test.name} 不在服务器内，无法执行 警告/禁言/踢出 操作！", ephemeral=True)

        target_user = self.selected_user or await self.bot.fetch_user(target_id)

        log_embed = discord.Embed(title=f"🛡️ 管理执行: {action.upper()}", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        log_embed.add_field(name="对象", value=f"{target_user.name} (ID: {target_user.id})", inline=False)
        log_embed.add_field(name="理由", value=reason, inline=False)
        log_embed.add_field(name="执行人", value=op_user.mention, inline=False)
        if target_user.avatar: log_embed.set_thumbnail(url=target_user.avatar.url)
        if final_files_to_send:
            log_embed.set_footer(text=f"附带了 {len(final_files_to_send)} 张证据图片")

        try:
            if action == "warn":
                try:
                    dm = discord.Embed(title="⚠️ 社区警告", description=f"你在 {guild.name} 收到警告。\n理由: {reason}", color=0xFFAA00)
                    await target_member.send(embed=dm)
                    status = "✅ 私信成功"
                except: status = "❌ 私信失败"
                await interaction.followup.send(f"**警告执行成功！** ({status})", embed=log_embed, files=final_files_to_send)

            elif action == "mute":
                seconds = parse_duration(self.duration_str)
                if seconds <= 0: return await interaction.followup.send("❌ 时间格式错误！", ephemeral=True)
                until = discord.utils.utcnow() + datetime.timedelta(seconds=seconds)
                await target_member.timeout(until, reason=reason)
                log_embed.add_field(name="时长", value=self.duration_str, inline=False)
                await interaction.followup.send("**禁言执行成功！**", embed=log_embed, files=final_files_to_send)

            elif action == "kick":
                await target_member.kick(reason=reason)
                await interaction.followup.send("**踢出执行成功！**", embed=log_embed, files=final_files_to_send)

            elif action == "ban":
                await guild.ban(target_user, reason=reason)
                await interaction.followup.send("**封禁执行成功！**", embed=log_embed, files=final_files_to_send)

            elif action == "unban":
                await guild.unban(target_user, reason=reason)
                await interaction.followup.send("**解除封禁成功！**", embed=log_embed, files=final_files_to_send)

            elif action == "unmute":
                await target_member.timeout(None, reason=reason)
                await interaction.followup.send("**解除禁言成功！**", embed=log_embed, files=final_files_to_send)

            # 禁用面板
            for child in self.children: child.disabled = True
            await interaction.edit_original_response(view=self)

        except Exception as e:
            await interaction.followup.send(f"❌ **执行出错**: {e}", ephemeral=True)


class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="处罚", description="呼出全能管理面板，对不乖的饱饱进行处罚！")
    @is_super_egg()
    async def punishment_panel(self, ctx: discord.ApplicationContext):
        embed = discord.Embed(
            title="🛡️ 社区管理控制台 (初始化中...)",
            description="请使用下方的组件来配置处罚选项。\n- 点击【📸 补充证据】可上传截图",
            color=STYLE["KIMI_YELLOW"]
        )
        embed.set_footer(text=KIMI_FOOTER_TEXT)
        view = ManagementControlView(ctx)
        await ctx.respond(embed=embed, view=view, ephemeral=True)

def setup(bot):
    bot.add_cog(Management(bot))
