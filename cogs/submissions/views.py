import discord
from discord import ui
import inspect

import config
from cogs.points.storage import format_shells, modify_user_points

from .storage import (
    KIND_BUG,
    KIND_RECOMMENDATION,
    KIND_REPO,
    STATUS_DELETED,
    add_comment,
    add_owner_reply,
    create_submission,
    find_by_message_id,
    get_panel_info,
    get_submission,
    list_user_submissions,
    mark_deleted,
    random_reward,
    save_submission,
    set_panel_info,
    toggle_useful,
    update_submission_fields,
)


PANEL_COLOR = 0xFFD36A
REPO_SFW_CHANNEL_ID = 1441437806617563156
REPO_NSFW_CHANNEL_ID = 1417576370451513495
BUG_CHANNEL_ID = 1417577014096957554
RECOMMENDATION_CHANNEL_ID = 1536024803587137536

DOMAIN_OPTIONS = ["酒馆好物", "书籍安利", "影视安利", "游戏安利", "便利生活", "其他类型"]
TYPE_OPTIONS = ["sfw", "nsfw"]


def _paragraph_style():
    text_style = getattr(discord, "TextStyle", None)
    if text_style is not None:
        return text_style.paragraph
    return discord.InputTextStyle.paragraph


def _text_input(label: str, *, value: str = "", style=None, max_length: int | None = None, required: bool = True):
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


def _image_urls_text(urls: list[str], spoiler: bool) -> str:
    if not urls:
        return ""
    lines = [f"{index + 1}. {url}" for index, url in enumerate(urls[:9])]
    text = "\n".join(lines)
    return _spoiler(text, spoiler)


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🥚 奇米蛋投稿箱",
        description=(
            "📮 想 repo、想捉虫、想安利，都可以投进这里。\n"
            "🥚 奇米蛋会给认真投稿的小饱饱发一点亮晶晶的蛋壳。\n"
            "📎 填完表后可以开启收图，最多收纳 9 张图片。"
        ),
        color=PANEL_COLOR,
    )
    embed.add_field(name="📦 我要repo", value="提交想 repo 的标题、类型与内容。", inline=False)
    embed.add_field(name="🐞 我要捉虫", value="提交问题对象与详细描述。", inline=False)
    embed.add_field(name="🌟 我要安利", value="分享好物、书籍、影视、游戏或生活经验。", inline=False)
    embed.add_field(name="🗂️ 管理投稿", value="修改或删除自己发过的投稿。", inline=False)
    embed.set_footer(text="填完投稿表后可开启附件收集，最多 9 张图。")
    return embed


def build_submission_embed(record: dict) -> discord.Embed:
    kind = record.get("kind", "")
    fields = record.get("fields", {})
    content_type = str(fields.get("content_type", "sfw")).lower()
    is_nsfw = content_type == "nsfw"
    title = fields.get("title") or fields.get("target") or "未命名投稿"
    embed = discord.Embed(
        title=f"🥚 {_kind_label(kind)}投稿 · {_spoiler(str(title), is_nsfw)}",
        color=0xF5C542 if kind != KIND_BUG else 0xFF9E80,
    )
    embed.add_field(name="投稿人", value=f"<@{record.get('author_id')}>", inline=True)
    embed.add_field(name="状态", value=record.get("status", "open"), inline=True)
    if kind != KIND_BUG:
        embed.add_field(name="类型", value=content_type, inline=True)
    if kind == KIND_RECOMMENDATION:
        embed.add_field(name="领域", value=str(fields.get("domain", "其他类型")), inline=True)
    content = str(fields.get("content", "") or "没有填写内容")
    embed.add_field(name="内容", value=_spoiler(content[:1024], is_nsfw), inline=False)
    image_urls = record.get("attachments", [])
    if isinstance(image_urls, list) and image_urls:
        if is_nsfw:
            embed.add_field(name="图片", value=_image_urls_text(image_urls, True)[:1024], inline=False)
        else:
            embed.set_image(url=str(image_urls[0]))
            if len(image_urls) > 1:
                embed.add_field(name="更多图片", value=_image_urls_text(image_urls[1:], False)[:1024], inline=False)

    replies = record.get("replies", [])
    if replies:
        latest = replies[-1]
        embed.add_field(
            name="服主回复",
            value=f"**{latest.get('user_name', '服主')}：** {str(latest.get('content', ''))[:900]}",
            inline=False,
        )

    if kind == KIND_RECOMMENDATION:
        useful_count = len(record.get("useful_user_ids", []) if isinstance(record.get("useful_user_ids", []), list) else [])
        embed.add_field(name="觉得有用", value=f"{useful_count} 人", inline=True)
        comments = record.get("comments", []) if isinstance(record.get("comments", []), list) else []
        if comments:
            lines = [
                f"**{row.get('user_name', '匿名')}：** {str(row.get('content', ''))[:80]}"
                for row in comments[-5:]
            ]
            embed.add_field(name="盖楼回复", value="\n".join(lines)[:1024], inline=False)

    total_reward = float(record.get("base_reward", 0) or 0) + float(record.get("extra_reward", 0) or 0)
    embed.set_footer(text=f"投稿ID: {record.get('id')} · 已奖励 {format_shells(total_reward)} 蛋壳")
    return embed


def _view_for_record(record: dict) -> discord.ui.View:
    if record.get("kind") == KIND_RECOMMENDATION:
        return RecommendationActionView(record)
    return OwnerReplyView()


async def _notify_user(client, record: dict, message: str) -> None:
    try:
        user = await client.fetch_user(int(record.get("author_id")))
        await user.send(message)
    except Exception:
        return


async def _attachments_to_files(attachments, *, spoiler: bool = False) -> list[discord.File]:
    files = []
    for attachment in attachments[:9]:
        try:
            files.append(await attachment.to_file(spoiler=spoiler))
        except (discord.NotFound, discord.HTTPException, AttributeError):
            continue
    return files


async def publish_or_update_submission(client, record: dict, attachments=None, *, force_resend: bool = False) -> tuple[dict, str]:
    channel_id = _channel_id(record.get("kind", ""), record.get("fields", {}))
    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
    if not channel:
        return record, "missing_channel"

    old_channel_id = int(record.get("channel_id") or 0)
    old_message_id = int(record.get("message_id") or 0)
    embed = build_submission_embed(record)
    view = _view_for_record(record)
    content_type = str(record.get("fields", {}).get("content_type", "sfw")).lower()
    files = await _attachments_to_files(attachments or [], spoiler=content_type == "nsfw")
    if files:
        force_resend = True

    if old_channel_id == channel_id and old_message_id and not force_resend:
        try:
            message = await channel.fetch_message(old_message_id)
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

    message = await channel.send(embed=embed, view=view, files=files, allowed_mentions=discord.AllowedMentions.none())
    record["channel_id"] = str(channel.id)
    record["message_id"] = str(message.id)
    if files:
        record["attachments"] = [att.url for att in message.attachments[:9]]
        save_submission(record)
        try:
            await message.edit(embed=build_submission_embed(record), view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass
    save_submission(record)
    return record, "sent"


async def deploy_submission_panel(channel, bot) -> str:
    embed = build_panel_embed()
    view = SubmissionPanelView()
    panel_info = get_panel_info()
    if str(channel.id) == str(panel_info.get("channel_id", "")) and panel_info.get("message_id"):
        try:
            message = await channel.fetch_message(int(panel_info["message_id"]))
            await message.edit(embed=embed, view=view)
            return "updated"
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    message = await channel.send(embed=embed, view=view)
    set_panel_info(channel.id, message.id)
    return "sent"


class SubmissionModal(discord.ui.Modal):
    def __init__(
        self,
        kind: str,
        record: dict | None = None,
        *,
        content_type: str | None = None,
        domain: str | None = None,
    ):
        self.kind = kind
        self.record = record
        self.content_type = (content_type or _field(record or {}, "content_type", "sfw")).lower()
        self.domain = domain or _field(record or {}, "domain", "其他类型")
        is_edit = record is not None
        title = "修改投稿" if is_edit else "提交投稿"
        super().__init__(title=f"{title} · {_kind_label(kind)}")

        if kind == KIND_REPO:
            self.add_item(_text_input("repo 标题", value=_field(record or {}, "title"), max_length=120, required=True))
            self.add_item(_text_input("repo 内容", value=_field(record or {}, "content"), style=_paragraph_style(), max_length=2000, required=True))
        elif kind == KIND_BUG:
            self.add_item(_text_input("捉虫对象", value=_field(record or {}, "target"), max_length=120, required=True))
            self.add_item(_text_input("捉虫内容", value=_field(record or {}, "content"), style=_paragraph_style(), max_length=2000, required=True))
        else:
            self.add_item(_text_input("安利对象", value=_field(record or {}, "target"), max_length=120, required=True))
            self.add_item(_text_input("安利内容", value=_field(record or {}, "content"), style=_paragraph_style(), max_length=2000, required=True))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("这个投稿箱只能在服务器里使用。", ephemeral=True)

        if self.kind == KIND_REPO:
            content_type = self.content_type if self.content_type in TYPE_OPTIONS else "sfw"
            fields = {
                "title": self.children[0].value.strip(),
                "content_type": content_type,
                "content": self.children[1].value.strip(),
            }
        elif self.kind == KIND_BUG:
            fields = {
                "target": self.children[0].value.strip(),
                "content": self.children[1].value.strip(),
            }
        else:
            content_type = self.content_type if self.content_type in TYPE_OPTIONS else "sfw"
            domain = self.domain if self.domain in DOMAIN_OPTIONS else "其他类型"
            fields = {
                "target": self.children[0].value.strip(),
                "content_type": content_type,
                "domain": domain,
                "content": self.children[1].value.strip(),
            }

        if self.record and str(self.record.get("author_id")) != str(interaction.user.id):
            return await interaction.response.send_message("只能修改自己的投稿。", ephemeral=True)

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
        embed.set_footer(text="可以直接完成，也可以开启附件收集后再完成。")
        await interaction.response.send_message(
            embed=embed,
            view=SubmissionDraftView(
                owner_id=interaction.user.id,
                kind=self.kind,
                fields=fields,
                record_id=str(self.record["id"]) if self.record else None,
            ),
            ephemeral=True,
        )


class OwnerReplyModal(discord.ui.Modal):
    def __init__(self, record: dict):
        self.record = record
        super().__init__(title=f"回复 {_kind_label(record.get('kind', ''))}投稿")
        self.add_item(_text_input("回复内容", style=_paragraph_style(), max_length=1500, required=True))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        record = get_submission(self.record["id"])
        if not record:
            return await interaction.followup.send("投稿记录不存在。", ephemeral=True)
        reward = random_reward(record.get("kind", KIND_REPO), "reply")
        record = add_owner_reply(record["id"], interaction.user.id, interaction.user.display_name, self.children[0].value.strip(), reward)
        if not record:
            return await interaction.followup.send("投稿已删除，不能回复。", ephemeral=True)
        modify_user_points(
            int(record["author_id"]),
            reward,
            interaction.guild_id,
            source=f"submission_reply_{record.get('kind')}",
            reason=f"submission_id={record['id']}",
        )
        await publish_or_update_submission(interaction.client, record)
        await _notify_user(
            interaction.client,
            record,
            f"🥚 你的{_kind_label(record.get('kind', ''))}投稿收到了服主回复，并追加 **{format_shells(reward)}** 蛋壳！",
        )
        await interaction.followup.send(f"✅ 已回复并追加 **{format_shells(reward)}** 蛋壳。", ephemeral=True)


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
        await publish_or_update_submission(interaction.client, record)
        await interaction.followup.send("✅ 评论已经盖到楼里啦。", ephemeral=True)


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
        super().__init__(placeholder="选择投稿类型", min_values=1, max_values=1, options=options, row=0)

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
            return await interaction.response.send_modal(
                SubmissionModal(KIND_REPO, self.record, content_type=content_type)
            )

        await interaction.response.edit_message(
            content="继续选择安利领域。",
            embed=None,
            view=RecommendationDomainSelectView(interaction.user.id, content_type, self.record),
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


class SubmissionPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="我要repo", emoji="📦", style=discord.ButtonStyle.primary, custom_id="submission_panel_repo")
    async def repo(self, button, interaction: discord.Interaction):
        await interaction.response.send_message(
            "先选择 repo 类型。",
            view=SubmissionTypeSelectView(interaction.user.id, KIND_REPO),
            ephemeral=True,
        )

    @discord.ui.button(label="我要捉虫", emoji="🐞", style=discord.ButtonStyle.danger, custom_id="submission_panel_bug")
    async def bug(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(SubmissionModal(KIND_BUG))

    @discord.ui.button(label="我要安利", emoji="🌟", style=discord.ButtonStyle.success, custom_id="submission_panel_recommend")
    async def recommend(self, button, interaction: discord.Interaction):
        await interaction.response.send_message(
            "先选择安利类型。",
            view=SubmissionTypeSelectView(interaction.user.id, KIND_RECOMMENDATION),
            ephemeral=True,
        )

    @discord.ui.button(label="管理投稿", emoji="🗂️", style=discord.ButtonStyle.secondary, custom_id="submission_panel_manage")
    async def manage(self, button, interaction: discord.Interaction):
        rows = list_user_submissions(interaction.user.id, interaction.guild_id)
        if not rows:
            return await interaction.response.send_message("你还没有可管理的投稿。", ephemeral=True)
        await interaction.response.send_message(
            "选择一条投稿进行修改或删除。",
            view=SubmissionManageView(interaction.user.id, rows),
            ephemeral=True,
        )


class SubmissionDraftView(discord.ui.View):
    def __init__(self, *, owner_id: int, kind: str, fields: dict, record_id: str | None = None):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.kind = kind
        self.fields = fields
        self.record_id = record_id
        self.collection_started = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("这个投稿确认面板只属于发起它的人。", ephemeral=True)
            return False
        return True

    @staticmethod
    def _get_submission_cog(interaction: discord.Interaction):
        return interaction.client.get_cog("SubmissionsCog") or interaction.client.get_cog("投稿面板")

    def _build_status_embed(self, interaction: discord.Interaction, temp_notify: str = "") -> discord.Embed:
        session = None
        cog = self._get_submission_cog(interaction)
        if cog and interaction.channel_id:
            session = cog.get_attachment_session(interaction.user.id, interaction.channel_id)

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
        if session:
            expire_text = discord.utils.format_dt(session["expires_at"], "R")
            embed.add_field(
                name="附件收集",
                value=f"进行中，已收纳 **{len(session['attachments'])}/9** 个，{expire_text} 结束。",
                inline=False,
            )
        else:
            embed.add_field(name="附件收集", value="未开启。可直接完成，也可以先收图。", inline=False)
        embed.set_footer(text=temp_notify or "确认无误后点击完成投稿。")
        return embed

    @discord.ui.button(label="开始收图", style=discord.ButtonStyle.secondary, emoji="📥")
    async def start_collect(self, button, interaction: discord.Interaction):
        cog = self._get_submission_cog(interaction)
        if not cog:
            return await interaction.response.send_message("找不到投稿模块实例，暂时无法收图。", ephemeral=True)
        expires_at = cog.start_attachment_session(interaction.user.id, interaction.channel_id, max_attachments=9, duration_seconds=300)
        self.collection_started = True
        await interaction.response.edit_message(
            embed=self._build_status_embed(
                interaction,
                temp_notify=f"已开启收图。请在当前频道发送图片附件，最多 9 张，{discord.utils.format_dt(expires_at, 'R')} 结束。",
            ),
            view=self,
        )

    @discord.ui.button(label="完成投稿", style=discord.ButtonStyle.success, emoji="✅")
    async def finish(self, button, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild_id:
            return await interaction.followup.send("这个投稿箱只能在服务器里使用。", ephemeral=True)

        cog = self._get_submission_cog(interaction)
        result = None
        if cog and interaction.channel_id:
            result = await cog.finish_attachment_session(
                interaction.user.id,
                interaction.channel_id,
                cleanup_channel=interaction.channel,
            )
        attachments = result["attachments"] if result else []

        if self.record_id:
            record = update_submission_fields(self.record_id, self.fields)
            if not record:
                return await interaction.followup.send("投稿不存在或已经删除。", ephemeral=True)
            record, status = await publish_or_update_submission(
                interaction.client,
                record,
                attachments=attachments,
                force_resend=bool(attachments),
            )
            msg = f"✅ 投稿已更新。({status})"
        else:
            reward = random_reward(self.kind, "base")
            record = create_submission(
                guild_id=interaction.guild_id,
                author_id=interaction.user.id,
                author_name=interaction.user.display_name,
                kind=self.kind,
                fields=self.fields,
                base_reward=reward,
            )
            modify_user_points(
                interaction.user.id,
                reward,
                interaction.guild_id,
                source=f"submission_{self.kind}",
                reason=f"submission_id={record['id']}",
            )
            record, status = await publish_or_update_submission(interaction.client, record, attachments=attachments)
            msg = f"✅ 投稿已送到小蛋箱！本次获得 **{format_shells(reward)}** 蛋壳。({status})"

        if result:
            msg += f"\n📎 已收纳 {len(attachments)} 个附件，清理 {result.get('deleted_messages', 0)} 条原消息。"
            if result.get("failed_deletions", 0):
                msg += f" 有 {result['failed_deletions']} 条原消息未能清理。"

        self.clear_items()
        try:
            await interaction.edit_original_response(embed=self._build_status_embed(interaction, "投稿流程已完成。"), view=self)
        except (discord.NotFound, discord.HTTPException):
            pass
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, button, interaction: discord.Interaction):
        cog = self._get_submission_cog(interaction)
        if cog and interaction.channel_id:
            cog.cancel_attachment_session(interaction.user.id, interaction.channel_id)
        self.clear_items()
        await interaction.response.edit_message(
            embed=self._build_status_embed(interaction, "已取消本次投稿。"),
            view=self,
        )


class OwnerReplyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

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
            for child in self.children:
                if getattr(child, "custom_id", "") == "submission_useful":
                    child.label = f"觉得有用 {useful_count}"
                    break

    @discord.ui.button(label="觉得有用", style=discord.ButtonStyle.success, custom_id="submission_useful")
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
        for tier in result["new_tier_rewards"]:
            modify_user_points(
                int(record["author_id"]),
                tier["reward"],
                interaction.guild_id,
                source="submission_useful_tier",
                reason=f"submission_id={record['id']};useful_count={tier['count']}",
            )
        await publish_or_update_submission(interaction.client, record)
        if result["new_tier_rewards"]:
            reward_text = format_shells(sum(x["reward"] for x in result["new_tier_rewards"]))
            await _notify_user(interaction.client, record, f"🥚 你的安利被大家觉得有用，追加 **{reward_text}** 蛋壳！")
        status = "已计入" if result["added"] else "已取消"
        await interaction.followup.send(f"✅ {status}觉得有用。", ephemeral=True)

    @discord.ui.button(label="盖楼回复", style=discord.ButtonStyle.secondary, custom_id="submission_comment")
    async def comment(self, button, interaction: discord.Interaction):
        record = find_by_message_id(interaction.message.id)
        if not record:
            return await interaction.response.send_message("没有找到投稿记录。", ephemeral=True)
        await interaction.response.send_modal(CommentModal(record))


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

    async def _record_for_user(self, interaction: discord.Interaction) -> dict | None:
        record = get_submission(self.record_id)
        if not record or str(record.get("author_id")) != str(interaction.user.id):
            return None
        return record

    @discord.ui.button(label="修改投稿", style=discord.ButtonStyle.primary)
    async def edit(self, button, interaction: discord.Interaction):
        record = await self._record_for_user(interaction)
        if not record:
            return await interaction.response.send_message("投稿不存在，或这不是你的投稿。", ephemeral=True)
        kind = record.get("kind", KIND_REPO)
        if kind in {KIND_REPO, KIND_RECOMMENDATION}:
            return await interaction.response.send_message(
                "先选择新的类型。",
                view=SubmissionTypeSelectView(interaction.user.id, kind, record),
                ephemeral=True,
            )
        await interaction.response.send_modal(SubmissionModal(kind, record))

    @discord.ui.button(label="删除投稿", style=discord.ButtonStyle.danger)
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

    @discord.ui.button(label="确认删除", style=discord.ButtonStyle.danger)
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

    @discord.ui.button(label="取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction: discord.Interaction):
        await interaction.response.send_message("已取消删除。", ephemeral=True)
