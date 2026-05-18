import discord


def build_notice_embed(*, target_name: str, target_mention: str, reason: str, deleted_count: int) -> discord.Embed:
    deleted_text = (
        f"移除身份组并清理了 {deleted_count} 条广告痕迹。"
        if deleted_count > 0
        else "已移除身份组，未发现可清理历史广告消息。"
    )

    embed = discord.Embed(
        title=f"{target_name} 已被广告拦截",
        description=(
            f"**目标**: {target_mention}\n"
            f"**原因**: {reason}\n"
            f"{deleted_text}\n\n"
            "请提高警惕，不要点击不明链接。"
        ),
        color=0xFF2233,
    )
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_log_embed(
    *,
    reason: str,
    executor_mention: str,
    target_mention: str,
    notice_url: str | None,
    detail_text: str | None,
) -> discord.Embed:
    embed = discord.Embed(title="防盗号广告拦截日志", color=0xA0AAB0)
    embed.add_field(name="执行者", value=executor_mention, inline=True)
    embed.add_field(name="目标", value=target_mention, inline=True)
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
        title="广告正则提取记录",
        description=f"目标: {target_mention}\n{desc}",
        color=0xFF9900,
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
