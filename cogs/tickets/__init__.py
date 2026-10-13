from config import MANUAL_REVIEW_ENABLED
from .core import Tickets
from .qq_bridge import setup_bridge

def setup(bot):
    # 不注册审核命令、持久化按钮、提醒任务或 QQ 审核桥接。
    if not MANUAL_REVIEW_ENABLED:
        return
    bot.add_cog(Tickets(bot))
    setup_bridge(bot)
