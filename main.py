import discord
from discord.ext import commands
import os
# from keep_alive import keep_alive  # Not needed for Reserved VM deployment

load_dotenv()
# 从环境变量读取 Bot Token（由 Replit Secrets 管理）
BOT_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN")

print(f"从.env文件中读取到的Token是: '{BOT_TOKEN}'")

# --- 机器人本体创建 ---
# 确保所有需要的 Intents 都已开启
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = discord.Bot(intents=intents)

# --- 启动时加载所有“魔法书” (Cogs) ---
# 将要加载的 Cog 文件名放在一个列表中
# 这样你就可以轻松地启用或禁用某个功能模块
cogs_list = ['general', 'management', 'tickets', 'quiz']

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

    # --- 调用 Tickets Cog 的函数，并加上保护 ---
    try:
        tickets_cog = bot.get_cog("Tickets")
        if tickets_cog:
            await tickets_cog.update_ticket_panel()
            print("🔧 已检查并更新工单面板。")
        else:
            print("⚠️ 未找到 Tickets Cog，跳过工单面板更新。")
    except Exception as e:
        print(f"❌ 更新工单面板时发生致命错误: {e}")  # 这会将错误打印到日志里！

    # --- 调用 General Cog 的函数，并加上保护 ---
    try:
        general_cog = bot.get_cog("General")
        if general_cog:
            await general_cog.check_and_post_wish_panel()
            print("🔧 已检查并更新许愿池面板。")
        else:
            print("⚠️ 未找到 General Cog，跳过许愿池面板更新。")
    except Exception as e:
        print(f"❌ 更新许愿池面板时发生致命错误: {e}")  # 这会将错误打印到日志里！

    print("========================================")
    print("本大王已经准备好萌翻全场惹！")
    print("========================================")


# --- 启动机器人 ---
# keep_alive()  # Not needed for Reserved VM deployment
if __name__ == "__main__":
    if BOT_TOKEN == "你的机器人TOKEN" or BOT_TOKEN == "":
        print("错误：请先在 config.py 文件中填写你的机器人TOKEN！")
    else:
        bot.run(BOT_TOKEN)
