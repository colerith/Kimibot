# cogs/forum_tracker/views.py

import discord
import datetime
from config import STYLE
from .db import db

class ForumStatsView(discord.ui.View):
    """论坛统计面板的翻页视图。"""
    def __init__(self, task_id, current_page=1, total_pages=1):
        super().__init__(timeout=None) # 持久化视图
        self.task_id = task_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.update_buttons()

    def update_buttons(self):
        """根据当前页码更新按钮状态。"""
        # 确保 self.children 存在且有足够的元素
        if len(self.children) < 4: return
        self.children[0].disabled = (self.current_page <= 1)
        self.children[1].disabled = (self.current_page >= self.total_pages)
        self.children[2].label = f"第 {self.current_page} / {self.total_pages} 页"

    async def update_embed(self, interaction: discord.Interaction):
        """根据当前状态刷新整个面板的 Embed 内容。"""
        posts = db.get_valid_posts(self.task_id, self.current_page)
        total_count = db.get_total_valid_count(self.task_id)

        task_info = db.get_task_by_id(self.task_id)
        if not task_info:
            return await interaction.response.edit_message(content="❌ 错误：此统计任务似乎已被删除。", embed=None, view=None)

        task_name, _, _, _, _, title_kw, content_kw, _, content_logic = task_info
        update_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

        desc_str = (
            f"📈 **总收录数：{total_count} 篇**\n"
            f"🕒 更新时间：{update_time}\n"
            f"🔍 标题包含：`{title_kw or '无'}`\n"
        )
        if content_kw:
            desc_str += f"📄 首楼包含：`{content_kw}` (模式: {content_logic})"

        embed = discord.Embed(title=f"📊 论坛统计：{task_name}", description=desc_str, color=STYLE["KIMI_YELLOW"])

        if not posts:
            embed.add_field(name="空空如也", value="暂时没有符合条件的帖子哦~", inline=False)
        else:
            content_list = []
            for i, post in enumerate(posts):
                index = (self.current_page - 1) * 20 + i + 1
                try: # 健壮的时间格式化
                    dt = datetime.datetime.fromisoformat(post[7]) if isinstance(post[7], str) else post[7]
                    date_str = dt.strftime('%Y-%m-%d')
                except:
                    date_str = str(post[7]).split(" ")[0]

                line = f"`{index}.` [{post[5]}]({post[6]}) - by {post[4]} ({date_str})"
                content_list.append(line)

            embed.add_field(name="统计列表", value="\n".join(content_list), inline=False)

        embed.set_footer(text=f"Task ID: {self.task_id} | 每日自动更新")

        self.total_pages = max(1, (total_count + 19) // 20)
        self.update_buttons()

        # 确保 interaction 是有效的
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            # 如果原始消息被删除了，就没办法了
            print(f"[View Update Error] Original interaction message for task {self.task_id} not found.")


    @discord.ui.button(label="◀️ 上一页", style=discord.ButtonStyle.primary, custom_id="stats_prev")
    async def prev_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page -= 1
        await self.update_embed(interaction)

    @discord.ui.button(label="▶️ 下一页", style=discord.ButtonStyle.primary, custom_id="stats_next")
    async def next_page(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.current_page += 1
        await self.update_embed(interaction)

    @discord.ui.button(label="页码", style=discord.ButtonStyle.secondary, disabled=True, custom_id="stats_page_info")
    async def page_info(self, button: discord.ui.Button, interaction: discord.Interaction):
        pass # This button is just for display

    @discord.ui.button(label="🔄 刷新", style=discord.ButtonStyle.success, custom_id="stats_refresh")
    async def refresh(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.update_embed(interaction)