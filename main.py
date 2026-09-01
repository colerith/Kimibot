# main.py
import discord
from discord.ext import commands
import sys
import traceback
import os

from dotenv import load_dotenv
from cogs.shared.sqlite_store import migrate_runtime_json_namespaces
from cogs.shared.discord_http_scheduler import install_discord_http_scheduler


load_dotenv()
migrate_runtime_json_namespaces()
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
bot = discord.Bot(intents=intents, debug_guilds=DEBUG_GUILDS)

# Pycord handles route buckets and 429 retries. This shared pre-flight scheduler
# prevents unrelated cogs from collectively bursting through the global limit.
http_scheduler = install_discord_http_scheduler(
    bot,
    requests_per_second=float(os.getenv("DISCORD_HTTP_REQUESTS_PER_SECOND", "40")),
    max_concurrency=int(os.getenv("DISCORD_HTTP_MAX_CONCURRENCY", "8")),
    max_queue_size=int(os.getenv("DISCORD_HTTP_MAX_QUEUE_SIZE", "5000")),
    queue_warning_size=int(os.getenv("DISCORD_HTTP_QUEUE_WARNING_SIZE", "250")),
)

# --- 启动时加载所有“魔法书” (Cogs) ---
cogs_list = ['manage', 'tickets', 'lottery', 'forum_tracker','welcome', 'points', 'poll', 'roles', 'thread_tools', 'wish_pool']

for folder in os.listdir('cogs'):
    if os.path.exists(os.path.join('cogs', folder, '__init__.py')):
        try:
            bot.load_extension(f'cogs.{folder}')
            print(f'✅ 成功加载魔法书: {folder}')
        except Exception as e:
            print(f'❌ 加载魔法书 {folder} 失败:', file=sys.stderr)
            traceback.print_exc()

# --- 机器人完全准备就绪后执行的事件 ---
@bot.event
async def on_ready():
    print("----------------------------------------")
    print(f"唷呐！我是 {bot.user.name}，最可爱的美少年来捉！")
    print(f"机器人ID: {bot.user.id}")
    print(f"✅ 已成功连接到 {len(bot.guilds)} 个服务器")
    print("----------------------------------------")
    print("本大王已经准备好萌翻全场惹！")
    print("========================================")

# --- 启动机器人 ---
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
