import discord
import datetime
import random
import asyncio
from config import IDS, STYLE, SERVER_OWNER_ID
from .utils import TZ_CN, generate_progress_bar
from .storage import load_role_data, load_lottery_data, save_lottery_data

# ==================== 许愿池相关 ====================

class DetailedWishModal(discord.ui.Modal):
    def __init__(self, wish_type: str):
        title_str = f"📝 许愿: {wish_type}"
        if len(title_str) > 45: title_str = title_str[:42] + "..."
        super().__init__(title=title_str)
        self.wish_type = wish_type

        self.add_item(discord.ui.InputText(
            label=f"详细描述你的愿望/建议",
            placeholder=f"关于【{self.wish_type}】的想法...",
            style=discord.InputTextStyle.paragraph,
            min_length=5, max_length=2000, required=True
        ))
        self.add_item(discord.ui.InputText(
            label="是否匿名？(填 是/否)",
            placeholder="默认匿名。填“否”则公开许愿者身份。",
            style=discord.InputTextStyle.short, required=False, max_length=1
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        wish_content = self.children[0].value
        is_anonymous_raw = self.children[1].value.lower() if self.children[1].value else ""
        is_anonymous = not (is_anonymous_raw == '否' or is_anonymous_raw == 'n')

        try:
            owner = await interaction.client.fetch_user(SERVER_OWNER_ID)
        except:
            return await interaction.followup.send("找不到服主大人！", ephemeral=True)

        wish_id = random.randint(100000, 999999)
        safe_type = self.wish_type.replace(" ", "")

        try:
            thread = await interaction.channel.create_thread(
                name=f"💌-{safe_type}-{wish_id}",
                type=discord.ChannelType.private_thread,
                invitable=False
            )
            await thread.add_user(interaction.user)
            if owner: await thread.add_user(owner)

            embed = discord.Embed(
                title=f"💌 收到了一个新愿望！",
                description=f"**类型：** {self.wish_type}\n\n**内容：**\n```{wish_content}```",
                color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now()
            )
            embed.add_field(name="处理状态", value="⏳ 待受理", inline=False)
            if is_anonymous: embed.set_footer(text=f"来自一位匿名小饱饱")
            else: embed.set_author(name=f"来自 {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

            await thread.send(embed=embed, view=WishActionView())
            await interaction.followup.send(f"愿望已发送！快去 {thread.mention} 看看吧！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"创建帖子失败: {e}", ephemeral=True)

class WishActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == SERVER_OWNER_ID: return True
        await interaction.response.send_message("只有服主大人能操作哦！", ephemeral=True)
        return False

    async def update_status(self, interaction, status, close=False):
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="处理状态", value=status, inline=False)
        if close:
            for c in self.children: c.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        if close:
            await interaction.channel.send(f"标记为 **{status}**，10秒后锁定。")
            await asyncio.sleep(10)
            await interaction.channel.edit(archived=True, locked=True)

    @discord.ui.button(label="✅ 受理", style=discord.ButtonStyle.success, custom_id="wish_accept")
    async def accept(self, button, interaction): await self.update_status(interaction, "✅ 已受理")

    @discord.ui.button(label="🤔 暂不考虑", style=discord.ButtonStyle.secondary, custom_id="wish_reject")
    async def reject(self, button, interaction): await self.update_status(interaction, "🤔 暂不考虑", True)

    @discord.ui.button(label="🎉 已实现", style=discord.ButtonStyle.primary, custom_id="wish_done")
    async def done(self, button, interaction): await self.update_status(interaction, "🎉 已实现！", True)

class PresetFeatureView(discord.ui.View):
    def __init__(self): super().__init__(timeout=180)
    @discord.ui.button(label="🌌 极光", style=discord.ButtonStyle.primary)
    async def aurora(self, b, i): await i.response.send_modal(DetailedWishModal("预设功能-极光"))
    @discord.ui.button(label="🏛️ 象牙塔", style=discord.ButtonStyle.secondary)
    async def ivory(self, b, i): await i.response.send_modal(DetailedWishModal("预设功能-象牙塔"))

class WishSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="👇 选择愿望类型...", min_values=1, max_values=1, custom_id="wish_panel_select",
            options=[
                discord.SelectOption(label="预设新功能", emoji="💡", value="preset_feature"),
                discord.SelectOption(label="角色卡", emoji="🎭", value="角色卡"),
                discord.SelectOption(label="社区美化", emoji="🎨", value="社区美化"),
                discord.SelectOption(label="社区建设", emoji="🏗️", value="社区建设"),
                discord.SelectOption(label="其他", emoji="💭", value="其他"),
            ])
    async def callback(self, interaction):
        if self.values[0] == "preset_feature":
            await interaction.response.send_message("请选择功能：", view=PresetFeatureView(), ephemeral=True)
        else:
            await interaction.response.send_modal(DetailedWishModal(self.values[0]))

class WishPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WishSelect())

# ==================== 投票系统 ====================

class PollView(discord.ui.View):
    def __init__(self, question, options, end_time, creator_id):
        super().__init__(timeout=None)
        self.question = question
        self.options = options
        self.end_time = end_time
        self.creator_id = creator_id
        self.votes = {}
        for idx, opt in enumerate(options):
            b = discord.ui.Button(label=f"{idx+1}. {opt[:70]}", style=discord.ButtonStyle.secondary, custom_id=f"poll_{idx}")
            b.callback = self.create_callback(idx)
            self.add_item(b)

    def create_callback(self, idx):
        async def callback(interaction):
            if datetime.datetime.now(TZ_CN) > self.end_time:
                return await interaction.response.send_message("投票已截止！", ephemeral=True)
            uid = interaction.user.id
            if self.votes.get(uid) == idx:
                del self.votes[uid]
                msg = "🗑️ 取消投票。"
            else:
                self.votes[uid] = idx
                msg = f"✅ 投给了：{self.options[idx]}"
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            await interaction.followup.send(msg, ephemeral=True)
        return callback

    def build_embed(self, is_ended=False):
        total = len(self.votes)
        counts = [0] * len(self.options)
        for idx in self.votes.values(): counts[idx] += 1
        desc = ""
        for i, opt in enumerate(self.options):
            pct = (counts[i]/total*100) if total else 0
            desc += f"**{i+1}. {opt}**\n`{generate_progress_bar(pct)}` **{pct:.1f}%** ({counts[i]}票)\n\n"

        color = 0x99AAB5 if is_ended else STYLE["KIMI_YELLOW"]
        embed = discord.Embed(title=f"📊 {self.question}", description=desc, color=color)
        embed.set_author(name=f"发起人ID: {self.creator_id}")
        footer = f"已截止 | 总票数: {total}" if is_ended else f"截止: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')} (CN)"
        embed.set_footer(text=footer)
        return embed

# ==================== 公告系统 ====================

class AnnouncementModal(discord.ui.Modal):
    def __init__(self, channel, mention_role, attachments):
        super().__init__(title="公告编辑器")
        self.channel = channel
        self.mention_role = mention_role
        self.attachments = attachments
        self.add_item(discord.ui.InputText(label="内容", style=discord.InputTextStyle.paragraph, placeholder="在此输入...", required=True))

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        content = self.children[0].value
        outside = ""
        allowed = discord.AllowedMentions.none()

        if self.mention_role:
            if self.mention_role.id == interaction.guild.id:
                outside = "@everyone"
                allowed = discord.AllowedMentions(everyone=True)
            elif "here" in self.mention_role.name:
                outside = "@here"
                allowed = discord.AllowedMentions(everyone=True)
            else:
                outside = self.mention_role.mention
                allowed = discord.AllowedMentions(roles=[self.mention_role])

        embed = discord.Embed(title="📣 公告", description=content, color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.set_author(name=f"发布者: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        files = [await a.to_file() for a in self.attachments]
        if self.attachments: embed.set_image(url=f"attachment://{self.attachments[0].filename}")

        try:
            await self.channel.send(content=outside, embed=embed, files=files, allowed_mentions=allowed)
            await interaction.followup.send("发送成功！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"失败: {e}", ephemeral=True)

# ==================== 1. 身份组领取 (New) ====================

class RoleSelect(discord.ui.Select):
    def __init__(self, guild_roles):
        # guild_roles: [discord.Role, discord.Role...]
        options = []
        for role in guild_roles:
            options.append(discord.SelectOption(label=role.name, value=str(role.id), emoji="🏷️"))

        super().__init__(
            placeholder="👇 选择你要切换的身份组...",
            min_values=1, # 允许同时选多个？不，题目是切换/互斥，通常单选比较方便控制逻辑
            max_values=1,
            options=options[:25], # 限制25个
            custom_id="role_claim_select"
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        role_id = int(self.values[0])
        target_role = interaction.guild.get_role(role_id)

        if not target_role:
            return await interaction.followup.send("呜...这个身份组好像被删掉了！", ephemeral=True)

        prefix = target_role.name.split("·")[0] if "·" in target_role.name else None

        removed_roles = []
        added_role = target_role.name

        # 1. 扫描用户已有身份组
        data = load_role_data()
        claimable_ids = data.get("claimable_roles", [])

        user = interaction.user
        to_remove = []

        if prefix:
            for r in user.roles:
                # 必须也是可领取的身份组，才会被互斥移除（避免误删管理身份组）
                if r.id in claimable_ids and r.id != target_role.id:
                    r_prefix = r.name.split("·")[0] if "·" in r.name else None
                    if r_prefix == prefix:
                        to_remove.append(r)

        try:
            if to_remove:
                await user.remove_roles(*to_remove, reason="身份组切换-互斥移除")
                removed_roles = [r.name for r in to_remove]

            if target_role not in user.roles:
                await user.add_roles(target_role, reason="身份组领取")
                msg = f"✅ 已获得：**{target_role.name}**"
            else:
                # 如果已经有了，再次点击认为是取消佩戴
                await user.remove_roles(target_role, reason="身份组卸下")
                msg = f"❎ 已卸下：**{target_role.name}**"

            if removed_roles:
                msg += f"\n♻️ 自动替换了旧身份：{', '.join(removed_roles)}"

            await interaction.followup.send(msg, ephemeral=True)

        except discord.Forbidden:
            await interaction.followup.send("呜...本大王权限不足（请把我的身份组移到最高层）！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"出错惹: {e}", ephemeral=True)

class RoleClaimView(discord.ui.View):
    def __init__(self, guild_roles):
        super().__init__(timeout=None)
        if guild_roles:
            self.add_item(RoleSelect(guild_roles))

# ==================== 2. 抽奖功能 (New) ====================

class LotteryCreateModal(discord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="🎁 发起抽奖")
        self.cog = cog

        self.add_item(discord.ui.InputText(label="奖品名称", placeholder="例如: 1个月Nitro", max_length=100))
        self.add_item(discord.ui.InputText(label="抽奖文案/描述", placeholder="庆祝新功能上线！大家快来...", style=discord.InputTextStyle.paragraph))
        self.add_item(discord.ui.InputText(label="中奖人数", placeholder="填数字，例如: 1", max_length=5))
        self.add_item(discord.ui.InputText(label="持续时间", placeholder="例如: 10m, 2h, 1d", max_length=10))

    async def callback(self, interaction):
        prize = self.children[0].value
        desc = self.children[1].value
        try:
            winners = int(self.children[2].value)
            duration_str = self.children[3].value
            from .utils import parse_duration
            seconds = parse_duration(duration_str)
            if seconds < 60: raise ValueError("时间太短")
        except:
            return await interaction.response.send_message("❌ 人数必须是数字，时间格式如 10m, 1h，且至少1分钟！", ephemeral=True)

        await interaction.response.defer(ephemeral=False)

        # 计算结束时间
        now = datetime.datetime.now(TZ_CN)
        end_time = now + datetime.timedelta(seconds=seconds)
        end_timestamp = end_time.timestamp()

        embed = discord.Embed(title=f"🎁 {prize}", description=desc, color=STYLE["KIMI_YELLOW"])
        embed.add_field(name="🏆名额", value=str(winners), inline=True)
        embed.add_field(name="⏳开奖时间", value=f"<t:{int(end_timestamp)}:R>", inline=True)
        embed.set_footer(text="点击下方按钮参与 | 0 人已参与")

        msg = await interaction.followup.send(embed=embed, view=LotteryJoinView(prize))

        # 存入数据
        data = load_lottery_data()
        data["active_lotteries"][str(msg.id)] = {
            "channel_id": interaction.channel_id,
            "prize": prize,
            "text": desc,
            "winners": winners,
            "end_timestamp": end_timestamp,
            "participants": []
        }
        save_lottery_data(data)

        # 启动计时任务
        self.cog.bot.loop.create_task(self.cog.lottery_timer(msg.id, seconds))


class LotteryJoinView(discord.ui.View):
    def __init__(self, prize_name):
        super().__init__(timeout=None)
        # 必须给 custom_id 否则重启后按钮失效
        self.add_item(discord.ui.Button(label="🎉 参与抽奖", style=discord.ButtonStyle.primary, custom_id="lottery_join_btn"))

    async def interaction_check(self, interaction):
        # 处理参与逻辑
        if interaction.data["custom_id"] == "lottery_join_btn":
            await self.join_lottery(interaction)
            return False # 阻止后续默认处理，虽然这里没别的
        return True

    async def join_lottery(self, interaction):
        msg_id = str(interaction.message.id)
        data = load_lottery_data()

        if msg_id not in data["active_lotteries"]:
            return await interaction.response.send_message("这个抽奖已经失效或结束惹！", ephemeral=True)

        uid = interaction.user.id
        participants = data["active_lotteries"][msg_id]["participants"]

        if uid in participants:
            return await interaction.response.send_message("你已经参与过啦！乖乖等待开奖吧~", ephemeral=True)

        participants.append(uid)
        save_lottery_data(data)

        # 更新 Embed 显示人数
        embed = interaction.message.embeds[0]
        # 修改 footer
        embed.set_footer(text=f"点击下方按钮参与 | {len(participants)} 人已参与")
        await interaction.message.edit(embed=embed)

        await interaction.response.send_message("🎉 参与成功！祝你好运哦！", ephemeral=True)
