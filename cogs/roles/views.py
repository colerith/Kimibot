# cogs/roles/views.py

import discord
from discord import ui
import asyncio
import random

from .storage import load_role_data, save_role_data
from cogs.points.storage import get_user_points, modify_user_points
from config import STYLE, LOTTERY_COST, LOTTERY_REFUND
from discord.ui import Select

# --- 抽奖界面 ---
class RoleLotteryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎲 试试手气", style=discord.ButtonStyle.primary, emoji="🎰", custom_id="lottery_draw_btn")
    async def draw_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user

        # 1. 检查积分 (保持不变)
        current_points = get_user_points(user.id)
        if current_points < LOTTERY_COST:
            return await interaction.followup.send(
                f"💸 **积分不足！**\n你需要 **{LOTTERY_COST}** 积分才能抽奖，当前只有 **{current_points}**。",
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

        # 情况A: 已经有了这个身份组 -> 退款 (保持不变)
        if won_role in user.roles:
            modify_user_points(user.id, LOTTERY_REFUND)
            final_points = left_points + LOTTERY_REFUND
            embed.description = f"你抽到了 **{won_role.name}**！\n\n🤔 **但是...** 你好像已经拥有它了。\n\n💰 **退还积分**: {LOTTERY_REFUND}\n💳 **当前余额**: {final_points}"
            embed.color = discord.Color.light_grey()
            await interaction.followup.send(embed=embed, ephemeral=True)

        # 情况B: 抽到新的 -> 直接添加，不替换
        else:
            try:
                await user.add_roles(won_role, reason="积分抽奖获取")

                desc = f"🎉 **恭喜！！欧气爆发！**\n\n你获得了新的稀有装饰：**{won_role.mention}**\n它已经放入你的个人试衣间，快去看看吧！"
                desc += f"\n\n💳 **扣除积分**: {LOTTERY_COST}\n💰 **当前余额**: {left_points}"

                embed.description = desc
                embed.set_thumbnail(url="https://media.giphy.com/media/26tOZ42Mg6pbTUPVS/giphy.gif")
                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                # 出错退款
                modify_user_points(user.id, LOTTERY_COST)
                await interaction.followup.send(f"❌ 添加身份组失败 (积分已退还): {e}", ephemeral=True)

    @discord.ui.button(label="📜 查看积分", style=discord.ButtonStyle.secondary, emoji="👛", custom_id="lottery_check_points")
    async def check_points(self, button, interaction: discord.Interaction):
        p = get_user_points(interaction.user.id)
        await interaction.response.send_message(f"💰 你当前的社区活跃积分是：**{p}**", ephemeral=True)

    @discord.ui.button(label="📊 奖池图鉴", style=discord.ButtonStyle.success, emoji="🌌", custom_id="lottery_collection_view")
    async def collection_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data = load_role_data()
        pool_ids = set(data.get("lottery_roles", []))

        if not pool_ids:
            return await interaction.followup.send("🌑 这片星域空空如也（奖池未配置）。", ephemeral=True)

        guild = interaction.guild
        user_roles_ids = {r.id for r in interaction.user.roles}

        # 1. 梳理奖池和拥有状态
        valid_roles_in_pool = [r for r in [guild.get_role(rid) for rid in pool_ids] if r]
        owned_lottery_roles = [r for r in valid_roles_in_pool if r.id in user_roles_ids]

        total_count = len(valid_roles_in_pool)
        owned_count = len(owned_lottery_roles)

        if total_count == 0:
             return await interaction.followup.send("⚠️ 奖池里的身份组似乎都已失效。", ephemeral=True)

        # 2. 构建图鉴描述
        embed = discord.Embed(title="🌌 命运星图 · 珍藏馆", color=0x9b59b6)
        embed.description = f"这里记录着所有可能降临的命运。\n你已点亮了 **{owned_count} / {total_count}** 颗星辰。"

        # 显示所有已拥有
        if owned_lottery_roles:
            status_text = "\n".join([f"🌟 {r.mention}" for r in owned_lottery_roles])
        else:
            status_text = "⚪ 你尚未收集任何稀有装饰。"

        embed.add_field(name="我的收藏", value=status_text, inline=False)

        # 列出所有奖池内容
        pool_desc_list = []
        for r in sorted(valid_roles_in_pool, key=lambda role: role.name):
            if r in owned_lottery_roles:
                pool_desc_list.append(f"✅ **{r.name}** (已拥有)")
            else:
                pool_desc_list.append(f"❔ {r.name}")

        pool_text = "\n".join(pool_desc_list)
        if len(pool_text) > 1000:
            pool_text = pool_text[:950] + "\n... (更多星辰隐藏于深空)"

        embed.add_field(name=f"🏆 完整奖池 ({total_count}种)", value=pool_text, inline=False)
        embed.set_footer(text="愿命运女神眷顾你的每一次投掷。")

        await interaction.followup.send(embed=embed, ephemeral=True)

# --- 用户端视图 : 私密选择面板 ---
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
        except:
            return await interaction.followup.send("数据错误", ephemeral=True)

        if not target_role:
            return await interaction.followup.send("装饰已下架或失效", ephemeral=True)

        # 1. 判断身份组类型
        data = load_role_data()
        claimable_ids = data.get("claimable_roles", [])
        lottery_ids = data.get("lottery_roles", [])

        exclusive_type = None
        if target_role.id in claimable_ids:
            exclusive_type = "claimable"
        elif target_role.id in lottery_ids:
            exclusive_type = "lottery"

        # 2. 根据类型执行互斥移除并添加
        if target_role not in interaction.user.roles:
            try:
                # 只移除同类型的其他身份组
                removed = await remove_all_decorations(
                    interaction.user,
                    interaction.guild,
                    keep_role_id=target_role.id,
                    exclusive_type=exclusive_type
                )
                await interaction.user.add_roles(target_role, reason="面板自助领取/更换")

                msg = f"✅ **穿戴成功！**\n✨ 你现在拥有了 **{target_role.mention}**。"
                if removed:
                    msg += f"\n♻️ 已自动换下同类旧装饰：{', '.join([r.name for r in removed])}"
                await interaction.followup.send(msg, ephemeral=True)

            except Exception as e:
                await interaction.followup.send(f"❌ 权限不足或发生错误: {e}", ephemeral=True)
        else:
            # 卸下
            await interaction.user.remove_roles(target_role, reason="主动卸下")
            await interaction.followup.send(f"❎ **卸下成功！** 你已将 {target_role.mention} 收回衣柜。", ephemeral=True)

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

# --- 用户端视图: 公开主面板入口 ---
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
        # 1. 同时获取普通池和奖池的配置
        data = load_role_data()
        claimable_ids = set(data.get("claimable_roles", []))
        lottery_ids = set(data.get("lottery_roles", []))

        user_role_ids = {r.id for r in interaction.user.roles}

        # 2. 构建可选择的身份组列表
        selectable_roles = []

        # 添加所有有效的【普通身份组】
        for rid in claimable_ids:
            role = interaction.guild.get_role(rid)
            if role:
                selectable_roles.append(role)

        # 只添加用户【已拥有】的【奖池身份组】
        for rid in lottery_ids:
            if rid in user_role_ids:
                role = interaction.guild.get_role(rid)
                if role:
                    selectable_roles.append(role)

        if not selectable_roles:
            return await interaction.response.send_message("⚠️ 现在好像还没有任何可用的装饰品呢！", ephemeral=True)

        # 3. 构建当前状态文本，分别显示
        user_current_claimable = [r.name for r in interaction.user.roles if r.id in claimable_ids]
        user_current_lottery = [r.name for r in interaction.user.roles if r.id in lottery_ids]

        status_parts = []
        if user_current_claimable:
            status_parts.append(f"🎨 **普通装饰**: {', '.join(user_current_claimable)}")
        if user_current_lottery:
            status_parts.append(f"🎰 **稀有装饰**: {', '.join(user_current_lottery)}")

        status_text = "\n".join(status_parts) if status_parts else "你目前还没有佩戴任何装饰哦。"

        # 4. 发送私密选择面板
        embed = discord.Embed(
            title="👗 个人试衣间",
            description=f"**当前穿戴状态:**\n{status_text}\n\n请在下方菜单中选择你喜欢的装饰进行穿戴或更换：",
            color=0xFFB6C1
        )
        # 传入合并后的列表
        await interaction.response.send_message(embed=embed, view=RoleSelectionView(selectable_roles), ephemeral=True)
    
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

# --- 用户端：通知订阅 ---
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


# --- 管理端 ---
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


# --- 面板部署辅助函数 ---
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

async def remove_all_decorations(user, guild, keep_role_id=None, exclusive_type=None):
    """
    移除用户身上指定类型的互斥身份组。
    - keep_role_id: 如果提供了这个ID，则在移除时保留这个身份组（适用于换装时保留新装饰）
    - exclusive_type: "claimable", "lottery" 或 None (表示移除所有相关类型)，用于确定要清理哪个池的身份组
    """
    data = load_role_data()
    target_ids = set()

    # 根据传入的类型，确定要清理的身份组池
    if exclusive_type == "claimable":
        target_ids = set(data.get("claimable_roles", []))
    elif exclusive_type == "lottery":
        target_ids = set(data.get("lottery_roles", []))
    # 如果没有指定类型 (例如“一键移除”按钮)，则清理所有装饰
    else:
        target_ids = set(data.get("claimable_roles", []) + data.get("lottery_roles", []))

    to_remove = []
    for role in user.roles:
        if role.id in target_ids:
            # 如果是当前要装备的那个，保留它
            if keep_role_id and role.id == keep_role_id:
                continue
            to_remove.append(role)

    removed_roles = []
    if to_remove:
        try:
            # 使用 remove_roles 而不是单独调用，效率更高
            await user.remove_roles(*to_remove, reason=f"KimiBot Role Sync: Type '{exclusive_type}'")
            removed_roles.extend(to_remove)
        except Exception as e:
            print(f"Error removing roles for {user.name}: {e}") # 忽略权限错误

    return removed_roles