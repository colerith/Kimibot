# cogs/poll/views.py

import discord
import datetime

from discord import ui
from cogs.shared.utils import generate_progress_bar

# --- 核心视图 ---
class PollView(ui.View):
    def __init__(self, question: str, options: list[str], end_time: datetime.datetime, author_id: int):
        super().__init__(timeout=None)  # 计时由Cog处理，视图本身永不超时

        self.question = question
        self.options = options
        self.end_time = end_time
        self.author_id = author_id

        # 数据存储
        self.votes = {option: [] for option in self.options}
        self.voters = set() # 用于防止重复投票

        # 创建下拉选择菜单
        select_options = [discord.SelectOption(label=opt) for opt in self.options]
        self.select_menu = ui.Select(
            placeholder="请投出你宝贵的一票！",
            options=select_options,
            min_values=1,
            max_values=1,
            custom_id="poll_vote_select"
        )
        self.select_menu.callback = self.select_callback
        self.add_item(self.select_menu)


    async def select_callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        selected_option = interaction.data["values"][0]

        # 如果用户已经投过票，先移除旧票
        if user_id in self.voters:
            for opt, voters_list in self.votes.items():
                if user_id in voters_list:
                    voters_list.remove(user_id)
                    break # 找到并移除后即可跳出

        # 记录新票
        self.votes[selected_option].append(user_id)
        self.voters.add(user_id)

        # 更新投票面板并确认
        await interaction.response.edit_message(embed=self.build_embed(is_ended=False))
        await interaction.followup.send(f"✅ 你已将票投给「{selected_option}」！", ephemeral=True)


    def build_embed(self, is_ended: bool) -> discord.Embed:
        """根据当前状态构建投票的 Embed。"""
        if is_ended:
            title = f"🔴 [已结束] {self.question}"
            color = 0x99AAB5 # 灰色
        else:
            title = f"📊 {self.question}"
            color = 0x3498DB # 蓝色

        embed = discord.Embed(title=title, color=color)
        total_votes = len(self.voters)
        desc = ""

        # 对选项按票数排序
        sorted_options = sorted(self.options, key=lambda opt: len(self.votes[opt]), reverse=True)

        for option in sorted_options:
            vote_count = len(self.votes[option])
            percentage = (vote_count / total_votes * 100) if total_votes > 0 else 0
            bar = generate_progress_bar(percentage)
            desc += f"**{option}**\n{bar}  {vote_count} 票 ({percentage:.1f}%)\n\n"

        embed.description = desc.strip()

        if is_ended:
            embed.set_footer(text=f"投票已结束 | 总计 {total_votes} 票")
        else:
            embed.set_footer(text=f"将于 <t:{int(self.end_time.timestamp())}:R> 自动结束 | 当前 {total_votes} 票")

        return embed


    async def end_poll(self, message: discord.Message):
        """结束投票，禁用UI并更新消息。"""
        # 禁用所有组件
        for child in self.children:
            child.disabled = True

        await message.edit(embed=self.build_embed(is_ended=True), view=self)
