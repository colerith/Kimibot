# cogs/forum_tracker/db.py

import sqlite3

# 数据库文件路径
DB_PATH = "data/forum_data.db"

class DatabaseManager:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.check_and_migrate_logic_field() 
        self.check_and_migrate_pk_structure()
    def create_tables(self):
        # 任务表
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracking_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                forum_channel_id INTEGER,
                output_channel_id INTEGER,
                msg_id INTEGER,
                title_keyword TEXT,
                content_keyword TEXT,
                auto_verify BOOLEAN DEFAULT 0,
                content_logic TEXT DEFAULT 'OR'
            )
        """)
        
        # 帖子表 (新版结构：id 是主键，thread_id 可以重复)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id INTEGER,
                task_id INTEGER,
                author_id INTEGER,
                author_name TEXT,
                title TEXT,
                jump_url TEXT,
                created_at TIMESTAMP,
                status INTEGER DEFAULT 0,
                UNIQUE(thread_id, task_id)
            )
        """)
        self.conn.commit()

    def check_and_migrate_logic_field(self):
        """检查并自动添加 content_logic 字段"""
        try:
            self.cursor.execute("SELECT content_logic FROM tracking_tasks LIMIT 1")
        except sqlite3.OperationalError:
            print("⚠️ 正在升级表结构 (添加 content_logic)...")
            try:
                self.cursor.execute("ALTER TABLE tracking_tasks ADD COLUMN content_logic TEXT DEFAULT 'OR'")
                self.conn.commit()
            except Exception as e:
                print(f"❌ 升级失败: {e}")

    def check_and_migrate_pk_structure(self):
        """
        修复致命错误：
        旧版 tracked_posts 将 thread_id 设为主键，导致同一帖子无法被多个任务收录。
        此函数将迁移数据到新表结构。
        """
        try:
            # 检查当前表结构
            self.cursor.execute("PRAGMA table_info(tracked_posts)")
            columns = self.cursor.fetchall()
            
            # 检查 thread_id 是否为主键 (pk=1)
            thread_id_is_pk = False
            for col in columns:
                if col[1] == 'thread_id' and col[5] > 0:
                    thread_id_is_pk = True
                    break
            
            # 检查是否存在名为 id 的列 (新版主键)
            has_id_col = any(col[1] == 'id' for col in columns)

            if thread_id_is_pk or not has_id_col:
                print("⚠️ 检测到旧版数据库结构(单任务限制)，正在迁移数据以支持多任务统计...")
                
                # 1. 重命名旧表
                self.cursor.execute("ALTER TABLE tracked_posts RENAME TO tracked_posts_old")
                
                # 2. 创建新表
                self.cursor.execute("""
                    CREATE TABLE tracked_posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        thread_id INTEGER,
                        task_id INTEGER,
                        author_id INTEGER,
                        author_name TEXT,
                        title TEXT,
                        jump_url TEXT,
                        created_at TIMESTAMP,
                        status INTEGER DEFAULT 0,
                        UNIQUE(thread_id, task_id)
                    )
                """)
                
                # 3. 迁移数据
                self.cursor.execute("""
                    INSERT OR IGNORE INTO tracked_posts (thread_id, task_id, author_id, author_name, title, jump_url, created_at, status)
                    SELECT thread_id, task_id, author_id, author_name, title, jump_url, created_at, status FROM tracked_posts_old
                """)
                
                # 4. 删除旧表
                self.cursor.execute("DROP TABLE tracked_posts_old")
                self.conn.commit()
                print("✅ 数据库结构修复完成！现在同一个帖子可以被多个任务收录了。")
                
        except Exception as e:
            print(f"❌ 数据库结构修复失败 (如果这是第一次运行则忽略): {e}")

    def add_task(self, name, forum_id, output_id, msg_id, title_kw, content_kw, auto_verify, content_logic):
        self.cursor.execute("""
            INSERT INTO tracking_tasks (name, forum_channel_id, output_channel_id, msg_id, title_keyword, content_keyword, auto_verify, content_logic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, forum_id, output_id, msg_id, title_kw, content_kw, auto_verify, content_logic))
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
    
    def delete_post_by_thread_id(self, thread_id):
        self.cursor.execute("DELETE FROM tracked_posts WHERE thread_id = ?", (thread_id,))
        self.conn.commit()
        return self.cursor.rowcount

db = DatabaseManager()