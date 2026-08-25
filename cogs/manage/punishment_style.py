import re

import discord


NOTICE_COLOR = 0xE85D68
WARNING_COLOR = 0xF0A24A
RELIEF_COLOR = 0x57A773
LOG_COLOR = 0x586A8C
NOTICE_FOOTER = "奇米蛋社区管理中心 · 处罚记录已归档"
DM_FOOTER = "如有异议，请通过社区工单联系管理组"


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in str(text).splitlines())


def color_for_action(action: str) -> int:
    text = str(action).lower()
    if any(token in text for token in ("解除", "解禁", "解封", "撤销", "unmute", "unban", "unwarn")):
        return RELIEF_COLOR
    if "警告" in text or "warn" in text:
        return WARNING_COLOR
    return NOTICE_COLOR


def build_public_notice_embed(*, action: str, reason: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🚨 社区处罚公示・{action}",
        description=f"### ⚠️ 违规原因\n{_quote(reason)}",
        color=color_for_action(action),
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(text=NOTICE_FOOTER)
    return embed


def build_dm_embed(
    *,
    guild_name: str,
    action: str,
    reason: str,
    action_detail: str | None = None,
    notice_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="📨 社区管理通知",
        description=(
            f"你在 **{guild_name}** 收到了一项社区管理操作。\n\n"
            f"### ⚠️ 处理原因\n{_quote(reason)}"
        ),
        color=color_for_action(action),
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="📌 处理类型", value=f"**{action}**", inline=True)
    if action_detail:
        embed.add_field(name="⚖️ 处理结果", value=str(action_detail)[:1024], inline=True)
    if notice_url:
        embed.add_field(name="🔗 处罚公示", value=f"[点击查看完整公示]({notice_url})", inline=False)
    embed.set_footer(text=DM_FOOTER)
    return embed


def is_public_punishment_embed(embed: discord.Embed) -> bool:
    title = embed.title or ""
    return any(
        marker in title
        for marker in ("违规公示", "处罚公示", "广告风险处置通告", "社区处罚公示")
    )


def beautify_historical_notice(embed: discord.Embed) -> discord.Embed:
    styled = discord.Embed.from_dict(embed.to_dict())
    old_title = styled.title or "处罚记录"

    if "广告风险处置" in old_title:
        action = "广告风险处置"
    elif "・" in old_title:
        action = old_title.rsplit("・", 1)[-1].strip()
    elif "|" in old_title:
        action = old_title.rsplit("|", 1)[-1].strip()
    else:
        action = re.sub(r"^[^\w\u4e00-\u9fff]+", "", old_title).strip() or "处罚记录"

    styled.title = f"🚨 社区处罚公示・{action}"
    styled.color = discord.Color(color_for_action(action))
    styled.set_footer(text=NOTICE_FOOTER)

    field_names = {
        "违规者": "👤 违规成员",
        "处理对象": "👤 违规成员",
        "处罚原因": "⚠️ 处罚原因",
        "累计违规": "📌 累计记录",
        "处罚结果": "⚖️ 处罚结果",
        "执行结果": "⚖️ 执行结果",
        "自动处罚": "⚙️ 自动处罚",
        "原始消息": "🔗 原始消息",
        "目标数量": "👥 目标数量",
        "执行人": "🛡️ 执行管理",
    }
    new_fields = []
    for field in styled.fields:
        plain_name = re.sub(r"^[^\w\u4e00-\u9fff]+\s*", "", field.name)
        new_fields.append(
            {
                "name": field_names.get(plain_name, field.name),
                "value": field.value,
                "inline": field.inline,
            }
        )
    styled.clear_fields()
    for field in new_fields:
        styled.add_field(**field)
    return styled
