# cogs/forum_tracker/cog.py

import discord
from discord.ext import commands, tasks
from discord import Option, SlashCommandGroup
import datetime
import asyncio
import io
from typing import Union

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from config import IDS, STYLE
from .db import db
from .views import ForumStatsView
from .utils import get_task_autocomplete, check_keywords
from ..shared.utils import is_super_egg

class ForumTrackerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_update_task.start()

    def cog_unload(self):
        self.daily_update_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        print("📊 论坛统计模块已加载")

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        await asyncio.sleep(2)
        tasks_data = db.get_tasks()
        
        for task in tasks_data:
            task_id, _, forum_id, _, _, title_kw, content_kw, auto_verify = task[:8]
            content_logic = task[8] if len(task) > 8 else "OR" # 兼容旧数据
            
            if thread.parent_id != forum_id: continue
            if title_kw and title_kw not in thread.name: continue
            
            # 检查首楼内容（支持多关键词）
            if content_kw:
                try:
                    starter_msg = await thread.fetch_message(thread.id)
                    # 调用新的检查函数
                    if not check_keywords(starter_msg.content, content_kw, content_logic):
                        continue
                except: continue

            status = 1 if auto_verify else 0
            db.add_post(
                thread_id=thread.id,
                task_id=task_id,
                author_id=thread.owner_id,
                author_name=thread.owner.display_name if thread.owner else "未知用户",
                title=thread.name,
                url=thread.jump_url,
                created_at=thread.created_at,
                status=status
            )
            print(f"✅ [统计] 捕获新帖: {thread.name} -> Task {task_id}")

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        """监听帖子删除事件，自动同步数据库"""
        # 尝试从数据库删除对应的记录
        deleted_count = db.delete_post_by_thread_id(thread.id)
        
        if deleted_count > 0:
            print(f"🗑️ [统计] 监测到帖子被删，已从数据库移除: {thread.name} (ID: {thread.id})")

    @tasks.loop(hours=24)
    async def daily_update_task(self):
        await self.bot.wait_until_ready()
        print("⏰ 开始执行每日统计更新...")
        await self.refresh_all_panels()

    async def refresh_all_panels(self):
        tasks_data = db.get_tasks()
        for task in tasks_data:
            try:
                task_id, name, _, output_id, msg_id, _, _, _ = task[:8]
                
                channel = self.bot.get_channel(output_id)
                if not channel:
                    try:
                        channel = await self.bot.fetch_channel(output_id)
                    except: continue
                
                try:
                    msg = await channel.fetch_message(msg_id)
                except discord.NotFound:
                    msg = await channel.send("正在初始化统计面板...")
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE tracking_tasks SET msg_id = ? WHERE task_id = ?", (msg.id, task_id))
                    conn.commit()
                    conn.close()

                view = ForumStatsView(task_id=task_id, current_page=1)
                total_count = db.get_total_valid_count(task_id)
                view.total_pages = max(1, (total_count + 19) // 20)
                view.update_buttons()
                
                # 获取任务信息用于显示关键词
                task_info = db.get_task_by_id(task_id)
                title_kw = task_info[5]
                content_kw = task_info[6]
                content_logic = task_info[8] if len(task_info) > 8 else "OR"

                posts = db.get_valid_posts(task_id, 1)
                update_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

                desc_str = f"📈 **总收录数：{total_count} 篇**\n🕒 更新时间：{update_time}\n"
                desc_str += f"🔍 标题包含：`{title_kw}`\n"
                if content_kw:
                     desc_str += f"📄 首楼包含：`{content_kw}` (模式: {content_logic})"

                embed = discord.Embed(
                    title=f"📊 论坛统计：{name}",
                    description=desc_str,
                    color=STYLE["KIMI_YELLOW"]
                )
                if posts:
                    content_list = []
                    for i, post in enumerate(posts):
                        index = i + 1
                        # 修正索引
                        try:
                            if isinstance(post[7], str): dt = datetime.datetime.fromisoformat(post[7])
                            else: dt = post[7]
                            date_str = dt.strftime('%Y-%m-%d')
                        except: date_str = str(post[7]).split(" ")[0]
                        
                        # 修正：Title[5], URL[6], Author[4]
                        line = f"`{index}.` [{post[5]}]({post[6]}) - by {post[4]} ({date_str})"
                        content_list.append(line)
                    embed.add_field(name="统计列表", value="\n".join(content_list), inline=False)
                else:
                    embed.add_field(name="暂无数据", value="等待收录中...", inline=False)
                
                embed.set_footer(text=f"Task ID: {task_id} | 每日自动更新")
                await msg.edit(embed=embed, view=view)
                
            except Exception as e:
                print(f"刷新任务 {task[0]} 失败: {e}")

    # --- 命令组 ---
    stats = SlashCommandGroup("论坛统计", "管理论坛帖子的自动统计任务")

    @stats.command(name="新建", description="创建一个新的统计任务")
    @is_super_egg()
    async def create_task(self, ctx,
        name: Option(str, "任务名称 (如: 围炉杯统计)"),
        forum_channel: Option(discord.ForumChannel, "要监控的论坛频道"),
        output_channel: Option(Union[discord.TextChannel, discord.Thread], "统计结果发送到哪个频道/子区"),
        title_keyword: Option(str, "标题必须包含的关键词", required=True),
        content_keyword: Option(str, "首楼关键词 (多个用逗号分隔)", required=False, default=None),
        logic_mode: Option(str, "关键词匹配逻辑", choices=["满足任意一个(OR)", "满足所有(AND)"], default="满足任意一个(OR)"),
        auto_verify: Option(bool, "是否自动通过审核", default=True)
    ):
        await ctx.defer()
        
        # 解析逻辑模式
        logic_val = 'AND' if 'AND' in logic_mode else 'OR'
        
        try:
            embed = discord.Embed(title=f"📊 统计任务初始化: {name}", description="正在准备数据...", color=STYLE["KIMI_YELLOW"])
            msg = await output_channel.send(embed=embed)
        except Exception as e:
            await ctx.followup.send(f"❌ 发送初始化消息失败: {e}", ephemeral=True)
            return
        
        task_id = db.add_task(name, forum_channel.id, output_channel.id, msg.id, title_keyword, content_keyword, auto_verify, logic_val)
        await self.refresh_all_panels()
        await ctx.followup.send(f"✅ 任务 **{name}** (ID: {task_id}) 创建成功！", ephemeral=True)

    @stats.command(name="停止", description="删除一个统计任务")
    @is_super_egg()
    async def stop_task(self, ctx, task_id: Option(str, "选择任务", autocomplete=get_task_autocomplete)):
        try:
            tid = int(task_id)
            db.delete_task(tid)
            await ctx.respond(f"🗑️ 任务 ID {tid} 已删除。", ephemeral=True)
        except ValueError:
            await ctx.respond("❌ 任务ID格式错误", ephemeral=True)

    @stats.command(name="审核", description="在当前帖子内使用，或输入ID")
    @is_super_egg()
    async def verify_post(self, ctx,
        valid: Option(bool, "True=有效, False=移除"),
        thread_id: Option(str, "帖子ID (如果在帖子内使用可不填)", required=False) = None
    ):
        target_id = None
        if thread_id:
            target_id = int(thread_id)
        elif isinstance(ctx.channel, discord.Thread):
            target_id = ctx.channel.id
        
        if not target_id:
            await ctx.respond("❌ 请输入帖子ID，或在帖子内使用此命令！", ephemeral=True)
            return

        status = 1 if valid else 0
        db.update_post_status(target_id, status)
        action = "✅ 已计入统计" if valid else "🚫 已从统计移除"
        await ctx.respond(f"操作成功！帖子 `{target_id}` {action}。\n如有需要请前往 `/社区面板 管理` 刷新论坛统计。", ephemeral=True)

    @stats.command(name="手动录入", description="在当前帖子内使用，将其加入指定任务")
    @is_super_egg()
    async def manual_add(self, ctx,
        task_id: Option(str, "选择要加入的任务", autocomplete=get_task_autocomplete),
        thread_id: Option(str, "帖子ID (如果在帖子内使用可不填)", required=False) = None
    ):
        await ctx.defer(ephemeral=True)
        
        target_id = None
        if thread_id:
            target_id = int(thread_id)
        elif isinstance(ctx.channel, discord.Thread):
            target_id = ctx.channel.id

        if not target_id:
            await ctx.followup.send("❌ 请输入帖子ID，或在帖子内使用此命令！", ephemeral=True)
            return

        try:
            tid = int(task_id)
            thread = await self.bot.fetch_channel(target_id)
            if not isinstance(thread, discord.Thread):
                await ctx.followup.send("❌ 目标不是一个有效的帖子/子区！", ephemeral=True)
                return

            db.add_post(
                thread_id=thread.id,
                task_id=tid,
                author_id=thread.owner_id,
                author_name=thread.owner.display_name if thread.owner else "未知",
                title=thread.name,
                url=thread.jump_url,
                created_at=thread.created_at,
                status=1
            )
            await ctx.followup.send(f"✅ 帖子 **{thread.name}** 已补录到任务 {tid}！", ephemeral=True)
        except Exception as e:
            await ctx.followup.send(f"❌ 录入失败: {e}", ephemeral=True)

    @stats.command(name="导出", description="将统计结果导出为 Excel 表格")
    @is_super_egg()
    async def export_excel(self, ctx, 
        task_id: Option(str, "选择要导出的任务", autocomplete=get_task_autocomplete)
    ):
        if not HAS_OPENPYXL:
            await ctx.respond("❌ 需要安装 `openpyxl` 库。", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        try:
            tid = int(task_id)
            task_info = db.get_task_by_id(tid)
            if not task_info:
                await ctx.followup.send("❌ 找不到该任务。", ephemeral=True)
                return

            task_name = task_info[1]
            posts = db.get_valid_posts(tid, 1, 999999) 

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "统计结果"
            # 修改表头顺序以匹配数据
            headers = ["序号", "帖子ID", "作者ID", "作者名称", "标题", "链接", "发布时间", "状态"]
            ws.append(headers)
            
            for i, post in enumerate(posts):
                
                try:
                    if isinstance(post[7], str): dt = datetime.datetime.fromisoformat(post[7])
                    else: dt = post[7]
                    time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                except: time_str = str(post[7])

                row = [
                    i + 1,
                    str(post[1]), # thread_id
                    str(post[3]), # author_id
                    post[4],      # author_name
                    post[5],      # title
                    post[6],      # jump_url
                    time_str,     # created_at
                    "有效" if post[8] == 1 else "无效" # status
                ]
                ws.append(row)

            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            
            filename = f"统计_{task_name}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
            await ctx.followup.send(f"✅ 导出成功！", file=discord.File(buffer, filename=filename), ephemeral=True)

        except Exception as e:
            await ctx.followup.send(f"❌ 导出失败: {e}", ephemeral=True)

    @stats.command(name="清理", description="检测并移除已失效(被删除)的帖子数据")
    @is_super_egg()
    async def clean_invalid_posts(self, ctx,
        task_id: Option(str, "选择任务", autocomplete=get_task_autocomplete)
    ):
        await ctx.defer(ephemeral=True)
        try:
            tid = int(task_id)
            # 获取该任务下所有“有效”状态的帖子
            posts = db.get_valid_posts(tid, 1, 999999)
            
            cleaned_count = 0
            await ctx.followup.send(f"🔍 开始检查 {len(posts)} 个帖子的有效性，请稍候...", ephemeral=True)
            
            for post in posts:
                # post[1] 是 thread_id
                thread_id = post[1]
                
                try:
                    await self.bot.fetch_channel(thread_id)
                except discord.NotFound:
                    db.delete_post_by_thread_id(thread_id)
                    cleaned_count += 1
                except Exception:
                    pass
                
                await asyncio.sleep(0.1)
            
            if cleaned_count > 0:
                await self.refresh_all_panels() # 
                await ctx.followup.send(f"✅ 清理完成！共移除了 **{cleaned_count}** 个已删除的帖子数据。\n面板已自动刷新。", ephemeral=True)
            else:
                await ctx.followup.send("✅ 数据很健康！没有发现失效的帖子。", ephemeral=True)
                
        except ValueError:
            await ctx.followup.send("❌ 任务ID错误。", ephemeral=True)
        except Exception as e:
            await ctx.followup.send(f"❌ 清理过程中出错: {e}", ephemeral=True)
