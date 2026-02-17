#general/views.py

import discord
from discord import ui
import datetime
import asyncio
import random
from config import STYLE, SERVER_OWNER_ID, IDS, LOTTERY_COST, LOTTERY_REFUND
from .utils import TZ_CN, generate_progress_bar
from .storage import load_role_data, save_role_data, load_lottery_data, save_lottery_data, modify_user_points, get_user_points

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

async def remove_all_decorations(user, guild, keep_role_id=None):
    """
    移除用户身上所有的装饰身份组（包括普通和抽奖的），
    keep_role_id 为当前要穿戴的，不移除它。
    """
    data = load_role_data()
    # 所有的装饰ID集合
    all_decor_ids = set(data.get("claimable_roles", []) + data.get("lottery_roles", []))

    to_remove = []
    for role in user.roles:
        if role.id in all_decor_ids:
            if keep_role_id and role.id == keep_role_id:
                continue
            to_remove.append(role)

    if to_remove:
        await user.remove_roles(*to_remove, reason="装饰互斥自动卸下")
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
                # 先执行互斥移除
                removed = await remove_all_decorations(user, interaction.guild, keep_role_id=won_role.id)
                await user.add_roles(won_role, reason="积分抽奖获取")

                desc = f"🎉 **恭喜！！欧气爆发！**\n\n你获得了稀有装饰：**{won_role.mention}**"
                if removed:
                    desc += f"\n\n♻️ 已自动换下旧装饰：{', '.join([r.name for r in removed])}"

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
    def __init__(self, parent_view, is_lottery=False):
        # 区分是添加进普通池 还是 奖池
        self.is_lottery = is_lottery
        label = "➕ 添加到【奖池】..." if is_lottery else "➕ 添加到【普通池】..."
        super().__init__(
            placeholder=label,
            min_values=1, max_values=1,
            row=1 if not is_lottery else 0, # 这里排版稍微错开一下
            select_type=discord.ComponentType.role_select
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        role_id = int(interaction.data['values'][0])
        role = interaction.guild.get_role(role_id)
        if not role: return

        data = load_role_data()
        target_list = "lottery_roles" if self.is_lottery else "claimable_roles"
        other_list = "claimable_roles" if self.is_lottery else "lottery_roles"

        # 检查逻辑
        if role.id in data[target_list]:
            return await interaction.response.send_message("⚠️ 已存在该列表中！", ephemeral=True)
        if role.id in data[other_list]:
            return await interaction.response.send_message("⚠️ 该身份组已在另一个池子中，请先移除再添加！", ephemeral=True)

        data[target_list].append(role.id)
        save_role_data(data)
        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send(f"✅ 添加成功 ({'奖池' if self.is_lottery else '普通'})：{role.name}", ephemeral=True)


# 为了简化，移除 Select 复用旧的，我们只需要在 RoleManagerView 里加上 两个 AddSelect
class AdminRemoveSelect(discord.ui.Select):
    # 下架逻辑 (合并显示所有，方便管理)
    def __init__(self, all_roles_map, parent_view):
        options = []
        # all_roles_map: {role_obj: 'lottery' or 'claimable'}
        for r, r_type in all_roles_map.items():
            emoji = "🎰" if r_type == 'lottery' else "🎨"
            options.append(discord.SelectOption(label=r.name, value=str(r.id), emoji=emoji, description=f"类型: {r_type}"))

        if not options: options.append(discord.SelectOption(label="无数据", value="none"))

        super().__init__(placeholder="➖ 下架任意身份组...", options=options[:25], row=2)
        self.parent_view = parent_view

    async def callback(self, interaction):
        if self.values[0] == "none": return
        rid = int(self.values[0])
        data = load_role_data()

        found = False
        if rid in data["claimable_roles"]:
            data["claimable_roles"].remove(rid)
            found = True
        elif rid in data["lottery_roles"]:
            data["lottery_roles"].remove(rid)
            found = True

        if found:
            save_role_data(data)
            await self.parent_view.refresh_content(interaction)
            await interaction.followup.send("🗑️ 已下架。", ephemeral=True)

class RoleManagerView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.guild = ctx.guild
        self.setup_ui()

    def setup_ui(self):
        self.clear_items()

        # 1. 奖池添加口
        self.add_item(AdminAddRoleSelect(self, is_lottery=True))
        # 2. 普通池添加口
        self.add_item(AdminAddRoleSelect(self, is_lottery=False))

        # 准备数据给移除列表
        data = load_role_data()
        role_map = {}
        # 为了避免过多，只取前25个混合展示，或者做分页(这里简化处理)
        for rid in data["claimable_roles"]:
            r = self.guild.get_role(rid)
            if r: role_map[r] = "普通"
        for rid in data["lottery_roles"]:
            r = self.guild.get_role(rid)
            if r: role_map[r] = "奖池"

        self.add_item(AdminRemoveSelect(role_map, self))

        # 按钮
        btn = discord.ui.Button(label="刷新", style=discord.ButtonStyle.secondary, row=3)
        btn.callback = self.refresh_callback
        self.add_item(btn)

        snd_btn = discord.ui.Button(label="发送面板", style=discord.ButtonStyle.primary, row=3)
        snd_btn.callback = self.send_panel_callback
        self.add_item(snd_btn)

    async def refresh_callback(self, interaction): await self.refresh_content(interaction)
    
    async def send_panel_callback(self, interaction):
        result = await deploy_role_panel(interaction.channel, self.guild, interaction.user.display_avatar.url)
        if result == "updated":
            await interaction.response.send_message("✅ 面板已更新！", ephemeral=True)
        elif result == "sent":
            await interaction.response.send_message("✅ 面板已发送到当前频道！", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 发生未知错误。", ephemeral=True)

    async def refresh_content(self, interaction):
        self.setup_ui()
        data = load_role_data()

        # 构建可视化的 Embed
        embed = discord.Embed(title="⚙️ 综合身份组管理", color=discord.Color.blurple())

        def list_names(key):
            ids = data.get(key, [])
            names = []
            for rid in ids:
                r = self.guild.get_role(rid)
                if r: names.append(r.mention)
                else: names.append(f"<无效ID:{rid}>")
            return ", ".join(names) if names else "*(空)*"

        embed.add_field(name="🎰 稀有奖池 (Lottery)", value=list_names("lottery_roles"), inline=False)
        embed.add_field(name="🎨 普通领取 (Claimable)", value=list_names("claimable_roles"), inline=False)

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
        self.add_item(AdminRemoveSelect(current_roles, self))
        
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
