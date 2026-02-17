#general/views.py

import discord
from discord import ui
import datetime
import asyncio
import random
from config import STYLE, SERVER_OWNER_ID, IDS, LOTTERY_COST, LOTTERY_REFUND
from .utils import TZ_CN, generate_progress_bar
from .storage import load_role_data, save_role_data, load_lottery_data, save_lottery_data, modify_user_points, get_user_points
from discord.ui import View, Button, Select, Modal, InputText

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

# ==================== 身份组中心  ====================
# ==================== 3. 通知订阅系统 (新增) ====================

class NotificationSelect(discord.ui.Select):
    """
    用户侧：通知身份组多选菜单
    """
    def __init__(self, user, guild, notify_role_ids):
        self.user = user
        self.guild = guild
        self.notify_role_ids = notify_role_ids

        options = []
        default_values = []

        # 遍历配置的通知身份组，构建选项
        for rid in notify_role_ids:
            role = guild.get_role(rid)
            if not role: continue

            is_owned = role in user.roles

            # 构建选项
            options.append(discord.SelectOption(
                label=role.name,
                value=str(role.id),
                emoji="🔔" if not is_owned else "🔕", # 视觉提示
                description="点击选中以订阅，取消选中以移除",
                default=is_owned # 如果用户已有该身份组，默认选中
            ))

            if is_owned:
                default_values.append(str(role.id))

        # Discord 限制 max_values 不能超过选项总数
        max_val = len(options) if options else 1

        super().__init__(
            placeholder="👇 在此勾选你需要订阅的消息类型...",
            min_values=0, # 允许全都不选（即取消所有订阅）
            max_values=max_val,
            options=options if options else [discord.SelectOption(label="暂无通知订阅", value="none")],
            disabled=len(options) == 0,
            custom_id="notify_select_menu"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        selected_ids = set(int(v) for v in self.values)
        all_config_ids = set(self.notify_role_ids)

        added = []
        removed = []

        # 批量处理逻辑
        for rid in all_config_ids:
            role = self.guild.get_role(rid)
            if not role: continue

            # 如果在选中列表中，也就是用户想要这个身份组
            if rid in selected_ids:
                if role not in self.user.roles:
                    await self.user.add_roles(role, reason="通知订阅面板：主动订阅")
                    added.append(role.name)

            # 如果不在选中列表中，也就是用户取消了选择
            else:
                if role in self.user.roles:
                    await self.user.remove_roles(role, reason="通知订阅面板：取消订阅")
                    removed.append(role.name)

        msg_parts = []
        if added: msg_parts.append(f"✅ **订阅了**: {', '.join(added)}")
        if removed: msg_parts.append(f"🔕 **取消了**: {', '.join(removed)}")

        final_msg = "\n".join(msg_parts) if msg_parts else "🤷 你的订阅状态没有变化。"

        await interaction.followup.send(final_msg, ephemeral=True)

class NotificationControlView(discord.ui.View):
    """
    用户侧：点击入口按钮后看到的私密视图
    """
    def __init__(self, user, guild):
        super().__init__(timeout=None)
        data = load_role_data()
        notify_ids = data.get("notification_roles", []) # 获取通知身份组列表

        if notify_ids:
            self.add_item(NotificationSelect(user, guild, notify_ids))
        else:
            self.add_item(discord.ui.Button(label="暂无可用订阅", disabled=True))

class NotificationEntranceView(discord.ui.View):
    """
    用户侧：公共频道的入口按钮
    """
    def __init__(self):
        super().__init__(timeout=None) # 持久化

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    @discord.ui.button(label="🔔 管理我的通知订阅", style=discord.ButtonStyle.primary, custom_id="notify_entrance_btn")
    async def open_settings(self, button, interaction: discord.Interaction):
        # 打开私密的多选面板
        await interaction.response.send_message(
            "👇 **请在下方菜单中勾选你感兴趣的内容：**\n(保持选中代表订阅，取消选中代表退订)",
            view=NotificationControlView(interaction.user, interaction.guild),
            ephemeral=True
        )

async def remove_all_decorations(user, guild, keep_role_id=None, role_type="lottery"):
    """
    移除用户身上指定类型的互斥身份组。
    role_type="lottery": 只清理抽奖池的旧身份组。
    role_type="claimable": 只清理自选池的旧身份组。
    """
    data = load_role_data()

    # 🌟 Nova的修正：不再混合两个池子，而是根据类型选择目标池
    if role_type == "lottery":
        target_ids = set(data.get("lottery_roles", []))
    elif role_type == "claimable":
        target_ids = set(data.get("claimable_roles", []))
    else:
        # 如果未指定类型，或者是混合清理模式（备用），则两个都包含
        target_ids = set(data.get("claimable_roles", []) + data.get("lottery_roles", []))

    to_remove = []
    for role in user.roles:
        if role.id in target_ids:
            # 如果是当前抽到/选中的那个，保留它
            if keep_role_id and role.id == keep_role_id:
                continue
            to_remove.append(role)

    if to_remove:
        try:
            await user.remove_roles(*to_remove, reason=f"Nova Protocol: {role_type} replace")
        except Exception:
            pass # 忽略权限错误，防止打断流程

    return to_remove

# --- 抽奖界面 ---

class RoleLotteryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎲 试试手气", style=discord.ButtonStyle.primary, emoji="🎰", custom_id="lottery_draw_btn")
    async def draw_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user

        # 1. 检查积分
        current_points = get_user_points(user.id)
        if current_points < LOTTERY_COST:
            return await interaction.followup.send(
                f"💸 **积分不足！**\n你需要 **{LOTTERY_COST}** 积分才能抽奖，当前只有 **{current_points}**。\n快去社区里找小伙伴聊天吧！(拒绝水贴哦)",
                ephemeral=True
            )

        # 2. 检查奖池
        data = load_role_data()
        pool_ids = data.get("lottery_roles", [])
        if not pool_ids:
            return await interaction.followup.send("🏜️ 奖池目前是空的，请联系管理员进货！", ephemeral=True)

        valid_pool = []
        for rid in pool_ids:
            r = interaction.guild.get_role(rid)
            if r: valid_pool.append(r)

        if not valid_pool:
           return await interaction.followup.send("⚠️ 奖池里的身份组好像失效了，请联系管理员。", ephemeral=True)

        # 3. 扣费并抽奖
        modify_user_points(user.id, -LOTTERY_COST)
        left_points = current_points - LOTTERY_COST

        won_role = random.choice(valid_pool)

        # 4. 结果判定的 Embed
        embed = discord.Embed(title="🎰 命运之轮转动了...", color=discord.Color.gold())

        # 情况A: 已经有了这个身份组 -> 退款
        if won_role in user.roles:
            modify_user_points(user.id, LOTTERY_REFUND)
            final_points = left_points + LOTTERY_REFUND

            embed.description = f"你抽到了 **{won_role.name}**！\n\n🤔 **但是...** 你好像已经拥有它了。\n\n💰 **退还积分**: {LOTTERY_REFUND}\n💳 **当前余额**: {final_points}"
            embed.color = discord.Color.light_grey()
            await interaction.followup.send(embed=embed, ephemeral=True)

        # 情况B: 中奖 -> 穿戴 (互斥移除其他的)
        else:
            try:
                # 🌟 Nova的修正：调用函数时指定 role_type="lottery"
                # 这样它只会移除旧的【抽奖身份组】，不会动用户的【自选身份组】
                removed = await remove_all_decorations(
                    user,
                    interaction.guild,
                    keep_role_id=won_role.id,
                    role_type="lottery"
                )

                await user.add_roles(won_role, reason="积分抽奖获取")

                desc = f"🎉 **恭喜！！欧气爆发！**\n\n你获得了稀有装饰：**{won_role.mention}**"
                if removed:
                    desc += f"\n\n♻️ 已自动换下同类旧装饰：{', '.join([r.name for r in removed])}"

                desc += f"\n\n💳 **扣除积分**: {LOTTERY_COST}\n💰 **当前余额**: {left_points}"

                embed.description = desc
                # 可以加个图片增加氛围
                embed.set_thumbnail(url="https://media.giphy.com/media/26tOZ42Mg6pbTUPVS/giphy.gif")
                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                # 出错退款
                modify_user_points(user.id, LOTTERY_COST)
                await interaction.followup.send(f"❌ 佩戴失败 (积分已退还): {e}", ephemeral=True)

    @discord.ui.button(label="📜 查看积分", style=discord.ButtonStyle.secondary, emoji="👛", custom_id="lottery_check_points")
    async def check_points(self, button, interaction: discord.Interaction):
        p = get_user_points(interaction.user.id)
        await interaction.response.send_message(f"💰 你当前的社区活跃积分是：**{p}**", ephemeral=True)

    @discord.ui.button(label="📊 奖池图鉴", style=discord.ButtonStyle.success, emoji="🌌", custom_id="lottery_collection_view")
    async def collection_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data = load_role_data()
        pool_ids = data.get("lottery_roles", []) # 获取所有抽奖身份组ID

        if not pool_ids:
            return await interaction.followup.send("🌑 这片星域空空如也（奖池未配置）。", ephemeral=True)

        guild = interaction.guild
        user_roles_ids = set(r.id for r in interaction.user.roles)

        # 1. 梳理奖池状态
        valid_roles_in_pool = [] # 服务器里还存在的有效身份组
        owned_lottery_role = None # 用户当前佩戴的那个

        for rid in pool_ids:
            role = guild.get_role(rid)
            if role:
                valid_roles_in_pool.append(role)
                if rid in user_roles_ids:
                    owned_lottery_role = role

        total_count = len(valid_roles_in_pool)

        # 2. 构建图鉴描述
        # 既然是互斥的（只能穿一件），“收集进度”更多是“图鉴概览”
        if total_count == 0:
             return await interaction.followup.send("⚠️ 奖池里的身份组似乎都已失效。", ephemeral=True)

        embed = discord.Embed(title="🌌 命运星图 (Lottery Collection)", color=0x9b59b6)
        embed.description = f"这里记录着所有可能降临的命运。\n(规则：每次只能点亮一颗星辰，获取新星将通过互斥替换旧星)"

        # 显示当前拥有
        if owned_lottery_role:
            status_text = f"✅ **当前佩戴**: {owned_lottery_role.mention}"
        else:
            status_text = "⚪ **当前状态**: 未拥有任何抽奖身份组"

        embed.add_field(name="我的星轨", value=status_text, inline=False)

        # 列出所有奖池内容
        # 如果奖池太大，可能需要分页或简化显示，这里假设数量适中
        pool_desc_list = []
        for r in valid_roles_in_pool:
            if owned_lottery_role and r.id == owned_lottery_role.id:
                pool_desc_list.append(f"🌟 **{r.name}** (已拥有)")
            else:
                pool_desc_list.append(f"🔹 {r.name}")

        # 将列表连接成字符串
        pool_text = "\n".join(pool_desc_list)

        # 防止超出Discord字符限制
        if len(pool_text) > 1000:
            pool_text = pool_text[:950] + "\n... (更多星辰隐藏于深空)"

        embed.add_field(name=f"🏆 完整奖池 ({total_count}种)", value=pool_text, inline=False)
        embed.set_footer(text="愿命运女神眷顾你的每一次投掷。")

        await interaction.followup.send(embed=embed, ephemeral=True)

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
        return True

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            role_id = int(self.values[0])
            target_role = interaction.guild.get_role(role_id)
        except: return await interaction.followup.send("数据错误", ephemeral=True)

        if not target_role: return await interaction.followup.send("装饰已下架", ephemeral=True)

        # === 修改处：使用全局互斥移除 ===
        if target_role not in interaction.user.roles:
            try:
                # 移除所有其他的(包含抽奖的和普通领取的)
                removed = await remove_all_decorations(interaction.user, interaction.guild, keep_role_id=target_role.id)
                await interaction.user.add_roles(target_role, reason="面板自助领取")

                msg = f"✅ **穿戴成功！**\n✨ 你现在拥有了 **{target_role.name}**。"
                if removed:
                    msg += f"\n♻️ 已自动收纳旧装饰：{', '.join([r.name for r in removed])}"
                await interaction.followup.send(msg, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ 权限不足或错误: {e}", ephemeral=True)
        else:
            # 卸下
            await interaction.user.remove_roles(target_role, reason="主动卸下")
            await interaction.followup.send(f"❎ **卸下成功！**", ephemeral=True)

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

    @discord.ui.button(label="🎨 领取/更换", style=discord.ButtonStyle.success, custom_id="role_main_start")
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
    
    @discord.ui.button(label="🎲 积分抽奖", style=discord.ButtonStyle.primary, custom_id="role_main_lottery")
    async def lottery_entry_callback(self, button, interaction: discord.Interaction):
        points = get_user_points(interaction.user.id)
        embed = discord.Embed(
            title="🌌 **星之运势 · 身份组抽奖**",
            description=f"这里藏着一些无法直接领取的 **稀有款式**！\n你会是那个被命运选中的孩子吗？\n\n"
                        f"💳 **单次消耗**: {LOTTERY_COST} 积分\n"
                        f"🔄 **重复补偿**: 返还 {LOTTERY_REFUND} 积分\n"
                        f"💰 **你的积蓄**: **{points}**\n\n"
                        f"*注：抽到的稀有装饰也会替换掉当前的普通装饰哦，毕竟荣耀是唯一的。*",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=RoleLotteryView(), ephemeral=True)

    @discord.ui.button(label="🧹 一键移除", style=discord.ButtonStyle.danger, custom_id="role_main_remove_all")
    async def remove_all_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # 调用我们的全局移除函数
        removed = await remove_all_decorations(interaction.user, interaction.guild)
        if removed:
            await interaction.followup.send(f"🧹 已清空身上的 {len(removed)} 个装饰！", ephemeral=True)
        else:
            await interaction.followup.send("❔ 你身上本来就很干净哦。", ephemeral=True)

# --- 管理端视图 : 管理台 ---
class AdminAddRoleSelect(discord.ui.Select):
    def __init__(self, parent_view, pool_type="claimable"):
        # pool_type: "claimable" (普通), "lottery" (抽奖), "notification" (通知)
        self.pool_type = pool_type

        map_titles = {
            "claimable": "➕ 添加到【普通池】...",
            "lottery": "➕ 添加到【奖池】...",
            "notification": "➕ 添加到【通知订阅】..."
        }

        row_map = {
            "lottery": 0,
            "claimable": 1,
            "notification": 2
        }

        super().__init__(
            placeholder=map_titles.get(pool_type, "选择身份组..."),
            min_values=1, max_values=1,
            row=row_map.get(pool_type, 0),
            select_type=discord.ComponentType.role_select
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        role_id = int(interaction.data['values'][0])
        role = interaction.guild.get_role(role_id)
        if not role: return

        data = load_role_data()

        # 映射 key
        key_map = {
            "claimable": "claimable_roles",
            "lottery": "lottery_roles",
            "notification": "notification_roles"
        }
        target_list_key = key_map.get(self.pool_type)
        if not target_list_key: return

        # 确保数据结构存在
        if target_list_key not in data: data[target_list_key] = []

        # 检查逻辑：全池查重
        all_lists = ["claimable_roles", "lottery_roles", "notification_roles"]
        for k in all_lists:
            if role.id in data.get(k, []):
                return await interaction.response.send_message(f"⚠️ 该身份组已存在于【{k}】中，请先移除！", ephemeral=True)

        data[target_list_key].append(role.id)
        save_role_data(data)
        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send(f"✅ 添加成功 ({self.pool_type})：{role.name}", ephemeral=True)

class AdminRemoveSelect(Select):
    def __init__(self, role_datas, view_parent):
        self.view_parent = view_parent
        if isinstance(role_datas, list):
            role_datas = {r: "unknown" for r in role_datas}

        options = []
        for role, r_type in role_datas.items():
            if not isinstance(role, discord.Role): continue

            # 图标区分
            emoji_map = {"lottery": "🎟️", "claimable": "🎨", "notification": "🔔"}
            emoji = emoji_map.get(r_type, "❓")

            desc = f"ID: {role.id} | 类型: {r_type}"

            options.append(discord.SelectOption(
                label=role.name,
                value=str(role.id),
                description=desc,
                emoji=emoji
            ))

        if not options:
            options.append(discord.SelectOption(label="暂无身份组", value="none", description="列表中空空如也"))
            disabled = True
        else:
            disabled = False

        super().__init__(
            placeholder="➖ 选择要移除的身份组...",
            min_values=1, max_values=1, options=options, custom_id="admin_remove_select",
            disabled=disabled, row=3
        )

    async def callback(self, interaction: discord.Interaction):
        role_id = self.values[0]
        if role_id == "none":
            return await interaction.response.send_message("这里什么也没有。", ephemeral=True)

        data = load_role_data()
        target_rid = int(role_id)
        removed = False

        # 遍历所有可能的列表进行删除
        keys = ["claimable_roles", "lottery_roles", "notification_roles"]
        for k in keys:
            if target_rid in data.get(k, []):
                data[k].remove(target_rid)
                removed = True

        if removed:
            save_role_data(data)
            await interaction.response.send_message(f"🗑️ 已移除身份组配置", ephemeral=True)
            await self.view_parent.refresh_content(interaction)
        else:
            await interaction.response.send_message("❌ 数据库中未找到该记录。", ephemeral=True)

class RoleManagerView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.guild = ctx.guild if ctx else None
        if self.guild:
            self.setup_ui()

    def setup_ui(self):
        self.clear_items()
        data = load_role_data()
        role_map = {}

        # 构建 {Role: Type} 字典
        def load_to_map(key_name, type_name):
            for rid in data.get(key_name, []):
                r = self.guild.get_role(rid)
                if r: role_map[r] = type_name

        load_to_map("claimable_roles", "claimable")
        load_to_map("lottery_roles", "lottery")
        load_to_map("notification_roles", "notification") # 新增

        # 添加组件
        self.add_item(AdminAddRoleSelect(self, pool_type="lottery"))      # Row 0
        self.add_item(AdminAddRoleSelect(self, pool_type="claimable"))    # Row 1
        self.add_item(AdminAddRoleSelect(self, pool_type="notification")) # Row 2 (新增)
        self.add_item(AdminRemoveSelect(role_map, self))                  # Row 3

        # 功能按钮 Row 4
        ref_btn = discord.ui.Button(label="🔄 刷新", style=discord.ButtonStyle.secondary, row=4, custom_id="admin_refresh")
        ref_btn.callback = self.refresh_callback
        self.add_item(ref_btn)

    def build_dashboard_embed(self):
        data = load_role_data()
        embed = discord.Embed(title="⚙️ 身份组管理控制台", color=0x2b2d31)
        embed.set_footer(text=f"{self.guild.name}", icon_url=self.guild.icon.url if self.guild.icon else None)

        def fmt_roles(key):
            ids = data.get(key, [])
            names = []
            for rid in ids:
                r = self.guild.get_role(rid)
                names.append(r.mention if r else f"`{rid} (失效)`")
            return ", ".join(names) if names else "*空*"

        embed.add_field(name="🎰 抽奖模式", value=fmt_roles("lottery_roles"), inline=False)
        embed.add_field(name="🎨 自选模式", value=fmt_roles("claimable_roles"), inline=False)
        embed.add_field(name="🔔 通知订阅", value=fmt_roles("notification_roles"), inline=False) # 新增展示

        embed.description = "⬇️ **使用下方菜单配置你的社区身份组系统**"
        return embed

    async def refresh_callback(self, interaction: discord.Interaction):
        await self.refresh_content(interaction)

    async def refresh_content(self, interaction: discord.Interaction):
        self.setup_ui()
        embed = self.build_dashboard_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

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
                    "🔸 **自动替换**：选择同系列新款式会自动替换旧的哦！\n"
                    "🔸 **积分抽奖**：多种身份颜色任你选择，抽奖更刺激！\n\n"
                    "📜 **当前上架款式一览**：\n"
                    f"{role_list_str}",
        color=STYLE["KIMI_YELLOW"]
    )

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
