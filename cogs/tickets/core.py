# cogs/tickets/core.py

import discord
from discord.ext import commands, tasks
import asyncio
import datetime
import random
import io
import zipfile

from config import IDS, QUOTA, STYLE
from .utils import (
    STRINGS, SPECIFIC_REVIEWER_ID, TIMEOUT_HOURS_ARCHIVE, TIMEOUT_HOURS_REMIND,
    is_reviewer_egg, get_ticket_info, load_quota_data, save_quota_data, execute_archive
)
from .views import (
    TicketActionView, TimeoutOptionView, ArchiveRequestView,
    NotifyReviewerView
)
# 注意：为了解决循环引用，TicketPanelView 有时会放在这里定义，或者通过传递 Cog 实例解决。
# 这里我们在本文件定义它，以确保它能直接调用 Cog 的方法。

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
        self.audit_suspended = False
        self.audit_suspend_reason = None
        self.suspend_end_time = None
        self.audit_suspended_until = None # 兼容你旧代码里的变量名

    @commands.Cog.listener()
    async def on_ready(self):
        # 注册所有 Persistent Views
        self.bot.add_view(TicketActionView())
        self.bot.add_view(TicketPanelView(self))
        self.bot.add_view(ArchiveRequestView())
        self.bot.add_view(NotifyReviewerView(SPECIFIC_REVIEWER_ID))
        # 你的旧代码里可能还有 TimeoutOptionView 需要持久化吗？通常这种是临时的，但如果它是发在消息里的，重启后失效也没关系。
        # 如果需要持久化，也可以添加
        # self.bot.add_view(TimeoutOptionView(self.bot, None)) # 这需要改写 View 逻辑以支持无参数初始化

        print("Tickets Cog Loaded & Views Registered.")

        # 启动定时任务
        if not self.reset_daily_quota.is_running(): self.reset_daily_quota.start()
        if not self.check_inactive_tickets.is_running(): self.check_inactive_tickets.start()
        if not self.close_tickets_at_night.is_running(): self.close_tickets_at_night.start()

    # ======================================================================================
    # --- 核心逻辑方法 (供 View 调用) ---
    # ======================================================================================

    async def create_ticket_logic(self, interaction):
        # 1. 检查暂停状态
        if self.audit_suspended:
            if self.audit_suspended_until:
                now = datetime.datetime.now()
                # 检查是否已过暂停时间
                if self.audit_suspended_until != "infinite" and now >= self.audit_suspended_until:
                    self.audit_suspended = False
                    self.audit_suspended_until = None
                    # 恢复了，继续往下走
                else:
                    reason = self.audit_suspend_reason or "管理员暂停了审核功能"
                    until_str = "恢复时间待定" if self.audit_suspended_until == "infinite" else f"预计 {self.audit_suspended_until.strftime('%H:%M')} 恢复"
                    return await interaction.response.send_message(f"🚫 **审核通道已暂时关闭**\n原因：{reason}\n{until_str}", ephemeral=True)
            else:
                 # 简单的暂停
                 return await interaction.response.send_message(f"🚫 审核暂停中: {self.audit_suspend_reason}", ephemeral=True)

        # 2. 检查时间 (08:00 - 23:00)
        now = datetime.datetime.now(QUOTA["TIMEZONE"])
        if not (8 <= now.hour < 23):
             return await interaction.response.send_message(STRINGS["messages"]["err_time_limit"], ephemeral=True)

        # 3. 检查资格 (Role & ID)
        user_roles = [r.id for r in interaction.user.roles]
        has_perm = (IDS["VERIFICATION_ROLE_ID"] in user_roles) or \
                   (IDS["SUPER_EGG_ROLE_ID"] in user_roles) or \
                   (interaction.user.id == SPECIFIC_REVIEWER_ID)

        if not has_perm:
            return await interaction.response.send_message(STRINGS["messages"]["err_perm_create"], ephemeral=True)

        # 4. 检查重复 & 额度
        c1 = interaction.guild.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])
        c2 = interaction.guild.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])

        # 检查分类是否存在
        if not c1 or not isinstance(c1, discord.CategoryChannel):
             return await interaction.response.send_message("呜...找不到【一审】的频道分类！请服主检查配置！", ephemeral=True)

        # 检查分类容量
        if len(c1.channels) >= 50:
             return await interaction.response.send_message("🚫 **无法创建工单**\n呜...当前的审核队列（一审分类）已经满了（50/50）！", ephemeral=True)

        # 检查是否已有工单
        for c in [c1, c2]:
            if not c: continue
            for ch in c.text_channels:
                if str(interaction.user.id) in (ch.topic or ""):
                     return await interaction.response.send_message(STRINGS["messages"]["err_already_has"].format(channel=ch.mention), ephemeral=True)

        q_data = load_quota_data()
        if q_data["daily_quota_left"] <= 0:
            return await interaction.response.send_message(STRINGS["messages"]["err_quota_limit"], ephemeral=True)

        # 5. 执行创建
        await interaction.response.defer(ephemeral=True)

        # 先扣额度
        q_data["daily_quota_left"] -= 1
        save_quota_data(q_data)
        await self.update_panel_message()

        tid = random.randint(100000, 999999)
        c_name = f"审核中-{tid}-{interaction.user.name}" # 改回你原来的"审核中"还是"一审中"？你原来代码是"一审中"
        c_name = f"一审中-{tid}-{interaction.user.name}"

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        # 添加管理员权限
        staff = interaction.guild.get_member(SPECIFIC_REVIEWER_ID)
        if staff: overwrites[staff] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        super_egg = interaction.guild.get_role(IDS["SUPER_EGG_ROLE_ID"])
        if super_egg: overwrites[super_egg] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        try:
            ch = await interaction.guild.create_text_channel(
                name=c_name, category=c1, overwrites=overwrites,
                topic=f"创建者ID: {interaction.user.id} | 创建者: {interaction.user.name} | 工单ID: {tid}"
            )

            # 发送初始消息
            e_create = discord.Embed.from_dict(STRINGS["embeds"]["ticket_created"])
            e_create.description = e_create.description.replace("{ticket_id}", str(tid))
            e_create.color = STYLE["KIMI_YELLOW"]
            await ch.send(f"{interaction.user.mention} <@&{SPECIFIC_REVIEWER_ID}>", embed=e_create, view=TicketActionView())

            # 发送要求
            req_data = STRINGS["embeds"]["requirements"]
            e_req = discord.Embed(title=req_data["title"], description=req_data["desc"], color=STYLE["KIMI_YELLOW"])
            for f in req_data["fields"]: e_req.add_field(name=f["name"], value=f["value"], inline=False)
            e_req.set_image(url=req_data["image"])
            e_req.set_footer(text=req_data["footer"])
            await ch.send(f"你好呀 {interaction.user.mention}，请按下面的要求提交材料哦~", embed=e_req)

            # 发送唤起按钮
            rem_text = STRINGS["messages"]["reminder_text"].format(ticket_id=tid, user_id=interaction.user.id)
            await ch.send(embed=discord.Embed(description=rem_text, color=STYLE["KIMI_YELLOW"]), view=NotifyReviewerView(SPECIFIC_REVIEWER_ID))

            # 私信
            try:
                msg = STRINGS["messages"]["dm_create_success"].format(guild_name=interaction.guild.name, channel_mention=ch.mention)
                await interaction.user.send(msg)
                msg_status = STRINGS["messages"]["dm_status_ok"]
            except:
                msg_status = STRINGS["messages"]["dm_status_fail"]

            await interaction.followup.send(f"好惹！你的审核频道 {ch.mention} 已经创建好惹！审核要求已发送到频道内~ {msg_status}", ephemeral=True)

        except Exception as e:
            # 失败回滚
            print(f"创建工单失败: {e}")
            q_data["daily_quota_left"] += 1
            save_quota_data(q_data)
            await self.update_panel_message()
            await interaction.followup.send(f"创建失败: {e}", ephemeral=True)

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

        # 状态判断
        if self.audit_suspended:
            label = p_data["btn_suspended"]
            disabled = False # 允许点击看原因
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

        # 你的旧逻辑：遍历一审二审分类
        cats = [self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"]), self.bot.get_channel(IDS["SECOND_REVIEW_CHANNEL_ID"])]

        for cat in cats:
            if not cat: continue
            for channel in cat.text_channels:
                # 过滤
                if not ("一审中-" in channel.name or "二审中-" in channel.name or "待接单" in channel.name or "已过审" in channel.name):
                    continue

                try:
                    info = get_ticket_info(channel)
                    tid = info.get("工单ID")

                    # 获取最后消息
                    last_msg = None
                    async for m in channel.history(limit=1): last_msg = m; break
                    if not last_msg: continue

                    time_diff = now - last_msg.created_at

                    # 1. 检查已过审在等待确认的 (3小时自动归档)
                    is_approved_waiting = False
                    if last_msg.author.id == self.bot.user.id and last_msg.embeds and "恭喜小宝加入社区" in (last_msg.embeds[0].title or ""):
                        is_approved_waiting = True

                    if is_approved_waiting and time_diff > datetime.timedelta(hours=3):
                        await channel.send("⏳ **自动归档**\n检测到通过审核后超过 **3小时** 未点击确认。\n本大王已自动归档！")
                        # 移动到归档区
                        await execute_archive(self.bot, None, channel, "已过审3小时无响应自动归档", is_timeout=False)
                        continue

                    # 2. 常规超时 (12小时)
                    # 重新计算最后有效活动 (排除 bot 提醒)
                    last_active = channel.created_at
                    has_reminded = False
                    async for m in channel.history(limit=20):
                        if m.author.bot:
                            if "温馨提醒" in m.content or (m.embeds and "温馨提醒" in (m.embeds[0].title or "")):
                                has_reminded = True
                        else:
                            last_active = m.created_at
                            break

                    diff_active = now - last_active

                    if diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_ARCHIVE):
                        # 超时归档
                        await execute_archive(self.bot, None, channel, f"超过{TIMEOUT_HOURS_ARCHIVE}小时无活动", is_timeout=True)

                    elif diff_active > datetime.timedelta(hours=TIMEOUT_HOURS_REMIND) and not has_reminded and not is_approved_waiting:
                        # 提醒
                        embed = discord.Embed(title="⏰ 温馨提醒", description=f"工单已沉睡超过 {TIMEOUT_HOURS_REMIND} 小时！\n超过 {TIMEOUT_HOURS_ARCHIVE} 小时会自动归档哦！", color=0xFFA500)
                        uid = info.get("创建者ID")
                        txt = f"<@{uid}>" if uid else ""
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
                        break  # 修复最新这一个就够了
        except Exception as e:
            print(f"修复按钮时出错: {e}")

        # 3. 反馈结果
        if fixed:
            await ctx.followup.send("✅ 已成功修复当前频道的旧操作面板！按钮应该能用啦！", ephemeral=True)
        else:
            # 如果实在找不到旧面板，作为兜底方案才发一个新的
            embed = discord.Embed(
                title="🔧 管理员操作面板 (补发)",
                description="呜...本蛋没找到旧的面板消息，所以给你补发了一个新的！",
                color=STYLE["KIMI_YELLOW"]
            )
            await ctx.channel.send(embed=embed, view=TicketActionView())
            await ctx.followup.send("⚠️ 未找到可修复的旧消息，已为你补发新的面板。", ephemeral=True)


    @ticket.command(name="中止新蛋审核", description="（管理员）设置中止工单申请。")
    @is_reviewer_egg()
    async def suspend_audit(self, ctx: discord.ApplicationContext,
                            duration: discord.Option(str, "中止时长 (例如 1h, 30m, 留空或inf为无限期)", required=False) = None,
                            reason: discord.Option(str, "中止原因", default="管理员正在进行系统维护") = None):
        await ctx.defer(ephemeral=True)
        self.audit_suspended = True
        self.audit_suspend_reason = reason
        self.audit_suspended_until = "infinite" # 默认

        msg = f"✅ 已中止审核功能。\n原因：{reason}\n"

        # 简单的时长解析逻辑
        if duration and duration.lower() != "inf":
            seconds = 0
            if duration.endswith('h'): seconds = int(duration[:-1]) * 3600
            elif duration.endswith('m'): seconds = int(duration[:-1]) * 60

            if seconds > 0:
                self.audit_suspended_until = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
                msg += f"预计恢复时间：{duration} 后"
                # 自动恢复Task
                self.bot.loop.create_task(self.auto_resume_audit(seconds))

        await self.update_panel_message()
        await ctx.followup.send(msg, ephemeral=True)

    async def auto_resume_audit(self, seconds):
        await asyncio.sleep(seconds)
        self.audit_suspended = False
        self.audit_suspended_until = None
        await self.update_panel_message()

    @ticket.command(name="恢复工单状态", description="（审核小蛋用）误操作恢复！")
    @is_reviewer_egg()
    async def recover_ticket(self, ctx: discord.ApplicationContext,
                             state: discord.Option(str, "选择恢复到的状态", choices=["一审中", "二审中", "已过审", "归档"]),
                             reason: discord.Option(str, "给用户的解释", required=False, default="管理员手动调整了工单状态。")):
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        info = get_ticket_info(channel)
        if not info.get("工单ID"): return await ctx.followup.send("无效工单頻道", ephemeral=True)

        # 确定目标分类
        tid_prefix = state
        target_id = IDS["FIRST_REVIEW_CHANNEL_ID"]
        if state in ["二审中", "已过审"]: target_id = IDS["SECOND_REVIEW_CHANNEL_ID"]
        elif state == "归档": target_id = IDS["ARCHIVE_CHANNEL_ID"]

        target_cat = ctx.guild.get_channel(target_id)
        if not target_cat: return await ctx.followup.send("找不到目标分类配置", ephemeral=True)

        # 确定权限
        overwrites = {ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False)}
        spec = ctx.guild.get_member(SPECIFIC_REVIEWER_ID)
        if spec: overwrites[spec] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        # 用户权限
        uid = info.get("创建者ID")
        user = ctx.guild.get_member(int(uid)) if uid else None
        if user and state != "归档": # 归档不给看
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
        # 简单做: 直接弹确认
        await ctx.defer(ephemeral=True)
        channel = ctx.channel
        if not get_ticket_info(channel).get("工单ID"): return await ctx.followup.send("无效频道", ephemeral=True)

        d = load_quota_data()
        d["daily_quota_left"] += 1
        save_quota_data(d)
        await self.update_panel_message()

        await channel.delete(reason=f"管理员 {ctx.author.name} 删除并返还名额")
        # 由于频道删了，followup可能会报错，忽略即可或者在日志频道发

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
        # 因为改名操作比较慢，我们要先告诉 Discord 稍微等一下
        await ctx.defer(ephemeral=True)

        # 获取一审分类（如果是二审区也要改，可以把这里换成 SECOND_REVIEW_CHANNEL_ID）
        target_category = self.bot.get_channel(IDS["FIRST_REVIEW_CHANNEL_ID"])

        if not target_category:
            await ctx.followup.send("呜...找不到配置的【一审分类】！请检查 ID 配置。", ephemeral=True); return

        await ctx.followup.send(f"收到！正在扫描 “{target_category.name}” 中需要更名的频道...", ephemeral=True)

        # 筛选出名字里包含 "一审中" 的频道
        channels_to_rename = [ch for ch in target_category.text_channels if "一审中" in ch.name]

        if not channels_to_rename:
            await ctx.followup.send("在这个分类下没有发现带“一审中”前缀的频道哦~", ephemeral=True); return

        success_count = 0

        # 发送一个初始进度提示
        progress_msg = await ctx.followup.send(f"开始处理... 预计需要 {len(channels_to_rename) * 2} 秒完成", ephemeral=True)

        for index, channel in enumerate(channels_to_rename):
            try:
                # 生成新名字：把 "一审中" 替换为 "审核中"
                old_name = channel.name
                new_name = old_name.replace("一审中", "审核中")

                if old_name != new_name:
                    await channel.edit(name=new_name)
                    success_count += 1
                    # 打印一下日志方便后台看
                    print(f"[批量更名] {old_name} -> {new_name}")

                    # 这一点非常重要：Discord 对改名有限速，如果不休息会被临时封禁接口
                    # 妈妈为了你的安全，设置了1.5秒的间隔
                    await asyncio.sleep(1.5)

            except Exception as e:
                print(f"更名频道 {channel.name} 时出错: {e}")

        await progress_msg.edit(content=f"✅ 处理完成！\n共扫描: {len(channels_to_rename)} 个\n成功更名: {success_count} 个")

    # 上下文菜单：右键消息超时归档
    @discord.message_command(name="超时归档此工单")
    @is_reviewer_egg()
    async def timeout_archive_ctx(self, ctx: discord.ApplicationContext, message: discord.Message):
        if not get_ticket_info(ctx.channel).get("工单ID"): return await ctx.respond("无效频道", ephemeral=True)
        await ctx.respond("确认归档？", view=TimeoutOptionView(self.bot, ctx.channel), ephemeral=True)

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
