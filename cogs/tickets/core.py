# cogs/tickets/core.py

import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import random
import io
import zipfile
import json
import os

from config import IDS, QUOTA, STYLE
from .utils import (
    STRINGS, SPECIFIC_REVIEWER_ID, TIMEOUT_HOURS_ARCHIVE, TIMEOUT_HOURS_REMIND,
    is_reviewer_egg, get_ticket_info, load_quota_data, save_quota_data, execute_archive
)
from .views import (
    TicketActionView, TimeoutOptionView, ArchiveRequestView,
    NotifyReviewerView, SuspendAuditModal
)

# --- 持久化工具函数 (新增) ---
AUDIT_SCHEDULE_FILE = "data/audit_schedule.json"

def load_audit_schedule():
    if not os.path.exists(AUDIT_SCHEDULE_FILE):
        return {
            "suspended": False,
            "reason": None,
            "start_dt": None, # 存时间戳
            "end_dt": None
        }
    try:
        with open(AUDIT_SCHEDULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"suspended": False, "reason": None, "start_dt": None, "end_dt": None}

def save_audit_schedule(data):
    # 确保存储目录存在
    os.makedirs(os.path.dirname(AUDIT_SCHEDULE_FILE), exist_ok=True)
    with open(AUDIT_SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

class TicketPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🥚 申请全区权限", style=discord.ButtonStyle.primary, custom_id="create_ticket_panel_button")
    async def create_ticket(self, button, interaction):
        await self.cog.create_ticket_logic(interaction)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # 加载持久化的暂停计划
        self.schedule_data = load_audit_schedule()

        # 内存锁：防止同一用户并发创建
        # 集合中存储正在处理中的 user_id
        self.creating_lock = set()

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(TicketActionView())
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(ArchiveRequestView())
        self.bot.add_view(NotifyReviewerView(SPECIFIC_REVIEWER_ID))

        print("Tickets Cog Loaded & Views Registered.")
        print(f"当前审核暂停状态: {self.schedule_data.get('suspended')}")

        # 启动定时任务
        if not self.reset_daily_quota.is_running(): self.reset_daily_quota.start()
        if not self.check_inactive_tickets.is_running(): self.check_inactive_tickets.start()
        if not self.close_tickets_at_night.is_running(): self.close_tickets_at_night.start()

    # ======================================================================================
    # --- 核心逻辑方法 (供 View 调用) ---
    # ======================================================================================

    async def create_ticket_logic(self, interaction: discord.Interaction):
        user = interaction.user

        # [0] 并发锁检查：如果该用户正在创建中，直接阻止
        if user.id in self.creating_lock:
            return await interaction.response.send_message("🚧 **正在处理中...**\n请不要频繁点击按钮哦，正在为你创建这里！", ephemeral=True)

        # 加锁
        self.creating_lock.add(user.id)

        try:
            # 1. 检查暂停状态 (使用持久化数据)
            if self.schedule_data.get("suspended", False):
                now = datetime.datetime.now(QUOTA["TIMEZONE"])
                is_active_suspension = False

                # 读取时间戳并转换回 datetime 对象
                start_ts = self.schedule_data.get("start_dt")
                end_ts = self.schedule_data.get("end_dt")

                start_dt = datetime.datetime.fromtimestamp(start_ts, QUOTA["TIMEZONE"]) if start_ts else None
                end_dt = datetime.datetime.fromtimestamp(end_ts, QUOTA["TIMEZONE"]) if end_ts else None

                if not start_dt:
                    is_active_suspension = True
                else:
                    if start_dt <= now:
                        if end_dt:
                            if now < end_dt:
                                is_active_suspension = True
                            else:
                                is_active_suspension = False
                        else:
                            is_active_suspension = True
                    else:
                        is_active_suspension = False

                if is_active_suspension:
                    reason = self.schedule_data.get("reason") or "管理员暂停了审核功能"
                    until_str = "恢复时间待定"
                    if end_dt:
                        diff = end_dt - now
                        hours, remainder = divmod(int(diff.total_seconds()), 3600)
                        minutes, _ = divmod(remainder, 60)
                        if hours > 24:
                            until_str = f"预计 {end_dt.strftime('%m-%d %H:%M')} 恢复"
                        else:
                            until_str = f"预计 {hours}小时{minutes}分 后恢复"

                    # 只要返回，记得解锁
                    self.creating_lock.discard(user.id)
                    return await interaction.response.send_message(f"🚫 **审核通道已暂时关闭**\n原因：{reason}\n{until_str}", ephemeral=True)

            # 2. 检查时间
            now = datetime.datetime.now(QUOTA["TIMEZONE"])
            if not (8 <= now.hour < 23):
                self.creating_lock.discard(user.id)
                return await interaction.response.send_message(STRINGS["messages"]["err_time_limit"], ephemeral=True)

            # 3. 检查资格
            user_roles = [r.id for r in interaction.user.roles]
            has_perm = (IDS["VERIFICATION_ROLE_ID"] in user_roles) or \
                    (IDS["SUPER_EGG_ROLE_ID"] in user_roles) or \
                    (interaction.user.id == SPECIFIC_REVIEWER_ID)

            if not has_perm:
                self.creating_lock.discard(user.id)
                return await interaction.response.send_message(STRINGS["messages"]["err_perm_create"], ephemeral=True)

            # 4. 检查重复 & 额度
            # 获取所有相关分类
            c1 = interaction.guild.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])
            c1_extra = interaction.guild.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"))
            c2 = interaction.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])

            if not c1:
                self.creating_lock.discard(user.id)
                return await interaction.response.send_message("配置错误：找不到一审分类。", ephemeral=True)

            # 确定目标分类（处理容量50上限）
            target_category = c1
            if isinstance(c1, discord.CategoryChannel) and len(c1.channels) >= 50:
                if c1_extra and isinstance(c1_extra, discord.CategoryChannel) and len(c1_extra.channels) < 50:
                    target_category = c1_extra
                else:
                    self.creating_lock.discard(user.id)
                    return await interaction.response.send_message("🚫 **无法创建工单**\n所有审核窗口都满员啦（50/50）！请稍后再试。", ephemeral=True)

            # 严查是否已有频道：遍历所有可能存在的分类
            check_cats = [c1, c2, interaction.guild.get_channel(IDS["ARCHIVE_CHANNEL_ID"])]
            if c1_extra: check_cats.append(c1_extra)

            for c in check_cats:
                if not c or not isinstance(c, discord.CategoryChannel): continue
                for ch in c.text_channels:
                    # 检查 Topic 里的 ID，且排除归档区（允许归档后重建，但这里根据需求，如果归档区还要查重，可以加上）
                    # 通常如果之前工单没删（在归档区），也不让建新的？看你的需求。
                    # 之前的代码是 "除非该工单被删除才能重新申请"，意味着归档了（没删）也不能申请。
                    if ch.topic and str(interaction.user.id) in ch.topic:
                        # 再次确认不是误判（检查topic格式）
                        if f"创建者ID: {interaction.user.id}" in ch.topic:
                            self.creating_lock.discard(user.id)
                            return await interaction.response.send_message(STRINGS["messages"]["err_already_has"].format(channel=ch.mention), ephemeral=True)

            # 检查额度
            q_data = load_quota_data()
            if q_data["daily_quota_left"] <= 0:
                self.creating_lock.discard(user.id)
                return await interaction.response.send_message(STRINGS["messages"]["err_quota_limit"], ephemeral=True)

            # 5. 执行创建 (正式开始耗时操作，Defer)
            await interaction.response.defer(ephemeral=True)

            # 扣除额度
            q_data["daily_quota_left"] -= 1
            save_quota_data(q_data)
            await self.update_panel_message()

            tid = random.randint(100000, 999999)
            c_name = f"审核中-{tid}-{interaction.user.name}"

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            staff = interaction.guild.get_member(SPECIFIC_REVIEWER_ID)
            if staff: overwrites[staff] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            super_egg = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
            if super_egg: overwrites[super_egg] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            ch = await interaction.guild.create_text_channel(
                name=c_name, category=target_category, overwrites=overwrites,
                topic=f"创建者ID: {interaction.user.id} | 创建者: {interaction.user.name} | 工单ID: {tid}"
            )

            # 发送初始消息
            e_create = discord.Embed.from_dict(STRINGS["embeds"]["ticket_created"])
            if e_create.title: e_create.title = e_create.title.replace("{ticket_id}", str(tid))
            if e_create.description: e_create.description = e_create.description.replace("{ticket_id}", str(tid))
            e_create.color = STYLE["KIMI_YELLOW"]
            await ch.send(f"{interaction.user.mention}", embed=e_create, view=TicketActionView())

            # 发送要求
            req_data = STRINGS["embeds"]["requirements"]
            e_req = discord.Embed(title=req_data["title"], description=req_data["desc"], color=STYLE["KIMI_YELLOW"])
            for f in req_data["fields"]: e_req.add_field(name=f["name"], value=f["value"], inline=False)
            e_req.set_image(url=req_data["image"])
            e_req.set_footer(text=req_data["footer"])
            await ch.send(f"你好呀 {interaction.user.mention}，请按下面的要求提交材料哦~", embed=e_req)

            # 发送给审核员的提醒
            rem_text = STRINGS["messages"]["reminder_text"].format(ticket_id=tid, user_id=interaction.user.id)
            await ch.send(embed=discord.Embed(description=rem_text, color=STYLE["KIMI_YELLOW"]), view=NotifyReviewerView(SPECIFIC_REVIEWER_ID))

            # 私信通知
            try:
                msg = STRINGS["messages"]["dm_create_success"].format(guild_name=interaction.guild.name, channel_mention=ch.mention)
                await interaction.user.send(msg)
                msg_status = STRINGS["messages"]["dm_status_ok"]
            except:
                msg_status = STRINGS["messages"]["dm_status_fail"]

            await interaction.followup.send(f"好惹！你的审核频道 {ch.mention} 已经创建好惹！审核要求已发送到频道内~ {msg_status}", ephemeral=True)

        except Exception as e:
            print(f"创建工单逻辑出错: {e}")
            # 出错回滚额度
            q_data = load_quota_data() # 重新读一遍防止并发覆盖
            q_data["daily_quota_left"] += 1
            save_quota_data(q_data)
            await self.update_panel_message()

            try:
                # 尝试发送错误信息，如果 interaction 过期可能会失败，所以加 try
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"创建失败: {e}", ephemeral=True)
                else:
                    await interaction.followup.send(f"创建失败: {e}", ephemeral=True)
            except:
                pass

        finally:
            # 无论成功失败，最后都要释放锁
            self.creating_lock.discard(user.id)



    async def approve_ticket_logic(self, interaction_or_ctx):
        """核心过审逻辑"""
        # 兼容 ctx 和 interaction
        respond = interaction_or_ctx.respond if hasattr(interaction_or_ctx, 'respond') else interaction_or_ctx.response.send_message
        channel = interaction_or_ctx.channel
        guild = interaction_or_ctx.guild
        user_op = interaction_or_ctx.author if hasattr(interaction_or_ctx, 'author') else interaction_or_ctx.user

        info = get_ticket_info(channel)
        uid = info.get("创建者ID")
        user = guild.get_member(int(uid)) if uid else None

        # 1. 给身份
        if user:
            r_new = guild.get_role(IDS["VERIFICATION_ROLE_ID"])
            r_done = guild.get_role(IDS["HATCHED_ROLE_ID"])
            try:
                if r_new: await user.remove_roles(r_new, reason="审核通过")
                if r_done: await user.add_roles(r_done, reason="审核通过")

                # 私信
                dm_data = STRINGS["embeds"]["dm_approved"]
                content = dm_data["desc_template"].format(user_name=user.name, guild_name=guild.name)
                em = discord.Embed(title=dm_data["title"], description=content, color=STYLE.get("KIMI_YELLOW", 0xFFFF00))
                em.add_field(name="🔗 前往工单频道", value=channel.mention, inline=False)
                await user.send(embed=em)
            except Exception as e:
                print(f"给身份或私信失败: {e}")

        # 2. 移动频道到二审(已过审)分类
        cat2 = guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        if cat2:
            new_name = f"已过审-{info.get('工单ID')}-{info.get('创建者')}"
            try:
                # 保持用户可见以便确认，但也给管理权限
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                }
                if user: overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                spec = guild.get_member(SPECIFIC_REVIEWER_ID)
                if spec: overwrites[spec] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                super_egg = guild.get_role(IDS.get("SUPER_EGG_ROLE_ID", 0))
                if super_egg: overwrites[super_egg] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

                await channel.edit(name=new_name, category=cat2, overwrites=overwrites)
            except Exception as e:
                print(f"移动频道失败: {e}")

        # 3. 发送过审面板
        ap_data = STRINGS["embeds"]["approved"]
        em = discord.Embed(title=ap_data["title"], description=ap_data["desc"], color=STYLE.get("KIMI_YELLOW", 0xFFFF00))
        em.set_image(url=ap_data["image"])
        em.set_footer(text=ap_data["footer"])

        c_text = f"恭喜 {user.mention} 通过审核！" if user else "恭喜通过审核！(用户已不在服务器)"
        await channel.send(c_text, embed=em, view=ArchiveRequestView(user_op))

        # 反馈
        msg = "✅ 已执行过审流程！"
        if hasattr(interaction_or_ctx, 'followup'): await interaction_or_ctx.followup.send(msg, ephemeral=True)
        else: await respond(msg, ephemeral=True)


    async def update_panel_message(self):
        ch = self.bot.get_channel(IDS["TICKET_PANEL_CHANNEL_ID"])
        if not ch: return

        d = load_quota_data()
        p_data = STRINGS["embeds"]["panel"]
        now = datetime.datetime.now(QUOTA["TIMEZONE"])

        desc = p_data["description_head"] + "\n" + p_data["req_newbie"] + "\n"
        desc += f"**-` 审核开放时间: 每日 08:00 - 23:00 `**\n**-` 今日剩余名额: {d['daily_quota_left']}/{QUOTA['DAILY_TICKET_LIMIT']} `**"

        is_active_suspension = False

        # 使用持久化数据判断暂停
        if self.schedule_data.get("suspended", False):
            # 将时间戳转为 datetime
            start_ts = self.schedule_data.get("start_dt")
            end_ts = self.schedule_data.get("end_dt")

            start_dt = datetime.datetime.fromtimestamp(start_ts, QUOTA["TIMEZONE"]) if start_ts else None
            end_dt = datetime.datetime.fromtimestamp(end_ts, QUOTA["TIMEZONE"]) if end_ts else None

            if not start_dt:
                is_active_suspension = True
            else:
                if now >= start_dt:
                    if end_dt:
                        if now < end_dt:
                            is_active_suspension = True
                        else:
                            is_active_suspension = False
                    else:
                        is_active_suspension = True
                else:
                    is_active_suspension = False

        if is_active_suspension:
            label = p_data["btn_suspended"]
            disabled = False # 按钮不禁用，但点进去会提示暂停
        elif d["daily_quota_left"] <= 0:
            label = p_data["btn_full"]
            disabled = True
        elif not (8 <= now.hour < 23):
            label = p_data["btn_rest"]
            disabled = True
            desc += "\n\n**" + p_data["status_off_time"] + "**"
        else:
            label = p_data["btn_normal"]
            disabled = False

        embed = discord.Embed(title=p_data["title"], description=desc, color=STYLE.get("KIMI_YELLOW", 0xFFFF00))
        view = TicketPanelView(self)
        btn = view.children[0]
        btn.label = label
        btn.disabled = disabled

        try:
            async for m in ch.history(limit=5):
                if m.author == self.bot.user and m.embeds and "全区权限申请" in m.embeds[0].title:
                    await m.edit(embed=embed, view=view)
                    return
            await ch.send(embed=embed, view=view)
        except Exception as e:
            print(f"刷新面板失败: {e}")

    # ======================================================================================
    # --- 定时任务 ---
    # ======================================================================================

    @tasks.loop(time=datetime.time(hour=8, minute=0, tzinfo=QUOTA["TIMEZONE"]))
    async def reset_daily_quota(self):
        await self.bot.wait_until_ready()
        today_str = datetime.datetime.now(QUOTA["TIMEZONE"]).strftime('%Y-%m-%d')
        d = load_quota_data()
        if d["last_reset_date"] != today_str:
            d["last_reset_date"] = today_str
            d["daily_quota_left"] = QUOTA["DAILY_TICKET_LIMIT"]
            save_quota_data(d)
            await self.update_panel_message()

    @tasks.loop(time=datetime.time(hour=23, minute=0, tzinfo=QUOTA["TIMEZONE"]))
    async def close_tickets_at_night(self):
        await self.bot.wait_until_ready()
        await self.update_panel_message()

    @tasks.loop(hours=1)
    async def check_inactive_tickets(self):
        await self.bot.wait_until_ready()
        now = discord.utils.utcnow()

        # 遍历一审和二审分类
        cats = [
            self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"]), 
            self.bot.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID")),
            self.bot.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])]
        # 获取归档分类
        archive_cat = self.bot.get_channel(IDS["ARCHIVE_CHANNEL_ID"])

        for cat in cats:
            if not cat: continue
            for channel in cat.text_channels:
                valid_prefixes = ["一审中", "二审中", "审核中", "已过审"]
                if not any(prefix in channel.name for prefix in valid_prefixes):
                    continue

                try:
                    info = get_ticket_info(channel)
                    tid = info.get("工单ID")
                    creator_id = info.get("创建者ID")

                    # 获取该频道的Member对象
                    member = None
                    if creator_id:
                        member = channel.guild.get_member(int(creator_id))

                    # 扫描历史消息 & 收集状态
                    last_active = channel.created_at
                    found_active = False
                    has_reminded = False
                    is_locked = False
                    is_approved_waiting = False
                    last_msg_time = None

                    # 遍历历史消息
                    i = 0
                    async for m in channel.history(limit=20):
                        if i == 0: # 检查最新一条
                            last_msg_time = m.created_at
                            if m.author.id == self.bot.user.id and m.embeds:
                                embed_title = m.embeds[0].title or ""
                                if "恭喜小宝加入社区" in embed_title:
                                    is_approved_waiting = True

                        raw_content = m.content or ""
                        e_title = (m.embeds[0].title or "") if m.embeds else ""
                        e_desc = (m.embeds[0].description or "") if m.embeds else ""
                        full_text = f"{raw_content} {e_title} {e_desc}"

                        if "已锁定" in full_text:
                            is_locked = True
                        if m.author.bot and ("温馨提醒" in full_text):
                            has_reminded = True

                        if not found_active:
                            is_bot_remind = m.author.bot and ("温馨提醒" in full_text)
                            if not is_bot_remind:
                                last_active = m.created_at
                                found_active = True
                        i += 1

                    if not last_msg_time: continue

                    diff_approved = now - last_msg_time
                    diff_active = now - last_active


                    # --- 逻辑分支 ---

                    # 1. 处理：已过审但在等待确认 (1小时处理)
                    if is_approved_waiting and diff_approved > datetime.timedelta(hours=1):

                        # a. 尝试发送 DM 私信通知 (新增功能)
                        if member:
                            try:
                                dm_embed = discord.Embed(
                                    title="✨ 工单自动归档通知",
                                    description=(
                                        f"亲爱的小宝，您在 **{channel.guild.name}** 的审核工单 **{channel.name}** "
                                        f"已通过审核。\n\n"
                                        f"由于超过 1 小时未确认，系统已自动将其归档保存。\n"
                                        f"您现在的身份组应该已经更新啦，欢迎正式加入我们！🎉"
                                    ),
                                    color=0x4CAF50  # 柔和的绿色
                                )
                                dm_embed.set_footer(text=f"工单ID: {tid} | 操作时间: {now.strftime('%Y-%m-%d %H:%M')}")
                                await member.send(embed=dm_embed)
                            except discord.Forbidden:
                                print(f"无法发送私信给用户 {member.display_name} (ID: {member.id}) - 可能已关闭私信")
                            except Exception as e:
                                print(f"发送私信时发生未知错误: {e}")

                        # b. 频道内提示
                        await channel.send("✅ **自动完成**\n检测到通过审核后超过 **1小时** 未操作，系统已默认处理并归档。")

                        # c. 锁定权限
                        if member:
                            try:
                                await channel.set_permissions(member, send_messages=False)
                            except Exception as e:
                                print(f"锁定权限失败 {channel.name}: {e}")

                        # d. 移动到归档分类
                        if archive_cat:
                            try:
                                await channel.edit(category=archive_cat, reason="已过审3小时无响应自动完成")
                            except Exception as e:
                                print(f"移动频道失败 {channel.name}: {e}")

                        # 保持原名，不发归档报告
                        continue


                    # 2. 常规超时归档 (12小时)
                    if diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_ARCHIVE):
                        await execute_archive(self.bot, None, channel, f"超过{TIMEOUT_HOURS_ARCHIVE}小时无活动", is_timeout=True)

                    # 3. 温馨提醒 (6小时)
                    elif diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_REMIND):
                        if not has_reminded and not is_approved_waiting and not is_locked:
                            embed = discord.Embed(title="⏰ 温馨提醒", description=f"工单已沉睡超过 {TIMEOUT_HOURS_REMIND} 小时！\n超过 {TIMEOUT_HOURS_ARCHIVE} 小时会自动归档哦！", color=0xFFA500)
                            txt = f"<@{creator_id}>" if creator_id else ""
                            await channel.send(txt, embed=embed)

                except Exception as e:
                    print(f"检查频道 {channel.name} 错误: {e}")

    # ======================================================================================
    # --- 命令组 (Slash Commands) ---
    # ======================================================================================

    ticket = discord.SlashCommandGroup("工单", "工单相关指令")

    @ticket.command(name="手动过审", description="（审核小蛋用）一键给身份、发通知、移频道！")
    @is_reviewer_egg()
    async def manual_approve(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        if not get_ticket_info(ctx.channel).get("工单ID"):
            await ctx.followup.send("这里不是工单频道哦！", ephemeral=True); return
        await self.approve_ticket_logic(ctx)

    @ticket.command(name="修复按钮", description="（审核小蛋用）按钮没反应？尝试修复当前频道已有的面板！")
    @is_reviewer_egg()
    async def fix_ticket_button(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 1. 检查是否在工单频道
        if not get_ticket_info(ctx.channel).get("工单ID"):
            await ctx.followup.send("这里不是工单频道哦！", ephemeral=True)
            return

        # 2. 尝试寻找并修复旧消息
        fixed = False
        target_titles = ["已创建", "管理员操作面板", "一审中", "审核中"]  # 识别面板的关键词

        try:
            async for message in ctx.channel.history(limit=50):  # 搜索最近50条消息
                if message.author.id == self.bot.user.id and message.embeds:
                    embed_title = message.embeds[0].title or ""
                    # 只要标题匹配或者是工单初始消息，就尝试修复View
                    if any(t in embed_title for t in target_titles):
                        await message.edit(view=TicketActionView())
                        fixed = True
                        break
        except Exception as e:
            print(f"修复按钮时出错: {e}")

        # 3. 反馈结果
        if fixed:
            await ctx.followup.send("✅ 已成功修复当前频道的旧操作面板！按钮应该能用啦！", ephemeral=True)
        else:
            embed = discord.Embed(
                title="🔧 管理员操作面板 (补发)",
                description="呜...本蛋没找到旧的面板消息，所以给你补发了一个新的！",
                color=STYLE["KIMI_YELLOW"]
            )
            await ctx.channel.send(embed=embed, view=TicketActionView())
            await ctx.followup.send("⚠️ 未找到可修复的旧消息，已为你补发新的面板。", ephemeral=True)


    @ticket.command(name="中止新蛋审核", description="（管理员）弹出面板，设置定时或立即中止工单申请。")
    @is_reviewer_egg()
    async def suspend_audit(self, ctx: discord.ApplicationContext):
        modal = SuspendAuditModal(self)
        await ctx.send_modal(modal)

    @ticket.command(name="恢复新蛋审核", description="（管理员）手动立即恢复审核功能。")
    @is_reviewer_egg()
    async def resume_audit(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 清除所有暂停状态 (逻辑同上)
        self.schedule_data = {
            "suspended": False,
            "reason": None,
            "start_dt": None,
            "end_dt": None
        }
        save_audit_schedule(self.schedule_data)

        await self.update_panel_message()
        await ctx.followup.send("✅ **已手动恢复审核功能！**\n现在大家可以正常创建工单了。", ephemeral=True)


    @ticket.command(name="清理重复工单", description="（慎用）一键删除指定用户所有重复创建的工单，保留最早的一个。")
    @is_reviewer_egg()
    async def clean_user_duplicates(self, ctx: discord.ApplicationContext,
                                    user: discord.Member,
                                    dry_run: discord.Option(bool, "是否仅模拟（不真删）", default=True)):
        """
        查找该用户创建的所有工单频道，保留最早创建的一个，其余删除并返还额度。
        """
        await ctx.defer(ephemeral=True)

        # 扫描所有相关分类
        categories = [
            self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"]),
            self.bot.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID")),
            self.bot.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        ]

        user_channels = []
        for cat in categories:
            if not cat or not isinstance(cat, discord.CategoryChannel): continue
            for ch in cat.text_channels:
                # 检查 topic 中的用户ID
                if ch.topic and f"创建者ID: {user.id}" in ch.topic:
                    user_channels.append(ch)

        if not user_channels:
            return await ctx.followup.send(f"✅ 未在审核区发现用户 {user.mention} 的任何工单。", ephemeral=True)

        if len(user_channels) == 1:
            return await ctx.followup.send(f"✅ 用户 {user.mention} 只有一个工单 {user_channels[0].mention}，无需清理。", ephemeral=True)

        # 按创建时间排序：最早的在前
        user_channels.sort(key=lambda c: c.created_at)

        keep_channel = user_channels[0]
        delete_channels = user_channels[1:]

        msg = f"🔍 **发现重复工单！**\n用户: {user.mention}\n共发现: {len(user_channels)} 个\n\n"
        msg += f"🛡️ **将保留**: {keep_channel.mention} (创建于 {keep_channel.created_at.strftime('%H:%M:%S')})\n"
        msg += f"🗑️ **将删除**: {len(delete_channels)} 个 (并返还对应额度)\n"

        for c in delete_channels:
            msg += f"- {c.mention} ({c.created_at.strftime('%H:%M:%S')})\n"

        if dry_run:
            msg += "\n⚠️ **当前为模拟模式 (Dry Run)**，未执行实际删除。\n如果要执行，请重新运行命令并将 `dry_run` 设为 `False`。"
            await ctx.followup.send(msg, ephemeral=True)
        else:
            # 执行删除
            d = load_quota_data()
            count = 0
            for c in delete_channels:
                try:
                    await c.delete(reason=f"清理重复工单 - 操作人: {ctx.author.name}")
                    count += 1
                except Exception as e:
                    msg += f"\n❌ 删除 {c.name} 失败: {e}"

            # 返还额度
            d["daily_quota_left"] += count
            save_quota_data(d)
            await self.update_panel_message()

            msg += f"\n✅ **清理完成！** 已删除 {count} 个频道，并返还了 {count} 个名额。\n当前剩余名额: {d['daily_quota_left']}"
            await ctx.followup.send(msg, ephemeral=True)

    @ticket.command(name="恢复工单状态", description="（审核小蛋用）误操作恢复！")
    @is_reviewer_egg()
    async def recover_ticket(self, ctx: discord.ApplicationContext,
                             state: discord.Option(str, "选择恢复到的状态", choices=["一审中", "二审中", "已过审", "归档"]),
                             reason: discord.Option(str, "给用户的解释", required=False, default="管理员手动调整了工单状态。")):
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        info = get_ticket_info(channel)
        if not info.get("工单ID"): return await ctx.followup.send("无效工单頻道", ephemeral=True)

        # 🟢 逻辑完善：根据状态确定目标位置，如果是恢复到一审，需要考虑容量
        if state == "一审中":
             c1 = ctx.guild.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])
             c1_extra = ctx.guild.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"))

             target_cat = c1
             # 如果主分类满了，且有备用分类，则放到备用
             if len(c1.channels) >= 50:
                 if c1_extra and len(c1_extra.channels) < 50:
                     target_cat = c1_extra
        elif state in ["二审中", "已过审"]:
            target_cat = ctx.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        elif state == "归档":
            target_cat = ctx.guild.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        else:
            target_cat = None

        if not target_cat: return await ctx.followup.send("找不到目标分类配置或分类已满", ephemeral=True)

        overwrites = {ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False)}
        spec = ctx.guild.get_member(SPECIFIC_REVIEWER_ID)
        if spec: overwrites[spec] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        uid = info.get("创建者ID")
        user = ctx.guild.get_member(int(uid)) if uid else None
        if user and state != "归档":
            overwrites[user] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        new_name = f"{state}-{info.get('工单ID')}-{info.get('创建者')}"
        await channel.edit(name=new_name, category=target_cat, overwrites=overwrites, reason=reason)

        embed = discord.Embed(title="🔄 工单状态已恢复", description=f"恢复为：**{state}**\n原因: {reason}", color=STYLE["KIMI_YELLOW"])
        await channel.send(embed=embed)
        if user:
            try: await user.send(f"你的工单 `{info.get('工单ID')}` 状态已变更为: {state}。")
            except: pass
        await ctx.followup.send("恢复完成！", ephemeral=True)

    @ticket.command(name="超时归档", description="（审核小蛋用）手动标记超时。")
    @is_reviewer_egg()
    async def timeout_archive(self, ctx: discord.ApplicationContext, note: discord.Option(str, "备注", required=False)="手动超时"):
        await ctx.defer(ephemeral=True)
        if not get_ticket_info(ctx.channel).get("工单ID"): return await ctx.followup.send("这里不是工单频道", ephemeral=True)

        await execute_archive(self.bot, ctx, ctx.channel, note, is_timeout=True)

    @ticket.command(name="删除并释放名额", description="（审核小蛋用）删除工单并返还名额。")
    @is_reviewer_egg()
    async def delete_and_refund(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        if not get_ticket_info(channel).get("工单ID"): return await ctx.followup.send("无效频道", ephemeral=True)

        d = load_quota_data()
        d["daily_quota_left"] += 1
        save_quota_data(d)
        await self.update_panel_message()

        await channel.delete(reason=f"管理员 {ctx.author.name} 删除并返还名额")

    @ticket.command(name="发送过审祝贺", description="手动发送过审消息")
    @is_reviewer_egg()
    async def send_approved(self, ctx: discord.ApplicationContext):
        await ctx.defer()
        ap_data = STRINGS["embeds"]["approved"]
        em = discord.Embed(title=ap_data["title"], description=ap_data["desc"], color=STYLE["KIMI_YELLOW"])
        em.set_image(url=ap_data["image"])
        em.set_footer(text=ap_data["footer"])
        await ctx.send(embed=em, view=ArchiveRequestView(ctx.author))

    @ticket.command(name="批量导出", description="（服主用）将二审区已过审的频道打包并删除！")
    @is_reviewer_egg()
    async def bulk_export_and_archive(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        target_category = self.bot.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])
        log_channel = self.bot.get_channel(IDS["TICKET_LOG_CHANNEL_ID"])

        if not target_category:
            await ctx.followup.send("呜...找不到配置的【二审】分类！请检查 ID 配置。", ephemeral=True); return
        if not log_channel:
            await ctx.followup.send("呜...找不到存放日志的频道！", ephemeral=True); return

        await ctx.followup.send(f"收到！开始扫描 “{target_category.name}” 中带 “已过审” 的频道...", ephemeral=True)

        # 在目标分类下筛选名字里包含 "已过审" 的文字频道
        channels_to_process = [ch for ch in target_category.text_channels if "已过审" in ch.name]

        if not channels_to_process:
            await ctx.followup.send(f"在 {target_category.name} 里没找到带“已过审”的频道哦~", ephemeral=True); return

        # 按创建时间排序
        channels_to_process.sort(key=lambda x: x.created_at)

        exported_count = 0
        current_date_header = ""

        for channel in channels_to_process:
            try:
                # 获取频道创建日期用于日志分割
                channel_date = channel.created_at.astimezone(QUOTA["TIMEZONE"]).strftime('%Y%m%d')
                if channel_date != current_date_header:
                    current_date_header = channel_date
                    await log_channel.send(f"## 📅 {current_date_header}")

                # 提取工单信息
                info = get_ticket_info(channel)
                qq_number = info.get("QQ", "未录入")
                ticket_id = info.get("工单ID", "未知")
                creator_name = info.get("创建者", "未知")

                # HTML 模板构建
                html_template = """
                <!DOCTYPE html><html><head><title>Log for {channel_name}</title><meta charset="UTF-8"><style>
                body {{ background-color: #313338; color: #dbdee1; font-family: 'Whitney', 'Helvetica Neue', sans-serif; padding: 20px; }}
                .info-box {{ background-color: #2b2d31; padding: 15px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #F1C40F; }}
                .info-item {{ margin: 5px 0; font-size: 1.1em; }}
                .message-group {{ display: flex; margin-bottom: 20px; }} .avatar img {{ width: 40px; height: 40px; border-radius: 50%; margin-right: 20px; }}
                .message-content .author {{ font-weight: 500; color: #f2f3f5; }} .message-content .timestamp {{ font-size: 0.75rem; color: #949ba4; margin-left: 10px; }}
                .message-content .text {{ margin-top: 5px; line-height: 1.375rem; }} .attachment img {{ max-width: 400px; border-radius: 5px; margin-top: 10px; }}
                .embed {{ background-color: #2b2d31; border-left: 4px solid {embed_color}; padding: 10px; border-radius: 5px; margin-top: 10px; }}
                .embed-title {{ font-weight: bold; color: white; }} .embed-description {{ font-size: 0.9rem; }}
                </style></head><body>
                <h1>工单日志: {channel_name}</h1>
                <div class="info-box">
                    <div class="info-item">🎫 <b>工单编号:</b> {ticket_id}</div>
                    <div class="info-item">👤 <b>申请用户:</b> {creator_name}</div>
                    <div class="info-item">🐧 <b>绑定QQ:</b> {qq_number}</div>
                </div>
                <hr>
                """
                html_content = html_template.format(
                    channel_name=channel.name,
                    embed_color=hex(STYLE['KIMI_YELLOW']).replace('0x', '#'),
                    ticket_id=ticket_id,
                    creator_name=creator_name,
                    qq_number=qq_number
                )

                # 读取历史消息
                async for message in channel.history(limit=None, oldest_first=True):
                    message_text = message.clean_content.replace('\n', '<br>')
                    timestamp = message.created_at.astimezone(QUOTA["TIMEZONE"]).strftime('%Y-%m-%d %H:%M:%S')
                    html_content += f'<div class="message-group"><div class="avatar"><img src="{message.author.display_avatar.url}"></div>'
                    html_content += f'<div class="message-content"><span class="author">{message.author.display_name}</span><span class="timestamp">{timestamp}</span>'
                    html_content += f'<div class="text">{message_text}</div>'

                    # 处理附件
                    for attachment in message.attachments:
                        if "image" in attachment.content_type:
                            html_content += f'<div class="attachment"><img src="{attachment.url}"></div>'

                    # 处理 Embed
                    for embed in message.embeds:
                        html_content += f'<div class="embed">'
                        if embed.title: html_content += f'<div class="embed-title">{embed.title}</div>'
                        if embed.description:
                            description_text = embed.description.replace("\n", "<br>")
                            html_content += f'<div class="embed-description">{description_text}</div>'
                        html_content += '</div>'
                    html_content += '</div></div>'
                html_content += "</body></html>"

                # 压缩为 ZIP
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    zip_file.writestr(f'{channel.name}.html', html_content.encode('utf-8'))
                zip_buffer.seek(0)

                # 发送日志
                await log_channel.send(f"📄 归档记录: `{channel.name}` (QQ: {qq_number})")
                await log_channel.send(file=discord.File(zip_buffer, filename=f"{channel.name}.zip"))

                # 删除原频道
                await channel.delete(reason="批量导出并归档")
                exported_count += 1
                await asyncio.sleep(1) 

            except Exception as e:
                print(f"批量导出频道 {channel.name} 时出错: {e}")
                await log_channel.send(f"❌ 导出频道 `{channel.name}` 时出错: {e}")

        await ctx.followup.send(f"批量导出完成！成功处理了 **{exported_count}/{len(channels_to_process)}** 个频道！", ephemeral=True)

    @ticket.command(name="录入qq", description="录入QQ号")
    @is_reviewer_egg()
    async def record_qq(self, ctx: discord.ApplicationContext, qq_number: str):
        channel = ctx.channel
        if not channel.topic: return
        await ctx.defer(ephemeral=True)
        info = get_ticket_info(channel)
        info["QQ"] = qq_number
        new_topic = " | ".join([f"{k}: {v}" for k, v in info.items()])
        await channel.edit(topic=new_topic)
        await ctx.followup.send(f"✅ QQ已录入: {qq_number}", ephemeral=True)

    @ticket.command(name="批量清理超时", description="清除超时归档频道")
    @is_reviewer_egg()
    async def bulk_clean_timeouts(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        cat = self.bot.get_channel(IDS["ARCHIVE_CHANNEL_ID"])
        if not cat: return

        chs = [c for c in cat.text_channels if "超时归档" in c.name]
        if not chs: return await ctx.followup.send("没有超时归档", ephemeral=True)

        await ctx.followup.send(f"开始清理 {len(chs)} 个频道...", ephemeral=True)
        for c in chs:
            await c.delete(reason="批量清理")
            await asyncio.sleep(1)
        await ctx.followup.send("清理完成", ephemeral=True)
    
    @ticket.command(name="批量更名", description="（管理用）一键将【一审中】前缀修正为【审核中】")
    @is_reviewer_egg()
    async def bulk_rename_tickets(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 🟢 逻辑修改：同时扫描主分类和备用分类
        categories = [
            self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"]),
            self.bot.get_channel(IDS.get("FIRST_REVIEW_EXTRA_CHANNEL_ID"))
        ]

        channels_to_rename = []
        for cat in categories:
            if not cat: continue
            channels_to_rename.extend([ch for ch in cat.text_channels if "一审中" in ch.name])

        if not channels_to_rename:
            await ctx.followup.send("没有发现需要更名的频道哦~", ephemeral=True); return

        progress_msg = await ctx.followup.send(f"开始处理... 预计需要 {len(channels_to_rename) * 2} 秒", ephemeral=True)
        success_count = 0

        for channel in channels_to_rename:
            try:
                old_name = channel.name
                new_name = old_name.replace("一审中", "审核中")
                if old_name != new_name:
                    await channel.edit(name=new_name)
                    success_count += 1
                    await asyncio.sleep(1.5)
            except Exception as e:
                print(f"更名出错: {e}")

        await progress_msg.edit(content=f"✅ 处理完成！\n扫描: {len(channels_to_rename)} 个\n更名: {success_count} 个")

    # 上下文菜单：右键消息超时归档
    @discord.message_command(name="超时归档此工单")
    @is_reviewer_egg()
    async def timeout_archive_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        if not get_ticket_info(ctx.channel).get("工单ID"): return await ctx.respond("无效频道", ephemeral=True)
        await ctx.respond("确认归档？", view=TimeoutOptionView(self.bot, ctx.channel), ephemeral=True)

    # --- 工单计划管理组 ---
    schedule_group = discord.SlashCommandGroup("工单计划", "管理工单/审核系统的维护计划", checks=[is_reviewer_egg()])

    @schedule_group.command(name="查看", description="查看当前工单审核的自动暂停计划")
    async def view_audit_schedule(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 从字典读取数据
        is_suspended = self.schedule_data.get("suspended", False)

        if not is_suspended:
            desc = "🟢 **当前工单系统正常开放**\n没有检测到预设的暂停计划。"
            color = 0x00FF00
        else:
            now = datetime.datetime.now(QUOTA["TIMEZONE"])
            desc = "🔴 **检测到维护/暂停计划**\n"

            # 显示预设的原因
            reason = self.schedule_data.get("reason") or "未填写原因"
            desc += f"原因: {reason}\n"

            # 读取时间戳
            start_ts = self.schedule_data.get("start_dt")
            end_ts = self.schedule_data.get("end_dt")

            # 转换时间用于显示
            if start_ts:
                start_dt = datetime.datetime.fromtimestamp(start_ts, QUOTA["TIMEZONE"])
                start_str = start_dt.strftime('%m-%d %H:%M')
            else:
                start_dt = None
                start_str = "立即生效"

            if end_ts:
                end_dt = datetime.datetime.fromtimestamp(end_ts, QUOTA["TIMEZONE"])
                end_str = end_dt.strftime('%m-%d %H:%M')
            else:
                end_dt = None
                end_str = "手动恢复"

            desc += f"📅 **计划时间表**:\nStart: `{start_str}`\nEnd: `{end_str}`\n\n"

            # 判断当前这一秒是否真的暂停了
            is_active_now = False
            if not start_dt:
                is_active_now = True
            elif now >= start_dt:
                if not end_dt or now < end_dt:
                    is_active_now = True

            status_text = "⛔ **服务已暂停** (当前生效中)" if is_active_now else "⏳ **计划等待执行中** (尚未开始)"
            desc += f"⚡ **当前状态**: {status_text}"
            color = 0xFF0000

        await ctx.followup.send(embed=discord.Embed(title="📅 工单计划管理器", description=desc, color=color), ephemeral=True)


    @schedule_group.command(name="清除", description="移除所有定时计划并立即恢复工单系统")
    async def clear_audit_schedule(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)

        # 重置所有状态到字典
        self.schedule_data = {
            "suspended": False,
            "reason": None,
            "start_dt": None,
            "end_dt": None
        }
        # 保存到文件
        save_audit_schedule(self.schedule_data)

        # 立即更新面板显示
        await self.update_panel_message()

        await ctx.followup.send(
            embed=discord.Embed(description="✅ **已清除所有计划任务！**\n工单系统已强制恢复为开放状态，面板已刷新。", color=0x00FF00),
            ephemeral=True
        )


    # --- 名额管理组 ---
    quota_mg = discord.SlashCommandGroup("名额管理", "（仅限审核小蛋）手动调整工单名额~", checks=[is_reviewer_egg()])

    @quota_mg.command(name="重置", description="将今天的剩余名额恢复到最大值！")
    async def reset_quota(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        d = load_quota_data(); d["daily_quota_left"] = QUOTA["DAILY_TICKET_LIMIT"]
        save_quota_data(d); await self.update_panel_message()
        await ctx.followup.send(f"已重置为 {QUOTA['DAILY_TICKET_LIMIT']}", ephemeral=True)

    @quota_mg.command(name="设置", description="手动设置今天的剩余名额数量！")
    async def set_quota(self, ctx: discord.ApplicationContext, amount: discord.Option(int)):
        await ctx.defer(ephemeral=True)
        if amount < 0: return await ctx.followup.send("不能为负", ephemeral=True)
        d = load_quota_data(); d["daily_quota_left"] = amount
        save_quota_data(d); await self.update_panel_message()
        await ctx.followup.send(f"已设置为 {amount}", ephemeral=True)

    @quota_mg.command(name="增加", description="给今天的剩余名额增加指定数量！")
    async def add_quota(self, ctx: discord.ApplicationContext, amount: discord.Option(int)):
        await ctx.defer(ephemeral=True)
        if amount <= 0: return await ctx.followup.send("必须大于0", ephemeral=True)
        d = load_quota_data(); d["daily_quota_left"] += amount
        save_quota_data(d); await self.update_panel_message()
        await ctx.followup.send(f"已增加，当前: {d['daily_quota_left']}", ephemeral=True)

    @discord.slash_command(name="刷新工单创建面板", description="（仅限审核小蛋）手动发送或刷新工单创建面板！")
    @is_reviewer_egg()
    async def setup_ticket_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        await self.update_panel_message()
        await ctx.followup.send("已刷新面板", ephemeral=True)
