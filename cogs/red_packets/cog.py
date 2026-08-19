import discord
from discord import Option
from discord.ext import commands, tasks

from cogs.points.storage import get_user_points, modify_user_points

from . import storage


MAX_PACKET_COUNT = 50
MIN_PACKET_UNIT = 0.1
RED_PACKET_IMAGE_URL = (
    "https://i.postimg.cc/kMKjMnc1/"
    "qi-mi-dan-hong-bao-feng-mian-2-cong-cong-da-wang123-lai-zi-xiao-hong-shu-wang-ye-ban.jpg"
)


def _build_claim_progress(claimed_count: int, count: int) -> str:
    progress_units = 10
    ratio = claimed_count / count if count > 0 else 0
    filled_units = max(0, min(progress_units, round(ratio * progress_units)))
    return f"{'▰' * filled_units}{'▱' * (progress_units - filled_units)}  **{claimed_count}/{count}**"


def is_admin_packet_sender(member) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def build_packet_embed(packet: dict, *, closed_note: str | None = None) -> discord.Embed:
    remaining_count = int(packet.get("remaining_count", 0))
    count = int(packet.get("count", 0))
    remaining_amount = storage.round_shells(packet.get("remaining_amount", 0))
    claimed_count = max(0, count - remaining_count)
    admin_free = bool(packet.get("admin_free"))
    status = packet.get("status", "active")

    title = "🧧 奇米蛋红包来啦！"
    color = 0xED4245
    footer_text = "点击下方按钮领取 · 每人限领一次 · 24 小时后自动结束"
    if status == "empty":
        title = "🎉 红包已被抢光"
        color = 0xF0B232
        footer_text = "手慢啦，这个红包已经被大家抢完了"
    elif status == "expired":
        title = "⌛ 红包已经过期"
        color = 0x747F8D
        footer_text = "红包已结束，未领取部分已按规则处理"

    expires_timestamp = int(storage.parse_time(packet.get("expires_at", "")).timestamp())
    message = packet.get("message") or "奇米蛋抱着红包跑来啦。"
    admin_badge = "\n\n✨ **管理员福利红包 · 免费发放**" if admin_free else ""

    embed = discord.Embed(
        title=title,
        description=f"> {message}\n\n来自 <@{packet.get('sender_id')}> 的小小心意{admin_badge}",
        color=color,
    )
    embed.add_field(
        name="💰 红包总额",
        value=f"**{storage.format_shells(packet.get('total_amount', 0))}** 蛋壳",
        inline=True,
    )
    embed.add_field(name="🧧 红包数量", value=f"**{count}** 个", inline=True)
    embed.add_field(
        name="🥚 剩余蛋壳",
        value=f"**{storage.format_shells(remaining_amount)}**",
        inline=True,
    )
    embed.add_field(
        name="📊 领取进度",
        value=_build_claim_progress(claimed_count, count),
        inline=False,
    )
    embed.add_field(
        name="⏰ 结束时间",
        value=f"<t:{expires_timestamp}:F>（<t:{expires_timestamp}:R>）",
        inline=False,
    )
    if closed_note:
        embed.add_field(name="📌 处理结果", value=closed_note, inline=False)

    embed.set_image(url=RED_PACKET_IMAGE_URL)
    embed.set_footer(text=footer_text)
    return embed


class RedPacketView(discord.ui.View):
    def __init__(self, cog: "RedPacketCog", packet_id: str, *, disabled: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.packet_id = packet_id
        button = discord.ui.Button(
            label="抢红包",
            style=discord.ButtonStyle.danger,
            emoji="🧧",
            custom_id=f"red_packet:claim:{packet_id}",
            disabled=disabled,
        )
        button.callback = self.claim_callback
        self.add_item(button)

    async def claim_callback(self, interaction: discord.Interaction):
        await self.cog.handle_claim(interaction, self.packet_id)


class RedPacketCog(commands.Cog, name="蛋壳红包"):
    def __init__(self, bot):
        self.bot = bot
        self._registered_packet_ids: set[str] = set()

    async def cog_load(self):
        if not self.cleanup_expired_packets.is_running():
            self.cleanup_expired_packets.start()

    def cog_unload(self):
        if self.cleanup_expired_packets.is_running():
            self.cleanup_expired_packets.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        for packet in storage.get_active_packets():
            packet_id = str(packet.get("id", ""))
            if not packet_id or packet_id in self._registered_packet_ids:
                continue
            self.bot.add_view(RedPacketView(self, packet_id))
            self._registered_packet_ids.add(packet_id)
        print("[RedPackets] Cog loaded and active packet views registered.")

    @discord.slash_command(name="发红包", description="把蛋壳装进小蛋红包让大家抢。")
    async def send_red_packet(
        self,
        ctx: discord.ApplicationContext,
        金额: Option(float, "红包总金额，最小单位 0.1 蛋壳", required=True),  # pyright: ignore[reportInvalidTypeForm]
        数量: Option(int, "红包数量，每个红包至少 0.1 蛋壳", required=True),  # pyright: ignore[reportInvalidTypeForm]
        留言: Option(str, "红包留言，可选", required=False, default="奇米蛋把蛋壳红包端上来啦。"),  # pyright: ignore[reportInvalidTypeForm]
    ):
        if not ctx.guild or not ctx.channel:
            await ctx.respond("红包只能在服务器频道里发送哦。", ephemeral=True)
            return

        amount = storage.round_shells(金额)
        count = int(数量)
        if count <= 0 or count > MAX_PACKET_COUNT:
            await ctx.respond(f"红包数量需要在 1-{MAX_PACKET_COUNT} 个之间。", ephemeral=True)
            return
        if amount < storage.round_shells(count * MIN_PACKET_UNIT):
            await ctx.respond("红包金额太少啦，每个红包至少要有 0.1 蛋壳。", ephemeral=True)
            return

        admin_free = is_admin_packet_sender(ctx.author)
        if not admin_free:
            balance = get_user_points(ctx.author.id, ctx.guild.id)
            if balance < amount:
                await ctx.respond(
                    f"蛋壳不够哦，需要 **{storage.format_shells(amount)}**，"
                    f"你现在只有 **{storage.format_shells(balance)}**。",
                    ephemeral=True,
                )
                return
            modify_user_points(
                ctx.author.id,
                -amount,
                ctx.guild.id,
                source="red_packet_create",
                reason=f"count={count}",
            )

        packet = storage.create_packet(
            guild_id=ctx.guild.id,
            channel_id=ctx.channel.id,
            sender_id=ctx.author.id,
            sender_name=getattr(ctx.author, "display_name", ctx.author.name),
            total_amount=amount,
            count=count,
            message=(留言 or "奇米蛋把蛋壳红包端上来啦。")[:120],
            admin_free=admin_free,
        )

        view = RedPacketView(self, packet["id"])
        self.bot.add_view(view)
        self._registered_packet_ids.add(packet["id"])

        try:
            await ctx.respond(
                embed=build_packet_embed(packet),
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            response = await ctx.interaction.original_response()
            storage.set_packet_message(packet["id"], response.id)
        except discord.HTTPException:
            storage.mark_packet_cancelled(packet["id"])
            if not admin_free:
                modify_user_points(
                    ctx.author.id,
                    amount,
                    ctx.guild.id,
                    source="red_packet_refund",
                    reason=f"packet={packet['id']};send_failed",
                )
            raise

    async def handle_claim(self, interaction: discord.Interaction, packet_id: str):
        if not interaction.guild:
            await interaction.response.send_message("红包只能在服务器里领取哦。", ephemeral=True)
            return

        result = storage.claim_packet(packet_id, interaction.user.id)
        packet = result.get("packet") or storage.get_packet(packet_id)

        if not result.get("success"):
            reason = result.get("reason")
            if reason == "sender_blocked":
                text = "发红包的人不能抢自己的红包哦。"
            elif reason == "already_claimed":
                text = f"你已经抢过啦，本次拿到 **{storage.format_shells(result.get('amount', 0))}** 蛋壳。"
            elif reason == "expired":
                text = "这个红包已经超过 24 小时，正在等小蛋清理退款。"
            elif reason == "empty":
                text = "这个红包已经被抢光啦。"
            else:
                text = "这个红包找不到了，可能已经被清理。"

            await interaction.response.send_message(text, ephemeral=True)
            if packet:
                if reason == "expired":
                    await self._refund_expired_packet(packet)
                    packet = storage.get_packet(packet_id) or packet
                await self._refresh_packet_message(packet)
            return

        amount = storage.round_shells(result["amount"])
        balance = modify_user_points(
            interaction.user.id,
            amount,
            interaction.guild.id,
            source="red_packet_claim",
            reason=f"packet={packet_id}",
        )

        await interaction.response.send_message(
            f"抢到 **{storage.format_shells(amount)}** 蛋壳！"
            f" 当前余额：**{storage.format_shells(balance)}**。",
            ephemeral=True,
        )
        await self._refresh_packet_message(packet)

    @tasks.loop(minutes=30)
    async def cleanup_expired_packets(self):
        expired_packets = storage.expire_due_packets()
        for packet in expired_packets:
            refund_amount = await self._refund_expired_packet(packet)
            if packet.get("admin_free"):
                closed_note = f"已自动清理，未领取的 **{storage.format_shells(refund_amount)}** 蛋壳不再发放。"
            else:
                closed_note = f"已自动清理，未领取部分退还 **{storage.format_shells(refund_amount)}** 蛋壳。"
            await self._refresh_packet_message(
                storage.get_packet(packet["id"]) or packet,
                closed_note=closed_note,
            )

    @cleanup_expired_packets.before_loop
    async def before_cleanup_expired_packets(self):
        await self.bot.wait_until_ready()

    async def _refund_expired_packet(self, packet: dict) -> float:
        refund_amount = storage.round_shells(packet.get("refund_amount", packet.get("remaining_amount", 0)))
        if refund_amount > 0 and not packet.get("admin_free") and not packet.get("refunded"):
            modify_user_points(
                int(packet["sender_id"]),
                refund_amount,
                int(packet["guild_id"]),
                source="red_packet_refund",
                reason=f"packet={packet['id']};expired",
            )
        storage.mark_refunded(packet["id"])
        return refund_amount

    async def _refresh_packet_message(self, packet: dict, *, closed_note: str | None = None):
        if not packet:
            return
        guild = self.bot.get_guild(int(packet.get("guild_id", 0) or 0))
        channel = None
        if guild:
            channel_id = int(packet.get("channel_id", 0) or 0)
            channel = guild.get_channel(channel_id) or guild.get_thread(channel_id)
            if channel is None:
                try:
                    channel = await guild.fetch_channel(channel_id)
                except discord.HTTPException:
                    channel = None
        if channel is None:
            return

        try:
            message = await channel.fetch_message(int(packet.get("message_id", 0) or 0))
        except (discord.NotFound, discord.HTTPException, ValueError):
            return

        disabled = packet.get("status") != "active"
        view = RedPacketView(self, packet["id"], disabled=disabled)
        try:
            await message.edit(embed=build_packet_embed(packet, closed_note=closed_note), view=view)
        except discord.HTTPException:
            pass
