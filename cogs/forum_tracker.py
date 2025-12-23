# cogs/forum_tracker.py

import discord
from discord.ext import commands, tasks
import sqlite3
import datetime
import asyncio
import io
from discord.commands import SlashCommandGroup, Option
from typing import Union

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from config import IDS, STYLE

# 数据库文件路径
DB_PATH = "forum_data.db"

# ======================================================================================
# --- 数据库管理类 ---
# ======================================================================================

class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracking_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                forum_channel_id INTEGER,
                output_channel_id INTEGER,
                msg_id INTEGER,
                title_keyword TEXT,
                content_keyword TEXT,
                auto_verify BOOLEAN DEFAULT 0
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_posts (
                thread_id INTEGER PRIMARY KEY,
                task_id INTEGER,
                author_id INTEGER,
                author_name TEXT,
                title TEXT,
                jump_url TEXT,
                created_at TIMESTAMP,
                status INTEGER DEFAULT 0 
            )
        """)
        self.conn.commit()

    def add_task(self, name, forum_id, output_id, msg_id, title_kw, content_kw, auto_verify):
        self.cursor.execute("""
            INSERT INTO tracking_tasks (name, forum_channel_id, output_channel_id, msg_id, title_keyword, content_keyword, auto_verify)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, forum_id, output_id, msg_id, title_kw, content_kw, auto_verify))
        self.conn.commit()
        return self.cursor.lastrowid

    def delete_task(self, task_id):
        self.cursor.execute("DELETE FROM tracking_tasks WHERE task_id = ?", (task_id,))
        self.cursor.execute("DELETE FROM tracked_posts WHERE task_id = ?", (task_id,))
        self.conn.commit()

    def add_post(self, thread_id, task_id, author_id, author_name, title, url, created_at, status):
        try:
            self.cursor.execute("""
                INSERT OR IGNORE INTO tracked_posts (thread_id, task_id, author_id, author_name, title, jump_url, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (thread_id, task_id, author_id, author_name, title, url, created_at, status))
            self.conn.commit()
        except Exception as e:
            print(f"Database Error: {e}")

    def update_post_status(self, thread_id, status):
        self.cursor.execute("UPDATE tracked_posts SET status = ? WHERE thread_id = ?", (status, thread_id))
        self.conn.commit()

    def get_tasks(self):
        self.cursor.execute("SELECT * FROM tracking_tasks")
        return self.cursor.fetchall()
    
    def get_task_by_id(self, task_id):
        self.cursor.execute("SELECT * FROM tracking_tasks WHERE task_id = ?", (task_id,))
        return self.cursor.fetchone()

    def get_valid_posts(self, task_id, page=1, per_page=20):
        offset = (page - 1) * per_page
        self.cursor.execute("""
            SELECT * FROM tracked_posts 
            WHERE task_id = ? AND status = 1 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        """, (task_id, per_page, offset))
        return self.cursor.fetchall()
    
    def get_all_posts_for_export(self, task_id):
        """获取某任务下的所有帖子（包括无效的，用于导出）"""
        self.cursor.execute("""
            SELECT * FROM tracked_posts 
            WHERE task_id = ? 
            ORDER BY created_at DESC 
        """, (task_id,))
        return self.cursor.fetchall()

    def get_total_valid_count(self, task_id):
        self.cursor.execute("SELECT COUNT(*) FROM tracked_posts WHERE task_id = ? AND status = 1", (task_id,))
        result = self.cursor.fetchone()
        return result[0] if result else 0

db = DatabaseManager()

# ======================================================================================
# --- 辅助函数 ---
# ======================================================================================

async def get_task_autocomplete(ctx: discord.AutocompleteContext):
    """用于 Slash Command 的任务自动补全"""
    tasks_data = db.get_tasks()
    # 过滤逻辑：如果用户输入了内容，匹配任务名；否则显示所有
    user_input = ctx.value.lower()
    return [
        discord.OptionChoice(name=f"{task[1]} (ID: {task[0]})", value=str(task[0]))
        for task in tasks_data if user_input in task[1].lower() or str(task[0]) in user_input
    ]

def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        allowed_ids = [1452321798308888776, IDS.get("SUPER_EGG_ROLE_ID")] 
        if ctx.author.id in allowed_ids: return True
        if hasattr(ctx.author, 'roles'):
            role_ids = [r.id for r in ctx.author.roles]
            if IDS.get("SUPER_EGG_ROLE_ID") in role_ids: return True
        await ctx.respond("🚫 只有管理员才能管理统计任务哦！", ephemeral=True)
        return False
    return commands.check(predicate)

# ======================================================================================
# --- 翻页视图 ---
# ======================================================================================

class ForumStatsView(discord.ui.View):
    def __init__(self, task_id, current_page=1, total_pages=1):
        super().__init__(timeout=None)
        self.task_id = task_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.current_page <= 1)
        self.children[1].disabled = (self.current_page >= self.total_pages)
        self.children[2].label = f"第 {self.current_page} / {self.total_pages} 页"

    async def update_embed(self, interaction):
        posts = db.get_valid_posts(self.task_id, self.current_page)
        total_count = db.get_total_valid_count(self.task_id) # 获取总数
        
        task_info = db.get_task_by_id(self.task_id)
        if not task_info:
            await interaction.response.send_message("该任务似乎已被删除。", ephemeral=True)
            return

        task_name, _, _, _, _, title_kw, _, _ = task_info
        
        # [修改] 时间格式化
        update_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        
        embed = discord.Embed(
            title=f"📊 论坛统计：{task_name}",
            # [修改] 描述中显示总收录数和固定时间格式
            description=f"🔍 关键词：`{title_kw}`\n📈 **总收录数：{total_count} 篇**\n🕒 更新时间：{update_time}",
            color=STYLE["KIMI_YELLOW"]
        )
        
        if not posts:
            embed.add_field(name="空空如也", value="暂时没有符合条件的帖子哦~", inline=False)
        else:
            content_list = []
            for i, post in enumerate(posts):
                # post: 0:id, 1:task_id, 2:uid, 3:name, 4:title, 5:url, 6:time, 7:status
                index = (self.current_page - 1) * 20 + i + 1
                
                # [修改] 帖子时间格式化
                try:
                    # 尝试解析时间字符串
                    if isinstance(post[6], str):
                        dt = datetime.datetime.fromisoformat(post[6])
                    else:
                        dt = post[6]
                    date_str = dt.strftime('%Y-%m-%d')
                except:
                    date_str = str(post[6]).split(" ")[0]

                line = f"`{index}.` [{post[4]}]({post[5]}) - by {post[3]} ({date_str})"
                content_list.append(line)
            
            chunk_text = "\n".join(content_list)
            embed.add_field(name="统计列表", value=chunk_text, inline=False)

        embed.set_footer(text=f"Task ID: {self.task_id} | 每日自动更新")
        
        self.total_pages = max(1, (total_count + 19) // 20)
        self.update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀️ 上一页", style=discord.ButtonStyle.primary, custom_id="stats_prev")
    async def prev_page(self, button, interaction):
        self.current_page -= 1
        await self.update_embed(interaction)

    @discord.ui.button(label="▶️ 下一页", style=discord.ButtonStyle.primary, custom_id="stats_next")
    async def next_page(self, button, interaction):
        self.current_page += 1
        await self.update_embed(interaction)

    @discord.ui.button(label="页码", style=discord.ButtonStyle.secondary, disabled=True, custom_id="stats_info")
    async def page_info(self, button, interaction):
        pass

    @discord.ui.button(label="🔄 刷新", style=discord.ButtonStyle.success, custom_id="stats_refresh")
    async def refresh(self, button, interaction):
        await self.update_embed(interaction)

# ======================================================================================
# --- Cog主体 ---
# ======================================================================================

class ForumTracker(commands.Cog):
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
            task_id, _, forum_id, _, _, title_kw, content_kw, auto_verify = task
            
            if thread.parent_id != forum_id: continue
            if title_kw and title_kw not in thread.name: continue
            
            if content_kw:
                try:
                    starter_msg = await thread.fetch_message(thread.id)
                    if content_kw not in starter_msg.content: continue
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

    @tasks.loop(hours=24)
    async def daily_update_task(self):
        await self.bot.wait_until_ready()
        print("⏰ 开始执行每日统计更新...")
        await self.refresh_all_panels()

    async def refresh_all_panels(self):
        tasks_data = db.get_tasks()
        for task in tasks_data:
            try:
                task_id, name, _, output_id, msg_id, _, _, _ = task
                
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
                
                posts = db.get_valid_posts(task_id, 1)
                update_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

                embed = discord.Embed(
                    title=f"📊 论坛统计：{name}",
                    description=f"📈 **总收录数：{total_count} 篇**\n🕒 更新时间：{update_time}",
                    color=STYLE["KIMI_YELLOW"]
                )
                if posts:
                    content_list = []
                    for i, post in enumerate(posts):
                        index = i + 1
                        try:
                            if isinstance(post[6], str): dt = datetime.datetime.fromisoformat(post[6])
                            else: dt = post[6]
                            date_str = dt.strftime('%Y-%m-%d')
                        except: date_str = str(post[6]).split(" ")[0]
                        line = f"`{index}.` [{post[4]}]({post[5]}) - by {post[3]} ({date_str})"
                        content_list.append(line)
                    embed.add_field(name="统计列表", value="\n".join(content_list), inline=False)
                else:
                    embed.add_field(name="暂无数据", value="等待收录中...", inline=False)
                
                embed.set_footer(text=f"Task ID: {task_id} | 每日自动更新")
                await msg.edit(embed=embed, view=view)
                
            except Exception as e:
                print(f"刷新任务 {task[0]} 失败: {e}")

    # ======================================================================================
    # --- 命令组 ---
    # ======================================================================================

    stats = SlashCommandGroup("论坛统计", "管理论坛帖子的自动统计任务")

    @stats.command(name="新建", description="创建一个新的统计任务")
    @is_super_egg()
    async def create_task(self, ctx,
        name: Option(str, "任务名称 (如: 围炉杯统计)"),
        forum_channel: Option(discord.ForumChannel, "要监控的论坛频道"),
        output_channel: Option(Union[discord.TextChannel, discord.Thread], "统计结果发送到哪个频道/子区"),
        title_keyword: Option(str, "标题必须包含的关键词", required=True),
        content_keyword: Option(str, "首楼必须包含的关键词", required=False, default=None),
        auto_verify: Option(bool, "是否自动通过审核", default=True)
    ):
        await ctx.defer()
        try:
            embed = discord.Embed(title=f"📊 统计任务初始化: {name}", description="正在准备数据...", color=STYLE["KIMI_YELLOW"])
            msg = await output_channel.send(embed=embed)
        except Exception as e:
            await ctx.followup.send(f"❌ 发送初始化消息失败: {e}", ephemeral=True)
            return
        
        task_id = db.add_task(name, forum_channel.id, output_channel.id, msg.id, title_keyword, content_keyword, auto_verify)
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
        # [修改] 自动获取 ID 逻辑
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
        await ctx.respond(f"操作成功！帖子 `{target_id}` {action}。\n如有需要请 `/论坛统计 手动刷新`。", ephemeral=True)

    @stats.command(name="手动刷新", description="立即刷新所有统计面板")
    @is_super_egg()
    async def manual_refresh(self, ctx):
        await ctx.defer(ephemeral=True)
        await self.refresh_all_panels()
        await ctx.followup.send("✅ 所有统计面板已刷新！", ephemeral=True)
        
    @stats.command(name="手动录入", description="在当前帖子内使用，将其加入指定任务")
    @is_super_egg()
    async def manual_add(self, ctx,
        task_id: Option(str, "选择要加入的任务", autocomplete=get_task_autocomplete),
        thread_id: Option(str, "帖子ID (如果在帖子内使用可不填)", required=False) = None
    ):
        await ctx.defer(ephemeral=True)
        
        # [修改] 自动获取 ID 逻辑
        target_id = None
        if thread_id:
            target_id = int(thread_id)
        elif isinstance(ctx.channel, discord.Thread):
            target_id = ctx.channel.id

        if not target_id:
            await ctx.followup.send("❌ 请输入帖子ID，或在帖子内使用此命令！", ephemeral=True)
            return

        try:
            tid = int(task_id) # 确保任务ID是数字
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
            
        except ValueError:
            await ctx.followup.send("❌ ID格式错误。", ephemeral=True)
        except Exception as e:
            await ctx.followup.send(f"❌ 录入失败: {e}", ephemeral=True)

    # [新增] 导出 Excel 命令
    @stats.command(name="导出", description="将统计结果导出为 Excel 表格")
    @is_super_egg()
    async def export_excel(self, ctx, 
        task_id: Option(str, "选择要导出的任务", autocomplete=get_task_autocomplete)
    ):
        if not HAS_OPENPYXL:
            await ctx.respond("❌ 导出功能需要安装 `openpyxl` 库。\n请联系管理员在后台运行 `pip install openpyxl`。", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        try:
            tid = int(task_id)
            task_info = db.get_task_by_id(tid)
            if not task_info:
                await ctx.followup.send("❌ 找不到该任务。", ephemeral=True)
                return

            task_name = task_info[1]
            # 获取该任务下的所有帖子（包括无效的，也可以选择只导出有效的）
            # 这里我设置为只导出有效的(status=1)，如果需要全部请改用 get_all_posts_for_export
            posts = db.get_valid_posts(tid, 1, 999999) # 获取所有有效帖子

            # 创建 Excel
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "统计结果"
            
            # 表头
            headers = ["序号", "帖子ID", "作者ID", "作者名称", "标题", "链接", "发布时间", "状态"]
            ws.append(headers)
            
            for i, post in enumerate(posts):
                # post: 0:thread_id, 1:task_id, 2:author_id, 3:author_name, 4:title, 5:jump_url, 6:created_at, 7:status
                
                # 处理时间格式
                try:
                    if isinstance(post[6], str): dt = datetime.datetime.fromisoformat(post[6])
                    else: dt = post[6]
                    time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                except: time_str = str(post[6])

                row = [
                    i + 1,
                    str(post[0]),
                    str(post[2]),
                    post[3],
                    post[4],
                    post[5],
                    time_str,
                    "有效" if post[7] == 1 else "无效"
                ]
                ws.append(row)

            # 保存到内存
            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
            
            filename = f"统计_{task_name}_{datetime.datetime.now().strftime('%Y%m%d')}.xlsx"
            await ctx.followup.send(f"✅ 导出成功！", file=discord.File(buffer, filename=filename), ephemeral=True)

        except Exception as e:
            await ctx.followup.send(f"❌ 导出失败: {e}", ephemeral=True)

def setup(bot):
    bot.add_cog(ForumTracker(bot))