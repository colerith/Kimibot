import datetime

import discord

from config import PHONE_WISH_CHANNEL_ID, SERVER_OWNER_ID, SUPER_EGG_ROLE_ID
from .storage import (
    add_entry_reply,
    bind_entry_message,
    create_entry,
    delete_unpublished_entry,
    find_entry_by_message_id,
    get_entry,
    set_entry_status,
)


PANEL_MARKER = "电波手机许愿面板"
PANEL_COLOR = 0x8B7CF6
WISH_COLOR = 0xF0B45A
BUG_COLOR = 0xE56B7F


def _is_owner(user) -> bool:
    return bool(user and int(getattr(user, "id", 0) or 0) == int(SERVER_OWNER_ID))


def _is_staff(user) -> bool:
    if _is_owner(user):
        return True
    role_id = int(SUPER_EGG_ROLE_ID or 0)
    return any(int(getattr(role, "id", 0) or 0) == role_id for role in getattr(user, "roles", []))


def _status_label(status: str) -> str:
    return {
        "pending": "🕰️ 待处理",
        "accepted": "📬 已受理",
        "implemented": "✨ 已实现",
        "rejected": "🌙 不受理",
    }.get(status, "🕰️ 待处理")


def _kind_label(kind: str) -> tuple[str, str, int]:
    if kind == "bug":
        return "🐞", "Bug 反馈", BUG_COLOR
    return "🌠", "功能愿望", WISH_COLOR


def _quote(text: str, limit: int = 700) -> str:
    text = str(text or "").strip()
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return "\n".join(f"> {line}" if line else ">" for line in (text.splitlines() or ["（空）"]))


def build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📡 电波手机 · 愿望与捉虫信箱",
        description=(
            "这里专门收集 **【电波手机】** 的新功能愿望与 Bug 反馈。\n"
            "选一个入口，把你捕捉到的灵感或异常发送给电波系吧。"
        ),
        color=PANEL_COLOR,
    )
    embed.add_field(
        name="🌠 我想许愿",
        value="告诉我们你希望电波手机新增或改进什么功能。",
        inline=False,
    )
    embed.add_field(
        name="🐞 我来捉虫",
        value="请写清问题现象、触发方式与预期结果，方便快速定位。",
        inline=False,
    )
    embed.add_field(
        name="💬 公开沟通",
        value="投稿不匿名，也不会创建子区；内容与后续回复都留在本频道的投稿卡片中。",
        inline=False,
    )
    embed.set_footer(text=f"{PANEL_MARKER} · 电波持续接收中")
    return embed


def build_entry_embed(entry: dict) -> discord.Embed:
    icon, label, color = _kind_label(str(entry.get("kind", "wish")))
    created_at = str(entry.get("created_at") or "")
    try:
        timestamp = datetime.datetime.fromisoformat(created_at)
    except ValueError:
        timestamp = None
    embed = discord.Embed(
        title=f"{icon} {label}｜{str(entry.get('subject') or '未命名投稿')[:120]}",
        color=color,
        timestamp=timestamp,
    )
    author_name = str(entry.get("author_name") or "投稿人")
    embed.add_field(
        name="👤 投稿人",
        value=f"<@{entry.get('author_id')}> · {author_name}",
        inline=True,
    )
    embed.add_field(name="📌 处理状态", value=_status_label(str(entry.get("status", "pending"))), inline=True)
    embed.add_field(name="📝 投稿内容", value=_quote(str(entry.get("content", "")), 1000), inline=False)

    replies = entry.get("replies", []) if isinstance(entry.get("replies", []), list) else []
    if replies:
        blocks = []
        for reply in replies[-6:]:
            role = "💌 电波回信" if reply.get("role") == "owner" else "📨 投稿人补充"
            name = str(reply.get("user_name") or "未知用户")[:40]
            content = str(reply.get("content") or "").strip().replace("\n", " ")
            if len(content) > 180:
                content = content[:177] + "..."
            blocks.append(f"**{role} · {name}**\n> {content}")
        kept_blocks = []
        current_length = 0
        for block in reversed(blocks):
            extra = len(block) + (2 if kept_blocks else 0)
            if current_length + extra > 1024:
                break
            kept_blocks.append(block)
            current_length += extra
        conversation = "\n\n".join(reversed(kept_blocks))
        embed.add_field(name="📻 往来电波", value=conversation, inline=False)

    embed.set_footer(text=f"电波手机投稿 #{entry.get('id')} · 所有交流均公开显示")
    return embed


def _entry_jump_url(entry: dict) -> str | None:
    if not entry.get("guild_id") or not entry.get("channel_id") or not entry.get("message_id"):
        return None
    return f"https://discord.com/channels/{entry['guild_id']}/{entry['channel_id']}/{entry['message_id']}"


async def _fetch_target_channel(client):
    channel = client.get_channel(int(PHONE_WISH_CHANNEL_ID))
    if channel is None:
        channel = await client.fetch_channel(int(PHONE_WISH_CHANNEL_ID))
    return channel


async def _refresh_entry_message(interaction: discord.Interaction, entry: dict) -> None:
    message = getattr(interaction, "message", None)
    if message is None:
        channel = interaction.client.get_channel(int(entry["channel_id"])) or await interaction.client.fetch_channel(int(entry["channel_id"]))
        message = await channel.fetch_message(int(entry["message_id"]))
    await message.edit(
        embed=build_entry_embed(entry),
        view=PhoneWishEntryView(),
        allowed_mentions=discord.AllowedMentions.none(),
    )


class WishSubmissionModal(discord.ui.Modal):
    def __init__(self, kind: str):
        self.kind = kind
        _icon, label, _color = _kind_label(kind)
        super().__init__(title=f"电波手机 · {label}")
        self.add_item(discord.ui.InputText(
            label="一句话标题",
            placeholder="简要概括你的愿望或遇到的问题",
            min_length=2,
            max_length=120,
            required=True,
        ))
        self.add_item(discord.ui.InputText(
            label="详细说明",
            placeholder=(
                "愿望：请说明使用场景与希望的效果"
                if kind == "wish"
                else "Bug：请说明问题现象、复现步骤与预期结果"
            ),
            style=discord.InputTextStyle.paragraph,
            min_length=5,
            max_length=2000,
            required=True,
        ))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            return await interaction.response.send_message("请在服务器频道内投稿。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        entry = create_entry(
            guild_id=interaction.guild_id,
            author_id=interaction.user.id,
            author_name=interaction.user.display_name,
            kind=self.kind,
            subject=self.children[0].value,
            content=self.children[1].value,
        )
        try:
            channel = await _fetch_target_channel(interaction.client)
            message = await channel.send(
                embed=build_entry_embed(entry),
                view=PhoneWishEntryView(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            entry = bind_entry_message(entry["id"], channel_id=channel.id, message_id=message.id) or entry
            cog = interaction.client.get_cog("WishPoolCog")
            if cog:
                cog.request_panel_refresh("phone", channel)
            await interaction.followup.send(
                f"✅ 已公开投递到 {channel.mention}，编号 `#{entry['id']}`。\n"
                "本面板不匿名，后续可在投稿卡片上使用「投稿人回复」补充信息。",
                ephemeral=True,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
            delete_unpublished_entry(entry["id"])
            await interaction.followup.send(f"❌ 投稿暂时未能送达，请联系管理组。`{type(error).__name__}`", ephemeral=True)


class EntryReplyModal(discord.ui.Modal):
    def __init__(self, entry: dict, role: str):
        self.entry_id = str(entry["id"])
        self.role = role
        title = "电波回信" if role == "owner" else "补充投稿"
        super().__init__(title=title)
        self.add_item(discord.ui.InputText(
            label="回复内容",
            placeholder="写下要追加到公开投稿卡片中的内容",
            style=discord.InputTextStyle.paragraph,
            min_length=1,
            max_length=1000,
            required=True,
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = get_entry(self.entry_id)
        if not current:
            return await interaction.followup.send("这条投稿记录不存在。", ephemeral=True)
        if self.role == "owner" and not _is_staff(interaction.user):
            return await interaction.followup.send("只有服主或小蛋管理组可以发送电波回信。", ephemeral=True)
        if self.role == "author" and str(current.get("author_id")) != str(interaction.user.id):
            return await interaction.followup.send("只有这条投稿的投稿人可以补充回复。", ephemeral=True)

        reply_content = self.children[0].value.strip()
        entry = add_entry_reply(
            self.entry_id,
            role=self.role,
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            content=reply_content,
        )
        if not entry:
            return await interaction.followup.send("这条投稿记录不存在。", ephemeral=True)
        await _refresh_entry_message(interaction, entry)

        if self.role == "owner":
            dm_sent = False
            try:
                user = interaction.client.get_user(int(entry["author_id"])) or await interaction.client.fetch_user(int(entry["author_id"]))
                dm_embed = discord.Embed(
                    title="💌 你收到了一封电波回信",
                    description=f"你提交的 **{entry.get('subject', '电波手机投稿')}** 收到了回应。",
                    color=PANEL_COLOR,
                )
                dm_embed.add_field(name="📨 回信内容", value=_quote(reply_content, 950), inline=False)
                dm_embed.add_field(name="📡 回信来自", value=interaction.user.display_name, inline=True)
                dm_embed.add_field(name="📌 当前状态", value=_status_label(str(entry.get("status", "pending"))), inline=True)
                dm_embed.set_footer(text=f"电波手机投稿 #{entry['id']}")
                view = discord.ui.View(timeout=86400)
                jump_url = _entry_jump_url(entry)
                if jump_url:
                    view.add_item(discord.ui.Button(label="查看投稿", emoji="🔗", style=discord.ButtonStyle.link, url=jump_url))
                await user.send(embed=dm_embed, view=view)
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException):
                pass
            notice = "💌 投稿人私信已送达。" if dm_sent else "⚠️ 卡片已更新，但投稿人可能关闭了私信。"
            return await interaction.followup.send(f"✅ 电波回信已公开追加。\n{notice}", ephemeral=True)

        await interaction.followup.send("✅ 你的补充回复已追加到投稿卡片。", ephemeral=True)


class WishStatusSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="📌 服主选择处理状态…",
            min_values=1,
            max_values=1,
            custom_id="phone_wish_status",
            options=[
                discord.SelectOption(label="已受理", value="accepted", emoji="📬"),
                discord.SelectOption(label="已实现", value="implemented", emoji="✨"),
                discord.SelectOption(label="不受理", value="rejected", emoji="🌙"),
            ],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if not _is_owner(interaction.user):
            return await interaction.response.send_message("只有服主可以修改处理状态。", ephemeral=True)
        entry = find_entry_by_message_id(interaction.message.id)
        if not entry:
            return await interaction.response.send_message("这条投稿记录不存在。", ephemeral=True)
        entry = set_entry_status(entry["id"], self.values[0])
        if not entry:
            return await interaction.response.send_message("这条投稿记录不存在。", ephemeral=True)
        await interaction.response.edit_message(
            embed=build_entry_embed(entry),
            view=PhoneWishEntryView(),
            allowed_mentions=discord.AllowedMentions.none(),
        )


class PhoneWishEntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WishStatusSelect())

    @discord.ui.button(label="电波回信", emoji="💌", style=discord.ButtonStyle.primary, custom_id="phone_wish_owner_reply", row=0)
    async def owner_reply(self, button, interaction: discord.Interaction):
        if not _is_staff(interaction.user):
            return await interaction.response.send_message("只有服主或小蛋管理组可以发送电波回信。", ephemeral=True)
        entry = find_entry_by_message_id(interaction.message.id)
        if not entry:
            return await interaction.response.send_message("这条投稿记录不存在。", ephemeral=True)
        await interaction.response.send_modal(EntryReplyModal(entry, "owner"))

    @discord.ui.button(label="投稿人回复", emoji="📨", style=discord.ButtonStyle.secondary, custom_id="phone_wish_author_reply", row=0)
    async def author_reply(self, button, interaction: discord.Interaction):
        entry = find_entry_by_message_id(interaction.message.id)
        if not entry:
            return await interaction.response.send_message("这条投稿记录不存在。", ephemeral=True)
        if str(entry.get("author_id")) != str(interaction.user.id):
            return await interaction.response.send_message("只有这条投稿的投稿人可以使用这个按钮。", ephemeral=True)
        await interaction.response.send_modal(EntryReplyModal(entry, "author"))


class PhoneWishPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="我想许愿", emoji="🌠", style=discord.ButtonStyle.primary, custom_id="phone_wish_submit")
    async def submit_wish(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(WishSubmissionModal("wish"))

    @discord.ui.button(label="我来捉虫", emoji="🐞", style=discord.ButtonStyle.danger, custom_id="phone_bug_submit")
    async def submit_bug(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(WishSubmissionModal("bug"))
