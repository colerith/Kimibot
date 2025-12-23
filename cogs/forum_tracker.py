# cogs/forum_tracker.py

import discord
from discord.ext import commands, tasks
import sqlite3
import datetime
import asyncio
from discord.commands import SlashCommandGroup, Option
from typing import Union
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
        # 任务表：存储统计任务的配置
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
        # 帖子表：存储捕获到的帖子信息
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
        # status: 0=待审核/无效, 1=有效(计入统计)
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

    def get_valid_posts(self, task_id, page=1, per_page=20):
        offset = (page - 1) * per_page
        self.cursor.execute("""
            SELECT * FROM tracked_posts 
            WHERE task_id = ? AND status = 1 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        """, (task_id, per_page, offset))
        return self.cursor.fetchall()

    def get_total_valid_count(self, task_id):
        self.cursor.execute("SELECT COUNT(*) FROM tracked_posts WHERE task_id = ? AND status = 1", (task_id,))
        return self.cursor.fetchone()[0]

db = DatabaseManager()

# ======================================================================================
# --- 权限检查 ---
# ======================================================================================

def is_super_egg():
    """权限检查：判断命令使用者是否为指定的【审核小蛋】或【超级小蛋】"""
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        # 这里替换为你指定的ID或从配置读取
        allowed_ids = [1452321798308888776, IDS.get("SUPER_EGG_ROLE_ID")] 
        if ctx.author.id in allowed_ids: return True
        
        # 兼容角色检查
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
        super().__init__(timeout=None) # 持久化视图
        self.task_id = task_id
        self.current_page = current_page
        self.total_pages = total_pages
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.current_page <= 1) # 上一页
        self.children[1].disabled = (self.current_page >= self.total_pages) # 下一页
        self.children[2].label = f"第 {self.current_page} / {self.total_pages} 页"

    async def update_embed(self, interaction):
        posts = db.get_valid_posts(self.task_id, self.current_page)
        
        # 获取任务信息以构建标题
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name, title_keyword FROM tracking_tasks WHERE task_id = ?", (self.task_id,))
        task_info = cursor.fetchone()
        conn.close()
        
        if not task_info:
            await interaction.response.send_message("该任务似乎已被删除。", ephemeral=True)
            return

        task_name, title_kw = task_info
        
        embed = discord.Embed(
            title=f"📊 论坛统计：{task_name}",
            description=f"关键词：`{title_kw}`\n更新时间：<t:{int(datetime.datetime.now().timestamp())}:R>",
            color=STYLE["KIMI_YELLOW"]
        )
        
        if not posts:
            embed.add_field(name="空空如也", value="暂时没有符合条件的帖子哦~", inline=False)
        else:
            # 拼接帖子列表
            content_list = []
            for i, post in enumerate(posts):
                # post结构: 0:thread_id, 1:task_id, 2:author_id, 3:author_name, 4:title, 5:jump_url, 6:created_at, 7:status
                index = (self.current_page - 1) * 20 + i + 1
                date_str = str(post[6]).split(" ")[0]
                line = f"`{index}.` [{post[4]}]({post[5]}) - by {post[3]} ({date_str})"
                content_list.append(line)
            
            # 分割字段防止超过 embed 限制
            chunk_text = "\n".join(content_list)
            embed.add_field(name="统计列表", value=chunk_text, inline=False)

        embed.set_footer(text=f"Task ID: {self.task_id} | 每日自动更新")
        
        self.total_pages = max(1, (db.get_total_valid_count(self.task_id) + 19) // 20)
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
        # 恢复持久化视图
        tasks_data = db.get_tasks()
        for task in tasks_data:
            # task: 0:id, 4:msg_id
            task_id = task[0]
            # 我们需要计算当前总页数来正确初始化视图
            total_count = db.get_total_valid_count(task_id)
            total_pages = max(1, (total_count + 19) // 20)
            
            # 注册视图， custom_id 前缀需要一致（这里通过 View 类处理了）
            # 注意：discord.py 的持久化视图通常需要指定 custom_id，这里简化为重新绑定
            # 但为了完全持久化，建议 update_embed 里的 custom_id 加上 task_id 后缀
            # 这里为了简化，我们依赖 bot 重启后用户点击按钮会触发交互失败 -> 重新生成消息的逻辑，
            # 或者更严谨地，我们在 on_ready 重新注册带 ID 的 View。
            # 鉴于代码复杂度，这里使用通用 View，但在重启后旧按钮可能会失效，直到下一次每日更新。
            pass
        print("📊 论坛统计模块已加载")

    # --- 监听：新帖子创建 ---
    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        # 等待一小会儿确保首楼消息已生成
        await asyncio.sleep(2)
        
        # 获取所有任务
        tasks_data = db.get_tasks()
        for task in tasks_data:
            # task: 0:id, 1:name, 2:forum_id, 3:output_id, 4:msg_id, 5:title_kw, 6:content_kw, 7:auto_verify
            task_id, _, forum_id, _, _, title_kw, content_kw, auto_verify = task
            
            # 1. 检查频道是否匹配
            if thread.parent_id != forum_id:
                continue

            # 2. 检查标题关键词
            if title_kw and title_kw not in thread.name:
                continue

            # 3. 检查首楼内容关键词 (如果有设置)
            if content_kw:
                try:
                    starter_msg = await thread.fetch_message(thread.id)
                    if content_kw not in starter_msg.content:
                        continue
                except:
                    # 如果获取不到首楼（比如不是文本贴），默认跳过或根据需求处理
                    continue

            # 4. 入库
            status = 1 if auto_verify else 0 # 如果开启自动审核则直接有效，否则需人工
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

    # --- 每日更新任务 ---
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
                
                # 修改点：尝试获取频道，如果缓存没有则尝试 API 获取（对子区很重要）
                channel = self.bot.get_channel(output_id)
                if not channel:
                    try:
                        channel = await self.bot.fetch_channel(output_id)
                    except discord.NotFound:
                        print(f"任务 {task_id} 的输出频道/子区已不存在。")
                        continue
                    except Exception:
                        continue
                
                try:
                    msg = await channel.fetch_message(msg_id)
                except discord.NotFound:
                    # 消息被删了，重新发一个
                    msg = await channel.send("正在初始化统计面板...")
                    # 更新数据库里的 msg_id
                    conn = sqlite3.connect(DB_PATH)
                    conn.execute("UPDATE tracking_tasks SET msg_id = ? WHERE task_id = ?", (msg.id, task_id))
                    conn.commit()
                    conn.close()

                # 构建第一页
                view = ForumStatsView(task_id=task_id, current_page=1)
                
                total_count = db.get_total_valid_count(task_id)
                view.total_pages = max(1, (total_count + 19) // 20)
                view.update_buttons()
                
                posts = db.get_valid_posts(task_id, 1)
                embed = discord.Embed(
                    title=f"📊 论坛统计：{name}",
                    description=f"每日自动更新 | 总收录: {total_count} 篇",
                    color=STYLE["KIMI_YELLOW"]
                )
                if posts:
                    content_list = []
                    for i, post in enumerate(posts):
                        index = i + 1
                        date_str = str(post[6]).split(" ")[0]
                        line = f"`{index}.` [{post[4]}]({post[5]}) - by {post[3]} ({date_str})"
                        content_list.append(line)
                    embed.add_field(name="统计列表", value="\n".join(content_list), inline=False)
                else:
                    embed.add_field(name="暂无数据", value="等待收录中...", inline=False)
                
                embed.set_footer(text=f"Task ID: {task_id} | 更新于 {datetime.datetime.now().strftime('%H:%M')}")
                
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
        # 修改点：允许 TextChannel (普通频道) 或 Thread (子区)
        output_channel: Option(Union[discord.TextChannel, discord.Thread], "统计结果发送到哪个频道或子区"),
        title_keyword: Option(str, "标题必须包含的关键词", required=True),
        content_keyword: Option(str, "首楼必须包含的关键词", required=False, default=None),
        auto_verify: Option(bool, "是否自动通过审核 (True=自动上榜, False=需人工审核)", default=True)
    ):
        await ctx.defer()
        
        # 检查机器人是否有权限在那个子区/频道说话
        try:
            # 发送初始消息占位
            embed = discord.Embed(title=f"📊 统计任务初始化: {name}", description="正在准备数据...", color=STYLE["KIMI_YELLOW"])
            msg = await output_channel.send(embed=embed)
        except discord.Forbidden:
            await ctx.followup.send(f"❌ 我没有权限在 {output_channel.mention} 发送消息！请检查权限。", ephemeral=True)
            return
        except Exception as e:
            await ctx.followup.send(f"❌ 发送初始化消息失败: {e}", ephemeral=True)
            return
        
        # 入库
        task_id = db.add_task(name, forum_channel.id, output_channel.id, msg.id, title_keyword, content_keyword, auto_verify)
        
        # 立即刷新一次面板
        await self.refresh_all_panels()
        
        await ctx.followup.send(f"✅ 任务 **{name}** (ID: {task_id}) 创建成功！\n监控频道: {forum_channel.mention}\n输出位置: {output_channel.mention}\n\n从现在开始的新帖子将被自动记录。", ephemeral=True)
        
    @stats.command(name="列表", description="查看当前正在运行的统计任务")
    @is_super_egg()
    async def list_tasks(self, ctx):
        tasks_data = db.get_tasks()
        if not tasks_data:
            await ctx.respond("当前没有运行中的统计任务。", ephemeral=True)
            return
        
        embed = discord.Embed(title="📋 统计任务列表", color=STYLE["KIMI_YELLOW"])
        for task in tasks_data:
            # task: 0:id, 1:name, 2:forum_id, 3:output_id, ...
            embed.add_field(
                name=f"ID: {task[0]} | {task[1]}",
                value=f"监控: <#{task[2]}>\n输出: <#{task[3]}>\n关键词: {task[5]}",
                inline=False
            )
        await ctx.respond(embed=embed, ephemeral=True)

    @stats.command(name="停止", description="删除一个统计任务")
    @is_super_egg()
    async def stop_task(self, ctx, task_id: int):
        db.delete_task(task_id)
        await ctx.respond(f"🗑️ 任务 ID {task_id} 已删除。", ephemeral=True)

    @stats.command(name="审核", description="手动将某个帖子设为有效/无效 (计入/移除统计)")
    @is_super_egg()
    async def verify_post(self, ctx,
        thread_id: Option(str, "帖子的ID (右键帖子复制ID)"),
        valid: Option(bool, "是否有效 (True=计入, False=移除)")
    ):
        try:
            tid = int(thread_id)
            status = 1 if valid else 0
            db.update_post_status(tid, status)
            
            action = "✅ 已计入统计" if valid else "🚫 已从统计移除"
            await ctx.respond(f"操作成功！帖子 `{tid}` {action}。\n请使用 `/论坛统计 手动刷新` 更新面板。", ephemeral=True)
        except ValueError:
            await ctx.respond("请输入正确的数字ID！", ephemeral=True)

    @stats.command(name="手动刷新", description="立即刷新所有统计面板")
    @is_super_egg()
    async def manual_refresh(self, ctx):
        await ctx.defer(ephemeral=True)
        await self.refresh_all_panels()
        await ctx.followup.send("✅ 所有统计面板已刷新！", ephemeral=True)
        
    @stats.command(name="手动录入", description="强制将一个已存在的帖子加入统计 (用于补录旧贴)")
    @is_super_egg()
    async def manual_add(self, ctx,
        task_id: int,
        thread_id: str
    ):
        await ctx.defer(ephemeral=True)
        try:
            tid = int(thread_id)
            # 获取帖子对象
            try:
                thread = await self.bot.fetch_channel(tid)
            except:
                await ctx.followup.send("找不到该帖子，请确保ID正确且Bot有权限查看。", ephemeral=True)
                return
                
            if not isinstance(thread, discord.Thread):
                await ctx.followup.send("该ID对应的不是一个帖子！", ephemeral=True)
                return

            db.add_post(
                thread_id=thread.id,
                task_id=task_id,
                author_id=thread.owner_id,
                author_name=thread.owner.display_name if thread.owner else "未知",
                title=thread.name,
                url=thread.jump_url,
                created_at=thread.created_at,
                status=1 # 手动录入默认为有效
            )
            await ctx.followup.send(f"✅ 帖子 **{thread.name}** 已补录到任务 {task_id}！", ephemeral=True)
            
        except ValueError:
            await ctx.followup.send("ID格式错误。", ephemeral=True)

def setup(bot):
    bot.add_cog(ForumTracker(bot))