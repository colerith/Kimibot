import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
# 从环境变量读取 Bot Token
BOT_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN")

# 安全起见，不要在日志里直接打印完整的 Token，只显示前几位
if BOT_TOKEN:
    print(f"成功读取 Token: {BOT_TOKEN[:5]}...******")
else:
    print("❌ 未检测到 Token！请检查环境变量或 .env 文件")

# --- 机器人本体创建 ---
# 确保所有需要的 Intents 都已开启
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- 启动时加载所有“魔法书” (Cogs) ---
cogs_list = ['general', 'management', 'tickets', 'quiz', 'forum_tracker']

for cog in cogs_list:
    try:
        bot.load_extension(f'cogs.{cog}')
        print(f'✅ 成功加载魔法书: {cog}.py')
    except Exception as e:
        print(f'❌ 加载魔法书 {cog}.py 失败: {e}')


# --- 机器人完全准备就绪后执行的事件 ---
@bot.event
async def on_ready():
    print("----------------------------------------")
    print(f"唷呐！我是 {bot.user.name}，最可爱的美少年来捉！")
    print(f"机器人ID: {bot.user.id}")
    print("----------------------------------------")
    
    # 注意：
    # 这里的 Tickets 和 General 的面板更新逻辑已经移除。
    # 因为在它们各自的 Cog 文件 (tickets.py, general.py) 的 on_ready 中已经包含了自动启动逻辑。
    # 这样可以避免机器人启动时重复发送两次面板！

    print("========================================")
    print("本大王已经准备好萌翻全场惹！")
    print("========================================")


# --- 启动机器人 ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("错误：请先在 .env 文件或环境变量中配置 Token！")
    else:
        bot.run(BOT_TOKEN)