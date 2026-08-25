import discord

from .punishment_style import LOG_COLOR, NOTICE_FOOTER, color_for_action


def build_notice_embed(
    *,
    target_name: str,
    target_mention: str,
    reason: str,
    deleted_count: int,
    role_removed: bool = True,
    muted_text: str | None = None,
    target_id: int,
    punishment_id: int,
) -> discord.Embed:
    embed = discord.Embed(
        title="🚨 社区处罚公示・广告风险处置",
        description=(
            "检测到疑似盗号或恶意广告行为，系统已完成拦截与清理。\n"
            "> 🔒 请勿点击陌生链接，也不要向他人提供账号验证码。"
        ),
        color=color_for_action("广告风险处置"),
    )
    embed.add_field(
        name="👤 处理对象",
        value=target_mention,
        inline=True,
    )
    embed.add_field(name="🏷️ 昵称", value=target_name, inline=True)
    embed.add_field(name="🆔 用户 ID", value=f"`{target_id}`", inline=False)
    embed.add_field(name="📁 处罚编号", value=f"`#{punishment_id:06d}`", inline=True)
    embed.add_field(
        name="⚠️ 处罚原因",
        value=str(reason)[:1024],
        inline=True,
    )

    action_lines = []
    if role_removed:
        action_lines.append("✅ 已移除可操作身份组")
    action_lines.append(
        f"🧹 已清理 **{deleted_count}** 条广告痕迹"
        if deleted_count > 0
        else "🧹 未发现可清理的历史广告消息"
    )
    if muted_text:
        mute_icon = "⏳" if not str(muted_text).startswith("禁言失败") else "⚠️"
        action_lines.append(f"{mute_icon} {muted_text}")
    embed.add_field(
        name="🛡️ 执行结果",
        value="\n".join(action_lines),
        inline=False,
    )
    embed.set_footer(text=NOTICE_FOOTER)
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_log_embed(
    *,
    reason: str,
    executor_mention: str,
    target_mention: str,
    notice_url: str | None,
    detail_text: str | None,
    target_name: str,
    target_id: int,
    punishment_id: int,
) -> discord.Embed:
    embed = discord.Embed(title="🛡️ 处罚执行记录・广告风险处置", color=LOG_COLOR)
    embed.add_field(name="执行者", value=executor_mention, inline=True)
    embed.add_field(name="目标", value=target_mention, inline=True)
    embed.add_field(name="昵称", value=target_name, inline=True)
    embed.add_field(name="用户 ID", value=f"`{target_id}`", inline=False)
    embed.add_field(name="处罚编号", value=f"`#{punishment_id:06d}`", inline=True)
    embed.add_field(name="原因", value=reason, inline=False)

    if detail_text:
        embed.add_field(name="拦截详情", value=detail_text[:1024], inline=False)

    if notice_url:
        embed.add_field(name="公示链接", value=notice_url, inline=False)

    embed.timestamp = discord.utils.utcnow()
    return embed


def build_manage_regex_embed(*, target_mention: str, extracted_links: list[str]) -> discord.Embed:
    if extracted_links:
        lines = "\n".join(extracted_links[:30])
        if len(extracted_links) > 30:
            lines += f"\n... 以及其余 {len(extracted_links) - 30} 条"

        desc = f"提取到 {len(extracted_links)} 条链接并尝试加入规则库:\n```\n{lines}\n```"
    else:
        desc = "未从消息中提取到可用链接。"

    embed = discord.Embed(
        title="🧾 风险规则提取记录",
        description=f"目标: {target_mention}\n{desc}",
        color=LOG_COLOR,
    )
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_context_feedback(result: dict | None, mention: str, added_count: int) -> str:
    if result is None:
        punish = f"⏳ {mention} 正在被处理中，请勿重复操作。"
    else:
        actions = []
        if result.get("deleted_count", 0):
            actions.append(f"清理 {result['deleted_count']} 条消息")
        if result.get("role_removed"):
            actions.append("移除身份组")
        if result.get("mute_text"):
            actions.append(result["mute_text"])

        if actions:
            punish = f"🔨 已制裁 {mention}: {'，'.join(actions)}。"
        else:
            punish = f"⚠️ {mention} 无可执行清理目标。"

    link_line = (
        f"✅ 自动抓取并保存 {added_count} 条规则。"
        if added_count
        else "⚠️ 未提取到可新增规则。"
    )
    return f"{punish}\n{link_line}"
