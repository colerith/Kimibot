import discord
from discord import ui
import asyncio
import inspect
import io
import uuid

import config
from cogs.points.storage import format_shells, grant_monthly_eligible_reward, modify_user_points

from .storage import (
    KIND_BUG,
    KIND_RECOMMENDATION,
    KIND_REPO,
    STATUS_DELETED,
    add_comment,
    add_owner_reply,
    can_create_submission,
    create_submission_once,
    find_by_message_id,
    grant_comment_reward,
    get_panel_info,
    get_submission,
    list_submissions,
    list_user_submissions,
    mark_deleted,
    parse_manual_reply_reward,
    random_reward,
    save_submission,
    set_panel_info,
    set_submission_notifications,
    submission_notifications_enabled,
    toggle_useful,
    update_submission_fields,
    validate_submission_content,
)


PANEL_COLOR = 0xFFD36A
SUBMISSION_MAIN_PANEL_COLOR = 0xB88F8A  # 莫兰迪灰粉 / Dusty Rose
REPO_SFW_CHANNEL_ID = 1441437806617563156
REPO_NSFW_CHANNEL_ID = 1417576370451513495
BUG_CHANNEL_ID = 1417577014096957554
RECOMMENDATION_CHANNEL_ID = 1536024803587137536

DOMAIN_OPTIONS = ["酒馆好物", "书籍安利", "影视安利", "音乐安利", "游戏安利", "便利生活", "其他类型"]
TYPE_OPTIONS = ["sfw", "nsfw"]
REPO_TYPE_OPTIONS = ["预设", "角色卡", "脚本", "美化", "其他"]
COMMENTS_PER_PAGE = 10
CONTENT_COLLAPSE_LIMIT = 350
_SUBMISSION_PUBLISH_LOCKS: dict[str, asyncio.Lock] = {}

RECOMMENDATION_DOMAIN_COLORS = {
    # 图一自然系配色
    "酒馆好物": 0xB66E4A,  # Warm Wood
    "书籍安利": 0xB7D3F4,  # Sunlit Linen
    "影视安利": 0xFFCDB0,  # Peach Blossom
    "音乐安利": 0xABABDC,  
    "游戏安利": 0x87A6BF,  # Harbor Sky
    "便利生活": 0xB9D4CF,  # Ocean Breeze
    "其他类型": 0xFFD47F,  # Honeycomb
}

REPO_SUBMISSION_COLOR = 0x6C8D5D  # 图二 Irish Charm
BUG_SUBMISSION_COLOR = 0x7359C0   # 图二 Fuchsia Blue


def _paragraph_style():
    text_style = getattr(discord, "TextStyle", None)
    if text_style is not None:
        return text_style.paragraph
    return discord.InputTextStyle.paragraph


def _text_input(label: str | None, *, value: str = "", style=None, max_length: int | None = None, required: bool = True):
    input_cls = getattr(ui, "TextInput", None) or getattr(ui, "InputText")
    kwargs = {"label": label, "required": required}
    if style is not None:
        kwargs["style"] = style
    if max_length is not None:
        kwargs["max_length"] = max_length

    params = inspect.signature(input_cls).parameters
    if "default" in params:
        kwargs["default"] = value
    elif "value" in params:
        kwargs["value"] = value

    return input_cls(**kwargs)


class CachedModalAttachment:
    """Keep modal uploads available until the user confirms the draft."""

    def __init__(self, attachment: discord.Attachment, data: bytes):
        self.filename = attachment.filename
        self.content_type = getattr(attachment, "content_type", None)
        self.size = getattr(attachment, "size", len(data))
        self._data = data

    async def to_file(self, *, spoiler: bool = False):
        return discord.File(io.BytesIO(self._data), filename=self.filename, spoiler=spoiler)


async def _cache_modal_attachments(attachments: list[discord.Attachment]) -> list[CachedModalAttachment]:
    cached = []
    for attachment in attachments[:9]:
        try:
            cached.append(CachedModalAttachment(attachment, await attachment.read()))
        except (discord.NotFound, discord.HTTPException):
            continue
    return cached


def _submission_config() -> dict:
    cfg = getattr(config, "SUBMISSIONS", {})
    return cfg if isinstance(cfg, dict) else {}


def _channel_id(kind: str, fields: dict) -> int:
    cfg = _submission_config()
    channels = cfg.get("CHANNEL_IDS", {}) if isinstance(cfg.get("CHANNEL_IDS", {}), dict) else {}
    if kind == KIND_REPO:
        if str(fields.get("content_type", "sfw")).lower() == "nsfw":
            return int(channels.get("repo_nsfw", REPO_NSFW_CHANNEL_ID))
        return int(channels.get("repo_sfw", REPO_SFW_CHANNEL_ID))
    if kind == KIND_BUG:
        return int(channels.get("bug", BUG_CHANNEL_ID))
    return int(channels.get("recommendation", RECOMMENDATION_CHANNEL_ID))


def _is_admin(member: discord.Member | discord.User | None) -> bool:
    if member is None:
        return False
    if member.id == int(getattr(config, "SERVER_OWNER_ID", 0) or 0):
        return True
    role_id = int(getattr(config, "SUPER_EGG_ROLE_ID", 0) or 0)
    return any(getattr(role, "id", 0) == role_id for role in getattr(member, "roles", []))


def _field(record: dict, key: str, default: str = "") -> str:
    fields = record.get("fields", {})
    if not isinstance(fields, dict):
        return default
    return str(fields.get(key, default) or default)


def _kind_label(kind: str) -> str:
    return {
        KIND_REPO: "repo",
        KIND_BUG: "捉虫",
        KIND_RECOMMENDATION: "安利",
    }.get(kind, kind)


def _spoiler(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"||{text.replace('||', '')}||"


def _clamp_comment_page(record: dict, comments: list[dict]) -> int:
    max_page = max(0, (len(comments) - 1) // COMMENTS_PER_PAGE)
    try:
        page = int(record.get("comment_page", 0) or 0)
    except (TypeError, ValueError):
        page = 0
    return min(max(page, 0), max_page)


def _quote_comment(content: str, limit: int = 900) -> str:
    content = str(content or "").strip()
    if len(content) > limit:
        content = content[: limit - 3] + "..."
    lines = content.splitlines() or ["*空*"]
    return "\n".join(f"> {line}" if line else ">" for line in lines)[:1024]


def _content_is_collapsed(record: dict) -> bool:
    fields = record.get("fields", {})
    if not isinstance(fields, dict):
        return False
    return len(str(fields.get("content", "") or "")) > CONTENT_COLLAPSE_LIMIT


def _content_preview(content: str, is_nsfw: bool) -> str:
    content = str(content or "没有填写内容")
    if len(content) <= CONTENT_COLLAPSE_LIMIT:
        return _spoiler(content, is_nsfw)
    preview = content[:CONTENT_COLLAPSE_LIMIT].rstrip() + "..."
    return _spoiler(
        f"{preview}\n\n*内容较长，已折叠。点击「展开全文」仅自己可见查看完整内容。*",
        is_nsfw,
    )


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🥚 奇米蛋投稿箱",
        description=(
            "📮 想给电波系repo、想捉虫电波系预设的小bug、想安利，都可以投进这里。\n"
            "🥚 奇米蛋会给认真投稿的小饱饱发一点亮晶晶的蛋壳。\n"
            "📎 投稿表单里可以直接拖入附件，最多上传 9 个。\n"
            "🧺 每类投稿每天最多 5 次，防止小蛋箱被塞爆~\n"
            "💬 盖楼回复也会随机掉蛋壳，每日最多 15 蛋壳~"
        ),
        color=SUBMISSION_MAIN_PANEL_COLOR,
    )
    embed.add_field(name="📦 我要repo", value="提交想 repo 的标题、类型与内容，仅限电波系的作品哦。", inline=False)
    embed.add_field(name="🐞 我要捉虫", value="提交问题对象与详细描述，仅限电波系的作品哦。", inline=False)
    embed.add_field(name="🌟 我要安利", value="分享好物、书籍、影视、音乐、游戏或生活经验。", inline=False)
    embed.add_field(name="🗂️ 管理投稿", value="修改或删除自己发过的投稿。", inline=False)
    embed.set_footer(text="每日投稿次数按北京时间刷新。")
    return embed


def build_submission_embed(record: dict) -> discord.Embed:
    kind = record.get("kind", "")
    fields = record.get("fields", {})
    content_type = str(fields.get("content_type", "sfw")).lower()
    is_nsfw = content_type == "nsfw"
    title = fields.get("title") or fields.get("target") or "未命名投稿"
    if kind == KIND_RECOMMENDATION:
        domain = str(fields.get("domain", "其他类型"))
        embed_color = RECOMMENDATION_DOMAIN_COLORS.get(domain, RECOMMENDATION_DOMAIN_COLORS["其他类型"])
    elif kind == KIND_BUG:
        embed_color = BUG_SUBMISSION_COLOR
    else:
        embed_color = REPO_SUBMISSION_COLOR
    kind_icon = {
        KIND_RECOMMENDATION: "🌟",
        KIND_BUG: "🐞",
        KIND_REPO: "📦",
    }.get(kind, "🥚")
    status_label = {
        "open": "🟢 收集中",
        "closed": "⚪ 已关闭",
        "deleted": "⚪ 已删除",
    }.get(str(record.get("status", "open")), str(record.get("status", "open")))
    type_label = "🔞 NSFW" if is_nsfw else "🌿 SFW"

    embed = discord.Embed(
        title=f"{kind_icon} {_kind_label(kind)}投稿｜{_spoiler(str(title), is_nsfw)}",
        color=embed_color,
    )
    embed.add_field(name="👤 投稿人", value=f"<@{record.get('author_id')}>", inline=True)
    embed.add_field(name="📌 状态", value=status_label, inline=True)
    if kind != KIND_BUG:
        embed.add_field(name="🛡️ 内容分级", value=type_label, inline=True)
    if kind == KIND_REPO:
        repo_type = str(fields.get("repo_type", "其他"))
        embed.add_field(name="🧩 作品类型", value=repo_type, inline=True)
    if kind == KIND_RECOMMENDATION:
        embed.add_field(name="🗂️ 安利领域", value=str(fields.get("domain", "其他类型")), inline=True)
    content = str(fields.get("content", "") or "没有填写内容")
    embed.add_field(name="📝 投稿内容", value=_content_preview(content, is_nsfw)[:1024], inline=False)
    replies = record.get("replies", [])
    if replies:
        latest = replies[-1]
        embed.add_field(
            name="💌 服主回复",
            value=f"**{latest.get('user_name', '服主')}：** {str(latest.get('content', ''))[:900]}",
            inline=False,
        )

    if kind == KIND_RECOMMENDATION:
        useful_count = len(record.get("useful_user_ids", []) if isinstance(record.get("useful_user_ids", []), list) else [])
        embed.add_field(name="👍 觉得有用", value=f"**{useful_count}** 人", inline=True)
        comments = record.get("comments", []) if isinstance(record.get("comments", []), list) else []
        if comments:
            page = _clamp_comment_page(record, comments)
            start = page * COMMENTS_PER_PAGE
            end = start + COMMENTS_PER_PAGE
            total_pages = max(1, (len(comments) - 1) // COMMENTS_PER_PAGE + 1)
            for index, row in enumerate(comments[start:end], start=start + 1):
                user_name = str(row.get("user_name", "匿名"))[:80]
                embed.add_field(
                    name=f"#{index} {user_name}",
                    value=_quote_comment(str(row.get("content", ""))),
                    inline=False,
                )
            embed.add_field(
                name="盖楼页码",
                value=f"第 **{page + 1}/{total_pages}** 页，每页 {COMMENTS_PER_PAGE} 条，共 {len(comments)} 条回复。",
                inline=False,
            )

    total_reward = float(record.get("base_reward", 0) or 0) + float(record.get("extra_reward", 0) or 0)
    embed.set_footer(text=f"投稿 #{record.get('id')} · 已奖励 {format_shells(total_reward)} 蛋壳")
    return embed


def _view_for_record(record: dict) -> discord.ui.View:
    if record.get("kind") == KIND_RECOMMENDATION:
        return RecommendationActionView(record)
    return OwnerReplyView(record)


def _submission_title(record: dict) -> str:
    fields = record.get("fields", {}) if isinstance(record.get("fields"), dict) else {}
    return str(fields.get("title") or fields.get("target") or "未命名投稿")


def _submission_jump_url(record: dict) -> str | None:
    guild_id = str(record.get("guild_id") or "")
    channel_id = str(record.get("channel_id") or "")
    message_id = str(record.get("message_id") or "")
    if not guild_id or not channel_id or not message_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


class SubmissionNotificationView(discord.ui.View):
    def __init__(self, record: dict):
        super().__init__(timeout=86400)
        self.record_id = str(record.get("id", ""))
        self.author_id = int(record.get("author_id") or 0)
        jump_url = _submission_jump_url(record)
        if jump_url:
            self.add_item(discord.ui.Button(
                label="查看我的投稿",
                emoji="🔗",
                style=discord.ButtonStyle.link,
                url=jump_url,
            ))

    @discord.ui.button(label="取消此投稿提醒", emoji="🔕", style=discord.ButtonStyle.secondary)
    async def unsubscribe(self, button, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("只有投稿者可以修改这条投稿的提醒。", ephemeral=True)
        record = set_submission_notifications(self.record_id, self.author_id, False)
        if not record:
            return await interaction.response.send_message("投稿不存在或已经删除。", ephemeral=True)
        button.label = "提醒已取消"
        button.emoji = "🔕"
        button.disabled = True
        await interaction.response.edit_message(view=self)


async def _notify_submission_event(
    client,
    record: dict,
    *,
    event: str,
    actor,
    content: str = "",
    reward: float = 0.0,
) -> bool:
    if not submission_notifications_enabled(record):
        return False
    if event != "owner_reply" and actor and str(getattr(actor, "id", "")) == str(record.get("author_id")):
        return False

    event_config = {
        "useful": ("👍 你的投稿被点赞啦", 0x73C991, "觉得这条投稿很有用"),
        "comment": ("💬 你的投稿收到了新回复", 0x6EA8E5, "在楼里留下了回复"),
        "owner_reply": ("💌 你收到了一封电波回信", 0xB58BE2, "回复了你的投稿"),
    }
    title, color, action = event_config.get(event, ("🔔 投稿有了新动态", PANEL_COLOR, "与你的投稿产生了互动"))
    actor_name = str(getattr(actor, "display_name", None) or getattr(actor, "name", None) or "一位小饱饱")
    actor_id = str(getattr(actor, "id", "") or "")
    actor_text = f"**{actor_name}**" + (f"（<@{actor_id}>）" if actor_id else "")
    embed = discord.Embed(
        title=title,
        description=(
            f"你的 **{_kind_label(record.get('kind', ''))}投稿 · {_submission_title(record)[:100]}** 有了新动态。"
        ),
        color=color,
    )
    embed.add_field(name="✨ 互动来自", value=f"{actor_text}\n{action}", inline=False)
    if content:
        is_nsfw = str(record.get("fields", {}).get("content_type", "sfw")).lower() == "nsfw"
        preview = _quote_comment(content, limit=700)
        embed.add_field(name="📝 回复预览", value=_spoiler(preview, is_nsfw), inline=False)
    if event == "useful":
        useful_count = len(record.get("useful_user_ids", []) if isinstance(record.get("useful_user_ids"), list) else [])
        embed.add_field(name="👍 当前点赞", value=f"**{useful_count}** 人觉得有用", inline=True)
    if reward > 0:
        embed.add_field(name="🥚 追加奖励", value=f"**+{format_shells(reward)}** 蛋壳", inline=True)
    embed.set_footer(text=f"投稿 #{record.get('id')} · 可在下方直接查看或取消提醒")

    try:
        user = await client.fetch_user(int(record.get("author_id")))
        await user.send(embed=embed, view=SubmissionNotificationView(record))
        return True
    except Exception:
        return False


async def _attachments_to_files(attachments, *, spoiler: bool = False) -> list[discord.File]:
    files = []
    for attachment in attachments[:9]:
        try:
            files.append(await attachment.to_file(spoiler=spoiler))
        except (discord.NotFound, discord.HTTPException, AttributeError):
            continue
    return files


async def publish_or_update_submission(client, record: dict, attachments=None, *, force_resend: bool = False) -> tuple[dict, str]:
    record_id = str(record.get("id", ""))
    lock = _SUBMISSION_PUBLISH_LOCKS.setdefault(record_id, asyncio.Lock())
    async with lock:
        latest = get_submission(record_id) if record_id else None
        if latest:
            record = latest
        return await _publish_or_update_submission_unlocked(
            client,
            record,
            attachments=attachments,
            force_resend=force_resend,
        )


async def _publish_or_update_submission_unlocked(client, record: dict, attachments=None, *, force_resend: bool = False) -> tuple[dict, str]:
    channel_id = _channel_id(record.get("kind", ""), record.get("fields", {}))
    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    if not channel:
        return record, "missing_channel"

    old_channel_id = int(record.get("channel_id") or 0)
    old_message_id = int(record.get("message_id") or 0)
    view = _view_for_record(record)
    content_type = str(record.get("fields", {}).get("content_type", "sfw")).lower()
    files = await _attachments_to_files(attachments or [], spoiler=content_type == "nsfw")
    if files:
        force_resend = True

    if old_channel_id == channel_id and old_message_id and not force_resend:
        try:
            message = await channel.fetch_message(old_message_id)
            embed = build_submission_embed(record)
            await message.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            return record, "updated"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    if old_channel_id and old_message_id and (old_channel_id != channel_id or force_resend):
        try:
            old_channel = client.get_channel(old_channel_id) or await client.fetch_channel(old_channel_id)
            old_message = await old_channel.fetch_message(old_message_id)
            await old_message.delete()
        except Exception:
            pass

    embed = build_submission_embed(record)
    message = await channel.send(embed=embed, view=view, files=files, allowed_mentions=discord.AllowedMentions.none())
    record["channel_id"] = str(channel.id)
    record["message_id"] = str(message.id)
    if files:
        record["attachments"] = [att.url for att in message.attachments[:9]]
        save_submission(record)
        try:
            await message.edit(
                embed=build_submission_embed(record),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass
    save_submission(record)
    return record, "sent"


async def refresh_all_submission_panels(client) -> dict:
    refreshed = 0
    skipped = 0
    for record in list_submissions():
        channel_id = int(record.get("channel_id") or 0)
        message_id = int(record.get("message_id") or 0)
        if not channel_id or not message_id:
            skipped += 1
            continue
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            await message.edit(
                embed=build_submission_embed(record),
                view=_view_for_record(record),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            refreshed += 1
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            skipped += 1
    return {"refreshed": refreshed, "skipped": skipped}


async def refresh_submission_main_panel(client) -> bool:
    panel_info = get_panel_info()
    channel_id = int(panel_info.get("channel_id") or 0)
    message_id = int(panel_info.get("message_id") or 0)
    if not channel_id or not message_id:
        return False
    try:
        channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
        message = await channel.fetch_message(message_id)
        await message.edit(content=None, embed=None, view=SubmissionPanelView())
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def deploy_submission_panel(channel, bot) -> str:
    view = SubmissionPanelView()
    panel_info = get_panel_info()
    if str(channel.id) == str(panel_info.get("channel_id", "")) and panel_info.get("message_id"):
        try:
            message = await channel.fetch_message(int(panel_info["message_id"]))
            await message.edit(content=None, embed=None, view=view)
            return "updated"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    message = await channel.send(view=view)
    set_panel_info(channel.id, message.id)
    return "sent"


class SubmissionModal(ui.DesignerModal):
    def __init__(
        self,
        kind: str,
        record: dict | None = None,
        *,
        content_type: str | None = None,
        repo_type: str | None = None,
        domain: str | None = None,
    ):
        self.kind = kind
        self.record = record
        self.content_type = (content_type or _field(record or {}, "content_type", "sfw")).lower()
        self.repo_type = repo_type or _field(record or {}, "repo_type", "其他")
        self.domain = domain or _field(record or {}, "domain", "其他类型")
        is_edit = record is not None
        title = "修改投稿" if is_edit else "提交投稿"
        super().__init__(title=f"{title} · {_kind_label(kind)}")

        if kind == KIND_REPO:
            subject_label = "repo 标题"
            content_label = "repo 内容"
            subject_value = _field(record or {}, "title")
        elif kind == KIND_BUG:
            subject_label = "捉虫对象"
            content_label = "捉虫内容"
            subject_value = _field(record or {}, "target")
        else:
            subject_label = "安利对象"
            content_label = "安利内容"
            subject_value = _field(record or {}, "target")

        self.subject_input = _text_input(None, value=subject_value, max_length=120, required=True)
        self.content_input = _text_input(
            None,
            value=_field(record or {}, "content"),
            style=_paragraph_style(),
            max_length=2000,
            required=True,
        )
        self.attachment_upload = ui.FileUpload(required=False, min_values=0, max_values=9)
        self.add_item(ui.Label(subject_label, self.subject_input))
        self.add_item(ui.Label(content_label, self.content_input))
        self.add_item(
            ui.Label(
                "投稿附件（可选）",
                self.attachment_upload,
                description="可直接拖入或选择文件，最多 9 个；修改投稿时上传新附件会替换原附件。",
            )
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("这个投稿箱只能在服务器里使用。", ephemeral=True)

        if self.kind == KIND_REPO:
            content_type = self.content_type if self.content_type in TYPE_OPTIONS else "sfw"
            repo_type = self.repo_type if self.repo_type in REPO_TYPE_OPTIONS else "其他"
            fields = {
                "title": self.subject_input.value.strip(),
                "content_type": content_type,
                "repo_type": repo_type,
                "content": self.content_input.value.strip(),
            }

        elif self.kind == KIND_BUG:
            fields = {
                "target": self.subject_input.value.strip(),
                "content": self.content_input.value.strip(),
            }
        else:
            content_type = self.content_type if self.content_type in TYPE_OPTIONS else "sfw"
            domain = self.domain if self.domain in DOMAIN_OPTIONS else "其他类型"
            fields = {
                "target": self.subject_input.value.strip(),
                "content_type": content_type,
                "domain": domain,
                "content": self.content_input.value.strip(),
            }

        quality = validate_submission_content(fields.get("content", ""))
        if not quality["valid"]:
            if quality["reason"] == "too_short":
                notice = (
                    f"📝 投稿正文至少需要 **{quality['minimum']}** 个有效文字，"
                    f"目前只有 **{quality['length']}** 个。"
                )
            else:
                notice = "🚫 投稿正文包含明显的重复灌水内容，请写清楚具体信息后再提交。"
            return await interaction.response.send_message(notice, ephemeral=True)

        if self.record and str(self.record.get("author_id")) != str(interaction.user.id):
            return await interaction.response.send_message("只能修改自己的投稿。", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        attachments = await _cache_modal_attachments(self.attachment_upload.values or [])

        draft_record = {
            "id": self.record.get("id", "draft") if self.record else "draft",
            "author_id": str(interaction.user.id),
            "kind": self.kind,
            "fields": fields,
            "attachments": self.record.get("attachments", []) if self.record else [],
            "status": self.record.get("status", "preview") if self.record else "preview",
            "base_reward": self.record.get("base_reward", 0) if self.record else 0,
            "extra_reward": self.record.get("extra_reward", 0) if self.record else 0,
        }
        embed = build_submission_embed(draft_record)
        embed.title = f"投稿预览 · {_kind_label(self.kind)}"
        if attachments:
            embed.add_field(name="待上传附件", value=f"已从表单收纳 **{len(attachments)}/9** 个附件。", inline=False)
        embed.set_footer(text="确认无误后点击完成投稿。")
        await interaction.followup.send(
            embed=embed,
            view=SubmissionDraftView(
                owner_id=interaction.user.id,
                kind=self.kind,
                fields=fields,
                attachments=attachments,
                record_id=str(self.record["id"]) if self.record else None,
            ),
            ephemeral=True,
        )


class OwnerReplyModal(discord.ui.Modal):
    def __init__(self, record: dict):
        self.record = record
        super().__init__(title=f"回复 {_kind_label(record.get('kind', ''))}投稿")
        self.add_item(_text_input("回复内容", style=_paragraph_style(), max_length=1500, required=True))
        self.add_item(_text_input("手动追加蛋壳（可选）", max_length=8, required=False))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        record = get_submission(self.record["id"])
        if not record:
            return await interaction.followup.send("投稿记录不存在。", ephemeral=True)
        try:
            manual_reward = parse_manual_reply_reward(self.children[1].value)
        except ValueError as error:
            return await interaction.followup.send(f"❌ {error}", ephemeral=True)
        base_reward = manual_reward if manual_reward is not None else random_reward(record.get("kind", KIND_REPO), "reply")
        reply_content = self.children[0].value.strip()
        record = add_owner_reply(record["id"], interaction.user.id, interaction.user.display_name, reply_content, base_reward)
        if not record:
            return await interaction.followup.send("投稿已删除，不能回复。", ephemeral=True)
        if manual_reward is not None:
            modify_user_points(
                int(record["author_id"]),
                manual_reward,
                interaction.guild_id,
                source=f"submission_reply_{record.get('kind')}_manual",
                reason=f"submission_id={record['id']};reward_mode=manual",
            )
            reward = float(manual_reward)
        else:
            reward_result = grant_monthly_eligible_reward(
                int(record["author_id"]),
                interaction.guild_id,
                base_reward,
                source=f"submission_reply_{record.get('kind')}",
                reason=f"submission_id={record['id']};reward_mode=random",
            )
            reward = float(reward_result["amount"])
        reward_difference = round(reward - float(base_reward), 1)
        if reward_difference:
            record["replies"][-1]["reward"] = reward
            record["extra_reward"] = round(float(record.get("extra_reward", 0) or 0) + reward_difference, 1)
            record = save_submission(record)
        await publish_or_update_submission(interaction.client, record)
        dm_sent = await _notify_submission_event(
            interaction.client,
            record,
            event="owner_reply",
            actor=interaction.user,
            content=reply_content,
            reward=reward,
        )
        reward_mode = "手动填写" if manual_reward is not None else "默认随机"
        dm_status = "💌 私信与奖励提醒已送达。" if dm_sent else "⚠️ 私信未送达（用户可能关闭私信或取消了该投稿提醒）。"
        await interaction.followup.send(
            f"✅ 已发送电波回信并追加 **{format_shells(reward)}** 蛋壳（{reward_mode}）。\n{dm_status}",
            ephemeral=True,
        )


class CommentModal(discord.ui.Modal):
    def __init__(self, record: dict):
        self.record = record
        super().__init__(title="盖楼回复")
        self.add_item(_text_input("评论内容", style=_paragraph_style(), max_length=500, required=True))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        record = add_comment(self.record["id"], interaction.user.id, interaction.user.display_name, self.children[0].value.strip())
        if not record:
            return await interaction.followup.send("投稿不存在或已经删除。", ephemeral=True)
        comments = record.get("comments", []) if isinstance(record.get("comments", []), list) else []
        record["comment_page"] = max(0, (len(comments) - 1) // COMMENTS_PER_PAGE)
        save_submission(record)
        await publish_or_update_submission(interaction.client, record)
        await _notify_submission_event(
            interaction.client,
            record,
            event="comment",
            actor=interaction.user,
            content=self.children[0].value.strip(),
        )
        reward_result = grant_comment_reward(guild_id=interaction.guild_id, user_id=interaction.user.id)
        awarded = float(reward_result.get("awarded", 0.0))
        if awarded > 0:
            credited = grant_monthly_eligible_reward(
                interaction.user.id,
                interaction.guild_id,
                awarded,
                source=f"submission_comment_{record.get('kind', KIND_REPO)}",
                reason=f"submission_id={record['id']};daily_used={format_shells(reward_result.get('used', 0))}",
            )
            total_awarded = float(credited.get("amount", awarded))
            monthly_bonus = float(credited.get("monthly_bonus", 0))
            msg = (
                f"✅ 评论已经盖到楼里啦，奇米蛋塞给你 **{format_shells(total_awarded)}** 蛋壳~\n"
                + (f"月卡加成：+**{format_shells(monthly_bonus)}** 蛋壳\n" if monthly_bonus > 0 else "")
                + f"今日盖楼奖励：**{format_shells(reward_result.get('used', 0))} / {format_shells(reward_result.get('cap', 15.0))}**"
            )
        else:
            msg = (
                "✅ 评论已经盖到楼里啦。\n"
                f"今日盖楼奖励已达到 **{format_shells(reward_result.get('cap', 15.0))}** 蛋壳上限~"
            )
        await interaction.followup.send(msg, ephemeral=True)


class SubmissionTypeSelect(discord.ui.Select):
    def __init__(self, kind: str, record: dict | None = None):
        self.kind = kind
        self.record = record
        current = _field(record or {}, "content_type", "sfw").lower()
        options = [
            discord.SelectOption(
                label="SFW",
                value="sfw",
                emoji="🌤️",
                description="普通内容，正常展示。",
                default=current == "sfw",
            ),
            discord.SelectOption(
                label="NSFW",
                value="nsfw",
                emoji="🌙",
                description="敏感内容，图文会使用剧透效果。",
                default=current == "nsfw",
            ),
        ]
        super().__init__(placeholder="选择内容分级（SFW / NSFW）", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        content_type = self.values[0]
        self.view.selected_content_type = content_type
        for option in self.options:
            option.default = option.value == content_type
        await interaction.response.edit_message(
            content=f"已选择类型：**{content_type.upper()}**。确认后点击「下一步」。",
            view=self.view,
        )


class SubmissionTypeSelectView(discord.ui.View):
    def __init__(self, owner_id: int, kind: str, record: dict | None = None):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.kind = kind
        self.record = record
        self.selected_content_type = _field(record or {}, "content_type", "sfw").lower()
        self.add_item(SubmissionTypeSelect(kind, record))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("这个选择面板只属于发起它的人。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="下一步", emoji="➡️", style=discord.ButtonStyle.primary, row=1)
    async def next_step(self, button, interaction: discord.Interaction):
        content_type = self.selected_content_type if self.selected_content_type in TYPE_OPTIONS else "sfw"
        if self.kind == KIND_REPO:
            return await interaction.response.edit_message(
                content="继续选择 repo 的电波系作品类型。",
                embed=None,
                view=RepoWorkTypeSelectView(
                    interaction.user.id,
                    content_type,
                    self.record,
                ),
            )

        await interaction.response.edit_message(
            content="继续选择安利领域。",
            embed=None,
            view=RecommendationDomainSelectView(interaction.user.id, content_type, self.record),
        )


class RepoWorkTypeSelect(discord.ui.Select):
    def __init__(self, record: dict | None = None):
        current = _field(record or {}, "repo_type")
        emoji_map = {
            "预设": "🧠",
            "角色卡": "🎭",
            "脚本": "🧩",
            "美化": "🎨",
            "其他": "📦",
        }
        options = [
            discord.SelectOption(
                label=repo_type,
                value=repo_type,
                emoji=emoji_map[repo_type],
                default=current == repo_type,
            )
            for repo_type in REPO_TYPE_OPTIONS
        ]
        super().__init__(
            placeholder="选择 repo 的电波系作品类型",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        repo_type = self.values[0]
        self.view.selected_repo_type = repo_type
        for option in self.options:
            option.default = option.value == repo_type
        await interaction.response.edit_message(
            content=f"已选择作品类型：**{repo_type}**。确认后点击「下一步」。",
            view=self.view,
        )


class RepoWorkTypeSelectView(discord.ui.View):
    def __init__(self, owner_id: int, content_type: str, record: dict | None = None):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.content_type = content_type
        self.record = record
        current = _field(record or {}, "repo_type")
        self.selected_repo_type = current if current in REPO_TYPE_OPTIONS else None
        self.add_item(RepoWorkTypeSelect(record))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("这个选择面板只属于发起它的人。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="下一步", emoji="➡️", style=discord.ButtonStyle.primary, row=1)
    async def next_step(self, button, interaction: discord.Interaction):
        if self.selected_repo_type not in REPO_TYPE_OPTIONS:
            return await interaction.response.send_message("请先选择电波系作品类型。", ephemeral=True)
        await interaction.response.send_modal(
            SubmissionModal(
                KIND_REPO,
                self.record,
                content_type=self.content_type,
                repo_type=self.selected_repo_type,
            )
        )


class RecommendationDomainSelect(discord.ui.Select):
    def __init__(self, content_type: str, record: dict | None = None):
        self.content_type = content_type
        self.record = record
        current = _field(record or {}, "domain", "其他类型")
        options = [
            discord.SelectOption(
                label=domain,
                value=domain,
                emoji=emoji,
                default=current == domain,
            )
            for domain, emoji in [
                ("酒馆好物", "🍻"),
                ("书籍安利", "📚"),
                ("影视安利", "🎬"),
                ("音乐安利", "🎵"),
                ("游戏安利", "🎮"),
                ("便利生活", "🧰"),
                ("其他类型", "✨"),
            ]
        ]
        super().__init__(placeholder="选择安利领域", min_values=1, max_values=1, options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_domain = self.values[0]
        for option in self.options:
            option.default = option.value == self.values[0]
        await interaction.response.edit_message(
            content=f"已选择领域：**{self.values[0]}**。确认后点击「下一步」。",
            view=self.view,
        )


class RecommendationDomainSelectView(discord.ui.View):
    def __init__(self, owner_id: int, content_type: str, record: dict | None = None):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.content_type = content_type
        self.record = record
        self.selected_domain = _field(record or {}, "domain", "其他类型")
        self.add_item(RecommendationDomainSelect(content_type, record))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("这个选择面板只属于发起它的人。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="下一步", emoji="➡️", style=discord.ButtonStyle.primary, row=1)
    async def next_step(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(
            SubmissionModal(
                KIND_RECOMMENDATION,
                self.record,
                content_type=self.content_type,
                domain=self.selected_domain,
            )
        )


class SubmissionPanelView(ui.DesignerView):
    def __init__(self):
        super().__init__(timeout=None)
        repo_button = ui.Button(label="我要repo", emoji="📦", style=discord.ButtonStyle.primary, custom_id="submission_panel_repo")
        bug_button = ui.Button(label="我要捉虫", emoji="🐞", style=discord.ButtonStyle.danger, custom_id="submission_panel_bug")
        recommend_button = ui.Button(label="我要安利", emoji="🌟", style=discord.ButtonStyle.success, custom_id="submission_panel_recommend")
        manage_button = ui.Button(label="管理投稿", emoji="🗂️", style=discord.ButtonStyle.secondary, custom_id="submission_panel_manage")
        repo_button.callback = self.repo
        bug_button.callback = self.bug
        recommend_button.callback = self.recommend
        manage_button.callback = self.manage
        self.add_item(
            ui.Container(
                ui.TextDisplay(
                    "# 🥚 奇米蛋投稿箱\n"
                    "📮 想给电波系 repo、捉虫电波系预设的小 bug，或分享一份安利，都可以投进这里。\n\n"
                    "🥚 认真投稿会获得亮晶晶的蛋壳奖励。\n"
                    "📝 投稿正文至少 15 个有效文字，重复灌水会被拦截。\n"
                    "📎 投稿表单内可直接拖入附件，最多上传 9 个。\n"
                    "🧺 每类投稿每天最多 5 次，按北京时间刷新。"
                ),
                ui.Separator(),
                ui.TextDisplay(
                    "**📦 我要repo**　提交电波系作品相关的 repo 需求。\n"
                    "**🐞 我要捉虫**　反馈电波系作品的小 bug。\n"
                    "**🌟 我要安利**　分享好物、书影音、游戏或生活经验。\n"
                    "**🗂️ 管理投稿**　修改或删除自己发过的投稿。"
                ),
                ui.Separator(),
                ui.ActionRow(repo_button, bug_button, recommend_button, manage_button),
                color=SUBMISSION_MAIN_PANEL_COLOR,
            )
        )

    async def repo(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        await interaction.followup.send(
            "先选择内容分级（SFW / NSFW）。",
            view=SubmissionTypeSelectView(interaction.user.id, KIND_REPO),
            ephemeral=True,
        )

    async def bug(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(SubmissionModal(KIND_BUG))
        except discord.NotFound:
            return

    async def recommend(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        await interaction.followup.send(
            "先选择安利类型。",
            view=SubmissionTypeSelectView(interaction.user.id, KIND_RECOMMENDATION),
            ephemeral=True,
        )

    async def manage(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return
        rows = list_user_submissions(interaction.user.id, interaction.guild_id)
        if not rows:
            return await interaction.followup.send("你还没有可管理的投稿。", ephemeral=True)
        await interaction.followup.send(
            "选择一条投稿进行修改或删除。",
            view=SubmissionManageView(interaction.user.id, rows),
            ephemeral=True,
        )


class SubmissionDraftView(discord.ui.View):
    def __init__(self, *, owner_id: int, kind: str, fields: dict, attachments=None, record_id: str | None = None):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.kind = kind
        self.fields = fields
        self.attachments = list(attachments or [])[:9]
        self.record_id = record_id
        self.request_id = uuid.uuid4().hex
        self._submitting = False
        self._finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("这个投稿确认面板只属于发起它的人。", ephemeral=True)
            return False
        return True

    def _build_status_embed(self, interaction: discord.Interaction, temp_notify: str = "") -> discord.Embed:
        draft_record = {
            "id": self.record_id or "draft",
            "author_id": str(interaction.user.id),
            "kind": self.kind,
            "fields": self.fields,
            "attachments": [],
            "status": "preview",
            "base_reward": 0,
            "extra_reward": 0,
        }
        if self.record_id:
            old = get_submission(self.record_id)
            if old:
                draft_record.update({
                    "attachments": old.get("attachments", []),
                    "status": old.get("status", "preview"),
                    "base_reward": old.get("base_reward", 0),
                    "extra_reward": old.get("extra_reward", 0),
                })

        embed = build_submission_embed(draft_record)
        embed.title = f"投稿预览 · {_kind_label(self.kind)}"
        embed.add_field(
            name="投稿附件",
            value=f"已从表单收纳 **{len(self.attachments)}/9** 个附件。",
            inline=False,
        )
        embed.set_footer(text=temp_notify or "确认无误后点击完成投稿。")
        return embed

    @discord.ui.button(label="完成投稿", style=discord.ButtonStyle.success, emoji="✅")
    async def finish(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            return await interaction.followup.send("这个投稿箱只能在服务器里使用。", ephemeral=True)
        if self._finished:
            return await interaction.followup.send("这份投稿已经完成啦，重复点击不会再次发布。", ephemeral=True)
        if self._submitting:
            return await interaction.followup.send("这份投稿正在投递中，请不要重复点击~", ephemeral=True)

        self._submitting = True
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        try:
            await interaction.edit_original_response(
                embed=self._build_status_embed(interaction, "正在投递，请稍等一下~"),
                view=self,
            )
        except (discord.NotFound, discord.HTTPException):
            pass

        try:
            msg = await self._complete_submission(interaction)
            if msg is None:
                return
            self._finished = True
            self.clear_items()
            try:
                await interaction.edit_original_response(
                    embed=self._build_status_embed(interaction, "投稿流程已完成。"),
                    view=self,
                )
            except (discord.NotFound, discord.HTTPException):
                pass
            await interaction.followup.send(msg, ephemeral=True)
        except Exception as error:
            print(
                f"[投稿箱] 投稿处理失败 request={self.request_id} user={interaction.user.id} "
                f"kind={self.kind} error={error!r}"
            )
            await interaction.followup.send("投稿暂时没有送成功，按钮已经恢复，可以稍后重试。", ephemeral=True)
        finally:
            self._submitting = False
            if not self._finished:
                for item in self.children:
                    if hasattr(item, "disabled"):
                        item.disabled = False
                try:
                    await interaction.edit_original_response(
                        embed=self._build_status_embed(interaction),
                        view=self,
                    )
                except (discord.NotFound, discord.HTTPException):
                    pass

    async def _complete_submission(self, interaction: discord.Interaction) -> str | None:
        if not interaction.guild_id:
            return None

        quality = validate_submission_content(self.fields.get("content", ""))
        if not quality["valid"]:
            message = (
                f"投稿正文至少需要 **{quality['minimum']}** 个有效文字，目前只有 **{quality['length']}** 个。"
                if quality["reason"] == "too_short"
                else "投稿正文被识别为明显重复灌水，请修改成有实际信息的内容。"
            )
            await interaction.followup.send(f"🚫 {message}", ephemeral=True)
            return None

        if not self.record_id:
            limit_status = can_create_submission(
                guild_id=interaction.guild_id,
                author_id=interaction.user.id,
                kind=self.kind,
            )
            if not limit_status["allowed"]:
                if limit_status.get("blocked"):
                    await interaction.followup.send(
                        "🚫 你今天有投稿因无意义灌水被撤回，今日已禁止继续投稿。\n"
                        "请于北京时间次日再认真填写投稿内容。",
                        ephemeral=True,
                    )
                    return None
                await interaction.followup.send(
                    f"今天的 **{_kind_label(self.kind)}** 投稿已经达到上限啦。\n"
                    f"每类投稿每日最多 **{limit_status['limit']}** 次，你今天已经提交 **{limit_status['used']}** 次。\n"
                    "明天北京时间刷新后再来投递~",
                    ephemeral=True,
                )
                return None

        attachments = self.attachments

        if self.record_id:
            record = update_submission_fields(self.record_id, self.fields)
            if not record:
                await interaction.followup.send("投稿不存在或已经删除。", ephemeral=True)
                return None
            record, status = await publish_or_update_submission(
                interaction.client,
                record,
                attachments=attachments,
                force_resend=bool(attachments),
            )
            msg = f"✅ 投稿已更新。({status})"
        else:
            rolled_reward = random_reward(self.kind, "base")
            record, created = create_submission_once(
                guild_id=interaction.guild_id,
                author_id=interaction.user.id,
                author_name=interaction.user.display_name,
                kind=self.kind,
                fields=self.fields,
                base_reward=rolled_reward,
                request_id=self.request_id,
            )
            reward_result = grant_monthly_eligible_reward(
                interaction.user.id,
                interaction.guild_id,
                float(record.get("base_reward", rolled_reward) or 0),
                source=f"submission_{self.kind}",
                reason=f"submission_id={record['id']}",
                idempotency_key=f"submission:{self.request_id}",
            )
            reward = float(reward_result["amount"])
            if float(record.get("base_reward", 0) or 0) != reward:
                record["base_reward"] = reward
                record = save_submission(record)
            record, status = await publish_or_update_submission(interaction.client, record, attachments=attachments)
            prefix = "✅ 投稿已送到小蛋箱" if created else "✅ 重复请求已自动合并"
            msg = f"{prefix}！本次获得 **{format_shells(reward)}** 蛋壳。({status})"

        if attachments:
            msg += f"\n📎 已随投稿上传 {len(attachments)} 个附件。"
        return msg

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, button, interaction: discord.Interaction):
        self.clear_items()
        await interaction.response.edit_message(
            embed=self._build_status_embed(interaction, "已取消本次投稿。"),
            view=self,
        )


def _build_full_content_embed(record: dict) -> discord.Embed:
    fields = record.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}
    content_type = str(fields.get("content_type", "sfw")).lower()
    title = fields.get("title") or fields.get("target") or "未命名投稿"
    content = str(fields.get("content", "") or "没有填写内容")
    embed = discord.Embed(
        title=f"展开全文 · {_kind_label(record.get('kind', ''))} · {title}",
        description=_spoiler(content[:3900], content_type == "nsfw"),
        color=PANEL_COLOR,
    )
    embed.add_field(name="投稿ID", value=str(record.get("id", "")), inline=True)
    if record.get("kind") != KIND_BUG:
        embed.add_field(name="类型", value=content_type, inline=True)
    if record.get("kind") == KIND_REPO:
        embed.add_field(name="作品类型", value=str(fields.get("repo_type", "其他")), inline=True)
    if record.get("kind") == KIND_RECOMMENDATION:
        embed.add_field(name="领域", value=str(fields.get("domain", "其他类型")), inline=True)
    embed.set_footer(text="仅你可见的完整投稿内容。")
    return embed


class OwnerReplyView(discord.ui.View):
    def __init__(self, record: dict | None = None):
        super().__init__(timeout=None)
        if record and not _content_is_collapsed(record):
            for child in self.children:
                if getattr(child, "custom_id", "") == "submission_expand_content_owner":
                    child.disabled = True

    @discord.ui.button(label="展开全文", emoji="📖", style=discord.ButtonStyle.secondary, custom_id="submission_expand_content_owner")
    async def expand_content(self, button, interaction: discord.Interaction):
        record = find_by_message_id(interaction.message.id)
        if not record:
            return await interaction.response.send_message("没有找到投稿记录。", ephemeral=True)
        await interaction.response.send_message(embed=_build_full_content_embed(record), ephemeral=True)

    @discord.ui.button(label="电波回信", emoji="💌", style=discord.ButtonStyle.primary, custom_id="submission_owner_reply")
    async def reply(self, button, interaction: discord.Interaction):
        if not _is_admin(interaction.user):
            return await interaction.response.send_message("只有服主或小蛋管理组可以回复这条投稿。", ephemeral=True)
        record = find_by_message_id(interaction.message.id)
        if not record:
            return await interaction.response.send_message("没有找到投稿记录。", ephemeral=True)
        await interaction.response.send_modal(OwnerReplyModal(record))


class RecommendationActionView(discord.ui.View):
    def __init__(self, record: dict | None = None):
        super().__init__(timeout=None)
        if record:
            useful_count = len(record.get("useful_user_ids", []) if isinstance(record.get("useful_user_ids", []), list) else [])
            comments = record.get("comments", []) if isinstance(record.get("comments", []), list) else []
            page = _clamp_comment_page(record, comments)
            max_page = max(0, (len(comments) - 1) // COMMENTS_PER_PAGE)
            for child in self.children:
                if getattr(child, "custom_id", "") == "submission_useful":
                    child.label = f"觉得有用 {useful_count}"
                elif getattr(child, "custom_id", "") == "submission_comments_prev":
                    child.disabled = page <= 0
                elif getattr(child, "custom_id", "") == "submission_comments_next":
                    child.disabled = page >= max_page
                elif getattr(child, "custom_id", "") == "submission_expand_content_recommendation":
                    child.disabled = not _content_is_collapsed(record)

    @discord.ui.button(label="展开全文", emoji="📖", style=discord.ButtonStyle.secondary, custom_id="submission_expand_content_recommendation")
    async def expand_content(self, button, interaction: discord.Interaction):
        record = find_by_message_id(interaction.message.id)
        if not record:
            return await interaction.response.send_message("没有找到投稿记录。", ephemeral=True)
        await interaction.response.send_message(embed=_build_full_content_embed(record), ephemeral=True)

    @discord.ui.button(label="觉得有用", emoji="👍", style=discord.ButtonStyle.success, custom_id="submission_useful")
    async def useful(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        record = find_by_message_id(interaction.message.id)
        if not record:
            return await interaction.followup.send("没有找到投稿记录。", ephemeral=True)
        if str(record.get("author_id")) == str(interaction.user.id):
            return await interaction.followup.send("自己的安利就先不算进有用人数啦。", ephemeral=True)
        result = toggle_useful(record["id"], interaction.user.id)
        if not result:
            return await interaction.followup.send("投稿不存在或已经删除。", ephemeral=True)
        record = result["record"]
        credited_rewards = []
        for tier in result["new_tier_rewards"]:
            credited_rewards.append(grant_monthly_eligible_reward(
                int(record["author_id"]),
                interaction.guild_id,
                tier["reward"],
                source="submission_useful_tier",
                reason=f"submission_id={record['id']};useful_count={tier['count']}",
            ))
        await publish_or_update_submission(interaction.client, record)
        if result["added"]:
            reward_amount = sum(float(x.get("amount", 0)) for x in credited_rewards)
            await _notify_submission_event(
                interaction.client,
                record,
                event="useful",
                actor=interaction.user,
                reward=reward_amount,
            )
        status = "已计入" if result["added"] else "已取消"
        await interaction.followup.send(f"✅ {status}觉得有用。", ephemeral=True)

    @discord.ui.button(label="盖楼回复", emoji="💬", style=discord.ButtonStyle.secondary, custom_id="submission_comment")
    async def comment(self, button, interaction: discord.Interaction):
        record = find_by_message_id(interaction.message.id)
        if not record:
            return await interaction.response.send_message("没有找到投稿记录。", ephemeral=True)
        await interaction.response.send_modal(CommentModal(record))

    async def _turn_comment_page(self, interaction: discord.Interaction, delta: int):
        await interaction.response.defer(ephemeral=True)
        record = find_by_message_id(interaction.message.id)
        if not record:
            return await interaction.followup.send("没有找到投稿记录。", ephemeral=True)
        comments = record.get("comments", []) if isinstance(record.get("comments", []), list) else []
        if not comments:
            return await interaction.followup.send("这条安利还没有盖楼回复。", ephemeral=True)

        page = _clamp_comment_page(record, comments)
        max_page = max(0, (len(comments) - 1) // COMMENTS_PER_PAGE)
        record["comment_page"] = min(max(page + delta, 0), max_page)
        save_submission(record)
        await interaction.message.edit(
            embed=build_submission_embed(record),
            view=RecommendationActionView(record),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.followup.send(f"✅ 已切到第 {record['comment_page'] + 1} 页。", ephemeral=True)

    @discord.ui.button(label="上一页", emoji="◀️", style=discord.ButtonStyle.secondary, row=1, custom_id="submission_comments_prev")
    async def comments_prev(self, button, interaction: discord.Interaction):
        await self._turn_comment_page(interaction, -1)

    @discord.ui.button(label="下一页", emoji="▶️", style=discord.ButtonStyle.secondary, row=1, custom_id="submission_comments_next")
    async def comments_next(self, button, interaction: discord.Interaction):
        await self._turn_comment_page(interaction, 1)


class SubmissionManageSelect(discord.ui.Select):
    def __init__(self, rows: list[dict]):
        options = []
        for row in rows[:25]:
            fields = row.get("fields", {})
            label = str(fields.get("title") or fields.get("target") or row.get("id"))[:80]
            options.append(discord.SelectOption(
                label=f"{_kind_label(row.get('kind', ''))} · {label}"[:100],
                value=str(row["id"]),
                description=f"状态: {row.get('status', 'open')} | 奖励: {format_shells(float(row.get('base_reward', 0) or 0) + float(row.get('extra_reward', 0) or 0))} 蛋壳"[:100],
            ))
        super().__init__(placeholder="选择要管理的投稿", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        record = get_submission(self.values[0])
        if not record or str(record.get("author_id")) != str(interaction.user.id):
            return await interaction.response.send_message("投稿不存在，或这不是你的投稿。", ephemeral=True)
        await interaction.response.send_message(
            embed=build_submission_embed(record),
            view=SubmissionEditView(record),
            ephemeral=True,
        )


class SubmissionManageView(discord.ui.View):
    def __init__(self, owner_id: int, rows: list[dict]):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.add_item(SubmissionManageSelect(rows))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("这个管理面板只属于发起它的人。", ephemeral=True)
            return False
        return True


class SubmissionEditView(discord.ui.View):
    def __init__(self, record: dict):
        super().__init__(timeout=300)
        self.record_id = str(record["id"])
        enabled = submission_notifications_enabled(record)
        for child in self.children:
            if getattr(child, "custom_id", "") == "submission_manage_notifications":
                child.label = "取消提醒" if enabled else "订阅提醒"
                child.emoji = "🔔" if enabled else "🔕"
                child.style = discord.ButtonStyle.secondary if enabled else discord.ButtonStyle.success

    async def _record_for_user(self, interaction: discord.Interaction) -> dict | None:
        record = get_submission(self.record_id)
        if not record or str(record.get("author_id")) != str(interaction.user.id):
            return None
        return record

    @discord.ui.button(label="修改投稿", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit(self, button, interaction: discord.Interaction):
        record = await self._record_for_user(interaction)
        if not record:
            return await interaction.response.send_message("投稿不存在，或这不是你的投稿。", ephemeral=True)
        kind = record.get("kind", KIND_REPO)
        if kind in {KIND_REPO, KIND_RECOMMENDATION}:
            return await interaction.response.send_message(
                "先确认新的内容分级。",
                view=SubmissionTypeSelectView(interaction.user.id, kind, record),
                ephemeral=True,
            )
        await interaction.response.send_modal(SubmissionModal(kind, record))

    @discord.ui.button(
        label="订阅提醒",
        emoji="🔕",
        style=discord.ButtonStyle.success,
        custom_id="submission_manage_notifications",
    )
    async def notifications(self, button, interaction: discord.Interaction):
        record = await self._record_for_user(interaction)
        if not record:
            return await interaction.response.send_message("投稿不存在，或这不是你的投稿。", ephemeral=True)
        enabled = not submission_notifications_enabled(record)
        record = set_submission_notifications(self.record_id, interaction.user.id, enabled)
        if not record:
            return await interaction.response.send_message("提醒状态修改失败，请稍后再试。", ephemeral=True)
        await interaction.response.edit_message(
            embed=build_submission_embed(record),
            view=SubmissionEditView(record),
        )
        await interaction.followup.send(
            "🔔 已订阅这条投稿的点赞与回复提醒。" if enabled else "🔕 已取消这条投稿的互动提醒。",
            ephemeral=True,
        )

    @discord.ui.button(label="删除投稿", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete(self, button, interaction: discord.Interaction):
        record = await self._record_for_user(interaction)
        if not record:
            return await interaction.response.send_message("投稿不存在，或这不是你的投稿。", ephemeral=True)
        penalty_rate = float(getattr(config, "DELETE_PENALTY_RATE", 0.5))
        penalty_percent = int(round(penalty_rate * 100))
        await interaction.response.send_message(
            f"删除后会扣回该投稿已获得奖励的 {penalty_percent}%，确定要删除吗？",
            view=SubmissionDeleteConfirmView(record),
            ephemeral=True,
        )


class SubmissionDeleteConfirmView(discord.ui.View):
    def __init__(self, record: dict):
        super().__init__(timeout=120)
        self.record_id = str(record["id"])

    @discord.ui.button(label="确认删除", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm(self, button, interaction: discord.Interaction):
        record = get_submission(self.record_id)
        if not record or str(record.get("author_id")) != str(interaction.user.id):
            return await interaction.response.send_message("投稿不存在，或这不是你的投稿。", ephemeral=True)
        if record.get("status") == STATUS_DELETED:
            return await interaction.response.send_message("这条投稿已经删除过啦。", ephemeral=True)

        total_reward = float(record.get("base_reward", 0) or 0) + float(record.get("extra_reward", 0) or 0)
        penalty_rate = float(getattr(config, "DELETE_PENALTY_RATE", 0.5))
        penalty = round(max(0.0, total_reward * penalty_rate), 1)
        record = mark_deleted(self.record_id, penalty)
        if penalty > 0:
            modify_user_points(
                interaction.user.id,
                -penalty,
                interaction.guild_id,
                source="submission_delete_penalty",
                reason=f"submission_id={self.record_id}",
            )

        try:
            channel = interaction.client.get_channel(int(record.get("channel_id") or 0)) or await interaction.client.fetch_channel(int(record.get("channel_id") or 0))
            message = await channel.fetch_message(int(record.get("message_id") or 0))
            await message.delete(reason=f"投稿者删除投稿 submission_id={self.record_id}")
        except Exception:
            pass

        await interaction.response.send_message(f"✅ 投稿已删除，发布消息已移除，扣回 **{format_shells(penalty)}** 蛋壳。", ephemeral=True)

    @discord.ui.button(label="取消", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction: discord.Interaction):
        await interaction.response.send_message("已取消删除。", ephemeral=True)
