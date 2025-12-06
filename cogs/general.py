import discord
from discord import SlashCommandGroup, Option
from discord.ext import commands, tasks
import asyncio
import datetime
import random
from config import IDS, QUOTA, STYLE

# --- 从主文件引用的配置 ---
# 建议将这些ID统一存放在一个配置文件中，方便管理
IDS["SUPER_EGG_ROLE_ID"] = 1417724603253395526      # 【超级小蛋】的身份组ID
SERVER_OWNER_ID = 1353777207042113576        # 服务器主的ID
WISH_CHANNEL_ID = 1417577014096957554        # 许愿池频道的ID
VERIFICATION_ROLE_ID = 1417722528574738513   # 【新兵蛋子】(验证成功后发放)的身份组ID

# --- 外观配置 ---
STYLE["KIMI_YELLOW"] = 0xFFD700
KIMI_FOOTER_TEXT = "请遵守社区规则，一起做个乖饱饱嘛~！"

# --- 权限检查魔法 ---
# 确保只有“超级小蛋”才能使用受限命令
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
    """将时间字符串 (e.g., '1d', '2h', '30m') 转换为秒数。"""
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

# --- 功能所需的视图和弹窗 (Views & Modals) ---

# 公告弹窗 (已修复 @everyone 问题)
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
        content_outside_embed = "" # 默认消息内容为空
        description_for_embed = original_content # Embed描述就是公告内容
        allowed_mentions = discord.AllowedMentions.none()

        if self.mention_role:
            is_everyone_ping = (self.mention_role.id == interaction.guild.id)
            super_egg_role = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])

            # --- 核心修复在这里 ---
            # 检查是否要 @everyone 并且用户有权限
            if is_everyone_ping and super_egg_role and super_egg_role in interaction.user.roles:
                # 将 @everyone 放在普通 content 里
                content_outside_embed = "@everyone"
                allowed_mentions = discord.AllowedMentions(everyone=True)
            # 如果是普通的身份组提及
            elif not is_everyone_ping:
                content_outside_embed = self.mention_role.mention
                allowed_mentions = discord.AllowedMentions(roles=[self.mention_role])
            # 如果选择了@everyone但没有权限，则不会发出任何提及

        embed = discord.Embed(title="📣 奇米大王特别公告！", description=description_for_embed, color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.set_author(name=f"发布人：{interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        files = []
        if self.attachments:
            # 使用 f-string 动态生成附件URL，以便Discord正确显示
            embed.set_image(url=f"attachment://{self.attachments[0].filename}")
            for attachment in self.attachments:
                files.append(await attachment.to_file())

        await self.channel.send(content=content_outside_embed, embed=embed, files=files, allowed_mentions=allowed_mentions)
        await interaction.followup.send("公告发送成功惹！", ephemeral=True)


# 许愿池系统

# 弹窗1：用于填写详细愿望的通用弹窗
class DetailedWishModal(discord.ui.Modal):
    def __init__(self, wish_type: str):
        self.wish_type = wish_type
        super().__init__(title=f"📝 许愿: {self.wish_type}")
        self.add_item(discord.ui.InputText(
            label=f"详细描述你的愿望 ({self.wish_type})",
            placeholder=f"请在这里详细描述你关于【{self.wish_type}】的愿望或建议嘛~！",
            style=discord.InputTextStyle.paragraph,
            min_length=10, max_length=2000, required=True
        ))
        self.add_item(discord.ui.InputText(
            label="是否匿名？(填 是/否)",
            placeholder="默认匿名。如果想让服主知道是你，就填“否”哦！",
            style=discord.InputTextStyle.short, required=False, max_length=1
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        wish_content = self.children[0].value
        is_anonymous_raw = self.children[1].value.lower()
        is_anonymous = not (is_anonymous_raw == '否' or is_anonymous_raw == 'n')

        try:
            owner = await interaction.client.fetch_user(SERVER_OWNER_ID)
        except discord.NotFound:
            await interaction.followup.send("呜...找不到服主大人！愿望无法送达！", ephemeral=True)
            return

        wish_id = random.randint(100000, 999999)
        thread = await interaction.channel.create_thread(name=f"💌-{self.wish_type}-{wish_id}", type=discord.ChannelType.private_thread, invitable=False)

        await thread.add_user(interaction.user)
        if owner:
            await thread.add_user(owner)

        embed = discord.Embed(title=f"💌 收到了一个新愿望！({self.wish_type})", description=f"```{wish_content}```", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.add_field(name="处理状态", value="⏳ 待受理", inline=False)

        if is_anonymous:
            embed.set_footer(text=f"来自一位匿名小饱饱的愿望~")
        else:
            embed.set_author(name=f"来自 {interaction.user.display_name} 的愿望", icon_url=interaction.user.display_avatar.url)

        await thread.send(embed=embed, view=WishActionView())
        await interaction.followup.send(f"你的【{self.wish_type}】愿望已经悄悄地发送给服主惹！快去 {thread.mention} 里看看吧！", ephemeral=True)

# 视图1：当用户选择“预设新功能”后，展示【极光】和【象牙塔】按钮
class PresetFeatureView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180) # 3分钟内不操作按钮会自动消失

    async def create_preset_wish(self, interaction: discord.Interaction, feature_name: str):
        """通用函数，用于创建预设功能的愿望帖子"""
        await interaction.response.defer(ephemeral=True)
        try:
            owner = await interaction.client.fetch_user(SERVER_OWNER_ID)
        except discord.NotFound:
            await interaction.followup.send("呜...找不到服主大人！愿望无法送达！", ephemeral=True)
            return

        wish_id = random.randint(100000, 999999)
        thread_name = f"💌-预设功能-{feature_name}-{wish_id}"
        thread = await interaction.channel.create_thread(name=thread_name, type=discord.ChannelType.private_thread, invitable=False)

        await thread.add_user(interaction.user)
        if owner: await thread.add_user(owner)
        
        wish_content = f"我希望社区能够实装预设新功能：**{feature_name}**！"

        embed = discord.Embed(title=f"💌 收到了一个新愿望！(预设功能)", description=f"```{wish_content}```", color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.add_field(name="处理状态", value="⏳ 待受理", inline=False)
        # 预设功能默认不匿名
        embed.set_author(name=f"来自 {interaction.user.display_name} 的愿望", icon_url=interaction.user.display_avatar.url)

        await thread.send(embed=embed, view=WishActionView())
        await interaction.followup.send(f"你的【{feature_name}】愿望已经悄悄地发送给服主惹！快去 {thread.mention} 里看看吧！", ephemeral=True)
        
        # 禁用所有按钮并停止视图
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)
        self.stop()

    @discord.ui.button(label="🌌 极光", style=discord.ButtonStyle.primary)
    async def wish_aurora(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.create_preset_wish(interaction, "极光")

    @discord.ui.button(label="🏛️ 象牙塔", style=discord.ButtonStyle.secondary)
    async def wish_ivory_tower(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.create_preset_wish(interaction, "象牙塔")

# 下拉菜单：许愿的主选择菜单
class WishSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="预设新功能", description="许愿【极光】或【象牙塔】功能", emoji="💡", value="preset_feature"),
            discord.SelectOption(label="角色卡", description="许愿一张新的角色卡", emoji="🎭", value="角色卡"),
            discord.SelectOption(label="社区美化", description="许愿新的图标、表情或美化素材", emoji="🎨", value="社区美化"),
            discord.SelectOption(label="社区建设", description="对社区发展提出建议", emoji="🏗️", value="社区建设"),
            discord.SelectOption(label="其他", description="许一个天马行空的愿望", emoji="💭", value="其他"),
        ]
        super().__init__(placeholder="👇 请选择你的愿望类型...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "preset_feature":
            # 如果选择预设功能，发送带有两个按钮的新消息
            await interaction.response.send_message("请选择你想要的预设功能：", view=PresetFeatureView(), ephemeral=True)
        else:
            # 其他选项则弹出对应的填写框
            modal = DetailedWishModal(wish_type=choice)
            await interaction.response.send_modal(modal)

# 视图2：包含下拉菜单的主许愿面板
class WishPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(WishSelect()) # 将下拉菜单添加到视图中

# 视图3：服主在愿望帖内的操作按钮（这个类保持不变）
class WishActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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
    async def accept(self, button, interaction):
        await self.update_wish_status(interaction, "✅ 已受理")

    @discord.ui.button(label="🤔 暂不考虑", style=discord.ButtonStyle.secondary, custom_id="wish_reject")
    async def reject(self, button, interaction):
        await self.update_wish_status(interaction, "🤔 暂不考虑", close_thread=True)

    @discord.ui.button(label="🎉 已实现", style=discord.ButtonStyle.primary, custom_id="wish_done")
    async def done(self, button, interaction):
        await self.update_wish_status(interaction, "🎉 已实现！", close_thread=True)


# --- 通用功能的 Cog ---
class General(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.wish_panel_message_id = None

    # 创建一个新的异步函数来处理需要事件循环的操作
    @commands.Cog.listener()
    async def on_ready(self):
        # 这个事件触发时，可以保证机器人已准备好且事件循环正在运行
        self.bot.add_view(WishPanelView())
        self.bot.add_view(WishActionView())
        print("唷呐！通用功能模块的永久视图已成功注册！")
        asyncio.create_task(self.setup_persistent_wish_panel())

    # --- 事件监听器 (Listeners) ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        # 自动发放"新兵蛋子"身份组
        new_recruit_role = member.guild.get_role(VERIFICATION_ROLE_ID)
        if new_recruit_role:
            try:
                await member.add_roles(new_recruit_role, reason="新成员自动发放身份组")
            except discord.Forbidden:
                print(f"错误：本大王没有权限给 {member.name} 添加身份组！")
            except Exception as e:
                print(f"添加身份组时发生错误: {e}")

        channel = member.guild.system_channel
        if not channel:
            print(f"错误：服务器 {member.guild.name} 没有设置系统欢迎频道！")
            return

        rules_channel_url = "https://discord.com/channels/1397629012292931726/1417568378889175071" 
        verify_channel_url = "https://discord.com/channels/1397629012292931726/1417572579304013885" 

        embed = discord.Embed(
            title="🎉 欢迎来到\"🔮LOFI-加载中\"社区！",
            description=f"你好呀，{member.mention}！本大王是奇米大王，欢迎你加入我们温暖的大家庭！\n\n"
                        f"为了让大家都能愉快地玩耍，请先阅读我们的[**📜 社区守则**]({rules_channel_url})哦！\n\n"
                        f"阅读完毕后，请前往[**✅ 身份审核频道**]({verify_channel_url})进行身份审核，审核通过后才能解锁社区的全部内容捏！",
            color=STYLE["KIMI_YELLOW"]
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="期待与你一起玩耍！")

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """监听许愿频道的新消息，自动刷新面板到最底部。"""
        # 1. 如果消息不是来自许愿频道，或者发消息的是机器人自己，就直接忽略
        if message.channel.id != WISH_CHANNEL_ID or message.author == self.bot.user:
            return

        # 2. 确认我们有一个旧面板的ID可以删除
        if self.wish_panel_message_id:
            try:
                # 获取频道对象
                channel = self.bot.get_channel(WISH_CHANNEL_ID)
                if not channel: return
                
                # 根据ID找到旧的面板消息并删除它
                old_panel_message = await channel.fetch_message(self.wish_panel_message_id)
                await old_panel_message.delete()
            except discord.NotFound:
                # 如果消息已经被手动删了，就忽略错误
                print("旧的许愿面板消息找不到了，可能已被删除。")
            except discord.Forbidden:
                print("错误：本大王没有权限删除许愿频道的消息！")
            except Exception as e:
                print(f"删除旧许愿面板时发生未知错误: {e}")

        # 3. 无论之前是否成功删除，都重新发送一个新的面板
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
        # 发送新的面板，并把它的ID存到变量里
        panel_message = await channel.send(embed=embed, view=WishPanelView())
        self.wish_panel_message_id = panel_message.id

    # 新的启动设置函数
    async def setup_persistent_wish_panel(self):
        """机器人启动时运行，清理所有旧面板并发送一个新的。"""
        await self.bot.wait_until_ready() # 确保机器人已完全连接
        channel = self.bot.get_channel(WISH_CHANNEL_ID)
        if not channel:
            print("错误：找不到许愿池频道，无法设置持久化面板！")
            return

        try:
            # 遍历频道历史记录，删除所有由机器人自己发送的、且包含特定标题的旧面板
            async for message in channel.history(limit=100):
                if message.author == self.bot.user and message.embeds:
                    if "奇米大王的许愿池" in message.embeds[0].title:
                        await message.delete()
            
            print("已清理所有旧的许愿面板。")

        except discord.Forbidden:
            print(f"呜...本大王没有权限清理频道 {channel.name} 的旧面板！")
        except Exception as e:
            print(f"清理旧许愿面板时发生错误: {e}")

        # 清理完毕后，发送一个全新的面板
        await self.post_wish_panel()
        print("已成功发送全新的许愿面板到频道底部。")

    # --- 斜杠命令 (Slash Commands) ---

    @discord.slash_command(name="setup_wish_panel", description="（仅限超级小蛋）手动发送或刷新许愿面板！")
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

    @discord.slash_command(name="回顶", description="本大王带你坐穿梭机回到帖子最顶上！咻~")
    async def back_to_top(self, ctx: discord.ApplicationContext):
        if not isinstance(ctx.channel, discord.Thread):
            await ctx.respond("呜...这个魔法只能在帖子频道里用啦！", ephemeral=True)
            return
        try:
            starter_message = await ctx.channel.fetch_message(ctx.channel.id)
            view = discord.ui.View()
            button = discord.ui.Button(label="🚀 点我回到顶部！", style=discord.ButtonStyle.link, url=starter_message.jump_url)
            view.add_item(button)
            await ctx.respond("顶！🆙 本大王帮你创建了回到顶部嘟快速通道惹！", view=view, ephemeral=True)
        except discord.NotFound:
            await ctx.respond("咦？本大王找不到这个帖子的第一条消息惹...好奇怪！", ephemeral=True)

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
        if seconds > 21600: # Discord 限制为 6 小时
            await ctx.respond("最长时间不能超过6小时(21600秒)哦！", ephemeral=True)
            return

        await ctx.channel.edit(slowmode_delay=seconds)

        if seconds > 0:
            await ctx.respond(f"大家冷静一点捏~本大王开启了 **{seconds}秒** 慢速魔法！🐢")
        else:
            await ctx.respond("好惹！封印解除！大家可以尽情地聊天惹！冲鸭！🚀")

    # --- 投票命令组 ---
    vote = SlashCommandGroup("投票", "大家快来告诉本大王你的想法嘛！")

    @vote.command(name="创建", description="发起一个超级可爱的投票！")
    async def create_poll(self, ctx, 
        question: str, 
        option1: str, 
        option2: str, 
        option3: str = None, 
        option4: str = None, 
        option5: str = None
    ):
        await ctx.defer()
        options = [opt for opt in [option1, option2, option3, option4, option5] if opt]
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]

        description = "\n\n".join([f"{emojis[i]} {options[i]}" for i in range(len(options))])

        embed = discord.Embed(title=f"📣 {question}", description=description, color=STYLE["KIMI_YELLOW"])
        embed.set_footer(text="快来用表情符号投票告诉本大王你的想法嘛！")

        poll_message = await ctx.followup.send(embed=embed)
        for i in range(len(options)):
            await poll_message.add_reaction(emojis[i])

    @vote.command(name="结束", description="本大王来宣布投票结果惹！")
    async def end_poll(self, ctx, message_id: str):
        try:
            poll_message = await ctx.channel.fetch_message(int(message_id))
        except (discord.NotFound, ValueError):
            await ctx.respond("找不到这个投票消息捏，是不是ID错惹？", ephemeral=True)
            return

        if not poll_message.embeds or not poll_message.author == self.bot.user:
            await ctx.respond("这个不是本大王发起的投票唷！", ephemeral=True)
            return

        original_embed = poll_message.embeds[0]
        question = original_embed.title.strip("📣 ")

        results = []
        for reaction in poll_message.reactions:
            # 减去机器人自己的反应
            count = reaction.count - 1
            if count < 0: count = 0
            results.append(f"{reaction.emoji} : {count} 票")

        result_embed = discord.Embed(
            title="📊 投票结果发表！",
            description=f"**关于 “{question}” 的投票结果是...**\n\n" + "\n".join(results),
            color=STYLE["KIMI_YELLOW"]
        )
        result_embed.set_footer(text="谢谢大家的参与唷！本大王爱你们~")
        await ctx.respond(embed=result_embed)

        # 移除投票按钮，表示结束
        await poll_message.edit(view=None)


# 固定的setup函数，用于主文件加载Cog
def setup(bot):
    bot.add_cog(General(bot))
