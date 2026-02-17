#general/views.py

import discord
from discord import ui
import datetime
import asyncio
import random
from config import STYLE, SERVER_OWNER_ID, IDS
from .utils import TZ_CN, generate_progress_bar
from .storage import load_role_data, save_role_data, load_lottery_data, save_lottery_data

# ==================== 许愿池相关 ====================

class DetailedWishModal(discord.ui.Modal):
    def __init__(self, wish_type: str):
        title_str = f"📝 许愿: {wish_type}"
        if len(title_str) > 45: title_str = title_str[:42] + "..."
        super().__init__(title=title_str)
        self.wish_type = wish_type

        self.add_item(discord.ui.InputText(
            label=f"详细描述你的愿望/建议",
            placeholder=f"关于【{self.wish_type}】的想法...",
            style=discord.InputTextStyle.paragraph,
            min_length=5, max_length=2000, required=True
        ))
        self.add_item(discord.ui.InputText(
            label="是否匿名？(填 是/否)",
            placeholder="默认匿名。填“否”则公开许愿者身份。",
            style=discord.InputTextStyle.short, required=False, max_length=1
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        wish_content = self.children[0].value
        is_anonymous_raw = self.children[1].value.lower() if self.children[1].value else ""
        is_anonymous = not (is_anonymous_raw == '否' or is_anonymous_raw == 'n')

        try:
            owner = await interaction.client.fetch_user(SERVER_OWNER_ID)
        except:
            return await interaction.followup.send("找不到服主大人！", ephemeral=True)

        wish_id = random.randint(100000, 999999)
        safe_type = self.wish_type.replace(" ", "")

        try:
            thread = await interaction.channel.create_thread(
                name=f"💌-{safe_type}-{wish_id}",
                type=discord.ChannelType.private_thread,
                invitable=False
            )
            await thread.add_user(interaction.user)
            if owner: await thread.add_user(owner)

            embed = discord.Embed(
                title=f"💌 收到了一个新愿望！",
                description=f"**类型：** {self.wish_type}\n\n**内容：**\n```{wish_content}```",
                color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now()
            )
            embed.add_field(name="处理状态", value="⏳ 待受理", inline=False)
            if is_anonymous: embed.set_footer(text=f"来自一位匿名小饱饱")
            else: embed.set_author(name=f"来自 {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

            await thread.send(embed=embed, view=WishActionView())
            await interaction.followup.send(f"愿望已发送！快去 {thread.mention} 看看吧！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"创建帖子失败: {e}", ephemeral=True)

class WishActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == SERVER_OWNER_ID: return True
        await interaction.response.send_message("只有服主大人能操作哦！", ephemeral=True)
        return False

    async def update_status(self, interaction, status, close=False):
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="处理状态", value=status, inline=False)
        if close:
            for c in self.children: c.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        if close:
            await interaction.channel.send(f"标记为 **{status}**，10秒后锁定。")
            await asyncio.sleep(10)
            await interaction.channel.edit(archived=True, locked=True)

    @discord.ui.button(label="✅ 受理", style=discord.ButtonStyle.success, custom_id="wish_accept")
    async def accept(self, button, interaction): await self.update_status(interaction, "✅ 已受理")

    @discord.ui.button(label="🤔 暂不考虑", style=discord.ButtonStyle.secondary, custom_id="wish_reject")
    async def reject(self, button, interaction): await self.update_status(interaction, "🤔 暂不考虑", True)

    @discord.ui.button(label="🎉 已实现", style=discord.ButtonStyle.primary, custom_id="wish_done")
    async def done(self, button, interaction): await self.update_status(interaction, "🎉 已实现！", True)

class PresetFeatureView(discord.ui.View):
    def __init__(self): super().__init__(timeout=180)
    @discord.ui.button(label="🌌 极光", style=discord.ButtonStyle.primary)
    async def aurora(self, b, i): await i.response.send_modal(DetailedWishModal("预设功能-极光"))
    @discord.ui.button(label="🏛️ 象牙塔", style=discord.ButtonStyle.secondary)
    async def ivory(self, b, i): await i.response.send_modal(DetailedWishModal("预设功能-象牙塔"))

class WishSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="👇 选择愿望类型...", min_values=1, max_values=1, custom_id="wish_panel_select",
            options=[
                discord.SelectOption(label="预设新功能", emoji="💡", value="preset_feature"),
                discord.SelectOption(label="角色卡", emoji="🎭", value="角色卡"),
                discord.SelectOption(label="社区美化", emoji="🎨", value="社区美化"),
                discord.SelectOption(label="社区建设", emoji="🏗️", value="社区建设"),
                discord.SelectOption(label="其他", emoji="💭", value="其他"),
            ])
    async def callback(self, interaction):
        if self.values[0] == "preset_feature":
            await interaction.response.send_message("请选择功能：", view=PresetFeatureView(), ephemeral=True)
        else:
            await interaction.response.send_modal(DetailedWishModal(self.values[0]))

class WishPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WishSelect())

# ==================== 投票系统 ====================

class PollView(discord.ui.View):
    def __init__(self, question, options, end_time, creator_id):
        super().__init__(timeout=None)
        self.question = question
        self.options = options
        self.end_time = end_time
        self.creator_id = creator_id
        self.votes = {}
        for idx, opt in enumerate(options):
            b = discord.ui.Button(label=f"{idx+1}. {opt[:70]}", style=discord.ButtonStyle.secondary, custom_id=f"poll_{idx}")
            b.callback = self.create_callback(idx)
            self.add_item(b)

    def create_callback(self, idx):
        async def callback(interaction):
            if datetime.datetime.now(TZ_CN) > self.end_time:
                return await interaction.response.send_message("投票已截止！", ephemeral=True)
            uid = interaction.user.id
            if self.votes.get(uid) == idx:
                del self.votes[uid]
                msg = "🗑️ 取消投票。"
            else:
                self.votes[uid] = idx
                msg = f"✅ 投给了：{self.options[idx]}"
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            await interaction.followup.send(msg, ephemeral=True)
        return callback

    def build_embed(self, is_ended=False):
        total = len(self.votes)
        counts = [0] * len(self.options)
        for idx in self.votes.values(): counts[idx] += 1
        desc = ""
        for i, opt in enumerate(self.options):
            pct = (counts[i]/total*100) if total else 0
            desc += f"**{i+1}. {opt}**\n`{generate_progress_bar(pct)}` **{pct:.1f}%** ({counts[i]}票)\n\n"

        color = 0x99AAB5 if is_ended else STYLE["KIMI_YELLOW"]
        embed = discord.Embed(title=f"📊 {self.question}", description=desc, color=color)
        embed.set_author(name=f"发起人ID: {self.creator_id}")
        footer = f"已截止 | 总票数: {total}" if is_ended else f"截止: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')} (CN)"
        embed.set_footer(text=footer)
        return embed

# ==================== 公告系统 ====================

class AnnouncementModal(discord.ui.Modal):
    def __init__(self, channel, mention_role, attachments):
        super().__init__(title="公告编辑器")
        self.channel = channel
        self.mention_role = mention_role
        self.attachments = attachments
        self.add_item(discord.ui.InputText(label="内容", style=discord.InputTextStyle.paragraph, placeholder="在此输入...", required=True))

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        content = self.children[0].value
        outside = ""
        allowed = discord.AllowedMentions.none()

        if self.mention_role:
            if self.mention_role.id == interaction.guild.id:
                outside = "@everyone"
                allowed = discord.AllowedMentions(everyone=True)
            elif "here" in self.mention_role.name:
                outside = "@here"
                allowed = discord.AllowedMentions(everyone=True)
            else:
                outside = self.mention_role.mention
                allowed = discord.AllowedMentions(roles=[self.mention_role])

        embed = discord.Embed(title="📣 公告", description=content, color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.set_author(name=f"发布者: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        files = [await a.to_file() for a in self.attachments]
        if self.attachments: embed.set_image(url=f"attachment://{self.attachments[0].filename}")

        try:
            await self.channel.send(content=outside, embed=embed, files=files, allowed_mentions=allowed)
            await interaction.followup.send("发送成功！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"失败: {e}", ephemeral=True)

# ==================== 1. 身份组领取中心 ====================

# --- 用户端视图 Step 2 : 私密选择面板 ---

class RoleClaimSelect(discord.ui.Select):
    """
    具体的身份组选择下拉框 (放在私密面板中)
    """
    def __init__(self, guild_roles):
        options = []
        # 按名称排序
        sorted_roles = sorted(guild_roles, key=lambda r: r.name)

        for role in sorted_roles:
            emoji = "🎨"
            if "色" in role.name or "color" in role.name.lower(): emoji = "🌈"
            elif "男" in role.name or "女" in role.name: emoji = "🚻"
            elif "通知" in role.name or "Notify" in role.name: emoji = "🔕"

            options.append(discord.SelectOption(
                label=role.name,
                value=str(role.id),
                emoji=emoji,
                description=f"ID: {role.id}"
            ))

        super().__init__(
            placeholder="👇点击选择你要更换的装饰...",
            min_values=1,
            max_values=1,
            options=options[:25], # discord限制25个
            custom_id="role_claim_select_inner"
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 允许所有用户交互（这个下拉框是通过start_decor_callback发送的私密消息）
        return True

    async def callback(self, interaction: discord.Interaction):
        # 保持之前的逻辑不变
        await interaction.response.defer(ephemeral=True)

        try:
            role_id = int(self.values[0])
            target_role = interaction.guild.get_role(role_id)
        except:
             return await interaction.followup.send("呜...数据出错了，请重新打开面板试试！", ephemeral=True)

        if not target_role:
            return await interaction.followup.send("呜...这个装饰好像已经下架了！", ephemeral=True)

        # 互斥逻辑
        prefix = target_role.name.split("·")[0] if "·" in target_role.name else None

        data = load_role_data()
        claimable_ids = data.get("claimable_roles", [])
        user = interaction.user
        to_remove = []

        if prefix:
            for r in user.roles:
                if r.id in claimable_ids and r.id != target_role.id:
                    r_prefix = r.name.split("·")[0] if "·" in r.name else None
                    if r_prefix == prefix:
                        to_remove.append(r)

        try:
            msg = ""
            if to_remove:
                await user.remove_roles(*to_remove, reason="装饰更换-互斥移除")
                removed_names = ", ".join([r.name for r in to_remove])
                msg += f"♻️ 已自动收纳旧装饰：{removed_names}\n"

            if target_role not in user.roles:
                await user.add_roles(target_role, reason="装饰佩戴")
                msg += f"✅ **穿戴成功！**\n✨ 你现在拥有了 **{target_role.name}** 身份。"
            else:
                await user.remove_roles(target_role, reason="装饰主动卸下")
                msg += f"❎ **卸下成功！**\n🍃 你放下了 **{target_role.name}** 身份。"

            # 操作完成后，最好给个反馈告诉用户现在状态
            await interaction.followup.send(msg, ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("💥 哎呀！本大王的权限好像不够高，帮不了你换衣服... (请检查Bot身份组位置)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"😵 错误: {e}", ephemeral=True)

class RoleSelectionView(discord.ui.View):
    """
    点开【开始装饰】后看到的私密视图
    """
    def __init__(self, guild_roles):
        super().__init__(timeout=None) # 改为None：持久化监听，即使bot重启也能交互
        if guild_roles:
            self.add_item(RoleClaimSelect(guild_roles[:25]))
        else:
            self.add_item(discord.ui.Button(label="暂无可用装饰", disabled=True))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 允许此视图中的所有组件交互
        return True

# --- 用户端视图 Step 1 : 公开主面板入口 ---

class RoleClaimView(discord.ui.View):
    """
    放在公共频道的入口面板，只有按钮
    """
    def __init__(self):
        super().__init__(timeout=None) # 持久化监听

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 允许所有用户与这个公共面板交互
        return True

    @discord.ui.button(label="🎨 开始装饰", style=discord.ButtonStyle.success, custom_id="role_main_start")
    async def start_decor_callback(self, button, interaction: discord.Interaction):
        # 1. 动态获取当前配置的有效身份组
        data = load_role_data()
        valid_roles = []
        claimable_ids = data.get("claimable_roles", [])

        for rid in claimable_ids:
            r = interaction.guild.get_role(rid)
            if r:
                valid_roles.append(r)

        if not valid_roles:
            return await interaction.response.send_message("⚠️ 现在好像还没有上架任何装饰品呢！", ephemeral=True)

        # 2. 检查用户当前穿了哪些
        user_current_decor = []
        for r in interaction.user.roles:
            if r.id in claimable_ids:
                user_current_decor.append(r.name)

        status_text = "你目前还没有佩戴任何装饰哦。"
        if user_current_decor:
            status_text = f"你当前佩戴的装饰：\n👉 **{' | '.join(user_current_decor)}**"

        # 3. 发送私密选择面板
        embed = discord.Embed(
            title="👗 个人试衣间",
            description=f"{status_text}\n\n请在下方菜单中选择你喜欢的装饰进行穿戴或切换：",
            color=0xFFB6C1
        )
        await interaction.response.send_message(embed=embed, view=RoleSelectionView(valid_roles), ephemeral=True)

    @discord.ui.button(label="🧹 一键移除", style=discord.ButtonStyle.danger, custom_id="role_main_remove_all")
    async def remove_all_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data = load_role_data()
        claimable_ids = data.get("claimable_roles", [])
        user = interaction.user

        to_remove = []
        for r in user.roles:
            if r.id in claimable_ids:
                to_remove.append(r)

        if not to_remove:
            return await interaction.followup.send("❔ 你身上好像没有属于这里的装饰品哦，不需要清理。", ephemeral=True)

        try:
            await user.remove_roles(*to_remove, reason="用户一键移除所有装饰")
            await interaction.followup.send(f"🧹 呼~ 已帮你清除了 **{len(to_remove)}** 个装饰身份组，现在一身轻啦！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 移除失败: {e}", ephemeral=True)

# --- 管理端视图 : 管理台 ---
class AdminAddRoleSelect(discord.ui.Select):
    def __init__(self, parent_view):
        super().__init__(
            placeholder="➕ 点击这里添加新的身份组...",
            min_values=1,
            max_values=1,
            row=1,
            select_type=discord.ComponentType.role_select 
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        selected_roles = interaction.data.get('values', [])
        if not selected_roles: return
        
        role_id = int(selected_roles[0])
        role = interaction.guild.get_role(role_id)

        if not role: 
            return await interaction.response.send_message("❌ 无法解析选中的身份组！", ephemeral=True)
        
        data = load_role_data()
        
        # 逻辑检查
        if role.id in data["claimable_roles"]: 
            return await interaction.response.send_message(f"⚠️ **{role.name}** 已经在列表里啦！", ephemeral=True)
        
        if role.permissions.administrator or role.permissions.manage_guild: 
            return await interaction.response.send_message(f"🚫 达咩！**{role.name}** 权限太高了！", ephemeral=True)
            
        data["claimable_roles"].append(role.id)
        save_role_data(data)
        
        # 刷新父视图
        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send(f"✅ 成功上架：**{role.name}**", ephemeral=True)


class AdminRemoveRoleSelect(discord.ui.Select):
    def __init__(self, current_roles, parent_view):
        options = []
        for r in current_roles:
            options.append(discord.SelectOption(label=r.name, value=str(r.id), emoji="🗑️"))
        if not options:
            options.append(discord.SelectOption(label="暂无身份组", value="none", description="列表是空的"))
        
        super().__init__(
            placeholder="➖ 选择要移除（下架）的身份组...", 
            min_values=1, 
            max_values=1, 
            options=options[:25], 
            row=2, 
            disabled=(len(current_roles) == 0)
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        if self.values[0] == "none": return await interaction.response.send_message("这里没什么可删的捏。", ephemeral=True)
        role_id = int(self.values[0])
        data = load_role_data()
        if role_id in data["claimable_roles"]:
            data["claimable_roles"].remove(role_id)
            save_role_data(data)
            await self.parent_view.refresh_content(interaction)
            await interaction.followup.send("🗑️ 已下架该身份组。", ephemeral=True)
        else:
            await interaction.response.send_message("数据不同步，请刷新后再试。", ephemeral=True)

async def deploy_role_panel(channel, guild, user_avatar_url):
    """
    统一的面板部署逻辑
    """
    # 1. 准备数据和 Embed
    data = load_role_data()
    active_roles = []
    claimable_ids = data.get("claimable_roles", [])

    for rid in claimable_ids:
        r = guild.get_role(rid)
        if r: active_roles.append(r)

    if active_roles:
        role_lines = [f"> {role.mention}" for role in active_roles]
        role_list_str = "\n".join(role_lines)
    else:
        role_list_str = "> *暂无上架装饰*"

    embed = discord.Embed(
        title="🎨 **百变小蛋 · 装饰身份组中心**",
        description="欢迎来到装饰中心！在这里你可以自由装扮你的个人资料卡。\n\n"
                    "✨ **功能介绍**：\n"
                    "🔸 **开始装饰**：打开私密衣柜，查看并更换你的装饰。\n"
                    "🔸 **一键移除**：一键卸下所有在此处领取的装饰，恢复素颜。\n"
                    "🔸 **自动替换**：选择同系列新款式会自动替换旧的哦！\n\n"
                    "📜 **当前上架款式一览**：\n"
                    f"{role_list_str}",
        color=STYLE["KIMI_YELLOW"]
    )

    # 这里的 user_avatar_url 现在也能正确接收到字符串了
    if user_avatar_url:
        embed.set_thumbnail(url=user_avatar_url)

    embed.set_footer(text="点击下方按钮即可体验 👇")
    view = RoleClaimView()

    # 2. 检查是否需要更新
    panel_info = data.get("panel_info", {})
    last_channel_id = panel_info.get("channel_id")
    last_message_id = panel_info.get("message_id")

    message = None

    # 只有当目标频道和记录的频道一致时，才尝试编辑
    if last_channel_id == channel.id and last_message_id:
        try:
            message = await channel.fetch_message(last_message_id)
            await message.edit(embed=embed, view=view)
            return "updated"
        except (discord.NotFound, discord.Forbidden):
            message = None

    # 3. 发送新消息
    if not message:
        message = await channel.send(embed=embed, view=view)

        # 4. 保存新的消息ID到数据库
        data["panel_info"] = {
            "channel_id": channel.id,
            "message_id": message.id
        }
        save_role_data(data)
        return "sent"

# 3. 修复 RoleManagerView
class RoleManagerView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.guild = ctx.guild if ctx else None
        if self.guild:
            self.setup_ui()

    def get_current_roles(self):
        data = load_role_data()
        roles = []
        cleanup_needed = False
        new_list = []
        for rid in data["claimable_roles"]:
            r = self.guild.get_role(rid)
            if r:
                roles.append(r)
                new_list.append(rid)
            else:
                cleanup_needed = True
        if cleanup_needed:
            data["claimable_roles"] = new_list
            save_role_data(data)
        return roles

    def setup_ui(self, current_roles=None):
        self.clear_items()
        if current_roles is None: current_roles = self.get_current_roles()
        self.add_item(AdminAddRoleSelect(self))
        self.add_item(AdminRemoveRoleSelect(current_roles, self))
        
        # 4. 手动添加按钮 (Row 3)
        ref_btn = discord.ui.Button(label="🔄 刷新列表", style=discord.ButtonStyle.secondary, row=3)
        ref_btn.callback = self.refresh_callback
        self.add_item(ref_btn)
        
        snd_btn = discord.ui.Button(label="📤 发送面板到频道", style=discord.ButtonStyle.primary, row=3, emoji="📨")
        snd_btn.callback = self.send_panel_callback
        self.add_item(snd_btn)
    
    async def refresh_callback(self, interaction): 
        await self.refresh_content(interaction)

    async def send_panel_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        try:
            avatar_url = interaction.guild.me.display_avatar.url if interaction.guild.me else None
            
            # 调用我们定义的通用函数
            status = await deploy_role_panel(interaction.channel, interaction.guild, avatar_url)
            
            if status == "updated":
                await interaction.followup.send("🔄 面板已就地 **更新** 为最新状态！", ephemeral=True)
            else:
                await interaction.followup.send("📤 面板已 **发送** 到当前频道！", ephemeral=True)
                
        except Exception as e:
            await interaction.followup.send(f"❌ 发送失败: {e}", ephemeral=True)

    async def refresh_content(self, interaction):
        self.setup_ui()
        roles = self.get_current_roles() # 为了下面构建 Embed 描述

        embed = discord.Embed(title="⚙️ 身份组池管理控制台", color=discord.Color.blue())
        desc = "**当前已上架的身份组：**\n" + ("\n".join([f"• {r.mention} (ID: {r.id})" for r in roles]) if roles else "*(空空如也)*")
        desc += "\n\n**操作说明：**\n➕ 使用第一行菜单添加新身份组\n➖ 使用第二行菜单移除已有身份组"
        embed.description = desc
        
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

# ==================== 2. 抽奖功能 (New) ====================

class LotteryCreateModal(discord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="🎁 发起抽奖")
        self.cog = cog

        # 1. 奖品名称
        self.add_item(discord.ui.InputText(
            label="奖品名称",
            placeholder="例如: 1个月Nitro",
            max_length=100
        ))
        # 2. 奖品提供者 (新)
        self.add_item(discord.ui.InputText(
            label="奖品提供者 (选填)",
            placeholder="例如: 芝士喵喵 / @某人 (留空默认为官方)",
            max_length=50,
            required=False
        ))
        # 3. 描述
        self.add_item(discord.ui.InputText(
            label="抽奖文案/描述",
            placeholder="庆祝新功能上线！大家快来...",
            style=discord.InputTextStyle.paragraph
        ))
        # 4. 人数
        self.add_item(discord.ui.InputText(
            label="中奖人数 (数字)",
            placeholder="例如: 1",
            max_length=5
        ))
        # 5. 时间
        self.add_item(discord.ui.InputText(
            label="持续时间",
            placeholder="例如: 10m, 2h, 1d",
            max_length=10
        ))

    async def callback(self, interaction):
        prize = self.children[0].value
        provider_raw = self.children[1].value
        provider = provider_raw if provider_raw and provider_raw.strip() else "奇米大王官方"
        desc = self.children[2].value

        try:
            winners = int(self.children[3].value)
            duration_str = self.children[4].value
            from .utils import parse_duration
            seconds = parse_duration(duration_str)
            if seconds < 60: raise ValueError("时间太短")
        except:
            return await interaction.response.send_message("❌ 人数必须是数字，时间格式如 10m, 1h，且至少1分钟！", ephemeral=True)

        await interaction.response.defer(ephemeral=False)

        # 计算结束时间
        now = datetime.datetime.now(TZ_CN)
        end_time = now + datetime.timedelta(seconds=seconds)
        end_timestamp = end_time.timestamp()

        # === 构建美化版的 Embed ===
        # 标题带上状态
        embed = discord.Embed(title=f"🎆 [进行中] {prize}", color=STYLE["KIMI_YELLOW"])

        # 构造正文内容
        content_lines = []
        content_lines.append(f"**🎁 奖品** : {prize}")
        content_lines.append(f"**💖 提供者** : {provider}")
        content_lines.append("") # 空行
        content_lines.append(f"{desc}") # 描述
        content_lines.append("") # 空行
        content_lines.append(f"🏆 将抽取 **{winners}** 位幸运饱饱，中奖后请留意私信！")
        content_lines.append("")
        content_lines.append("⬇️ ⬇️ **点击下方按钮即可参与** ⬇️ ⬇️")

        embed.description = "\n".join(content_lines)

        # 底部状态栏
        embed.set_footer(text=f"正在进行 • 0 人已参与 | 结束时间")
        embed.timestamp = end_time # 使用 timestamp 显示本地化时间

        msg = await interaction.followup.send(embed=embed, view=LotteryJoinView(prize))

        # 存入数据
        data = load_lottery_data()
        data["active_lotteries"][str(msg.id)] = {
            "channel_id": interaction.channel_id,
            "prize": prize,
            "provider": provider, # 存入提供者
            "text": desc,
            "winners": winners,
            "end_timestamp": end_timestamp,
            "participants": []
        }
        save_lottery_data(data)

        # 启动计时任务
        self.cog.bot.loop.create_task(self.cog.lottery_timer(msg.id, seconds))


class LotteryJoinView(discord.ui.View):
    def __init__(self, prize_name):
        super().__init__(timeout=None)
        # 按钮样式调整
        btn = discord.ui.Button(
            label="🎉 立即参与抽奖",
            style=discord.ButtonStyle.primary, # 蓝色按钮比较显眼
            custom_id="lottery_join_btn",
            emoji="🎁"
        )
        self.add_item(btn)

    async def interaction_check(self, interaction):
        if interaction.data["custom_id"] == "lottery_join_btn":
            await self.join_lottery(interaction)
            return False
        return True

    async def join_lottery(self, interaction):
        msg_id = str(interaction.message.id)
        data = load_lottery_data()

        if msg_id not in data["active_lotteries"]:
            return await interaction.response.send_message("这个抽奖已经失效或结束惹！", ephemeral=True)

        uid = interaction.user.id
        participants = data["active_lotteries"][msg_id]["participants"]

        if uid in participants:
            return await interaction.response.send_message("你已经参与过啦！乖乖等待开奖吧~", ephemeral=True)

        participants.append(uid)
        save_lottery_data(data)

        # 实时更新 Footer 人数
        embed = interaction.message.embeds[0]
        # 保持原本的文字前缀，只改人数
        # 此时 title 应该是 [进行中]
        embed.set_footer(text=f"正在进行 • {len(participants)} 人已参与 | 结束时间")
        await interaction.message.edit(embed=embed)

        await interaction.response.send_message("🎉 参与成功！祝你好运哦！", ephemeral=True)
