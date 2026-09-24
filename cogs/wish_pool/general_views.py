import asyncio
import datetime
import discord

from config import SERVER_OWNER_ID, STYLE, SUPER_EGG_ROLE_ID, WISH_CHANNEL_ID
from .storage import (
    add_entry_reply,
    bind_entry_message,
    create_entry,
    delete_unpublished_entry,
    find_entry_by_message_id,
    get_entry,
    set_entry_status,
)


GENERAL_PANEL_MARKER = "奇米大王的许愿池"
GENERAL_ENTRY_COLOR = 0xF2B84B


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


def _quote(text: str, limit: int = 700) -> str:
    text = str(text or "").strip()
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return "\n".join(f"> {line}" if line else ">" for line in (text.splitlines() or ["（空）"]))


def build_general_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✨ 奇米大王的许愿池",
        description=(
            "有什么想要电波系实现的预设新功能，或者对社区的建议吗？\n\n"
            "**选择愿望类型后公开投稿，后续沟通与处理状态都会留在本频道。**"
        ),
        color=STYLE["KIMI_YELLOW"],
    )
    embed.add_field(
        name="💬 公开沟通",
        value="投稿不匿名、不创建子区；服主回信和投稿人补充都会显示在投稿卡片中。",
        inline=False,
    )
    embed.set_footer(text="通用许愿池 · 公开投稿")
    return embed


def build_general_entry_embed(entry: dict) -> discord.Embed:
    created_at = str(entry.get("created_at") or "")
    try:
        timestamp = datetime.datetime.fromisoformat(created_at)
    except ValueError:
        timestamp = None
    embed = discord.Embed(
        title=f"✨ 通用许愿｜{str(entry.get('subject') or '未命名愿望')[:120]}",
        color=GENERAL_ENTRY_COLOR,
        timestamp=timestamp,
    )
    embed.add_field(
        name="👤 投稿人",
        value=f"<@{entry.get('author_id')}> · {entry.get('author_name', '投稿人')}",
        inline=True,
    )
    embed.add_field(name="🏷️ 愿望类型", value=str(entry.get("category") or "其他"), inline=True)
    embed.add_field(name="📌 处理状态", value=_status_label(str(entry.get("status", "pending"))), inline=True)
    embed.add_field(name="📝 愿望内容", value=_quote(str(entry.get("content", "")), 1000), inline=False)
    if entry.get("status") == "rejected" and entry.get("status_reason"):
        embed.add_field(name="🌙 不受理理由", value=_quote(str(entry.get("status_reason")), 950), inline=False)

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
        kept = []
        length = 0
        for block in reversed(blocks):
            extra = len(block) + (2 if kept else 0)
            if length + extra > 1024:
                break
            kept.append(block)
            length += extra
        embed.add_field(name="📻 往来电波", value="\n\n".join(reversed(kept)), inline=False)
    embed.set_footer(text=f"通用许愿 #{entry.get('id')} · 所有交流均公开显示")
    return embed


def _entry_jump_url(entry: dict) -> str | None:
    if not entry.get("guild_id") or not entry.get("channel_id") or not entry.get("message_id"):
        return None
    return f"https://discord.com/channels/{entry['guild_id']}/{entry['channel_id']}/{entry['message_id']}"


async def _refresh_entry_message(interaction: discord.Interaction, entry: dict) -> None:
    message = getattr(interaction, "message", None)
    if message is None:
        channel = interaction.client.get_channel(int(entry["channel_id"])) or await interaction.client.fetch_channel(int(entry["channel_id"]))
        message = await channel.fetch_message(int(entry["message_id"]))
    await message.edit(
        embed=build_general_entry_embed(entry),
        view=GeneralWishEntryView(),
        allowed_mentions=discord.AllowedMentions.none(),
    )


class DetailedWishModal(discord.ui.Modal):
    def __init__(self, wish_type: str):
        title = f"📝 许愿: {wish_type}"
        super().__init__(title=title if len(title) <= 45 else title[:42] + "...")
        self.wish_type = wish_type
        self.add_item(discord.ui.InputText(
            label="一句话标题",
            placeholder=f"简要概括这条【{wish_type}】愿望",
            min_length=2,
            max_length=120,
            required=True,
        ))
        self.add_item(discord.ui.InputText(
            label="详细说明",
            placeholder="请说明使用场景、具体想法与希望达到的效果",
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
            kind="wish",
            subject=self.children[0].value,
            content=self.children[1].value,
            scope="general",
            category=self.wish_type,
        )

        channel = interaction.client.get_channel(int(WISH_CHANNEL_ID))
        if channel is None:
            try:
                channel = await interaction.client.fetch_channel(int(WISH_CHANNEL_ID))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                delete_unpublished_entry(entry["id"])
                return await interaction.followup.send("找不到通用许愿池频道，请联系管理组。", ephemeral=True)

        try:
            message = await channel.send(
                embed=build_general_entry_embed(entry),
                view=GeneralWishEntryView(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            entry = bind_entry_message(entry["id"], channel_id=channel.id, message_id=message.id) or entry
            cog = interaction.client.get_cog("WishPoolCog")
            if cog:
                cog.request_panel_refresh("general", channel)
            await interaction.followup.send(
                f"✅ 愿望已公开发送到 {channel.mention}，编号 `#{entry['id']}`。",
                ephemeral=True,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
            delete_unpublished_entry(entry["id"])
            await interaction.followup.send(
                f"愿望暂时未能送达，请联系管理组。`{type(error).__name__}`",
                ephemeral=True,
            )


class WishActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == int(SERVER_OWNER_ID):
            return True
        await interaction.response.send_message("只有服主大人能操作哦！", ephemeral=True)
        return False

    async def update_status(self, interaction: discord.Interaction, status: str, close: bool = False):
        if not interaction.message.embeds:
            return await interaction.response.send_message("愿望卡片不存在。", ephemeral=True)
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="处理状态", value=status, inline=False)
        if close:
            for child in self.children:
                child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        if close:
            await interaction.channel.send(f"已标记为 **{status}**，10 秒后锁定本子区。")
            await asyncio.sleep(10)
            await interaction.channel.edit(archived=True, locked=True)

    @discord.ui.button(label="受理", emoji="✅", style=discord.ButtonStyle.success, custom_id="wish_accept")
    async def accept(self, button, interaction: discord.Interaction):
        await self.update_status(interaction, "✅ 已受理")

    @discord.ui.button(label="暂不考虑", emoji="🤔", style=discord.ButtonStyle.secondary, custom_id="wish_reject")
    async def reject(self, button, interaction: discord.Interaction):
        await self.update_status(interaction, "🤔 暂不考虑", True)

    @discord.ui.button(label="已实现", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="wish_done")
    async def done(self, button, interaction: discord.Interaction):
        await self.update_status(interaction, "🎉 已实现！", True)


class GeneralReplyModal(discord.ui.Modal):
    def __init__(self, entry: dict, role: str):
        self.entry_id = str(entry["id"])
        self.role = role
        super().__init__(title="电波回信" if role == "owner" else "补充愿望")
        self.add_item(discord.ui.InputText(
            label="回复内容",
            placeholder="写下要追加到公开愿望卡片中的内容",
            style=discord.InputTextStyle.paragraph,
            min_length=1,
            max_length=1000,
            required=True,
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        current = get_entry(self.entry_id)
        if not current or current.get("scope") != "general":
            return await interaction.followup.send("这条愿望记录不存在。", ephemeral=True)
        if self.role == "owner" and not _is_staff(interaction.user):
            return await interaction.followup.send("只有服主或小蛋管理组可以发送电波回信。", ephemeral=True)
        if self.role == "author" and str(current.get("author_id")) != str(interaction.user.id):
            return await interaction.followup.send("只有这条愿望的投稿人可以补充回复。", ephemeral=True)

        content = self.children[0].value.strip()
        entry = add_entry_reply(
            self.entry_id,
            role=self.role,
            user_id=interaction.user.id,
            user_name=interaction.user.display_name,
            content=content,
        )
        if not entry:
            return await interaction.followup.send("这条愿望记录不存在。", ephemeral=True)
        await _refresh_entry_message(interaction, entry)

        if self.role == "owner":
            dm_sent = False
            try:
                user = interaction.client.get_user(int(entry["author_id"])) or await interaction.client.fetch_user(int(entry["author_id"]))
                embed = discord.Embed(
                    title="💌 你收到了一封许愿池回信",
                    description=f"你提交的 **{entry.get('subject', '通用愿望')}** 收到了回应。",
                    color=GENERAL_ENTRY_COLOR,
                )
                embed.add_field(name="📨 回信内容", value=_quote(content, 950), inline=False)
                embed.add_field(name="📡 回信来自", value=interaction.user.display_name, inline=True)
                embed.add_field(name="📌 当前状态", value=_status_label(str(entry.get("status", "pending"))), inline=True)
                embed.set_footer(text=f"通用许愿 #{entry['id']}")
                view = discord.ui.View(timeout=86400)
                jump_url = _entry_jump_url(entry)
                if jump_url:
                    view.add_item(discord.ui.Button(label="查看愿望", emoji="🔗", style=discord.ButtonStyle.link, url=jump_url))
                await user.send(embed=embed, view=view)
                dm_sent = True
            except (discord.Forbidden, discord.HTTPException):
                pass
            notice = "💌 投稿人私信已送达。" if dm_sent else "⚠️ 卡片已更新，但投稿人可能关闭了私信。"
            return await interaction.followup.send(f"✅ 电波回信已公开追加。\n{notice}", ephemeral=True)

        await interaction.followup.send("✅ 你的补充回复已追加到愿望卡片。", ephemeral=True)


class GeneralRejectionReasonModal(discord.ui.Modal):
    def __init__(self, entry: dict):
        self.entry_id = str(entry["id"])
        super().__init__(title="不受理 · 填写理由")
        self.add_item(discord.ui.InputText(
            label="不受理理由",
            placeholder="请具体说明未受理的原因，内容将公开显示并私信投稿人",
            style=discord.InputTextStyle.paragraph,
            min_length=2,
            max_length=1000,
            required=True,
        ))

    async def callback(self, interaction: discord.Interaction):
        if not _is_owner(interaction.user):
            return await interaction.response.send_message("只有服主可以修改处理状态。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        reason = self.children[0].value.strip()
        entry = set_entry_status(self.entry_id, "rejected", reason=reason)
        if not entry or entry.get("scope") != "general":
            return await interaction.followup.send("这条愿望记录不存在。", ephemeral=True)
        await _refresh_entry_message(interaction, entry)

        dm_sent = False
        try:
            user = interaction.client.get_user(int(entry["author_id"])) or await interaction.client.fetch_user(int(entry["author_id"]))
            embed = discord.Embed(
                title="🌙 你的愿望暂未受理",
                description=f"你提交的 **{entry.get('subject', '通用愿望')}** 已更新处理结果。",
                color=GENERAL_ENTRY_COLOR,
            )
            embed.add_field(name="📌 处理状态", value="🌙 不受理", inline=True)
            embed.add_field(name="📝 不受理理由", value=_quote(reason, 950), inline=False)
            embed.set_footer(text=f"通用许愿 #{entry['id']}")
            view = discord.ui.View(timeout=86400)
            jump_url = _entry_jump_url(entry)
            if jump_url:
                view.add_item(discord.ui.Button(label="查看愿望", emoji="🔗", style=discord.ButtonStyle.link, url=jump_url))
            await user.send(embed=embed, view=view)
            dm_sent = True
        except (discord.Forbidden, discord.HTTPException):
            pass
        notice = "私信已送达投稿人。" if dm_sent else "投稿人可能关闭了私信，状态与理由仍已公开更新。"
        await interaction.followup.send(f"✅ 已标记为不受理；{notice}", ephemeral=True)


class GeneralWishStatusSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="📌 服主选择处理状态…",
            min_values=1,
            max_values=1,
            custom_id="general_wish_status",
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
        if not entry or entry.get("scope") != "general":
            return await interaction.response.send_message("这条愿望记录不存在。", ephemeral=True)
        if self.values[0] == "rejected":
            return await interaction.response.send_modal(GeneralRejectionReasonModal(entry))
        entry = set_entry_status(entry["id"], self.values[0])
        await interaction.response.edit_message(
            embed=build_general_entry_embed(entry),
            view=GeneralWishEntryView(),
            allowed_mentions=discord.AllowedMentions.none(),
        )


class GeneralWishEntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GeneralWishStatusSelect())

    @discord.ui.button(label="电波回信", emoji="💌", style=discord.ButtonStyle.primary, custom_id="general_wish_owner_reply", row=0)
    async def owner_reply(self, button, interaction: discord.Interaction):
        if not _is_staff(interaction.user):
            return await interaction.response.send_message("只有服主或小蛋管理组可以发送电波回信。", ephemeral=True)
        entry = find_entry_by_message_id(interaction.message.id)
        if not entry or entry.get("scope") != "general":
            return await interaction.response.send_message("这条愿望记录不存在。", ephemeral=True)
        await interaction.response.send_modal(GeneralReplyModal(entry, "owner"))

    @discord.ui.button(label="投稿人回复", emoji="📨", style=discord.ButtonStyle.secondary, custom_id="general_wish_author_reply", row=0)
    async def author_reply(self, button, interaction: discord.Interaction):
        entry = find_entry_by_message_id(interaction.message.id)
        if not entry or entry.get("scope") != "general":
            return await interaction.response.send_message("这条愿望记录不存在。", ephemeral=True)
        if str(entry.get("author_id")) != str(interaction.user.id):
            return await interaction.response.send_message("只有这条愿望的投稿人可以使用这个按钮。", ephemeral=True)
        await interaction.response.send_modal(GeneralReplyModal(entry, "author"))


class PresetFeatureView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="极光", emoji="🌌", style=discord.ButtonStyle.primary)
    async def aurora(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(DetailedWishModal("预设功能-极光"))

    @discord.ui.button(label="象牙塔", emoji="🏛️", style=discord.ButtonStyle.secondary)
    async def ivory(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(DetailedWishModal("预设功能-象牙塔"))

    @discord.ui.button(label="日月西", emoji="⚖️", style=discord.ButtonStyle.secondary)
    async def sun_moon_west(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(DetailedWishModal("预设功能-日月西"))


class WishSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="👇 选择愿望类型...",
            min_values=1,
            max_values=1,
            custom_id="wish_panel_select",
            options=[
                discord.SelectOption(label="预设新功能", emoji="💡", value="preset_feature"),
                discord.SelectOption(label="社区建设", emoji="🏗️", value="社区建设"),
                discord.SelectOption(label="其他", emoji="💭", value="其他"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "preset_feature":
            await interaction.response.send_message("请选择功能：", view=PresetFeatureView(), ephemeral=True)
        else:
            await interaction.response.send_modal(DetailedWishModal(self.values[0]))


class GeneralWishPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WishSelect())
