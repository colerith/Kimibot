import re

import discord


NOTICE_COLOR = 0xE85D68
WARNING_COLOR = 0xF0A24A
RELIEF_COLOR = 0x57A773
MUTE_COLOR = 0xE76F51
KICK_COLOR = 0xD97706
BAN_COLOR = 0x8B1E3F
THIRD_PARTY_COLOR = 0x7C5CE7
AD_RISK_COLOR = 0xC0396B
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
    if "第三方" in text or "third" in text:
        return THIRD_PARTY_COLOR
    if "广告" in text or "风险" in text:
        return AD_RISK_COLOR
    if "封禁" in text or "ban" in text:
        return BAN_COLOR
    if "踢出" in text or "kick" in text:
        return KICK_COLOR
    if "禁言" in text or "mute" in text:
        return MUTE_COLOR
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
    target_mention: str,
    target_name: str,
    target_id: int,
    punishment_id: int,
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
    embed.add_field(name="👤 被处罚人", value=target_mention, inline=True)
    embed.add_field(name="🏷️ 昵称", value=target_name, inline=True)
    embed.add_field(name="🆔 用户 ID", value=f"`{target_id}`", inline=False)
    embed.add_field(name="📁 处罚编号", value=f"`#{punishment_id:06d}`", inline=True)
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
        for marker in (
            "违规公示",
            "处罚公示",
            "广告风险处置通告",
            "社区处罚公示",
            "已被广告拦截",
        )
    )


def action_from_notice_title(title: str | None) -> str:
    old_title = title or "处罚记录"
    if "广告风险处置" in old_title or "已被广告拦截" in old_title:
        return "广告风险处置"
    if "・" in old_title:
        return old_title.rsplit("・", 1)[-1].strip()
    if "|" in old_title:
        return old_title.rsplit("|", 1)[-1].strip()
    return re.sub(r"^[^\w\u4e00-\u9fff]+", "", old_title).strip() or "处罚记录"


def beautify_historical_notice(embed: discord.Embed) -> discord.Embed:
    styled = discord.Embed.from_dict(embed.to_dict())
    action = action_from_notice_title(styled.title)

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
