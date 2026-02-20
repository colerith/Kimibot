# cogs/lottery/cog.py

import discord
from discord.ext import commands
from discord import SlashCommandGroup
import asyncio
import datetime
import random

from .storage import load_lottery_data, save_lottery_data
from .views import LotteryCreateModal, LotteryJoinView
from cogs.shared.utils import is_super_egg

class LotteryCog(commands.Cog, name="抽奖系统"):
    """负责所有抽奖相关的功能。"""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(LotteryJoinView("placeholder_prize"))
        print("[Lottery] Cog loaded and persistent view registered.")
        asyncio.create_task(self.resume_lotteries())

    # --- 命令组定义 ---
    lottery_group = SlashCommandGroup("抽奖", "激动人心的抽奖功能！")

    @lottery_group.command(name="发起", description="（管理）发起一个新的抽奖活动。")
    @is_super_egg()
    async def start_lottery(self, ctx: discord.ApplicationContext):
        await ctx.send_modal(LotteryCreateModal(self))

    @lottery_group.command(name="结束", description="（管理）强制提前结束某个抽奖。")
    @is_super_egg()
    async def force_end_lottery(self, ctx: discord.ApplicationContext, message_id: str):
        await ctx.defer(ephemeral=True)
        data = load_lottery_data()
        if message_id not in data["active_lotteries"]:
            return await ctx.followup.send("❌ 在数据库中找不到这个抽奖ID！", ephemeral=True)

        await self.end_lottery(int(message_id))
        await ctx.followup.send("✅ 已强制结束该抽奖！", ephemeral=True)


    # --- 后台逻辑 ---
    async def lottery_timer(self, message_id: int, seconds: int):
        """后台计时，在指定时间后结束抽奖。"""
        await asyncio.sleep(seconds)
        await self.end_lottery(message_id)

    async def end_lottery(self, message_id: int):
        """结束抽奖、公布结果并清理数据。"""
        data = load_lottery_data()
        msg_id_str = str(message_id)
        if msg_id_str not in data["active_lotteries"]:
            return

        lottery = data["active_lotteries"][msg_id_str]
        channel = self.bot.get_channel(lottery["channel_id"])
        if not channel:
            # 如果找不到频道，也直接清理数据
            del data["active_lotteries"][msg_id_str]
            save_lottery_data(data)
            return

        # 选出获胜者
        participants = lottery["participants"]
        count = min(len(participants), lottery["winners"])
        winners = random.sample(participants, count) if participants else []

        # 更新原抽奖消息
        try:
            msg = await channel.fetch_message(message_id)
            embed = msg.embeds[0]
            embed.title = f"🏁 [已结束] {lottery['prize']}"
            embed.description = "开奖结果如下！"
            embed.color = 0x99AAB5 # 灰色
            embed.set_footer(text=f"已结束 | 共 {len(participants)} 人参与")

            view = LotteryJoinView(lottery["prize"])
            # 禁用按钮并更改标签
            view.join_button.disabled = True
            view.join_button.label = "活动已结束"
            view.join_button.style = discord.ButtonStyle.secondary
            await msg.edit(embed=embed, view=view)

            # 发送开奖公告
            if winners:
                winner_mentions = " ".join([f"<@{uid}>" for uid in winners])
                result_embed = discord.Embed(
                    title="🎉 恭喜中奖！",
                    description=f"关于 **{lottery['prize']}** 的抽奖已经结束啦！\n\n🏆 **获奖者名单**：\n{winner_mentions}\n\n请获奖的小饱饱留意私信或者联系 **{lottery.get('provider', '发起者')}** 领奖哦！",
                    color=0xFFD700 # 金色
                )
                await channel.send(content=f"开奖啦！{winner_mentions}", embed=result_embed, reference=msg)
            else:
                await channel.send(f"🥀 关于 **{lottery['prize']}** 的抽奖结束啦，可惜没人参与，奖品只能自己吃掉惹...", reference=msg)
        except (discord.NotFound, discord.Forbidden) as e:
            print(f"结束抽奖 {message_id} 时出错: {e}")

        # 清理数据
        del data["active_lotteries"][msg_id_str]
        save_lottery_data(data)


    async def resume_lotteries(self):
        """机器人启动时调用，恢复所有正在进行的抽奖计时器。"""
        await self.bot.wait_until_ready()
        data = load_lottery_data()
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()

        # 遍历所有活动中的抽奖
        for msg_id, info in list(data["active_lotteries"].items()):
            remaining = info["end_timestamp"] - now_ts
            if remaining <= 0:
                # 如果已经过期，立即开奖
                await self.end_lottery(int(msg_id))
            else:
                # 否则，创建一个新的计时器任务
                self.bot.loop.create_task(self.lottery_timer(int(msg_id), remaining))
        print(f"[Lottery] Resumed {len(data['active_lotteries'])} active lotteries.")