import discord
from discord import ui
import datetime
import random

from .storage import load_lottery_data, save_lottery_data
from config import STYLE

# --- 用户端：参与抽奖 ---
class LotteryJoinView(discord.ui.View):
    def __init__(self, prize_name: str = "Default Prize"):
        super().__init__(timeout=None)
        # ✅ 修正：将按钮实例化并赋值给 self.join_button
        self.join_button = discord.ui.Button(
            label="🎉 立即参与抽奖",
            style=discord.ButtonStyle.primary,
            custom_id="lottery_join_btn",
            emoji="🎁"
        )
        self.add_item(self.join_button)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.data["custom_id"] == "lottery_join_btn":
            await self.join_lottery(interaction)
        return False

    async def join_lottery(self, interaction: discord.Interaction):
        # 确保 interaction 未被响应
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        msg_id = str(interaction.message.id)
        data = load_lottery_data()

        if msg_id not in data["active_lotteries"]:
            return await interaction.followup.send("这个抽奖已经失效或结束惹！", ephemeral=True)

        uid = interaction.user.id
        participants = data["active_lotteries"][msg_id]["participants"]

        if uid in participants:
            return await interaction.followup.send("你已经参与过啦！乖乖等待开奖吧~", ephemeral=True)

        participants.append(uid)
        save_lottery_data(data)

        # 更新原消息的 embed
        try:
            embed = interaction.message.embeds[0]
            embed.set_footer(text=f"正在进行 • {len(participants)} 人已参与 | 结束时间")
            await interaction.message.edit(embed=embed)
        except Exception as e:
            print(f"Error editing lottery message on join: {e}")


        await interaction.followup.send("🎉 参与成功！祝你好运哦！", ephemeral=True)


# --- 管理端：创建抽奖 ---
class LotteryCreateModal(discord.ui.Modal):
    def __init__(self, cog):
        super().__init__(title="🎁 发起抽奖")
        self.cog = cog

        # 1. 奖品名称
        self.add_item(discord.ui.InputText(
            label="奖品名称",
            placeholder="例如: 1个月Nitro",
            max_length=100
        ))
        # 2. 奖品提供者 (新)
        self.add_item(discord.ui.InputText(
            label="奖品提供者 (选填)",
            placeholder="例如: 芝士喵喵 / @某人 (留空默认为官方)",
            max_length=50,
            required=False
        ))
        # 3. 描述
        self.add_item(discord.ui.InputText(
            label="抽奖文案/描述",
            placeholder="庆祝新功能上线！大家快来...",
            style=discord.InputTextStyle.paragraph
        ))
        # 4. 人数
        self.add_item(discord.ui.InputText(
            label="中奖人数 (数字)",
            placeholder="例如: 1",
            max_length=5
        ))
        # 5. 时间
        self.add_item(discord.ui.InputText(
            label="持续时间",
            placeholder="例如: 10m, 2h, 1d",
            max_length=10
        ))

    async def callback(self, interaction: discord.Interaction):
        prize = self.children[0].value
        provider_raw = self.children[1].value
        provider = provider_raw if provider_raw and provider_raw.strip() else "奇米大王官方"
        desc = self.children[2].value

        try:
            winners = int(self.children[3].value)
            duration_str = self.children[4].value
            from ..shared.utils import parse_duration
            seconds = parse_duration(duration_str)
            if seconds < 60: raise ValueError("时间太短")
        except:
            return await interaction.response.send_message("❌ 人数必须是数字，时间格式如 10m, 1h，且至少1分钟！", ephemeral=True)

        await interaction.response.defer(ephemeral=True) 

        # 计算结束时间
        now = discord.utils.utcnow()
        end_time = now + datetime.timedelta(seconds=seconds)

        # === 构建美化版的 Embed ===
        embed = discord.Embed(title=f"🎆 [进行中] {prize}", color=STYLE["KIMI_YELLOW"])

        content_lines = [
            f"**🎁 奖品** : {prize}",
            f"**💖 提供者** : {provider}",
            "",
            desc,
            "",
            f"🏆 将抽取 **{winners}** 位幸运饱饱，中奖后请留意私信！",
            "",
            "⬇️ ⬇️ **点击下方按钮即可参与** ⬇️ ⬇️"
        ]
        embed.description = "\n".join(content_lines)

        embed.set_footer(text="正在进行 • 0 人已参与 | 结束时间")
        embed.timestamp = end_time

        # 使用 interaction.channel 发送抽奖消息，而不是 followup
        msg = await interaction.channel.send(embed=embed, view=LotteryJoinView(prize))

        # 告诉发起者成功
        await interaction.followup.send(f"✅ 抽奖已成功在 {interaction.channel.mention} 发起！", ephemeral=True)

        # 存入数据
        data = load_lottery_data()
        data["active_lotteries"][str(msg.id)] = {
            "channel_id": interaction.channel_id,
            "prize": prize,
            "provider": provider,
            "text": desc,
            "winners": winners,
            "end_timestamp": end_time.timestamp(),
            "participants": []
        }
        save_lottery_data(data)

        # 启动计时任务
        self.cog.bot.loop.create_task(self.cog.lottery_timer(msg.id, seconds))