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

TZ_CN = datetime.timezone(datetime.timedelta(hours=8))

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

def generate_progress_bar(percent: float, length: int = 15) -> str:
    """生成文本进度条"""
    filled_length = int(length * percent // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return bar

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
        content_outside_embed = ""  # 默认消息内容为空
        description_for_embed = original_content  # Embed描述就是公告内容
        allowed_mentions = discord.AllowedMentions.none()

        if self.mention_role:
            is_everyone_ping = (self.mention_role.id == interaction.guild.id)
            is_here_ping = ('@here' in self.mention_role.name) # 检查是否是 @here

            # 检查是否有权限 @everyone 或 @here
            if (is_everyone_ping or is_here_ping) and interaction.user.guild_permissions.mention_everyone:
                content_outside_embed = "@everyone" if is_everyone_ping else "@here"
                allowed_mentions = discord.AllowedMentions(everyone=True) # everyone=True 同时也允许了 @here
            # 如果是普通的身份组提及
            elif not is_everyone_ping and not is_here_ping:
                content_outside_embed = self.mention_role.mention
                allowed_mentions = discord.AllowedMentions(roles=[self.mention_role])
            # 如果选择了@everyone但没有权限，则不会发出任何提及

        embed = discord.Embed(title="📣 奇米大王特别公告！", description=description_for_embed, color=STYLE["KIMI_YELLOW"], timestamp=datetime.datetime.now())
        embed.set_author(name=f"发布人：{interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        files = []
        if self.attachments:
            # 确保附件URL是正确的格式
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

class PollView(discord.ui.View):
    def __init__(self, question: str, options: list, end_time: datetime.datetime, creator_id: int):
        super().__init__(timeout=None) # 设置为None，我们将手动处理超时
        self.question = question
        self.options = options # list of option strings
        self.end_time = end_time
        self.creator_id = creator_id
        
        # 存储投票数据: {user_id: option_index}
        self.votes = {} 
        
        # 动态创建按钮
        for index, option in enumerate(options):
            button = discord.ui.Button(
                label=f"{index + 1}. {option[:70]}", # 按钮文字限制长度
                style=discord.ButtonStyle.secondary,
                custom_id=f"poll_btn_{index}"
            )
            button.callback = self.create_callback(index)
            self.add_item(button)

    def create_callback(self, index):
        """为每个按钮创建独立的回调函数"""
        async def callback(interaction: discord.Interaction):
            # 1. 检查是否过期 (虽然有后台任务，但双重保险)
            if datetime.datetime.now(TZ_CN) > self.end_time:
                await interaction.response.send_message("⏳ 投票已经截止啦！不能再投了哦~", ephemeral=True)
                await self.end_poll(interaction.message)
                return

            # 2. 处理投票逻辑 (单选：如果投过别的，先移除旧的)
            user_id = interaction.user.id
            current_choice = self.votes.get(user_id)

            if current_choice == index:
                # 如果点击已投的选项，视为取消投票
                del self.votes[user_id]
                msg = "🗑️ 你取消了投票。"
            else:
                # 记录新投票
                self.votes[user_id] = index
                msg = f"✅ 你投给了：**{self.options[index]}**"

            # 3. 更新面板
            embed = self.build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(msg, ephemeral=True)

        return callback

    def build_embed(self, is_ended=False):
        """根据当前投票数据构建 Embed"""
        total_votes = len(self.votes)
        
        # 统计每个选项的票数
        counts = [0] * len(self.options)
        for uid, opt_idx in self.votes.items():
            if 0 <= opt_idx < len(self.options):
                counts[opt_idx] += 1

        description = ""
        for i, option in enumerate(self.options):
            count = counts[i]
            percent = (count / total_votes * 100) if total_votes > 0 else 0.0
            bar = generate_progress_bar(percent)
            
            # 格式：1. 选项名
            # █░░░░░░ 20.0% (5票)
            description += f"**{i+1}. {option}**\n`{bar}` **{percent:.1f}%** ({count}票)\n\n"

        status_text = "🔴 已截止" if is_ended else "🟢 进行中"
        color = 0x99AAB5 if is_ended else STYLE["KIMI_YELLOW"] # 截止变灰，进行中为黄色

        embed = discord.Embed(title=f"📊 {self.question}", description=description, color=color)
        embed.set_author(name=f"发起人 ID: {self.creator_id}")
        
        if is_ended:
            embed.set_footer(text=f"投票已于 {self.end_time.strftime('%Y-%m-%d %H:%M')} (东八区) 结束 | 总票数: {total_votes}")
        else:
            embed.set_footer(text=f"截止时间: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')} (东八区) | 点击下方按钮投票")
        
        return embed

    async def end_poll(self, message: discord.Message):
        """结束投票：禁用所有按钮并更新 Embed"""
        for child in self.children:
            child.disabled = True
            child.style = discord.ButtonStyle.secondary # 变灰
        
        final_embed = self.build_embed(is_ended=True)
        try:
            await message.edit(embed=final_embed, view=self)
        except discord.NotFound:
            pass # 消息可能已被删除
        except Exception as e:
            print(f"结束投票时出错: {e}")
        
        self.stop()

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

    @vote.command(name="发起", description="创建一个支持多选项、自动截止的投票！")
    async def start_vote(self, ctx: discord.ApplicationContext,
        question: Option(str, "投票的问题是什么呢？", required=True),
        options_text: Option(str, "选项列表 (用 | 竖线分隔，最多20个)", required=True),
        duration: Option(str, "持续时间 (例如: 10m, 1h, 24h)", required=True)
    ):
        # 1. 解析时间
        seconds = parse_duration(duration)
        if seconds <= 0:
            await ctx.respond("呜...时间格式不对哦！请用 '10m', '1h' 这种格式捏！", ephemeral=True)
            return
        if seconds < 60:
            await ctx.respond("投票时间太短啦！至少要1分钟哦！", ephemeral=True)
            return

        # 2. 解析选项
        options = [opt.strip() for opt in options_text.split('|') if opt.strip()]
        if len(options) < 2:
            await ctx.respond("投票至少要有两个选项嘛！笨蛋！", ephemeral=True)
            return
        if len(options) > 20:
            await ctx.respond("选项太多啦！本大王记不住，最多只能20个哦！", ephemeral=True)
            return

        await ctx.defer()

        # 3. 计算截止时间 (东八区)
        now_cn = datetime.datetime.now(TZ_CN)
        end_time = now_cn + datetime.timedelta(seconds=seconds)

        # 4. 创建视图和 Embed
        view = PollView(question, options, end_time, ctx.author.id)
        embed = view.build_embed(is_ended=False)

        # 5. 发送消息
        message = await ctx.respond(embed=embed, view=view)
        
        # 获取原始消息对象 (respond 返回的是 InteractionWebhookMessage，有时需要 fetch 才能保证后续编辑)
        if isinstance(message, discord.Interaction):
             message = await message.original_response()

        # 6. 创建后台倒计时任务
        self.bot.loop.create_task(self.poll_timer(view, message, seconds))

    async def poll_timer(self, view: PollView, message: discord.Message, duration: int):
        """后台计时器，等待时间结束后自动关闭投票"""
        try:
            await asyncio.sleep(duration)
            # 时间到，执行结束逻辑
            await view.end_poll(message)
            
            # 发送一条提醒消息 (可选)
            
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

        # 禁用所有按钮
        new_view = discord.ui.View.from_message(message)
        for child in new_view.children:
            child.disabled = True
            child.style = discord.ButtonStyle.secondary
        
        # 更新 Embed 颜色和文字
        embed.color = 0x99AAB5
        embed.title = f"🔴 (管理员强制结束) {embed.title.strip('📊 ')}"
        embed.set_footer(text=f"被管理员 {ctx.author.display_name} 强制截止")

        await message.edit(embed=embed, view=new_view)
        await ctx.respond("好哒！本大王已经把这个投票强制关掉惹！😤", ephemeral=True)


# 固定的setup函数，用于主文件加载Cog
def setup(bot):
    bot.add_cog(General(bot))
