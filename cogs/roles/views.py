# cogs/roles/views.py

import discord
from discord import ui
import asyncio
import random
import config

from .storage import (
    load_role_data,
    save_role_data,
    add_to_collection,
    get_user_collection,
    get_lottery_pools_by_kind_and_rarity,
    get_lottery_config,
    get_lottery_role_rarity,
    get_lottery_role_kind,
    set_lottery_role_rarity,
    set_lottery_role_kind,
    update_lottery_config,
    RARITY_NORMAL,
    RARITY_RARE,
    RARITY_LEGENDARY,
    RARITY_JUNK,
    LOTTERY_KIND_COLOR,
    LOTTERY_KIND_ICON,
)
from cogs.points.storage import get_user_points, modify_user_points, sign_in_user
from config import STYLE
from discord.ui import Select


def _rarity_label(rarity: int) -> str:
    return {
        RARITY_NORMAL: "★ 普通",
        RARITY_RARE: "★★ 稀有",
        RARITY_LEGENDARY: "★★★ 传说",
        RARITY_JUNK: "☆ 安慰",
    }.get(rarity, "未知")


def _rarity_short(rarity: int) -> str:
    return {
        RARITY_JUNK: "☆",
        RARITY_NORMAL: "★",
        RARITY_RARE: "★★",
        RARITY_LEGENDARY: "★★★",
    }.get(rarity, "?")


def _lottery_kind_label(kind: str) -> str:
    return "颜色" if kind == LOTTERY_KIND_COLOR else "图标"


def _rules_text() -> str:
    return (
        "📌 **当前积分规则**\n"
        "- 🎯 十连抽消耗：**900** 积分\n"
        "- 💬 社区发言：每日最多获得 **100** 积分\n"
        "- 🧵 社区发帖：每帖 **10** 积分，每日最多 **50** 积分"
    )

# --- 抽奖界面 ---
class RoleLotteryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _run_draw(self, interaction: discord.Interaction, draw_count: int):
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild_id:
            return await interaction.followup.send("❌ 该功能仅支持在服务器内使用。", ephemeral=True)

        user = interaction.user
        guild_id = interaction.guild_id
        data = load_role_data()
        cfg = get_lottery_config(data)

        fallback_single = int(getattr(config, "LOTTERY_COST", 50))
        fallback_ten = int(getattr(config, "LOTTERY_TEN_COST", 900))
        fallback_refund = int(getattr(config, "LOTTERY_REFUND", 20))

        cost_single = max(1, int(cfg.get("cost_single", fallback_single)))
        cost_ten = max(900, fallback_ten, cost_single, int(cfg.get("cost_ten", fallback_ten)))
        cost = cost_ten if draw_count == 10 else cost_single * draw_count

        current_points = get_user_points(user.id, guild_id)
        if current_points < cost:
            return await interaction.followup.send(
                f"💸 **积分不足！**\n你需要 **{cost}** 积分才能执行本次抽奖，当前只有 **{current_points}**。",
                ephemeral=True,
            )

        pool_ids = data.get("lottery_roles", [])
        if not pool_ids:
            return await interaction.followup.send("🏜️ 奖池目前是空的，请联系管理员进货！", ephemeral=True)

        pools_by_kind_rarity = {
            LOTTERY_KIND_COLOR: {r: [] for r in (RARITY_JUNK, RARITY_NORMAL, RARITY_RARE, RARITY_LEGENDARY)},
            LOTTERY_KIND_ICON: {r: [] for r in (RARITY_JUNK, RARITY_NORMAL, RARITY_RARE, RARITY_LEGENDARY)},
        }
        for kind, rarity_map in get_lottery_pools_by_kind_and_rarity(data).items():
            for rarity, ids in rarity_map.items():
                for rid in ids:
                    role = interaction.guild.get_role(rid)
                    if role:
                        pools_by_kind_rarity[kind][rarity].append(role)

        if not any(pools_by_kind_rarity[k][r] for k in (LOTTERY_KIND_COLOR, LOTTERY_KIND_ICON) for r in (RARITY_JUNK, RARITY_NORMAL, RARITY_RARE, RARITY_LEGENDARY)):
            return await interaction.followup.send("⚠️ 奖池里的身份组好像失效了，请联系管理员。", ephemeral=True)

        modify_user_points(user.id, -cost, guild_id)

        weights_cfg = cfg.get("weights", {})
        rarity_pool = [RARITY_JUNK, RARITY_NORMAL, RARITY_RARE, RARITY_LEGENDARY]
        weights = [
            max(0, int(weights_cfg.get(str(r), 1)))
            for r in rarity_pool
        ]
        if sum(weights) <= 0:
            weights = [40, 40, 15, 5]

        picked_rarities = random.choices(rarity_pool, weights=weights, k=draw_count)

        user_collection_ids = set(get_user_collection(user.id))
        refund_cfg = cfg.get("refund", {})

        results = []
        granted_roles = []
        total_refund = 0

        for rarity in picked_rarities:
            available_kinds = [
                k for k in (LOTTERY_KIND_COLOR, LOTTERY_KIND_ICON)
                if pools_by_kind_rarity.get(k, {}).get(rarity, [])
            ]
            if not available_kinds:
                results.append({"role": None, "rarity": 0, "dupe": False, "refund": 0})
                continue

            picked_kind = random.choice(available_kinds)
            candidates = pools_by_kind_rarity[picked_kind][rarity]

            won_role = random.choice(candidates)
            if won_role.id in user_collection_ids:
                refund_amt = max(0, int(refund_cfg.get(str(rarity), fallback_refund)))
                total_refund += refund_amt
                results.append({"role": won_role, "rarity": rarity, "kind": picked_kind, "dupe": True, "refund": refund_amt})
            else:
                add_to_collection(user.id, won_role.id)
                user_collection_ids.add(won_role.id)
                granted_roles.append(won_role)
                results.append({"role": won_role, "rarity": rarity, "kind": picked_kind, "dupe": False, "refund": 0})

        if total_refund > 0:
            modify_user_points(user.id, total_refund, guild_id)

        equipped_role = granted_roles[-1] if granted_roles else None
        equip_error = None
        if equipped_role:
            equipped_kind = get_lottery_role_kind(equipped_role.id, data)
            exclusive_type = "lottery_color" if equipped_kind == LOTTERY_KIND_COLOR else "lottery_icon"
            try:
                await remove_all_decorations(
                    user,
                    interaction.guild,
                    keep_role_id=equipped_role.id,
                    exclusive_type=exclusive_type,
                )
                await user.add_roles(equipped_role, reason="积分抽奖获取")
            except Exception as e:
                equip_error = str(e)

        final_points = get_user_points(user.id, guild_id)
        new_count = sum(1 for row in results if row["role"] and not row["dupe"])
        dupe_count = sum(1 for row in results if row["dupe"])
        miss_count = sum(1 for row in results if row["role"] is None)

        title = "🎰 命运之轮转动了..." if draw_count == 1 else "🎰 十连演算已完成"
        embed = discord.Embed(title=title, color=discord.Color.gold())

        lines = []
        for row in results[:10]:
            if row["role"] is None:
                lines.append("▫️ 空抽 (该稀有度当前无上架身份组)")
                continue

            role = row["role"]
            rarity = row["rarity"]
            kind = row.get("kind", LOTTERY_KIND_COLOR)
            rarity_text = _rarity_label(rarity)
            kind_text = _lottery_kind_label(kind)
            if row["dupe"]:
                lines.append(f"♻️ [{kind_text}] {rarity_text} · {role.mention} (重复 +{row['refund']})")
            else:
                lines.append(f"✨ [{kind_text}] {rarity_text} · {role.mention} (新解锁)")

        embed.description = "\n".join(lines) if lines else "本次没有可展示的结果。"
        embed.add_field(
            name="结算",
            value=(
                f"本次消耗: **{cost}**\n"
                f"重复返还: **{total_refund}**\n"
                f"当前余额: **{final_points}**\n"
                f"新解锁: **{new_count}** | 重复: **{dupe_count}** | 空抽: **{miss_count}**"
            ),
            inline=False,
        )
        if equipped_role:
            embed.add_field(name="当前穿戴", value=f"已自动换装为 {equipped_role.mention}", inline=False)
        if equip_error:
            embed.add_field(name="提示", value=f"身份组发放时发生权限问题: {equip_error}", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🎲 试试手气", style=discord.ButtonStyle.primary, emoji="🎰", custom_id="lottery_draw_btn")
    async def draw_callback(self, button, interaction: discord.Interaction):
        await self._run_draw(interaction, draw_count=1)

    @discord.ui.button(label="🎯 十连试炼", style=discord.ButtonStyle.success, emoji="💫", custom_id="lottery_draw_ten_btn")
    async def draw_ten_callback(self, button, interaction: discord.Interaction):
        await self._run_draw(interaction, draw_count=10)

    @discord.ui.button(label="📜 查看积分", style=discord.ButtonStyle.secondary, emoji="👛", custom_id="lottery_check_points")
    async def check_points(self, button, interaction: discord.Interaction):
        p = get_user_points(interaction.user.id, interaction.guild_id or 0)
        await interaction.response.send_message(f"💰 你当前的社区活跃积分是：**{p}**", ephemeral=True)

    @discord.ui.button(label="📊 奖池图鉴", style=discord.ButtonStyle.success, emoji="🌌", custom_id="lottery_collection_view")
    async def collection_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        data = load_role_data()
        pool_ids = set(data.get("lottery_roles", []))

        if not pool_ids:
            return await interaction.followup.send("🌑 这片星域空空如也（奖池未配置）。", ephemeral=True)

        guild = interaction.guild

        # 【✨ 核心修改：从新的藏品数据库读取数据】
        user_collection_ids = set(get_user_collection(interaction.user.id))

        # 1. 梳理奖池和拥有状态
        valid_roles_in_pool = [r for r in [guild.get_role(rid) for rid in pool_ids] if r]

        # ✨ 现在通过藏品ID来判断拥有状态
        owned_lottery_roles = [r for r in valid_roles_in_pool if r.id in user_collection_ids]

        total_count = len(valid_roles_in_pool)
        owned_count = len(owned_lottery_roles)

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
            rarity = get_lottery_role_rarity(r.id, data)
            kind = get_lottery_role_kind(r.id, data)
            rarity_text = _rarity_label(rarity)
            kind_text = _lottery_kind_label(kind)
            if r in owned_lottery_roles:
                pool_desc_list.append(f"✅ **{r.name}** [{kind_text} | {rarity_text}] (已拥有)")
            else:
                pool_desc_list.append(f"❔ {r.name} [{kind_text} | {rarity_text}]")

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
            lot_kind = get_lottery_role_kind(target_role.id, data)
            exclusive_type = "lottery_color" if lot_kind == LOTTERY_KIND_COLOR else "lottery_icon"

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
        data = load_role_data()
        claimable_ids = set(data.get("claimable_roles", []))
        lottery_ids = set(data.get("lottery_roles", []))

        # 从藏品数据库获取稀有身份组
        user_lottery_collection_ids = set(get_user_collection(interaction.user.id))

        selectable_roles = []

        # 1. 添加所有有效的【普通身份组】
        for rid in claimable_ids:
            role = interaction.guild.get_role(rid)
            if role:
                selectable_roles.append(role)

        # 2. 添加用户【藏品中】的所有【稀有身份组】
        for rid in user_lottery_collection_ids:
            role = interaction.guild.get_role(rid)
            if role: # 确保身份组仍然存在于服务器
                selectable_roles.append(role)

        if not selectable_roles:
            return await interaction.response.send_message("⚠️ 现在好像还没有任何可用的装饰品呢！", ephemeral=True)

        # 3. 构建当前状态文本，分别显示
        user_current_claimable = [r.name for r in interaction.user.roles if r.id in claimable_ids]
        lottery_color_ids = {
            rid for rid in lottery_ids
            if get_lottery_role_kind(rid, data) == LOTTERY_KIND_COLOR
        }
        lottery_icon_ids = {
            rid for rid in lottery_ids
            if get_lottery_role_kind(rid, data) == LOTTERY_KIND_ICON
        }
        user_current_lottery_color = [r.name for r in interaction.user.roles if r.id in lottery_color_ids]
        user_current_lottery_icon = [r.name for r in interaction.user.roles if r.id in lottery_icon_ids]

        status_parts = []
        if user_current_claimable:
            status_parts.append(f"🎨 **普通装饰**: {', '.join(user_current_claimable)}")
        if user_current_lottery_color:
            status_parts.append(f"🎰 **稀有颜色**: {', '.join(user_current_lottery_color)}")
        if user_current_lottery_icon:
            status_parts.append(f"🏷️ **稀有图标**: {', '.join(user_current_lottery_icon)}")

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
        data = load_role_data()
        cfg = get_lottery_config(data)
        single_cost = max(1, int(cfg.get("cost_single", int(getattr(config, "LOTTERY_COST", 50)))))
        ten_cost = max(900, int(getattr(config, "LOTTERY_TEN_COST", 900)), single_cost, int(cfg.get("cost_ten", 900)))
        sign_reward = int(getattr(config, "POINTS_SIGN_REWARD", 30))
        msg_daily_cap = int(getattr(config, "POINTS_DAILY_MSG_CAP", 100))
        post_reward = int(getattr(config, "POINTS_POST_REWARD", 10))
        post_daily_cap = int(getattr(config, "POINTS_DAILY_POST_CAP", 50))

        refund_cfg = cfg.get("refund", {})
        refund_line = (
            f"☆{int(refund_cfg.get(str(RARITY_JUNK), 0))} / "
            f"★{int(refund_cfg.get(str(RARITY_NORMAL), 0))} / "
            f"★★{int(refund_cfg.get(str(RARITY_RARE), 0))} / "
            f"★★★{int(refund_cfg.get(str(RARITY_LEGENDARY), 0))}"
        )

        points = get_user_points(interaction.user.id, interaction.guild_id or 0)
        embed = discord.Embed(
            title="🌌 **星之运势 · 身份组抽奖**",
            description=f"这里藏着一些无法直接领取的 **稀有款式**！\n你会是那个被命运选中的孩子吗？\n\n"
                        f"💳 **单抽消耗**: {single_cost} 积分\n"
                        f"💳 **十连消耗**: {ten_cost} 积分\n"
                        f"🔄 **重复补偿**: {refund_line}\n"
                        f"💰 **你的积蓄**: **{points}**\n\n"
                        f"📌 **积分获取**\n"
                        f"- 📅 每日签到：+{sign_reward}\n"
                        f"- 💬 社区发言：每日最多 +{msg_daily_cap}\n"
                        f"- 🧵 社区发帖：每帖 +{post_reward}，每日最多 +{post_daily_cap}\n",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=RoleLotteryView(), ephemeral=True)

    @discord.ui.button(label="📅 每日签到", style=discord.ButtonStyle.secondary, emoji="🧧", custom_id="role_main_sign_in")
    async def main_sign_in_callback(self, button, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)

        reward = int(getattr(config, "POINTS_SIGN_REWARD", 30))
        success, points = sign_in_user(interaction.user.id, interaction.guild_id, reward=reward)
        if success:
            text = (
                f"✅ 今日签到成功，获得 **{reward}** 积分！\n"
                f"💰 当前余额：**{points}**\n\n"
                f"{_rules_text()}"
            )
        else:
            text = (
                f"🕒 今日已签到过啦。\n"
                f"💰 当前余额：**{points}**\n\n"
                f"{_rules_text()}"
            )

        await interaction.response.send_message(text, ephemeral=True)

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


class LotteryRarityRoleSelect(discord.ui.Select):
    def __init__(self, parent_view: "RoleManagerView", role_options: list[discord.SelectOption]):
        super().__init__(
            placeholder="选择奖池身份组",
            options=role_options,
            min_values=1,
            max_values=1,
            row=0,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        panel = self.view
        if not isinstance(panel, LotteryRarityConfigView):
            return await interaction.response.defer()

        panel.selected_role_id = int(self.values[0])
        await interaction.response.defer()


class LotteryRarityValueSelect(discord.ui.Select):
    def __init__(self, parent_view: "RoleManagerView"):
        super().__init__(
            placeholder="选择稀有度",
            options=[
                discord.SelectOption(label="★ 普通", value=str(RARITY_NORMAL), emoji="⭐"),
                discord.SelectOption(label="★★ 稀有", value=str(RARITY_RARE), emoji="🌟"),
                discord.SelectOption(label="★★★ 传说", value=str(RARITY_LEGENDARY), emoji="💫"),
                discord.SelectOption(label="☆ 安慰", value=str(RARITY_JUNK), emoji="▫️"),
            ],
            min_values=1,
            max_values=1,
            row=1,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        panel = self.view
        if not isinstance(panel, LotteryRarityConfigView):
            return await interaction.response.defer()

        panel.selected_rarity = int(self.values[0])
        await interaction.response.defer()


class LotteryKindValueSelect(discord.ui.Select):
    def __init__(self, parent_view: "RoleManagerView"):
        super().__init__(
            placeholder="选择分类",
            options=[
                discord.SelectOption(label="颜色身份组", value=LOTTERY_KIND_COLOR, emoji="🎨"),
                discord.SelectOption(label="图标身份组", value=LOTTERY_KIND_ICON, emoji="🏷️"),
            ],
            min_values=1,
            max_values=1,
            row=2,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        panel = self.view
        if not isinstance(panel, LotteryRarityConfigView):
            return await interaction.response.defer()

        panel.selected_kind = self.values[0]
        await interaction.response.defer()


class LotteryRarityApplyButton(discord.ui.Button):
    def __init__(self, parent_view: "RoleManagerView"):
        super().__init__(label="应用设置", emoji="✅", style=discord.ButtonStyle.success, row=3)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        panel = self.view
        if not isinstance(panel, LotteryRarityConfigView):
            return await interaction.response.send_message("❌ 面板状态异常。", ephemeral=True)

        if panel.selected_role_id is None or panel.selected_rarity is None or panel.selected_kind is None:
            return await interaction.response.send_message("❌ 请先选择身份组、稀有度和分类。", ephemeral=True)

        ok = set_lottery_role_rarity(panel.selected_role_id, panel.selected_rarity)
        if not ok:
            return await interaction.response.send_message("❌ 设置失败：该身份组不在抽奖池中。", ephemeral=True)

        ok_kind = set_lottery_role_kind(panel.selected_role_id, panel.selected_kind)
        if not ok_kind:
            return await interaction.response.send_message("❌ 分类设置失败。", ephemeral=True)

        role = interaction.guild.get_role(panel.selected_role_id) if interaction.guild else None
        role_name = role.mention if role else str(panel.selected_role_id)
        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send(
            f"✅ 已将 {role_name} 设为 [{_lottery_kind_label(panel.selected_kind)}] {_rarity_label(panel.selected_rarity)}",
            ephemeral=True,
        )


class LotteryRarityConfigView(discord.ui.View):
    def __init__(self, parent_view: "RoleManagerView", guild: discord.Guild):
        super().__init__(timeout=300)
        self.parent_view = parent_view
        self.selected_role_id: int | None = None
        self.selected_rarity: int | None = None
        self.selected_kind: str | None = None

        data = load_role_data()
        options = []
        for rid in data.get("lottery_roles", []):
            role = guild.get_role(rid)
            if not role:
                continue
            rarity = get_lottery_role_rarity(rid, data)
            kind = get_lottery_role_kind(rid, data)
            options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(rid),
                    description=f"当前: {_lottery_kind_label(kind)} | {_rarity_label(rarity)}",
                    emoji="🎟️",
                )
            )

        if options:
            self.add_item(LotteryRarityRoleSelect(parent_view, options[:25]))
            self.add_item(LotteryRarityValueSelect(parent_view))
            self.add_item(LotteryKindValueSelect(parent_view))
            self.add_item(LotteryRarityApplyButton(parent_view))
        else:
            empty_btn = discord.ui.Button(label="奖池为空，无法设置", disabled=True, row=0)
            self.add_item(empty_btn)


class LotteryCostModal(discord.ui.Modal):
    def __init__(self, parent_view: "RoleManagerView", config_data: dict):
        super().__init__(title="设置抽奖消耗")
        self.parent_view = parent_view

        self.single_input = ui.InputText(
            label="单抽消耗",
            placeholder="例如 50",
            value=str(config_data.get("cost_single", 50)),
            required=True,
            max_length=6,
        )
        self.ten_input = ui.InputText(
            label="十连消耗",
            placeholder="例如 900",
            value=str(config_data.get("cost_ten", 900)),
            required=True,
            max_length=6,
        )
        self.add_item(self.single_input)
        self.add_item(self.ten_input)

    async def callback(self, interaction: discord.Interaction):
        try:
            single = int((self.single_input.value or "").strip())
            ten = int((self.ten_input.value or "").strip())
        except ValueError:
            return await interaction.response.send_message("❌ 输入格式错误，请填写数字。", ephemeral=True)

        cfg = update_lottery_config(cost_single=single, cost_ten=ten)
        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send(
            f"✅ 抽奖消耗已更新：单抽 {int(cfg.get('cost_single', single))} / 十连 {int(cfg.get('cost_ten', 900))}",
            ephemeral=True,
        )


class LotteryWeightsRefundModal(discord.ui.Modal):
    def __init__(self, parent_view: "RoleManagerView", config_data: dict):
        super().__init__(title="设置概率与重复返还")
        self.parent_view = parent_view

        w = config_data.get("weights", {})
        r = config_data.get("refund", {})

        self.weights_input = ui.InputText(
            label="概率(☆,★,★★,★★★)",
            placeholder="例如 40,40,15,5",
            value=f"{int(w.get(str(RARITY_JUNK), 40))},{int(w.get(str(RARITY_NORMAL), 40))},{int(w.get(str(RARITY_RARE), 15))},{int(w.get(str(RARITY_LEGENDARY), 5))}",
            required=True,
            max_length=32,
        )
        self.refund_input = ui.InputText(
            label="重复返还(☆,★,★★,★★★)",
            placeholder="例如 8,20,40,100",
            value=f"{int(r.get(str(RARITY_JUNK), 8))},{int(r.get(str(RARITY_NORMAL), 20))},{int(r.get(str(RARITY_RARE), 40))},{int(r.get(str(RARITY_LEGENDARY), 100))}",
            required=True,
            max_length=32,
        )
        self.add_item(self.weights_input)
        self.add_item(self.refund_input)

    @staticmethod
    def _parse_quad(raw: str):
        values = [x.strip() for x in (raw or "").split(",") if x.strip()]
        if len(values) != 4:
            raise ValueError("需要4个数值")
        return [int(v) for v in values]

    async def callback(self, interaction: discord.Interaction):
        try:
            w_junk, w_normal, w_rare, w_legend = self._parse_quad(self.weights_input.value)
            r_junk, r_normal, r_rare, r_legend = self._parse_quad(self.refund_input.value)
        except ValueError:
            return await interaction.response.send_message(
                "❌ 输入格式错误，请按 `a,b,c,d` 填写 4 个整数。",
                ephemeral=True,
            )

        update_lottery_config(
            weights={
                str(RARITY_JUNK): w_junk,
                str(RARITY_NORMAL): w_normal,
                str(RARITY_RARE): w_rare,
                str(RARITY_LEGENDARY): w_legend,
            },
            refund={
                str(RARITY_JUNK): r_junk,
                str(RARITY_NORMAL): r_normal,
                str(RARITY_RARE): r_rare,
                str(RARITY_LEGENDARY): r_legend,
            },
        )

        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send("✅ 概率与重复返还已更新。", ephemeral=True)


class AdminActionButton(discord.ui.Button):
    def __init__(self, parent_view: "RoleManagerView", action: str, *, label: str, emoji: str):
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.secondary, row=4)
        self.parent_view = parent_view
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        cfg = get_lottery_config(load_role_data())
        if self.action == "rarity":
            rarity_view = LotteryRarityConfigView(self.parent_view, interaction.guild)
            await interaction.response.send_message(
                "请选择一个奖池身份组，再选择稀有度和分类后点击【应用设置】。",
                view=rarity_view,
                ephemeral=True,
            )
            return
        if self.action == "cost":
            await interaction.response.send_modal(LotteryCostModal(self.parent_view, cfg))
            return
        if self.action == "weights":
            await interaction.response.send_modal(LotteryWeightsRefundModal(self.parent_view, cfg))
            return

        await interaction.response.send_message("❌ 未知操作。", ephemeral=True)

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
        self.add_item(AdminActionButton(self, "rarity", label="稀有度", emoji="⭐"))
        self.add_item(AdminActionButton(self, "cost", label="抽奖消耗", emoji="💳"))
        self.add_item(AdminActionButton(self, "weights", label="概率/补偿", emoji="🎚️"))
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

        cfg = get_lottery_config(data)
        refunds = cfg.get("refund", {})
        weights = cfg.get("weights", {})

        rarity_lines = []
        kind_color_lines = []
        kind_icon_lines = []
        for rid in data.get("lottery_roles", []):
            role = self.guild.get_role(rid)
            if not role:
                continue
            rarity = get_lottery_role_rarity(rid, data)
            kind = get_lottery_role_kind(rid, data)
            line = f"{_rarity_short(rarity)} {role.mention}"
            rarity_lines.append(line)
            if kind == LOTTERY_KIND_COLOR:
                kind_color_lines.append(line)
            else:
                kind_icon_lines.append(line)

        rarity_text = "\n".join(rarity_lines[:10]) if rarity_lines else "*未配置*"
        if len(rarity_lines) > 10:
            rarity_text += "\n..."

        embed.add_field(
            name="⭐ 奖池稀有度",
            value=rarity_text,
            inline=False,
        )
        embed.add_field(
            name="🎨 抽奖池-颜色",
            value="\n".join(kind_color_lines[:10]) if kind_color_lines else "*空*",
            inline=False,
        )
        embed.add_field(
            name="🏷️ 抽奖池-图标",
            value="\n".join(kind_icon_lines[:10]) if kind_icon_lines else "*空*",
            inline=False,
        )
        embed.add_field(
            name="💳 抽奖参数",
            value=(
                f"单抽: **{int(cfg.get('cost_single', 50))}** | 十连: **{max(900, int(cfg.get('cost_ten', 900)))}**\n"
                f"概率(☆/★/★★/★★★): **{int(weights.get(str(RARITY_JUNK), 40))}/{int(weights.get(str(RARITY_NORMAL), 40))}/{int(weights.get(str(RARITY_RARE), 15))}/{int(weights.get(str(RARITY_LEGENDARY), 5))}**\n"
                f"补偿(☆/★/★★/★★★): **{int(refunds.get(str(RARITY_JUNK), 8))}/{int(refunds.get(str(RARITY_NORMAL), 20))}/{int(refunds.get(str(RARITY_RARE), 40))}/{int(refunds.get(str(RARITY_LEGENDARY), 100))}**"
            ),
            inline=False,
        )

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
                    "🔸 **积分抽奖**：多种身份颜色任你选择，抽奖更刺激！\n\n",
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
    - exclusive_type: "claimable", "lottery", "lottery_color", "lottery_icon" 或 None
    """
    data = load_role_data()
    target_ids = set()

    # 根据传入的类型，确定要清理的身份组池
    if exclusive_type == "claimable":
        target_ids = set(data.get("claimable_roles", []))
    elif exclusive_type == "lottery":
        target_ids = set(data.get("lottery_roles", []))
    elif exclusive_type == "lottery_color":
        target_ids = {
            rid for rid in data.get("lottery_roles", [])
            if get_lottery_role_kind(rid, data) == LOTTERY_KIND_COLOR
        }
    elif exclusive_type == "lottery_icon":
        target_ids = {
            rid for rid in data.get("lottery_roles", [])
            if get_lottery_role_kind(rid, data) == LOTTERY_KIND_ICON
        }
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