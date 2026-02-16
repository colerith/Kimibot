import json
import os
import datetime
import discord
from config import STYLE
from .views import RoleClaimView

ROLES_DATA_FILE = "data/general_roles.json"
LOTTERY_DATA_FILE = "data/general_lottery.json"

# --- 身份组数据 ---
async def deploy_role_panel(self, channel, guild, user_avatar_url):
    """
    统一的面板部署逻辑：
    1. 构建 Embed
    2. 检查数据库中是否已记录该频道的面板消息ID
    3. 尝试编辑旧消息，如果失败（被删了/找不到）则发送新消息
    4. 更新数据库记录
    """
    # 1. 准备数据和 Embed
    data = load_role_data()
    active_roles = []
    claimable_ids = data.get("claimable_roles", [])
    
    for rid in claimable_ids:
        r = guild.get_role(rid)
        if r: active_roles.append(r)

    # 构建可用身份组的展示文本
    role_list_str = "*(暂无上架装饰)*"
    if active_roles:
        names = [f"`{r.name}`" for r in active_roles]
        role_list_str = " | ".join(names)

    embed = discord.Embed(
        title="🎨 **百变小蛋 · 装饰身份组中心**",
        description="欢迎来到装饰中心！在这里你可以自由装扮你的个人资料卡。\n\n"
                    "✨ **功能介绍**：\n"
                    "🔸 **开始装饰**：打开私密衣柜，查看并更换你的装饰。\n"
                    "🔸 **一键移除**：一键卸下所有在此处领取的装饰，恢复素颜。\n"
                    "🔸 **自动替换**：选择同系列新款式会自动替换旧的哦！\n\n"
                    "📜 **当前上架款式一览**：\n"
                    f"{role_list_str}",
        color=STYLE["KIMI_YELLOW"] # 确保你有导入 STYLE
    )
    if user_avatar_url:
        embed.set_thumbnail(url=user_avatar_url)
    embed.set_footer(text="点击下方按钮即可体验 👇")
    
    view = RoleClaimView() # 你的主面板 View

    # 2. 检查是否需要更新
    panel_info = data.get("panel_info", {})
    last_channel_id = panel_info.get("channel_id")
    last_message_id = panel_info.get("message_id")

    message = None
    
    # 只有当目标频道和记录的频道一致时，才尝试编辑
    if last_channel_id == channel.id and last_message_id:
        try:
            message = await channel.fetch_message(last_message_id)
            await message.edit(embed=embed, view=view)
            return "updated" # 返回状态：更新成功
        except (discord.NotFound, discord.Forbidden):
            # 消息被删了或者找不到，忽略，准备发新的
            message = None
    
    # 3. 发送新消息 (如果上面没获取到 message)
    if not message:
        message = await channel.send(embed=embed, view=view)
        
        # 4. 保存新的消息ID到数据库
        data["panel_info"] = {
            "channel_id": channel.id,
            "message_id": message.id
        }
        save_role_data(data)
        return "sent" # 返回状态：发送新消息

def load_role_data():
    if not os.path.exists(ROLES_DATA_FILE):
        return {"claimable_roles": []} # 存 Role ID
    try:
        with open(ROLES_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"claimable_roles": []}

def save_role_data(data):
    os.makedirs(os.path.dirname(ROLES_DATA_FILE), exist_ok=True)
    with open(ROLES_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- 抽奖数据 ---
def load_lottery_data():
    if not os.path.exists(LOTTERY_DATA_FILE):
        return {"active_lotteries": {}}
    try:
        with open(LOTTERY_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"active_lotteries": {}}

def save_lottery_data(data):
    os.makedirs(os.path.dirname(LOTTERY_DATA_FILE), exist_ok=True)
    with open(LOTTERY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)