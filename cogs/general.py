import discord
from discord import SlashCommandGroup, Option
from discord.ext import commands, tasks
import asyncio
import datetime
import random
from config import IDS, QUOTA, STYLE

# --- 从主文件引用的配置 ---
IDS["SUPER_EGG_ROLE_ID"] = 1417724603253395526      
SERVER_OWNER_ID = 1353777207042113576        
WISH_CHANNEL_ID = 1417577014096957554        
VERIFICATION_ROLE_ID = 1417722528574738513   

TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

# --- 外观配置 ---
STYLE["KIMI_YELLOW"] = 0xFFD700
KIMI_FOOTER_TEXT = "请遵守社区规则，一起做个乖饱饱嘛~！"

# --- 权限检查魔法 ---
def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not isinstance(ctx.author, discord.Member) or not hasattr(ctx.author, 'roles'):
             await ctx.respond("呜...无法识别你的身份组信息！", ephemeral=True)
             return False

        super_egg_role = ctx.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if super_egg_role and super_egg_role in ctx.author.roles:
            return True
        await ctx.respond("呜...这个是【超级小蛋】专属嘟魔法，你还不能用捏！QAQ", ephemeral=True)
        return False
    return commands.check(predicate)

# --- 时间转换小工具 ---
def parse_duration(duration_str: str) -> int:
    try:
        unit = duration_str[-1].lower()
        value = int(duration_str[:-1])
        if unit == 's': return value
        elif unit == 'm': return value * 60
        elif unit == 'h': return value * 3600
        elif unit == 'd': return value * 86400
    except (ValueError, IndexError):
        return 0
    return 0

def generate_progress_bar(percent: float, length: int = 15) -> str:
    filled_length = int(length * percent // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return bar

# --- 功能所需的视图和弹窗 (Views & Modals) ---

class AnnouncementModal(discord.ui.Modal):
    def __init__(self, channel, mention_role, attachments):
        super().__init__(title="📝 奇米大王公告编辑器")
        self.channel = channel
        self.mention_role = mention_role
        self.attachments = attachments
        self.add_item(
            discord.ui.InputText(
                label="公告内容",
                placeholder="把你要发布的内容完整地粘贴到这里嘛~！\n可以直接换行哦！",
                style=discord.InputTextStyle.paragraph, required=True
            )
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        original_content = self.children[0].value
        content_outside_embed = ""
        description_for_embed = original_content
        allowed_mentions = discord.AllowedMentions.none()

        if self.mention_role:
            is_everyone_ping = (self.mention_role.id == interaction.guild.id)
            is_here_ping = ('@here' in self.mention_role.name)

            if (is_everyone_ping or is_here_ping) and interaction.user.guild_permissions.mention_everyone:
                content_outside_embed = "@everyone" if is_everyone_ping else "@here"
                allowed_mentions = discord.AllowedMentions(everyone=True)
            elif not is_everyone_ping and not is_here_ping:
                content_outside_embed = self.mention_role.mention
                allowed_mentions = discord.AllowedMentions(roles=[self.mention_role])

        embed = discord.Embed(title="📣 奇米大王特别公告！", description=description_for_embed, color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.set_author(name=f"发布人：{interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        files = []
        if self.attachments:
            if len(self.attachments) > 0:
                embed.set_image(url=f"attachment://{self.attachments[0].filename}")
            for attachment in self.attachments:
                files.append(await attachment.to_file())

        try:
            await self.channel.send(content=content_outside_embed, embed=embed, files=files, allowed_mentions=allowed_mentions)
            await interaction.followup.send("公告发送成功惹！", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"呜...本大王没有权限在 {self.channel.mention} 发送消息或附件！", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"发送公告时发生未知错误: {e}", ephemeral=True)


# 许愿池系统

class DetailedWishModal(discord.ui.Modal):
    def __init__(self, wish_type: str):
        self.wish_type = wish_type
        # 动态调整标题，如果名字太长Discord可能会报错，控制一下长度
        title_str = f"📝 许愿: {self.wish_type}"
        if len(title_str) > 45: title_str = title_str[:42] + "..."

        super().__init__(title=title_str)

        # 这里的Label根据 wish_type 动态变化
        self.add_item(discord.ui.InputText(
            label=f"详细描述你的愿望/建议",
            placeholder=f"请在这里详细描述你关于【{self.wish_type}】的具体想法、功能建议或愿望细节嘛~！",
            style=discord.InputTextStyle.paragraph,
            min_length=5, max_length=2000, required=True
        ))
        self.add_item(discord.ui.InputText(
            label="是否匿名？(填 是/否)",
            placeholder="默认匿名。如果想让服主知道是你，就填“否”哦！",
            style=discord.InputTextStyle.short, required=False, max_length=1
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        wish_content = self.children[0].value
        is_anonymous_raw = self.children[1].value.lower() if self.children[1].value else ""
        is_anonymous = not (is_anonymous_raw == '否' or is_anonymous_raw == 'n')

        try:
            owner = await interaction.client.fetch_user(SERVER_OWNER_ID)
        except discord.NotFound:
            await interaction.followup.send("呜...找不到服主大人！愿望无法送达！", ephemeral=True)
            return

        wish_id = random.randint(100000, 999999)
        # 创建帖子名称：去除空格和特殊字符，保持整洁
        safe_type_name = self.wish_type.replace(" ", "")
        thread = await interaction.channel.create_thread(
            name=f"💌-{safe_type_name}-{wish_id}",
            type=discord.ChannelType.private_thread,
            invitable=False
        )

        await thread.add_user(interaction.user)
        if owner:
            await thread.add_user(owner)

        # 构建 Embed
        embed = discord.Embed(
            title=f"💌 收到了一个新愿望！",
            description=f"**类型：** {self.wish_type}\n\n**内容：**\n```{wish_content}```",
            color=STYLE["KIMI_YELLOW"],
            timestamp=datetime.datetime.now()
        )
        embed.add_field(name="处理状态", value="⏳ 待受理", inline=False)

        if is_anonymous:
            embed.set_footer(text=f"来自一位匿名小饱饱的愿望~")
        else:
            embed.set_author(name=f"来自 {interaction.user.display_name} 的愿望", icon_url=interaction.user.display_avatar.url)

        await thread.send(embed=embed, view=WishActionView())

        # 反馈给用户
        await interaction.followup.send(f"好惹！你关于【{self.wish_type}】的愿望已经悄悄发送给服主惹！\n快去 {thread.mention} 里看看吧！", ephemeral=True)


class PresetFeatureView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    # 这里不再直接发帖，而是弹出 Modal 让用户填详情
    # 直接复用 DetailedWishModal 即可，非常方便~

    @discord.ui.button(label="🌌 极光", style=discord.ButtonStyle.primary)
    async def wish_aurora(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 弹出模态框，类型设定为“预设功能-极光”
        modal = DetailedWishModal(wish_type="预设功能-极光")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🏛️ 象牙塔", style=discord.ButtonStyle.secondary)
    async def wish_ivory_tower(self, button: discord.ui.Button, interaction: discord.Interaction):
        # 弹出模态框，类型设定为“预设功能-象牙塔”
        modal = DetailedWishModal(wish_type="预设功能-象牙塔")
        await interaction.response.send_modal(modal)


class WishSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="预设新功能", description="想要【极光】还是【象牙塔】？", emoji="💡", value="preset_feature"),
            discord.SelectOption(label="角色卡", description="许愿一张新的角色卡", emoji="🎭", value="角色卡"),
            discord.SelectOption(label="社区美化", description="许愿新的图标、表情或美化素材", emoji="🎨", value="社区美化"),
            discord.SelectOption(label="社区建设", description="对社区发展提出建议", emoji="🏗️", value="社区建设"),
            discord.SelectOption(label="其他", description="许一个天马行空的愿望", emoji="💭", value="其他"),
        ]
        super().__init__(
            placeholder="👇 请选择你的愿望类型...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="wish_panel_select_menu"
        )

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "preset_feature":
            # 如果选了预设功能，先弹出 View 让你选是哪一个
            await interaction.response.send_message("💡 请先选择你想要许愿的预设功能：", view=PresetFeatureView(), ephemeral=True)
        else:
            # 其他选项直接弹出填写框
            modal = DetailedWishModal(wish_type=choice)
            await interaction.response.send_modal(modal)

class WishPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WishSelect())

class WishActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # 只有服主才能操作
        if interaction.user.id == SERVER_OWNER_ID:
            return True
        await interaction.response.send_message("呜...只有服主大人才能操作这个按钮哦！", ephemeral=True)
        return False

    async def update_wish_status(self, interaction: discord.Interaction, status: str, close_thread: bool = False):
        original_embed = interaction.message.embeds[0]
        original_embed.set_field_at(0, name="处理状态", value=status, inline=False)

        if close_thread:
            for child in self.children:
                child.disabled = True

        await interaction.response.edit_message(embed=original_embed, view=self)

        if close_thread:
            await interaction.channel.send(f"本愿望已被标记为 **{status.strip('🤔🎉✅ ')}**，帖子将在10秒后自动关闭并锁定哦~")
            await asyncio.sleep(10)
            await interaction.channel.edit(archived=True, locked=True)

    @discord.ui.button(label="✅ 受理", style=discord.ButtonStyle.success, custom_id="wish_accept")
    async def accept(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.update_wish_status(interaction, "✅ 已受理")

    @discord.ui.button(label="🤔 暂不考虑", style=discord.ButtonStyle.secondary, custom_id="wish_reject")
    async def reject(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.update_wish_status(interaction, "🤔 暂不考虑", close_thread=True)

    @discord.ui.button(label="🎉 已实现", style=discord.ButtonStyle.primary, custom_id="wish_done")
    async def done(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.update_wish_status(interaction, "🎉 已实现！", close_thread=True)


class PollView(discord.ui.View):
    def __init__(self, question: str, options: list, end_time: datetime.datetime, creator_id: int):
        super().__init__(timeout=None) 
        self.question = question
        self.options = options
        self.end_time = end_time
        self.creator_id = creator_id
        
        self.votes = {} 
        
        for index, option in enumerate(options):
            button = discord.ui.Button(
                label=f"{index + 1}. {option[:70]}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll_btn_{index}"
            )
            button.callback = self.create_callback(index)
            self.add_item(button)

    def create_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if datetime.datetime.now(TZ_CN) > self.end_time:
                await interaction.response.send_message("⏳ 投票已经截止啦！不能再投了哦~", ephemeral=True)
                await self.end_poll(interaction.message)
                return

            user_id = interaction.user.id
            current_choice = self.votes.get(user_id)

            if current_choice == index:
                del self.votes[user_id]
                msg = "🗑️ 你取消了投票。"
            else:
                self.votes[user_id] = index
                msg = f"✅ 你投给了：**{self.options[index]}**"

            embed = self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(msg, ephemeral=True)

        return callback

    def build_embed(self, is_ended=False):
        total_votes = len(self.votes)
        counts = [0] * len(self.options)
        for uid, opt_idx in self.votes.items():
            if 0 <= opt_idx < len(self.options):
                counts[opt_idx] += 1

        description = ""
        for i, option in enumerate(self.options):
            count = counts[i]
            percent = (count / total_votes * 100) if total_votes > 0 else 0.0
            bar = generate_progress_bar(percent)
            description += f"**{i+1}. {option}**\n`{bar}` **{percent:.1f}%** ({count}票)\n\n"

        status_text = "🔴 已截止" if is_ended else "🟢 进行中"
        color = 0x99AAB5 if is_ended else STYLE["KIMI_YELLOW"]

        embed = discord.Embed(title=f"📊 {self.question}", description=description, color=color)
        embed.set_author(name=f"发起人 ID: {self.creator_id}")
        
        if is_ended:
            embed.set_footer(text=f"投票已于 {self.end_time.strftime('%Y-%m-%d %H:%M')} (东八区) 结束 | 总票数: {total_votes}")
        else:
            embed.set_footer(text=f"截止时间: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')} (东八区) | 点击下方按钮投票")
        
        return embed

    async def end_poll(self, message: discord.Message):
        for child in self.children:
            child.disabled = True
            child.style = discord.ButtonStyle.secondary
        
        final_embed = self.build_embed(is_ended=True)
        try:
            await message.edit(embed=final_embed, view=self)
        except discord.NotFound:
            pass 
        except Exception as e:
            print(f"结束投票时出错: {e}")
        
        self.stop()

# --- 通用功能的 Cog ---
class General(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.wish_panel_message_id = None

    @commands.Cog.listener()
    async def on_ready(self):
        # 注册持久化视图
        self.bot.add_view(WishPanelView())
        self.bot.add_view(WishActionView())
        print("唷呐！通用功能模块的永久视图已成功注册！")
        
        # 自动检查并更新许愿面板
        asyncio.create_task(self.check_and_post_wish_panel())

    # --- 事件监听器 (Listeners) ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # 0. 基础过滤：不欢迎机器人
        if member.bot: return

        print(f"检测到新成员加入: {member.name} (ID: {member.id})") # 妈妈加的调试日志

        # 1. 尝试获取配置的频道，如果没有就尝试系统频道，再没有就放弃
        targeted_channel_id = 1397629013152894978 

        channel = member.guild.get_channel(targeted_channel_id)

        # 如果找不到指定频道，再尝试系统默认频道
        if not channel:
            channel = member.guild.system_channel

        if not channel:
            print("找不到合适的欢迎频道，放弃发送欢迎消息。")
            return

        # 2. 准备频道ID
        # 答题频道 ID
        quiz_channel_id = IDS.get("QUIZ_CHANNEL_ID", 1467034060026286090)
        # 审核频道 ID
        ticket_channel_id = IDS.get("TICKET_PANEL_CHANNEL_ID", 0) # 确保config里有这个

        embed = discord.Embed(
            title="🎉 欢迎来到\"🔮LOFI-加载中\"社区！",
            description=f"你好呀，{member.mention}！欢迎你加入🔮LOFI-加载中大家庭！\n\n"
                        f"🚪 **第一步：获取基础权限**\n"
                        f"请前往 <#{quiz_channel_id}> 参与答题，答对后即可获得【新兵蛋子】身份。\n\n"
                        f"🔑 **第二步：解锁全区**\n"
                        f"获得身份后，如需访问卡区等更多内容，请前往 <#{ticket_channel_id}> 申请人工审核。\n\n"
                        f"祝你玩得开心捏！✨",
            color=STYLE["KIMI_YELLOW"]
        )

        if member.avatar:
             embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text="记得先看社区守则哦~")

        try:
            await channel.send(content=member.mention, embed=embed) # 加上@提醒，这样他能听到
            print(f"已向 {channel.name} 发送欢迎消息。")
        except discord.Forbidden:
            print(f"权限不足：无法在频道 {channel.name} 发送消息。")
        except Exception as e:
            print(f"发送欢迎消息时发生未知错误: {e}")


    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id != WISH_CHANNEL_ID or message.author == self.bot.user:
            return

        if self.wish_panel_message_id:
            try:
                channel = self.bot.get_channel(WISH_CHANNEL_ID)
                if not channel: return
                old_panel_message = await channel.fetch_message(self.wish_panel_message_id)
                await old_panel_message.delete()
            except discord.NotFound:
                print("旧的许愿面板消息找不到了，可能已被删除。")
            except discord.Forbidden:
                print("错误：本大王没有权限删除许愿频道的消息！")
            except Exception as e:
                print(f"删除旧许愿面板时发生未知错误: {e}")

        await self.post_wish_panel()

    # --- 许愿池相关辅助函数 ---
    async def post_wish_panel(self):
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if not channel:
            print("错误：找不到许愿池频道！")
            return
        embed = discord.Embed(
            title="✨ 奇米大王的许愿池",
            description="有什么想要的新功能、角色卡、或者对社区的建议吗？\n\n**点击下方的菜单选择你的愿望类型，然后告诉本大王吧！**",
            color=STYLE["KIMI_YELLOW"]
        )
        panel_message = await channel.send(embed=embed, view=WishPanelView())
        self.wish_panel_message_id = panel_message.id

    async def check_and_post_wish_panel(self):
        """机器人启动时运行，清理所有旧面板并发送一个新的。"""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if not channel:
            print("错误：找不到许愿池频道，无法设置持久化面板！")
            return

        try:
            async for message in channel.history(limit=100):
                if message.author == self.bot.user and message.embeds:
                    if "奇米大王的许愿池" in message.embeds[0].title:
                        await message.delete()
            
            print("已清理所有旧的许愿面板。")

        except discord.Forbidden:
            print(f"呜...本大王没有权限清理频道 {channel.name} 的旧面板！")
        except Exception as e:
            print(f"清理旧许愿面板时发生错误: {e}")

        await self.post_wish_panel()
        print("已成功发送全新的许愿面板到频道底部。")

    # --- 斜杠命令 (Slash Commands) ---

    @discord.slash_command(name="刷新许愿面板", description="（仅限超级小蛋）手动发送或刷新许愿面板！")
    @is_super_egg()
    async def setup_wish_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if channel:
            try:
                await self.post_wish_panel()
                await ctx.followup.send("许愿面板已经成功发送惹！✨", ephemeral=True)
            except discord.Forbidden:
                await ctx.followup.send(f"呜...本大王没有权限在频道 {channel.name} 发送消息！", ephemeral=True)
        else:
            await ctx.followup.send("呜...找不到许愿池频道！", ephemeral=True)

   # ======================================================================================
    # --- 辅助工具命令 (回顶) ---
    # ======================================================================================

    # 1. 斜杠命令版本 (/回顶)
    @discord.slash_command(name="回顶", description="本大王带你坐穿梭机回到帖子最顶上！咻~")
    async def back_to_top(self, ctx: discord.ApplicationContext):
        await self._back_to_top_logic(ctx)

    # 2. 右键菜单版本 (右键消息 -> Apps -> 🚀 回到帖子顶部)
    @discord.message_command(name="🚀 回到帖子顶部")
    async def back_to_top_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        await self._back_to_top_logic(ctx)

    # 共用逻辑函数
    async def _back_to_top_logic(self, ctx: discord.ApplicationContext):
        # 检查是否在帖子频道 (Thread)
        if not isinstance(ctx.channel, discord.Thread):
            await ctx.respond("呜...这个魔法只能在帖子频道里用啦！", ephemeral=True)
            return
        
        try:
            # 帖子的ID通常就是起始消息的ID
            starter_message = await ctx.channel.fetch_message(ctx.channel.id)
            
            view = discord.ui.View()
            button = discord.ui.Button(label="🚀 点我回到顶部！", style=discord.ButtonStyle.link, url=starter_message.jump_url)
            view.add_item(button)
            
            await ctx.respond("顶！🆙 本大王帮你创建了回到顶部嘟快速通道惹！", view=view, ephemeral=True)
            
        except discord.NotFound:
            await ctx.respond("咦？本大王找不到这个帖子的第一条消息惹...好奇怪！", ephemeral=True)
        except Exception as e:
            await ctx.respond(f"呜...发生错误惹: {e}", ephemeral=True)

    @discord.slash_command(name="发布公告", description="奇米大王的特别广播时间到惹！(会弹出编辑器哦)")
    @is_super_egg()
    async def publish_announcement(self, ctx: discord.ApplicationContext, 
        channel: discord.TextChannel, 
        mention_role: Option(discord.Role, "要@的身份组", required=False) = None, 
        image1: Option(discord.Attachment, "图片附件1", required=False) = None, 
        image2: Option(discord.Attachment, "图片附件2", required=False) = None,
        image3: Option(discord.Attachment, "图片附件3", required=False) = None,
        image4: Option(discord.Attachment, "图片附件4", required=False) = None,
        image5: Option(discord.Attachment, "图片附件5", required=False) = None,
        image6: Option(discord.Attachment, "图片附件6", required=False) = None,
        image7: Option(discord.Attachment, "图片附件7", required=False) = None,
        image8: Option(discord.Attachment, "图片附件8", required=False) = None,
        image9: Option(discord.Attachment, "图片附件9", required=False) = None
    ):
        attachments = [img for img in [image1, image2, image3, image4, image5, image6, image7, image8, image9] if img]
        modal = AnnouncementModal(channel, mention_role, attachments)
        await ctx.send_modal(modal)

    @discord.slash_command(name="清空消息", description="本大王来帮你打扫卫生惹！可以定时清理唷~")
    @is_super_egg()
    async def clear_messages(self, ctx: discord.ApplicationContext, 
        channel: discord.TextChannel, 
        amount: Option(int, "要删除的消息数量", required=True), 
        schedule: Option(str, "延迟执行 (例如: 10s, 5m, 1h)", required=False) = None
    ):
        await ctx.defer(ephemeral=True) 
        if schedule:
            delay = parse_duration(schedule)
            if delay > 0:
                await ctx.followup.send(f"收到唷呐！本大王已经把小闹钟定好惹，{delay}秒后开始大扫除！🕰️✨", ephemeral=True)
                await asyncio.sleep(delay)
                deleted_messages = await channel.purge(limit=amount)
                await channel.send(f"咻~！✨ 本大王施展惹清洁魔法，赶跑了 {len(deleted_messages)} 条坏蛋消息！", delete_after=10)
            else:
                await ctx.followup.send("呜...这个时间格式本大王看不懂捏！要用's', 'm', 'h'结尾才可以嘛！", ephemeral=True)
        else:
            deleted_messages = await channel.purge(limit=amount)
            await ctx.followup.send(f"咻~！✨ 本大王施展惹清洁魔法，赶跑了 {len(deleted_messages)} 条坏蛋消息！", ephemeral=True)

    @discord.slash_command(name="慢速模式", description="让大家冷静一点，优雅地聊天嘛~")
    @is_super_egg()
    async def slowmode(self, ctx: discord.ApplicationContext, seconds: int):
        if seconds < 0:
            await ctx.respond("秒数不能是负数啦，笨蛋饱饱！", ephemeral=True)
            return
        if seconds > 21600: 
            await ctx.respond("最长时间不能超过6小时(21600秒)哦！", ephemeral=True)
            return

        await ctx.channel.edit(slowmode_delay=seconds)

        if seconds > 0:
            await ctx.respond(f"大家冷静一点捏~本大王开启了 **{seconds}秒** 慢速魔法！🐢")
        else:
            await ctx.respond("好惹！封印解除！大家可以尽情地聊天惹！冲鸭！🚀")

    # --- 投票命令组 ---
    vote = SlashCommandGroup("投票", "大家快来告诉本大王你的想法嘛！")

    @vote.command(name="发起", description="创建一个支持多选项、自动截止的投票！")
    async def start_vote(self, ctx: discord.ApplicationContext,
        question: Option(str, "投票的问题是什么呢？", required=True),
        options_text: Option(str, "选项列表 (用 | 竖线分隔，最多20个)", required=True),
        duration: Option(str, "持续时间 (例如: 10m, 1h, 24h)", required=True)
    ):
        seconds = parse_duration(duration)
        if seconds <= 0:
            await ctx.respond("呜...时间格式不对哦！请用 '10m', '1h' 这种格式捏！", ephemeral=True)
            return
        if seconds < 60:
            await ctx.respond("投票时间太短啦！至少要1分钟哦！", ephemeral=True)
            return

        options = [opt.strip() for opt in options_text.split('|') if opt.strip()]
        if len(options) < 2:
            await ctx.respond("投票至少要有两个选项嘛！笨蛋！", ephemeral=True)
            return
        if len(options) > 20:
            await ctx.respond("选项太多啦！本大王记不住，最多只能20个哦！", ephemeral=True)
            return

        await ctx.defer()

        now_cn = datetime.datetime.now(TZ_CN)
        end_time = now_cn + datetime.timedelta(seconds=seconds)

        view = PollView(question, options, end_time, ctx.author.id)
        embed = view.build_embed(is_ended=False)

        message = await ctx.respond(embed=embed, view=view)
        
        if isinstance(message, discord.Interaction):
             message = await message.original_response()

        self.bot.loop.create_task(self.poll_timer(view, message, seconds))

    async def poll_timer(self, view: PollView, message: discord.Message, duration: int):
        try:
            await asyncio.sleep(duration)
            await view.end_poll(message)
        except Exception as e:
            print(f"投票计时器出错: {e}")

    @vote.command(name="提前结束", description="（管理员）强制结束正在进行的投票")
    @is_super_egg()
    async def force_end_vote(self, ctx: discord.ApplicationContext, message_id: str):
        try:
            message = await ctx.channel.fetch_message(int(message_id))
        except:
            await ctx.respond("呜...找不到这个消息ID，或者本大王在那个频道没有权限！", ephemeral=True)
            return

        if not message.author == self.bot.user or not message.embeds:
            await ctx.respond("这好像不是本大王发的投票消息哦！", ephemeral=True)
            return
        
        embed = message.embeds[0]
        if "已截止" in (embed.footer.text or ""):
            await ctx.respond("这个投票已经结束了呀！", ephemeral=True)
            return

        new_view = discord.ui.View.from_message(message)
        for child in new_view.children:
            child.disabled = True
            child.style = discord.ButtonStyle.secondary
        
        embed.color = 0x99AAB5
        embed.title = f"🔴 (管理员强制结束) {embed.title.strip('📊 ')}"
        embed.set_footer(text=f"被管理员 {ctx.author.display_name} 强制截止")

        await message.edit(embed=embed, view=new_view)
        await ctx.respond("好哒！本大王已经把这个投票强制关掉惹！😤", ephemeral=True)


def setup(bot):
    bot.add_cog(General(bot))