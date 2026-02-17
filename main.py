# main.py

import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
# 从环境变量读取 Bot Token
BOT_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN")

DEBUG_GUILDS = [1397629012292931726] 

if BOT_TOKEN:
    print(f"成功读取 Token: {BOT_TOKEN[:5]}...******")
else:
    print("❌ 未检测到 Token！请检查环境变量或 .env 文件")

# --- 机器人本体创建 ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# 💡 关键修改：在这里加入 debug_guilds 参数
bot = discord.Bot(intents=intents, debug_guilds=DEBUG_GUILDS)

# --- 启动时加载所有“魔法书” (Cogs) ---
cogs_list = ['management', 'tickets', 'quiz', 'forum_tracker','general.core']

for cog in cogs_list:
    try:
        # 加上判断文件存在的逻辑会更稳健，不过这样也行
        bot.load_extension(f'cogs.{cog}')
        print(f'✅ 成功加载魔法书: {cog}.py')
    except Exception as e:
        print(f'❌ 加载魔法书 {cog}.py 失败: {e}')
        # 如果是找不到文件，提示一下
        if "No module named" in str(e):
             print(f"   (提示: 请检查 cogs 文件夹下是否有 {cog}.py 文件)")


# --- 机器人完全准备就绪后执行的事件 ---
@bot.event
async def on_ready():
    print("----------------------------------------")
    print(f"唷呐！我是 {bot.user.name}，最可爱的美少年来捉！")
    print(f"机器人ID: {bot.user.id}")
    print("----------------------------------------")

    print("⏳ 正在强制刷新开发服务器指令...")

    try:
        await bot.sync_commands()
        print(f"✅ 指令已同步！(生效范围: {len(DEBUG_GUILDS)} 个测试服务器)")
        print("💡 提示: 在 debug_guilds 列表内的服务器，指令更新是秒级的哦！")
    except Exception as e:
        print(f"⚠️ 同步时遇到了一点小波折: {e}")

    print("========================================")
    print("本大王已经准备好萌翻全场惹！")
    print("========================================")


# --- 启动机器人 ---
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("错误：请先在 .env 文件或环境变量中配置 Token！")
    else:
        bot.run(BOT_TOKEN)
