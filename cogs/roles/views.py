# cogs/roles/views.py

import discord
from discord import ui
import asyncio
import random
import math
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
from cogs.points.storage import format_shells, get_user_points, get_user_summary, modify_user_points, sign_in_user
from cogs.points.storage import (
    get_acceleration_tiers,
    get_daily_signin_summary,
    load_random_events,
    purchase_acceleration_card,
)
from cogs.shared.utils import get_account_wait_status, has_verification_role
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
    data = load_role_data()
    cfg = get_lottery_config(data)

    single_cost = max(0.1, float(cfg.get("cost_single", float(getattr(config, "LOTTERY_COST", 1.0)))))
    five_cost = max(single_cost, float(cfg.get("cost_five", float(getattr(config, "LOTTERY_FIVE_COST", 5.0)))))
    ten_cost = max(five_cost, float(cfg.get("cost_ten", float(getattr(config, "LOTTERY_TEN_COST", 10.0)))))

    sign_reward = float(getattr(config, "POINTS_SIGN_REWARD", 1.0))
    post_reward = float(getattr(config, "POINTS_POST_REWARD", 5.0))
    post_daily_cap = float(getattr(config, "POINTS_DAILY_POST_CAP", 15.0))

    weights = cfg.get("weights", {})
    w_junk = int(weights.get(str(RARITY_JUNK), 55))
    w_normal = int(weights.get(str(RARITY_NORMAL), 37))
    w_rare = int(weights.get(str(RARITY_RARE), 6))
    w_legend = int(weights.get(str(RARITY_LEGENDARY), 2))

    return (
        "📌 **当前蛋壳/抽奖规则**\n"
        f"- 🎲 单抽消耗：**{format_shells(single_cost)}** 蛋壳\n"
        f"- 🍀 五抽消耗：**{format_shells(five_cost)}** 蛋壳\n"
        f"- 🎯 十连消耗：**{format_shells(ten_cost)}** 蛋壳\n"
        f"- 📈 抽奖概率(☆/★/★★/★★★)：**{w_junk}/{w_normal}/{w_rare}/{w_legend}**\n"
        f"- 📅 每日报到：基础 **{format_shells(sign_reward)}** 蛋壳\n"
        f"- 💬 有效发言：不再单条加分，会提升报到加成\n"
        f"- 🧵 社区发帖：每帖 **{format_shells(post_reward)}** 蛋壳，每日最多 **{format_shells(post_daily_cap)}** 蛋壳"
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

        fallback_single = float(getattr(config, "LOTTERY_COST", 1.0))
        fallback_five = float(getattr(config, "LOTTERY_FIVE_COST", 5.0))
        fallback_ten = float(getattr(config, "LOTTERY_TEN_COST", 10.0))
        fallback_refund = float(getattr(config, "LOTTERY_REFUND", 1.0))

        cost_single = max(0.1, float(cfg.get("cost_single", fallback_single)))
        cost_five = max(cost_single, float(cfg.get("cost_five", fallback_five)))
        cost_ten = max(cost_five, float(cfg.get("cost_ten", fallback_ten)))
        if draw_count == 10:
            cost = cost_ten
        elif draw_count == 5:
            cost = cost_five
        else:
            cost = cost_single * draw_count

        current_points = get_user_points(user.id, guild_id)
        if current_points < cost:
            return await interaction.followup.send(
                f"💸 **蛋壳不足！**\n你需要 **{format_shells(cost)}** 蛋壳才能执行本次抽奖，当前只有 **{format_shells(current_points)}**。",
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

        modify_user_points(user.id, -cost, guild_id, source="role_lottery", reason=f"draw_count={draw_count}")

        weights_cfg = cfg.get("weights", {})
        rarity_pool = [RARITY_JUNK, RARITY_NORMAL, RARITY_RARE, RARITY_LEGENDARY]
        weights = [
            max(0, int(weights_cfg.get(str(r), 1)))
            for r in rarity_pool
        ]
        if sum(weights) <= 0:
            weights = [55, 37, 6, 2]

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
                refund_amt = max(0.0, float(refund_cfg.get(str(rarity), fallback_refund)))
                total_refund += refund_amt
                results.append({"role": won_role, "rarity": rarity, "kind": picked_kind, "dupe": True, "refund": refund_amt})
            else:
                add_to_collection(user.id, won_role.id)
                user_collection_ids.add(won_role.id)
                granted_roles.append(won_role)
                results.append({"role": won_role, "rarity": rarity, "kind": picked_kind, "dupe": False, "refund": 0})

        if total_refund > 0:
            modify_user_points(user.id, total_refund, guild_id, source="role_lottery_refund", reason=f"draw_count={draw_count}")

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
                await user.add_roles(equipped_role, reason="蛋壳抽奖获取")
            except Exception as e:
                equip_error = str(e)

        final_points = get_user_points(user.id, guild_id)
        new_count = sum(1 for row in results if row["role"] and not row["dupe"])
        dupe_count = sum(1 for row in results if row["dupe"])
        miss_count = sum(1 for row in results if row["role"] is None)

        title_map = {
            1: "🎰 命运之轮转动了...",
            5: "🎰 五连小蛋已开奖",
            10: "🎰 十连演算已完成",
        }
        title = title_map.get(draw_count, "🎰 小蛋抽奖已完成")
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
                lines.append(f"♻️ [{kind_text}] {rarity_text} · {role.mention} (重复 +{format_shells(row['refund'])} 蛋壳)")
            else:
                lines.append(f"✨ [{kind_text}] {rarity_text} · {role.mention} (新解锁)")

        embed.description = "\n".join(lines) if lines else "本次没有可展示的结果。"
        embed.add_field(
            name="结算",
            value=(
                f"本次消耗: **{format_shells(cost)}** 蛋壳\n"
                f"重复返还: **{format_shells(total_refund)}** 蛋壳\n"
                f"当前余额: **{format_shells(final_points)}** 蛋壳\n"
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

    @discord.ui.button(label="🍀 五连试炼", style=discord.ButtonStyle.success, emoji="🍀", custom_id="lottery_draw_five_btn")
    async def draw_five_callback(self, button, interaction: discord.Interaction):
        await self._run_draw(interaction, draw_count=5)

    @discord.ui.button(label="🎯 十连试炼", style=discord.ButtonStyle.success, emoji="💫", custom_id="lottery_draw_ten_btn")
    async def draw_ten_callback(self, button, interaction: discord.Interaction):
        await self._run_draw(interaction, draw_count=10)

    @discord.ui.button(label="📜 查看蛋壳", style=discord.ButtonStyle.secondary, emoji="👛", custom_id="lottery_check_points")
    async def check_points(self, button, interaction: discord.Interaction):
        p = get_user_points(interaction.user.id, interaction.guild_id or 0)
        await interaction.response.send_message(f"🥚 你当前的蛋壳余额是：**{format_shells(p)}**", ephemeral=True)

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


class AccelerationShopView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        for tier in get_acceleration_tiers():
            self.add_item(AccelerationTierButton(tier))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("这不是你的加速购买面板。", ephemeral=True)
            return False
        return True


class AccelerationTierButton(discord.ui.Button):
    def __init__(self, tier: dict):
        super().__init__(
            label=tier["label"],
            style=discord.ButtonStyle.primary,
            emoji="⚡",
            custom_id=f"accel_buy_{tier['id']}",
        )
        self.tier = tier

    async def callback(self, interaction: discord.Interaction):
        if has_verification_role(interaction.user):
            return await interaction.response.send_message(
                "你已经通过验证答题啦，不需要再购买加速卡。",
                ephemeral=True,
            )

        result = purchase_acceleration_card(interaction.user.id, interaction.guild_id, self.tier["id"])
        if not result.get("success"):
            reason = result.get("reason")
            if reason == "insufficient_shells":
                msg = (
                    f"蛋壳不足，购买 **{self.tier['label']}** 需要 "
                    f"**{format_shells(result.get('cost', self.tier['cost']))}** 蛋壳，"
                    f"你当前只有 **{format_shells(result.get('balance', 0))}**。"
                )
            elif reason == "max_reached":
                msg = "你的加速天数已经达到上限，最快等待期已经压到 5 天啦。"
            else:
                msg = "购买失败，请稍后再试。"
            return await interaction.response.send_message(msg, ephemeral=True)

        status = result["status"]
        wait_status = get_account_wait_status(interaction.user, interaction.guild_id)
        msg = (
            f"✅ 已购买 **{self.tier['label']}** 加速卡。\n"
            f"本次生效：**{result['effective_days']}** 天\n"
            f"累计加速：**{status['acceleration_days']} / {status['max_days']}** 天\n"
            f"账号已注册：**{wait_status['account_age_days']}** 天\n"
            f"当前要求注册满：**{wait_status['required_wait_days']}** 天\n"
            f"实际还需等待：**{wait_status['remaining_wait_days']}** 天\n"
            f"🥚 当前余额：**{format_shells(result['balance'])}** 蛋壳"
        )
        await interaction.response.send_message(msg, ephemeral=True)


def build_acceleration_embed(member: discord.Member, guild_id: int) -> discord.Embed:
    status = get_account_wait_status(member, guild_id)
    lines = [
        f"累计加速：**{status['acceleration_days']} / {status['max_days']}** 天",
        f"账号已注册：**{status['account_age_days']}** 天",
        f"当前要求注册满：**{status['required_wait_days']}** 天",
        f"实际还需等待：**{status['remaining_wait_days']}** 天",
        "",
        "可购买档位：",
    ]
    for tier in status["tiers"]:
        lines.append(f"- {tier['label']}：{format_shells(tier['cost'])} 蛋壳")

    embed = discord.Embed(
        title="⚡ 加速购买",
        description="\n".join(lines),
        color=STYLE["KIMI_YELLOW"],
    )
    embed.set_footer(text="等待期会按你的 Discord 账号注册时间实时计算。")
    return embed


def build_shell_help_embed() -> discord.Embed:
    sign_reward = float(getattr(config, "POINTS_SIGN_REWARD", 1.0))
    forum_reward = float(getattr(config, "FORUM_REWARD_AMOUNT", 5.0))
    boost_reward = float(getattr(config, "BOOST_REWARD_AMOUNT", 10.0))
    prequiz_reward = float(getattr(config, "PRE_QUIZ_REWARD", 5.0))
    embed = discord.Embed(
        title="🥚 蛋壳帮助",
        description=(
            "这里是当前可以获取和使用蛋壳的机制总览。\n\n"
            f"**每日签到**：每天报到 1 次，基础 +{format_shells(sign_reward)} 蛋壳。\n"
            "**随机事件**：签到时触发，可能增加或扣除 0.1-1.9 蛋壳。\n"
            "**前十奖励**：每天前 10 名签到会额外获得 0.1-1.9 蛋壳。\n"
            "**连续加成**：连续签到满 7/14/30/60/90 天后，提高签到收益。\n"
            "**发言加成**：有效发言不再单条给蛋壳，会提高签到加成。\n"
            f"**发帖奖励**：指定论坛频道每天前 3 帖，每帖 +{format_shells(forum_reward)} 蛋壳。\n"
            f"**预备答题**：未验证成员通过后固定 +{format_shells(prequiz_reward)} 蛋壳，每人一次。\n"
            f"**服务器助力**：每次助力 +{format_shells(boost_reward)} 蛋壳。\n"
            "**蛋壳红包**：使用 `/发红包` 把蛋壳发给大家抢，普通成员扣除红包总额，管理员福利红包不扣除。\n\n"
            "**蛋壳用途**：身份抽奖、换装/商店相关兑换；加速卡仅未验证成员可购买。"
        ),
        color=STYLE["KIMI_YELLOW"],
    )
    embed.set_footer(text="具体数值以当前配置和实际结算为准。")
    return embed


def build_role_panel_embed(guild: discord.Guild, user_avatar_url: str | None = None) -> discord.Embed:
    summary = get_daily_signin_summary(guild.id)
    top10 = summary.get("top10", [])
    if top10:
        top_lines = [f"`{index}.` <@{user_id}>" for index, user_id in enumerate(top10, start=1)]
        top_text = "\n".join(top_lines)
    else:
        top_text = "今天还没有人报到，等一个第 1 名小蛋。"

    embed = discord.Embed(
        title="🥚 **小蛋报到**",
        description="每天来奇米蛋这里报到，就可以领取 **1 蛋壳**。\n\n"
                    "🐣 **每日签到**\n"
                    "每个成员每天只能报到 1 次，连续报到和有效发言会提高报到加成。\n\n"
                    f"📊 **今日报到**\n"
                    f"今日已报到：**{summary['count']}** 人\n"
                    f"日期：`{summary['date']}`\n\n"
                    f"🏆 **今日前十**\n{top_text}\n\n"
                    "🥚 **蛋壳用途**\n"
                    "蛋壳可以用于身份抽奖、加速卡、换装相关兑换，以及后续的小蛋商店功能。\n\n"
                    "🎲 **随机事件**\n"
                    "报到时会触发小蛋事件，可能获得或扣掉 `0.1 - 1.9` 蛋壳。",
        color=STYLE["KIMI_YELLOW"]
    )

    if user_avatar_url:
        embed.set_thumbnail(url=user_avatar_url)

    embed.set_footer(text="小蛋会记得你每天来过。")
    return embed


async def refresh_role_panel(guild: discord.Guild, user_avatar_url: str | None = None):
    data = load_role_data()
    panel_info = data.get("panel_info", {})
    channel_id = panel_info.get("channel_id")
    message_id = panel_info.get("message_id")
    if not channel_id or not message_id:
        return False

    channel = guild.get_channel(int(channel_id))
    if not channel:
        return False

    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=build_role_panel_embed(guild, user_avatar_url), view=RoleClaimView())
        return True
    except (discord.NotFound, discord.Forbidden):
        return False

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

    @discord.ui.button(label="蛋壳余额", style=discord.ButtonStyle.secondary, emoji="🥚", custom_id="role_main_shells", row=0)
    async def shells_callback(self, button, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)

        summary = get_user_summary(interaction.user.id, interaction.guild_id)
        text = (
            f"🥚 **你的蛋壳余额：{format_shells(summary['shells'])}**\n"
            f"连续报到：**{summary['streak_days']}** 天\n"
            f"今日有效发言：**{summary['daily_msg_count']}** 条\n\n"
            f"{_rules_text()}"
        )
        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="使用帮助", style=discord.ButtonStyle.secondary, emoji="❔", custom_id="role_main_shell_help", row=0)
    async def shell_help_callback(self, button, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_shell_help_embed(), ephemeral=True)

    @discord.ui.button(label="小蛋换装", style=discord.ButtonStyle.success, emoji="🎨", custom_id="role_main_start", row=1)
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
            title="👗 小蛋换装",
            description=f"**当前穿戴状态:**\n{status_text}\n\n请在下方菜单中选择你喜欢的装饰进行穿戴或更换：",
            color=0xFFB6C1
        )
        # 传入合并后的列表
        await interaction.response.send_message(embed=embed, view=RoleSelectionView(selectable_roles), ephemeral=True)

    @discord.ui.button(label="加速购买", style=discord.ButtonStyle.secondary, emoji="⚡", custom_id="role_main_acceleration", row=1)
    async def acceleration_callback(self, button, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)
        if has_verification_role(interaction.user):
            return await interaction.response.send_message(
                "你已经通过验证答题啦，不需要再购买加速卡。",
                ephemeral=True,
            )
        embed = build_acceleration_embed(interaction.user, interaction.guild_id)
        await interaction.response.send_message(embed=embed, view=AccelerationShopView(interaction.user.id), ephemeral=True)
    
    @discord.ui.button(label="身份抽奖", style=discord.ButtonStyle.primary, emoji="🎲", custom_id="role_main_lottery", row=1)
    async def lottery_entry_callback(self, button, interaction: discord.Interaction):
        data = load_role_data()
        cfg = get_lottery_config(data)
        single_cost = max(0.1, float(cfg.get("cost_single", float(getattr(config, "LOTTERY_COST", 1.0)))))
        five_cost = max(single_cost, float(cfg.get("cost_five", float(getattr(config, "LOTTERY_FIVE_COST", 5.0)))))
        ten_cost = max(five_cost, float(cfg.get("cost_ten", float(getattr(config, "LOTTERY_TEN_COST", 10.0)))))
        sign_reward = float(getattr(config, "POINTS_SIGN_REWARD", 1.0))
        post_reward = float(getattr(config, "POINTS_POST_REWARD", 5.0))
        post_daily_cap = float(getattr(config, "POINTS_DAILY_POST_CAP", 15.0))

        refund_cfg = cfg.get("refund", {})
        refund_line = (
            f"☆{format_shells(refund_cfg.get(str(RARITY_JUNK), 0))} / "
            f"★{format_shells(refund_cfg.get(str(RARITY_NORMAL), 0))} / "
            f"★★{format_shells(refund_cfg.get(str(RARITY_RARE), 0))} / "
            f"★★★{format_shells(refund_cfg.get(str(RARITY_LEGENDARY), 0))}"
        )

        points = get_user_points(interaction.user.id, interaction.guild_id or 0)
        embed = discord.Embed(
            title="🌌 **奇米蛋 · 身份抽奖**",
            description=f"这里藏着一些无法直接领取的 **稀有款式**！\n你会是那个被命运选中的孩子吗？\n\n"
                        f"💳 **单抽消耗**: {format_shells(single_cost)} 蛋壳\n"
                        f"💳 **五抽消耗**: {format_shells(five_cost)} 蛋壳\n"
                        f"💳 **十连消耗**: {format_shells(ten_cost)} 蛋壳\n"
                        f"🔄 **重复补偿**: {refund_line} 蛋壳\n"
                        f"🥚 **你的蛋壳**: **{format_shells(points)}**\n\n"
                        f"📌 **蛋壳获取**\n"
                        f"- 📅 小蛋报到：+{format_shells(sign_reward)} 起\n"
                        f"- 💬 有效发言：提升报到加成\n"
                        f"- 🧵 社区发帖：每帖 +{format_shells(post_reward)}，每日最多 +{format_shells(post_daily_cap)}\n",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=embed, view=RoleLotteryView(), ephemeral=True)

    @discord.ui.button(label="每日签到", style=discord.ButtonStyle.secondary, emoji="📅", custom_id="role_main_sign_in", row=0)
    async def main_sign_in_callback(self, button, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("❌ 该功能仅支持在服务器中使用。", ephemeral=True)

        reward = float(getattr(config, "POINTS_SIGN_REWARD", 1.0))
        result = sign_in_user(interaction.user.id, interaction.guild_id, reward=reward)
        if result.get("success"):
            await refresh_role_panel(
                interaction.guild,
                interaction.client.user.display_avatar.url if interaction.client.user else None,
            )
            event = result.get("event", {})
            event_delta = float(result.get("event_delta", 0))
            event_sign = "+" if event_delta > 0 else ""
            bonus_lines = []
            if result.get("bonus_amount", 0) > 0:
                bonus_lines.append(f"连续/活跃加成：+{format_shells(result['bonus_amount'])} 蛋壳")
            if result.get("rank_bonus", 0) > 0:
                bonus_lines.append(f"前十报到奖励：+{format_shells(result['rank_bonus'])} 蛋壳")
            bonus_text = "\n".join(bonus_lines) if bonus_lines else "今日暂无额外加成"
            text = (
                f"✅ **小蛋报到成功！**\n"
                f"基础奖励：+{format_shells(result['base_reward'])} 蛋壳\n"
                f"{bonus_text}\n"
                f"随机事件：**{event.get('title', '小蛋事件')}** ({event_sign}{format_shells(abs(event_delta))})\n"
                f"{event.get('description', '')}\n\n"
                f"连续报到：**{result['streak_days']}** 天\n"
                f"今日排名：第 **{result['rank']}** 位\n"
                f"本次合计：**{'-' if result['total_delta'] < 0 else '+'}{format_shells(abs(result['total_delta']))}** 蛋壳\n"
                f"🥚 当前余额：**{format_shells(result['balance'])}** 蛋壳\n\n"
                f"{_rules_text()}"
            )
        else:
            summary = get_user_summary(interaction.user.id, interaction.guild_id)
            text = (
                f"🕒 今日已经报到过啦。\n"
                f"连续报到：**{summary['streak_days']}** 天\n"
                f"🥚 当前余额：**{format_shells(result['balance'])}** 蛋壳\n\n"
                f"{_rules_text()}"
            )

        await interaction.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="一键移除", style=discord.ButtonStyle.danger, emoji="🧹", custom_id="role_main_remove_all", row=1)
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
            min_values=1, max_values=25,
            row=row_map.get(pool_type, 0),
            select_type=discord.ComponentType.role_select
        )
        self.parent_view = parent_view

    async def callback(self, interaction):
        selected_ids = [int(v) for v in interaction.data.get("values", [])]
        if not selected_ids:
            return await interaction.response.send_message("❌ 未选择任何身份组。", ephemeral=True)

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

        # 检查逻辑：全池查重（支持批量）
        all_lists = ["claimable_roles", "lottery_roles", "notification_roles"]
        added = []
        skipped = []
        for role_id in selected_ids:
            role = interaction.guild.get_role(role_id)
            if not role:
                skipped.append(f"{role_id}(失效)")
                continue

            duplicated = False
            for k in all_lists:
                if role_id in data.get(k, []):
                    duplicated = True
                    break

            if duplicated:
                skipped.append(role.name)
                continue

            data[target_list_key].append(role_id)
            added.append(role.name)

        save_role_data(data)
        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send(
            f"✅ 添加成功({self.pool_type})：{len(added)} 项\n"
            f"⚠️ 跳过：{len(skipped)} 项"
            + (f"\n- 已添加：{', '.join(added[:10])}" if added else "")
            + (f"\n- 已跳过：{', '.join(skipped[:10])}" if skipped else ""),
            ephemeral=True,
        )

class AdminRemoveSelect(Select):
    def __init__(self, role_datas, view_parent, page: int = 0, page_size: int = 25):
        self.view_parent = view_parent
        if isinstance(role_datas, list):
            role_datas = {r: "unknown" for r in role_datas}

        role_entries = []
        for role, r_type in role_datas.items():
            if not isinstance(role, discord.Role): continue
            role_entries.append((role, r_type))

        # 按显示名稳定排序，翻页时避免选项顺序抖动
        role_entries.sort(key=lambda item: item[0].name.lower())

        total_options = len(role_entries)
        total_pages = max(1, math.ceil(total_options / page_size)) if total_options > 0 else 1
        page = max(0, min(page, total_pages - 1))

        start = page * page_size
        end = start + page_size

        options = []
        for role, r_type in role_entries[start:end]:

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
            placeholder = "➖ 选择要移除的身份组..."
        else:
            disabled = False
            placeholder = (
                f"➖ 选择要移除的身份组... ({page + 1}/{total_pages})"
                if total_options > page_size
                else "➖ 选择要移除的身份组..."
            )

        super().__init__(
            placeholder=placeholder,
            min_values=1, max_values=min(25, len(options)), options=options, custom_id="admin_remove_select",
            disabled=disabled, row=3
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.values or self.values[0] == "none":
            return await interaction.response.send_message("这里什么也没有。", ephemeral=True)

        data = load_role_data()
        target_ids = {int(v) for v in self.values}
        removed_count = 0

        # 遍历所有可能的列表进行删除
        keys = ["claimable_roles", "lottery_roles", "notification_roles"]
        for k in keys:
            source = data.get(k, [])
            kept = [rid for rid in source if rid not in target_ids]
            removed_count += len(source) - len(kept)
            data[k] = kept

        if removed_count > 0:
            save_role_data(data)
            await self.view_parent.refresh_content(interaction)
            await interaction.followup.send(f"🗑️ 已移除配置：{removed_count} 条记录", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 数据库中未找到该记录。", ephemeral=True)


class AdminRemovePageButton(discord.ui.Button):
    def __init__(self, parent_view: "RoleManagerView"):
        super().__init__(
            label=f"移除列表翻页 ({parent_view.remove_page + 1}/{parent_view.remove_total_pages})",
            emoji="📄",
            style=discord.ButtonStyle.secondary,
            row=4,
            disabled=(parent_view.remove_total_pages <= 1),
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.parent_view.remove_total_pages <= 1:
            return await interaction.response.defer()

        self.parent_view.remove_page = (self.parent_view.remove_page + 1) % self.parent_view.remove_total_pages
        await self.parent_view.refresh_content(interaction)


class LotteryRarityRoleSelect(discord.ui.Select):
    def __init__(self, parent_view: "RoleManagerView", role_options: list[discord.SelectOption]):
        super().__init__(
            placeholder="选择奖池身份组",
            options=role_options,
            min_values=1,
            max_values=min(25, len(role_options)),
            row=0,
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        panel = self.view
        if not isinstance(panel, LotteryRarityConfigView):
            return await interaction.response.defer()

        panel.selected_role_ids = [int(v) for v in self.values]
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

        if not panel.selected_role_ids or panel.selected_rarity is None or panel.selected_kind is None:
            return await interaction.response.send_message("❌ 请先选择身份组、稀有度和分类。", ephemeral=True)

        success_count = 0
        for rid in panel.selected_role_ids:
            ok = set_lottery_role_rarity(rid, panel.selected_rarity)
            ok_kind = set_lottery_role_kind(rid, panel.selected_kind)
            if ok and ok_kind:
                success_count += 1

        await self.parent_view.refresh_content(interaction)
        await interaction.followup.send(
            f"✅ 批量设置完成：{success_count}/{len(panel.selected_role_ids)} 项\n"
            f"目标：[{_lottery_kind_label(panel.selected_kind)}] {_rarity_label(panel.selected_rarity)}",
            ephemeral=True,
        )


class LotteryRarityBackButton(discord.ui.Button):
    def __init__(self, parent_view: "RoleManagerView"):
        super().__init__(label="返回管理", emoji="↩️", style=discord.ButtonStyle.secondary, row=3)
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.refresh_content(interaction)


class LotteryRarityPageButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="翻页", emoji="📄", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        panel = self.view
        if not isinstance(panel, LotteryRarityConfigView):
            return await interaction.response.defer()

        if panel.total_pages <= 1:
            return await interaction.response.defer()

        panel.page = (panel.page + 1) % panel.total_pages
        panel.selected_role_ids = []
        panel._build()
        await interaction.response.edit_message(view=panel)


class LotteryRarityConfigView(discord.ui.View):
    def __init__(self, parent_view: "RoleManagerView", guild: discord.Guild):
        super().__init__(timeout=300)
        self.parent_view = parent_view
        self.selected_role_ids: list[int] = []
        self.selected_rarity: int | None = None
        self.selected_kind: str | None = None
        self.page = 0
        self.page_size = 25
        self.total_pages = 1

        data = load_role_data()
        self.all_options = []
        for rid in data.get("lottery_roles", []):
            role = guild.get_role(rid)
            if not role:
                continue
            rarity = get_lottery_role_rarity(rid, data)
            kind = get_lottery_role_kind(rid, data)
            self.all_options.append(
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(rid),
                    description=f"当前: {_lottery_kind_label(kind)} | {_rarity_label(rarity)}",
                    emoji="🎟️",
                )
            )

        # 统一排序，分页时顺序稳定
        self.all_options.sort(key=lambda o: o.label.lower())
        self.total_pages = max(1, math.ceil(len(self.all_options) / self.page_size)) if self.all_options else 1
        self._build()

    def _build(self):
        self.clear_items()
        if self.all_options:
            self.total_pages = max(1, math.ceil(len(self.all_options) / self.page_size))
            self.page = max(0, min(self.page, self.total_pages - 1))
            start = self.page * self.page_size
            end = start + self.page_size
            page_options = self.all_options[start:end]

            role_select = LotteryRarityRoleSelect(self.parent_view, page_options)
            role_select.placeholder = f"选择奖池身份组 ({self.page + 1}/{self.total_pages})"
            self.add_item(role_select)
            self.add_item(LotteryRarityValueSelect(self.parent_view))
            self.add_item(LotteryKindValueSelect(self.parent_view))
            self.add_item(LotteryRarityApplyButton(self.parent_view))
            self.add_item(LotteryRarityBackButton(self.parent_view))
            if self.total_pages > 1:
                btn = LotteryRarityPageButton()
                btn.label = f"翻页 ({self.page + 1}/{self.total_pages})"
                self.add_item(btn)
        else:
            empty_btn = discord.ui.Button(label="奖池为空，无法设置", disabled=True, row=0)
            self.add_item(empty_btn)
            self.add_item(LotteryRarityBackButton(self.parent_view))


class LotteryCostModal(discord.ui.Modal):
    def __init__(self, parent_view: "RoleManagerView", config_data: dict):
        super().__init__(title="设置抽奖消耗")
        self.parent_view = parent_view

        self.single_input = ui.InputText(
            label="单抽消耗（蛋壳）",
            placeholder="例如 1.0",
            value=str(config_data.get("cost_single", 1.0)),
            required=True,
            max_length=6,
        )
        self.five_input = ui.InputText(
            label="五抽消耗（蛋壳）",
            placeholder="例如 5.0",
            value=str(config_data.get("cost_five", 5.0)),
            required=True,
            max_length=6,
        )
        self.ten_input = ui.InputText(
            label="十连消耗（蛋壳）",
            placeholder="例如 10.0",
            value=str(config_data.get("cost_ten", 10.0)),
            required=True,
            max_length=6,
        )
        self.add_item(self.single_input)
        self.add_item(self.five_input)
        self.add_item(self.ten_input)

    async def callback(self, interaction: discord.Interaction):
        try:
            single = float((self.single_input.value or "").strip())
            five = float((self.five_input.value or "").strip())
            ten = float((self.ten_input.value or "").strip())
        except ValueError:
            return await interaction.response.send_message("❌ 输入格式错误，请填写数字。", ephemeral=True)

        update_lottery_config(cost_single=single, cost_five=five, cost_ten=ten)
        # 重新读取，确保回执展示的是实际落盘后的值
        cfg = get_lottery_config(load_role_data())

        # Modal 交互并不总有 message 上下文，安全刷新主面板
        self.parent_view.setup_ui()
        embed = self.parent_view.build_dashboard_embed()
        if interaction.message is not None:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self.parent_view)
            else:
                await interaction.edit_original_response(embed=embed, view=self.parent_view)
        else:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

        await interaction.followup.send(
            f"✅ 抽奖消耗已更新（已保存）\n"
            f"- 单抽：{format_shells(cfg.get('cost_single', single))} 蛋壳\n"
            f"- 五抽：{format_shells(cfg.get('cost_five', five))} 蛋壳\n"
            f"- 十连：{format_shells(cfg.get('cost_ten', ten))} 蛋壳",
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
            placeholder="例如 55,37,6,2",
            value=f"{int(w.get(str(RARITY_JUNK), 55))},{int(w.get(str(RARITY_NORMAL), 37))},{int(w.get(str(RARITY_RARE), 6))},{int(w.get(str(RARITY_LEGENDARY), 2))}",
            required=True,
            max_length=32,
        )
        self.refund_input = ui.InputText(
            label="重复返还蛋壳(☆,★,★★,★★★)",
            placeholder="例如 0.5,1.0,2.0,5.0",
            value=f"{format_shells(r.get(str(RARITY_JUNK), 0.5))},{format_shells(r.get(str(RARITY_NORMAL), 1.0))},{format_shells(r.get(str(RARITY_RARE), 2.0))},{format_shells(r.get(str(RARITY_LEGENDARY), 5.0))}",
            required=True,
            max_length=32,
        )
        self.add_item(self.weights_input)
        self.add_item(self.refund_input)

    @staticmethod
    def _parse_quad(raw: str, *, as_float: bool = False):
        values = [x.strip() for x in (raw or "").split(",") if x.strip()]
        if len(values) != 4:
            raise ValueError("需要4个数值")
        return [float(v) if as_float else int(v) for v in values]

    async def callback(self, interaction: discord.Interaction):
        try:
            w_junk, w_normal, w_rare, w_legend = self._parse_quad(self.weights_input.value)
            r_junk, r_normal, r_rare, r_legend = self._parse_quad(self.refund_input.value, as_float=True)
        except ValueError:
            return await interaction.response.send_message(
                "❌ 输入格式错误，请按 `a,b,c,d` 填写 4 个数值。",
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

        cfg = get_lottery_config(load_role_data())
        self.parent_view.setup_ui()
        embed = self.parent_view.build_dashboard_embed()
        if interaction.message is not None:
            if not interaction.response.is_done():
                await interaction.response.edit_message(embed=embed, view=self.parent_view)
            else:
                await interaction.edit_original_response(embed=embed, view=self.parent_view)
        else:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)

        weights = cfg.get("weights", {})
        refund = cfg.get("refund", {})
        await interaction.followup.send(
            "✅ 概率与重复返还已更新（已保存）\n"
            f"- 概率(☆/★/★★/★★★)：{int(weights.get(str(RARITY_JUNK), 55))}/{int(weights.get(str(RARITY_NORMAL), 37))}/{int(weights.get(str(RARITY_RARE), 6))}/{int(weights.get(str(RARITY_LEGENDARY), 2))}\n"
            f"- 补偿(☆/★/★★/★★★)：{format_shells(refund.get(str(RARITY_JUNK), 0.5))}/{format_shells(refund.get(str(RARITY_NORMAL), 1.0))}/{format_shells(refund.get(str(RARITY_RARE), 2.0))}/{format_shells(refund.get(str(RARITY_LEGENDARY), 5.0))} 蛋壳",
            ephemeral=True,
        )


class AdminActionButton(discord.ui.Button):
    def __init__(self, parent_view: "RoleManagerView", action: str, *, label: str, emoji: str):
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.secondary, row=4)
        self.parent_view = parent_view
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        cfg = get_lottery_config(load_role_data())
        if self.action == "rarity":
            rarity_view = LotteryRarityConfigView(self.parent_view, interaction.guild)
            embed = discord.Embed(
                title="⚙️ 抽奖身份组批量配置",
                description="请选择奖池身份组（支持多选），再选择稀有度和分类，最后点击【应用设置】。",
                color=0x2B2D31,
            )
            await interaction.response.edit_message(embed=embed, view=rarity_view)
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
        self.remove_page = 0
        self.remove_page_size = 25
        self.remove_total_pages = 1
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

        total_remove_items = len(role_map)
        self.remove_total_pages = max(1, math.ceil(total_remove_items / self.remove_page_size)) if total_remove_items > 0 else 1
        if self.remove_page >= self.remove_total_pages:
            self.remove_page = max(0, self.remove_total_pages - 1)

        # 添加组件
        self.add_item(AdminAddRoleSelect(self, pool_type="lottery"))      # Row 0
        self.add_item(AdminAddRoleSelect(self, pool_type="claimable"))    # Row 1
        self.add_item(AdminAddRoleSelect(self, pool_type="notification")) # Row 2 (新增)
        self.add_item(AdminRemoveSelect(role_map, self, page=self.remove_page, page_size=self.remove_page_size))  # Row 3

        # 功能按钮 Row 4
        self.add_item(AdminActionButton(self, "rarity", label="稀有度", emoji="⭐"))
        self.add_item(AdminActionButton(self, "cost", label="抽奖消耗", emoji="💳"))
        self.add_item(AdminActionButton(self, "weights", label="概率/补偿", emoji="🎚️"))
        self.add_item(AdminRemovePageButton(self))
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
                f"单抽: **{format_shells(cfg.get('cost_single', 1.0))}** 蛋壳 | "
                f"五抽: **{format_shells(cfg.get('cost_five', 5.0))}** 蛋壳 | "
                f"十连: **{format_shells(cfg.get('cost_ten', 10.0))}** 蛋壳\n"
                f"概率(☆/★/★★/★★★): **{int(weights.get(str(RARITY_JUNK), 55))}/{int(weights.get(str(RARITY_NORMAL), 37))}/{int(weights.get(str(RARITY_RARE), 6))}/{int(weights.get(str(RARITY_LEGENDARY), 2))}**\n"
                f"补偿(☆/★/★★/★★★): **{format_shells(refunds.get(str(RARITY_JUNK), 0.5))}/{format_shells(refunds.get(str(RARITY_NORMAL), 1.0))}/{format_shells(refunds.get(str(RARITY_RARE), 2.0))}/{format_shells(refunds.get(str(RARITY_LEGENDARY), 5.0))}** 蛋壳"
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


class CommunityPanelManageView(discord.ui.View):
    def __init__(self, ctx, bot):
        super().__init__(timeout=600)
        self.ctx = ctx
        self.bot = bot
        self.owner_id = ctx.author.id if getattr(ctx, "author", None) else None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id and interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ 这个管理台只允许发起命令的管理员操作。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="发送面板", style=discord.ButtonStyle.success, emoji="📌", custom_id="community_admin_send_panel")
    async def send_panel_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        status = await deploy_role_panel(interaction.channel, interaction.guild, avatar_url)
        if status == "updated":
            await interaction.followup.send("✅ 已更新当前频道的小蛋报到面板。", ephemeral=True)
        else:
            await interaction.followup.send("✅ 已发送新的小蛋报到面板。", ephemeral=True)

    @discord.ui.button(label="身份管理", style=discord.ButtonStyle.primary, emoji="🎨", custom_id="community_admin_roles")
    async def role_manage_callback(self, button, interaction: discord.Interaction):
        view = RoleManagerView(interaction)
        embed = view.build_dashboard_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="事件刷新", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="community_admin_events")
    async def event_refresh_callback(self, button, interaction: discord.Interaction):
        events = load_random_events()
        await interaction.response.send_message(
            f"✅ 随机事件已读取：**{len(events)}** 条。\n来源：`cogs/points/random_events.json`",
            ephemeral=True,
        )

    @discord.ui.button(label="答题面板", style=discord.ButtonStyle.success, emoji="📝", custom_id="community_admin_prequiz_panel")
    async def prequiz_panel_callback(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from cogs.prequiz.views import deploy_prequiz_panel

        status = await deploy_prequiz_panel(self.bot)
        if status == "sent":
            await interaction.followup.send("✅ 小蛋预答题面板已发送。", ephemeral=True)
        elif status == "missing_channel_id":
            await interaction.followup.send("❌ 未配置 PRE_QUIZ_CHANNEL_ID。", ephemeral=True)
        else:
            await interaction.followup.send("❌ 找不到预答题频道。", ephemeral=True)

    @discord.ui.button(label="题库刷新", style=discord.ButtonStyle.secondary, emoji="📚", custom_id="community_admin_prequiz_bank")
    async def prequiz_bank_callback(self, button, interaction: discord.Interaction):
        from cogs.prequiz.storage import load_question_bank

        bank = load_question_bank()
        await interaction.response.send_message(
            f"✅ 预答题题库已读取：**{len(bank['multiple_choice'])}** 道客观题，**{len(bank['short_questions'])}** 道简答题。\n"
            f"来源：`cogs/prequiz/question_bank.json`",
            ephemeral=True,
        )


def build_community_manage_embed(guild: discord.Guild | None):
    embed = discord.Embed(
        title="⚙️ 社区面板管理台",
        description=(
            "集中管理小蛋报到、蛋壳、身份组与随机事件。\n"
            "后续预答题、加速卡、红包等管理入口也统一接入这里。"
        ),
        color=0x2B2D31,
    )
    if guild:
        embed.set_footer(text=guild.name, icon_url=guild.icon.url if guild.icon else None)
    return embed


# --- 面板部署辅助函数 ---
async def deploy_role_panel(channel, guild, user_avatar_url):
    """
    统一的面板部署逻辑
    """
    embed = build_role_panel_embed(guild, user_avatar_url)
    view = RoleClaimView()

    # 2. 检查是否需要更新
    data = load_role_data()
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
