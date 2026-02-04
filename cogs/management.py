# cogs/management.py

import discord
from discord import SlashCommandGroup, Option, ui
from discord.ext import commands
import datetime
import sqlite3
import os
from config import IDS, STYLE, SERVER_OWNER_ID

# --- 配置常量 ---
PUBLIC_NOTICE_CHANNEL_ID = 1417573350598770739  # 公示频道
LOG_CHANNEL_ID = 1468508677144055818            # 后台日志频道
DB_PATH = "./data/punishments.db"               # 数据库路径

# --- 数据库管理工具 ---
class PunishmentDB:
    def __init__(self):
        # 确保目录存在
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH)
        self.cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS strikes (
                user_id INTEGER PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_updated TIMESTAMP
            )
        """)
        self.conn.commit()

    def add_strike(self, user_id: int):
        self.cursor.execute("""
            INSERT INTO strikes (user_id, count, last_updated)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            count = count + 1,
            last_updated = ?
        """, (user_id, datetime.datetime.now(), datetime.datetime.now()))
        self.conn.commit()
        return self.get_strikes(user_id)

    def get_strikes(self, user_id: int) -> int:
        self.cursor.execute("SELECT count FROM strikes WHERE user_id = ?", (user_id,))
        res = self.cursor.fetchone()
        return res[0] if res else 0

    def reset_strikes(self, user_id: int):
        self.cursor.execute("DELETE FROM strikes WHERE user_id = ?", (user_id,))
        self.conn.commit()

# 初始化数据库实例
db = PunishmentDB()

# --- 辅助函数 ---
def parse_duration(duration_str: str) -> int:
    try:
        if not duration_str: return 0
        s = duration_str.strip().lower()
        if len(s) < 2: return 0
        unit = s[-1]
        val_str = s[:-1]
        if not val_str.isdigit(): return 0
        val = int(val_str)

        if unit == 's': return val
        elif unit == 'm': return val * 60
        elif unit == 'h': return val * 3600
        elif unit == 'd': return val * 86400
    except: return 0
    return 0

# 权限检查
def is_super_egg():
    async def predicate(ctx: discord.ApplicationContext) -> bool:
        if not isinstance(ctx.author, discord.Member): return False
        if ctx.author.id == SERVER_OWNER_ID: return True
        super_egg_role_id = IDS.get("SUPER_EGG_ROLE_ID")
        if not super_egg_role_id: return False
        role = ctx.guild.get_role(super_egg_role_id)
        if role and role in ctx.author.roles: return True
        await ctx.respond("🚫 只有【超级小蛋】才能使用此魔法哦！", ephemeral=True)
        return False
    return commands.check(predicate)

# ======================================================
# Modal 组件
# ======================================================

class IDInputModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="🔍 手动输入用户ID")
        self.view_ref = view_ref
        self.add_item(ui.InputText(label="用户ID", min_length=15, max_length=20, required=True))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid_str = self.children[0].value.strip()
        if not uid_str.isdigit(): return await interaction.followup.send("❌ ID必须是数字", ephemeral=True)
        uid = int(uid_str)
        try:
            self.view_ref.selected_user = await interaction.client.fetch_user(uid)
            self.view_ref.selected_user_id = uid
            msg = "✅ 已锁定目标"
        except:
            self.view_ref.selected_user = None
            self.view_ref.selected_user_id = uid
            msg = "⚠️ ID已锁定 (未获取到资料)"
        await self.view_ref.refresh_view(interaction, temp_notify=msg)

class EvidenceAppendModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📸 追加证据链接")
        self.view_ref = view_ref
        self.add_item(ui.InputText(
            label="链接 (每行一个)", style=discord.InputTextStyle.paragraph, required=True
        ))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        for line in self.children[0].value.strip().split('\n'):
            if line.strip(): self.view_ref.evidence_links.append(line.strip())
        await self.view_ref.refresh_view(interaction, temp_notify=f"✅ 证据已更新")

class ReasonInputModal(ui.Modal):
    def __init__(self, view_ref):
        super().__init__(title="📝 处罚详情")
        self.view_ref = view_ref
        self.add_item(ui.InputText(label="理由", style=discord.InputTextStyle.paragraph, required=True, value=view_ref.reason))
        self.add_item(ui.InputText(label="时长", placeholder="10m, 1h", required=False, value=view_ref.duration_str))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.view_ref.reason = self.children[0].value
        if self.children[1].value: self.view_ref.duration_str = self.children[1].value
        await self.view_ref.refresh_view(interaction)

# ======================================================
# 核心视图
# ======================================================

class ManagementControlView(ui.View):
    def __init__(self, ctx, initial_files=None):
        super().__init__(timeout=900)
        self.ctx = ctx
        self.selected_user = None
        self.selected_user_id = None
        self.action_type = None
        self.reason = "违反社区规范"
        self.duration_str = "1h"
        self.evidence_links = [f.url for f in initial_files if f] if initial_files else []
        self.update_components()

    def update_components(self):
        can_exec = (self.selected_user_id is not None) and (self.action_type is not None)
        for child in self.children:
            if isinstance(child, ui.Button):
                if child.custom_id == "btn_execute":
                    child.disabled = not can_exec
                    child.style = discord.ButtonStyle.danger if can_exec else discord.ButtonStyle.secondary
                elif child.custom_id == "btn_reason":
                    child.disabled = (self.action_type is None)

    async def refresh_view(self, interaction, temp_notify=None):
        self.update_components()
        embed = discord.Embed(title="🛡️ 处罚控制台", color=STYLE["KIMI_YELLOW"])

        # 目标显示
        if self.selected_user:
            info = f"**{self.selected_user.name}**\n`{self.selected_user.id}`"
            embed.set_thumbnail(url=self.selected_user.display_avatar.url)
        elif self.selected_user_id:
            info = f"ID: `{self.selected_user_id}`"
        else:
            info = "🔴 **未选择**"
        embed.add_field(name="1. 目标", value=info, inline=True)

        # 动作显示
        act_map = {"warn": "⚠️ 警告", "mute": "🤐 禁言", "kick": "🚀 踢出", "ban": "🚫 封禁", "unmute": "🎤 解禁", "unban": "🔓 解封"}
        embed.add_field(name="2. 动作", value=act_map.get(self.action_type, "⚪ **未选择**"), inline=True)

        # 详情
        desc = f"> **理由:** {self.reason}\n"
        if self.action_type == "mute": desc += f"> **时长:** `{self.duration_str}`\n"
        desc += f"> **证据:** {len(self.evidence_links)} 条"

        # 获取当前违规次数预览
        if self.selected_user_id:
            current_strikes = db.get_strikes(self.selected_user_id)
            desc += f"\n> **历史违规:** {current_strikes} 次 (本次将+1)"

        embed.add_field(name="配置详情", value=desc, inline=False)
        embed.set_footer(text=temp_notify or "等待指令...")

        if interaction.response.is_done(): await interaction.edit_original_response(embed=embed, view=self)
        else: await interaction.response.edit_message(embed=embed, view=self)

    # --- 交互 ---
    @ui.user_select(placeholder="👥 选择目标...", row=0, custom_id="sel_user")
    async def cb_user(self, select, interaction):
        self.selected_user = select.values[0]
        self.selected_user_id = self.selected_user.id
        await self.refresh_view(interaction)

    @ui.select(placeholder="🔨 选择动作...", row=1, custom_id="sel_act", options=[
        discord.SelectOption(label="警告 (Warn)", value="warn", emoji="⚠️"),
        discord.SelectOption(label="禁言 (Mute)", value="mute", emoji="🤐"),
        discord.SelectOption(label="踢出 (Kick)", value="kick", emoji="🚀"),
        discord.SelectOption(label="封禁 (Ban)", value="ban", emoji="🚫"),
        discord.SelectOption(label="解除禁言", value="unmute", emoji="🎤"),
        discord.SelectOption(label="解除封禁", value="unban", emoji="🔓"),
    ])
    async def cb_act(self, select, interaction):
        self.action_type = select.values[0]
        await self.refresh_view(interaction)

    @ui.button(label="ID搜人", style=discord.ButtonStyle.secondary, row=2, emoji="🔍", custom_id="btn_id")
    async def cb_id(self, _, interaction): await interaction.response.send_modal(IDInputModal(self))

    @ui.button(label="追加证据", style=discord.ButtonStyle.secondary, row=2, emoji="📎", custom_id="btn_ev")
    async def cb_ev(self, _, interaction): await interaction.response.send_modal(EvidenceAppendModal(self))

    @ui.button(label="理由/时长", style=discord.ButtonStyle.primary, row=2, emoji="📝", custom_id="btn_reason")
    async def cb_rsn(self, _, interaction): await interaction.response.send_modal(ReasonInputModal(self))

    @ui.button(label="⚡ 确认执行", style=discord.ButtonStyle.danger, row=3, disabled=True, custom_id="btn_execute")
    async def cb_exec(self, _, interaction):
        await interaction.response.defer()

        # 1. 执行 Discord 操作
        tid = self.selected_user_id
        act = self.action_type
        guild = interaction.guild
        member = guild.get_member(tid) # 可能为None

        try:
            # 执行逻辑
            msg_act = ""
            if act == "warn":
                msg_act = "进行警告"
                if member: # 尝试私信
                    try:
                        dm = discord.Embed(title=f"⚠️ {guild.name} 警告", description=self.reason, color=0xFFAA00)
                        if self.evidence_links: dm.set_image(url=self.evidence_links[0])
                        await member.send(embed=dm)
                    except: pass
            elif act == "mute":
                secs = parse_duration(self.duration_str)
                if secs <= 0: return await interaction.followup.send("❌ 时间格式错误", ephemeral=True)
                if member: await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=secs), reason=self.reason)
                msg_act = f"禁言 ({self.duration_str})"
            elif act == "kick":
                if member: await member.kick(reason=self.reason)
                msg_act = "踢出"
            elif act == "ban":
                await guild.ban(discord.Object(id=tid), reason=self.reason)
                msg_act = "封禁"
            elif act == "unmute":
                if member: await member.timeout(None, reason=self.reason)
                msg_act = "解禁"
            elif act == "unban":
                await guild.unban(discord.Object(id=tid), reason=self.reason)
                msg_act = "解封"

            # 2. 数据库记录 (仅处罚类动作增加计数)
            new_count = db.get_strikes(tid)
            if act in ["warn", "mute", "kick", "ban"]:
                new_count = db.add_strike(tid)

            # 3. 发送公开公示 (Public Notice)
            public_chan = guild.get_channel(PUBLIC_NOTICE_CHANNEL_ID)
            if public_chan:
                # 颜色根据动作严重程度
                color_map = {"warn": 0xFFAA00, "mute": 0xFF5555, "kick": 0xFF0000, "ban": 0x000000}
                p_embed = discord.Embed(title=f"🚨 违规公示 | {msg_act}", color=color_map.get(act, 0x999999))
                if member:
                    p_embed.set_thumbnail(url=member.display_avatar.url)
                    user_name = f"{member.name}"
                else:
                    user_name = f"ID: {tid}"

                p_embed.add_field(name="违规者", value=f"<@{tid}>\n(`{user_name}`)", inline=True)
                p_embed.add_field(name="累计违规", value=f"**{new_count}** 次", inline=True)
                p_embed.description = f"**处罚理由:**\n{self.reason}"
                p_embed.set_footer(text="请大家遵守社区规范，共建良好环境。")
                p_embed.timestamp = datetime.datetime.now()
                await public_chan.send(embed=p_embed)

            # 4. 发送后台日志 (Audit Log)
            log_chan = guild.get_channel(LOG_CHANNEL_ID)
            if log_chan:
                l_embed = discord.Embed(title=f"🛡️ 管理执行: {act.upper()}", color=STYLE["KIMI_YELLOW"])
                l_embed.description = f"**对象:** <@{tid}> (`{tid}`)\n**执行人:** {interaction.user.mention}\n**理由:** {self.reason}"
                l_embed.add_field(name="累计违规", value=str(new_count))
                if act == "mute": l_embed.add_field(name="时长", value=self.duration_str)

                if self.evidence_links:
                    l_embed.add_field(name="📎 证据链", value="\n".join([f"<{x}>" for x in self.evidence_links]), inline=False)
                    first_img = next((x for x in self.evidence_links if any(ext in x.lower() for ext in ['.png', '.jpg','.jpeg','.webp'])), None)
                    if first_img: l_embed.set_image(url=first_img)

                l_embed.timestamp = datetime.datetime.now()
                await log_chan.send(embed=l_embed)

            # 5. 反馈给执行者
            await interaction.followup.send(f"✅ 执行成功！\n- 已记录违规次数: {new_count}\n- 已发送公示\n- 已发送日志", ephemeral=True)
            self.clear_items()

            fin_embed = interaction.message.embeds[0]
            fin_embed.color = discord.Color.green()
            fin_embed.title = "✅ 处理完毕"
            await interaction.edit_original_response(embed=fin_embed, view=self)

        except discord.Forbidden:
            await interaction.followup.send("❌ 权限不足 (对方身份可能更高)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 错误: {e}", ephemeral=True)

# ======================================================
# Cog
# ======================================================

class Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="处罚", description="打开管理面板 (可上传证据)")
    @is_super_egg()
    async def punishment_panel(self, ctx, 
            file1: Option(discord.Attachment, "证据1", required=False), 
            file2: Option(discord.Attachment, "证据2", required=False),
            file3: Option(discord.Attachment, "证据3", required=False),
            file4: Option(discord.Attachment, "证据4", required=False),
            file5: Option(discord.Attachment, "证据5", required=False),
            file6: Option(discord.Attachment, "证据6", required=False),
            file7: Option(discord.Attachment, "证据7", required=False),
            file8: Option(discord.Attachment, "证据8", required=False),
            file9: Option(discord.Attachment, "证据9", required=False)):
        files = [f for f in [file1, file2, file3, file4, file5, file6, file7, file8, file9] if f]
        view = ManagementControlView(ctx, initial_files=files)
        await ctx.respond(embed=discord.Embed(title="🛡️ 加载中..."), view=view, ephemeral=True)
        await view.refresh_view(ctx.interaction)

    @discord.slash_command(name="重置处罚", description="清空某用户的违规计数")
    @is_super_egg()
    async def reset_strikes(self, ctx, user: Option(discord.User, "选择用户")):
        db.reset_strikes(user.id)
        await ctx.respond(f"✅ 已清空 {user.mention} 的所有违规计数。", ephemeral=True)

def setup(bot):
    bot.add_cog(Management(bot))
