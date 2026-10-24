import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
import discord
from discord.ext import commands, tasks
from . import storage as store
from .views import EntryView, ReviewView, BottomView, entry_embed, application_embed, result_embed, jump_view

log = logging.getLogger(__name__)


class PromotionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_lock = asyncio.Lock()
        self.work_lock = asyncio.Lock()
        self.publish_lock = asyncio.Lock()
        self.panel_lock = asyncio.Lock()
        self.next_request = 0.0
        self.backfilled = False
        self.panel_signature = None
        self.entry_signature = None
        self.bot.add_view(EntryView())
        self.bot.add_view(ReviewView())
        self.worker.start()

    def cog_unload(self):
        self.worker.cancel()

    def report(self, action, error):
        log.warning('小蛋晋升 %s: %r', action, error)

    async def api(self, operation, *args, **kwargs):
        """Shared one-request-per-second lane, in addition to Pycord/global scheduling."""
        async with self.api_lock:
            await asyncio.sleep(max(0, self.next_request - time.monotonic()))
            try:
                return await operation(*args, **kwargs)
            except discord.HTTPException as error:
                if error.status == 429:
                    retry = getattr(error, 'retry_after', None)
                    if retry is None:
                        retry = getattr(error.response, 'headers', {}).get('Retry-After', 30)
                    self.next_request = time.monotonic() + max(30, float(retry))
                raise
            finally:
                self.next_request = max(self.next_request, time.monotonic() + 1)

    async def channel(self, channel_id):
        return self.bot.get_channel(channel_id) or await self.api(self.bot.fetch_channel, channel_id)

    async def find_sent(self, channel, row):
        """Recover an interrupted send, paging history through the same REST lane."""
        cursor = datetime.fromisoformat(row['created'])
        footer = f'小蛋晋升申请 #{row["id"]} · 北京时间 · 截图见附件'
        while True:
            messages = await self.api(channel.history(limit=100, after=cursor, oldest_first=True).flatten)
            for message in messages:
                if message.author.id == self.bot.user.id and message.embeds and message.embeds[0].footer.text == footer:
                    return message
            if len(messages) < 100:
                return None
            cursor = messages[-1]

    async def publish(self, row):
        async with self.publish_lock:
            row = await asyncio.to_thread(store.get, row['id'])
            if row['status'] != 'publishing':
                return
            channel = await self.channel(row.get('channel_id', store.CHANNEL_ID))
            # On an interrupted send, recover the canonical card before resending.
            if row.get('send_started'):
                found = await self.find_sent(channel, row)
                if found:
                    await asyncio.to_thread(store.update, row['id'], status='pending', message_id=found.id)
                    return
            await asyncio.to_thread(store.update, row['id'], send_started=True)
            display = dict(row, status='pending')
            files = [discord.File(path, filename=Path(path).name) for path in row['files']]
            embeds = [application_embed(display)]
            for index, path in enumerate(row['files'], 1):
                embeds.append(discord.Embed(title=f'使用足迹 · {index}', color=0xEBCB8B).set_image(url=f'attachment://{Path(path).name}'))
            try:
                msg = await self.api(channel.send, embeds=embeds, files=files, view=ReviewView(),
                    allowed_mentions=discord.AllowedMentions.none(), nonce=f'promotion-{row["id"]}', enforce_nonce=True)
                await asyncio.to_thread(store.update, row['id'], status='pending', message_id=msg.id, card_dirty=False)
            finally:
                for file in files:
                    file.close()

    async def review(self, interaction, application_id, approved, reason=''):
        if interaction.guild is None or interaction.user.id != interaction.guild.owner_id:
            return await interaction.followup.send('只有服主可以审批。', ephemeral=True)
        try:
            async with self.work_lock:
                existing = await asyncio.to_thread(store.get, application_id)
                if not existing or int(existing['guild_id']) != interaction.guild_id:
                    raise ValueError('申请不属于当前服务器。')
                row = await asyncio.to_thread(store.decide, application_id, interaction.user.id, approved, reason)
                await self.process(row)
            await interaction.followup.send('✅ 审批已保存，申请卡片、记录频道和私信将自动同步。', ephemeral=True)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except Exception as error:
            self.report('审批后同步', error)
            await interaction.followup.send('审批已记录，部分发放或通知尚未完成，后台会继续重试；请勿重复审批。', ephemeral=True)

    async def process(self, row):
        guild = self.bot.get_guild(int(row['guild_id']))
        if not guild:
            return
        if row['status'] == 'granting' and row.get('is_test'):
            row = await asyncio.to_thread(store.complete, row['id'])
        if row['status'] == 'granting':
            member = guild.get_member(int(row['user_id'])) or await self.api(guild.fetch_member, int(row['user_id']))
            role = guild.get_role(store.ROLE_ID)
            if role is None:
                raise ValueError('破壳而出身份组不存在，等待管理员修复。')
            if role not in member.roles:
                await self.api(member.add_roles, role, reason=f'服主批准小蛋晋升 #{row["id"]}')
            row = await asyncio.to_thread(store.complete, row['id'])
        card_error = None
        if row.get('card_dirty') and row.get('message_id'):
            try:
                channel = await self.channel(row.get('channel_id', store.CHANNEL_ID))
                message = await self.api(channel.fetch_message, row['message_id'])
                await self.api(message.edit, embeds=[application_embed(row)] + message.embeds[1:],
                    view=ReviewView() if row['status'] == 'pending' else None,
                    allowed_mentions=discord.AllowedMentions.none())
            except discord.NotFound:
                self.report('申请卡片被删除', ValueError(row['id']))
            except Exception as error:
                card_error = error
            if card_error is None:
                await asyncio.to_thread(store.update, row['id'], card_dirty=False)
        if row['status'] not in ('approved', 'rejected'):
            return
        log_error = None
        if row.get('log_state') != 'sent':
            try:
                cfg = await asyncio.to_thread(store.settings)
                log_channel_id = row.get('log_channel_id', store.LOG_CHANNEL_ID if row.get('log_send_started') else cfg['log_channel_id'])
                channel = await self.channel(log_channel_id)
                message = await self.find_sent(channel, row) if row.get('log_send_started') else None
                if message is None:
                    await asyncio.to_thread(store.update, row['id'], log_send_started=True, log_channel_id=log_channel_id)
                    embed = application_embed(row)
                    embed.add_field(name='审批时间', value=row.get('reviewed', '—'), inline=False)
                    if row['status'] == 'approved' and not row.get('is_test'):
                        embed.add_field(name='权益发放', value='破壳而出身份组已确认；永久权益已开通，首次赠礼仅到账一次。', inline=False)
                    message = await self.api(channel.send, embed=embed, view=jump_view(row),
                        allowed_mentions=discord.AllowedMentions.none(), nonce=f'promotion-log-{row["id"]}', enforce_nonce=True)
                row = await asyncio.to_thread(store.update, row['id'], log_state='sent', log_message_id=message.id, log_channel_id=log_channel_id)
            except Exception as error:
                log_error = error
        if row.get('dm_state') == 'pending':
            # Persist before send: an uncertain process crash must not spam the applicant.
            await asyncio.to_thread(store.update, row['id'], dm_state='sending')
            try:
                user = self.bot.get_user(int(row['user_id'])) or await self.api(self.bot.fetch_user, int(row['user_id']))
                await self.api(user.send, embed=result_embed(row), view=jump_view(row),
                    allowed_mentions=discord.AllowedMentions.none(), nonce=f'promotion-dm-{row["id"]}', enforce_nonce=True)
            except discord.Forbidden:
                await asyncio.to_thread(store.update, row['id'], dm_state='blocked')
            except discord.HTTPException:
                await asyncio.to_thread(store.update, row['id'], dm_state='pending')
                raise
            except Exception:
                await asyncio.to_thread(store.update, row['id'], dm_state='unknown')
                raise
            else:
                await asyncio.to_thread(store.update, row['id'], dm_state='sent')

        current = await asyncio.to_thread(store.get, row['id'])
        if current.get('log_message_id') and current.get('dm_state') != current.get('logged_dm_state'):
            channel = await self.channel(current.get('log_channel_id', store.LOG_CHANNEL_ID))
            message = await self.api(channel.fetch_message, current['log_message_id'])
            embed = application_embed(current)
            embed.add_field(name='审批时间', value=current.get('reviewed', '—'), inline=False)
            label = {'sent': '已送达', 'blocked': '未送达：成员关闭私信或屏蔽机器人',
                     'sending': '发送中断，送达状态待确认', 'unknown': '送达状态待确认', 'pending': '等待发送'}
            embed.add_field(name='私信通知', value=label.get(current.get('dm_state'), '等待发送'), inline=False)
            await self.api(message.edit, embed=embed, allowed_mentions=discord.AllowedMentions.none())
            await asyncio.to_thread(store.update, row['id'], logged_dm_state=current.get('dm_state'))
        if log_error:
            raise log_error
        if card_error:
            raise card_error

    async def configure(self, changes):
        async with self.panel_lock:
            previous = await asyncio.to_thread(store.settings)
            current = await asyncio.to_thread(store.save_settings, changes)
            self.entry_signature = self.panel_signature = None
            if previous['channel_id'] != current['channel_id']:
                self.backfilled = False
                # Retire entry/navigation only; application cards stay reviewable in place.
                for name in ('entry', 'bottom'):
                    message_id = await asyncio.to_thread(store.panel, name, channel_id=previous['channel_id'])
                    if not message_id:
                        continue
                    try:
                        channel = await self.channel(previous['channel_id'])
                        message = channel.get_partial_message(message_id)
                        if name == 'entry':
                            await self.api(message.edit, content=f'小蛋晋升入口已迁移至 <#{current["channel_id"]}>。',
                                           embed=None, view=None, allowed_mentions=discord.AllowedMentions.none())
                        else:
                            await self.api(message.delete)
                    except discord.HTTPException as error:
                        self.report('清理旧晋升入口', error)
            return current

    async def refresh_panels(self):
        async with self.panel_lock:
            cfg = await asyncio.to_thread(store.settings)
            channel = await self.channel(cfg['channel_id'])
            used = await asyncio.to_thread(store.quota, channel.guild.id)
            signature = (store.today(), used, tuple(sorted(cfg.items())))
            if self.entry_signature != signature:
                message_id = await asyncio.to_thread(store.panel, 'entry', channel_id=channel.id)
                message = None
                if message_id:
                    try:
                        message = await self.api(channel.fetch_message, message_id)
                    except discord.NotFound:
                        pass
                if message:
                    await self.api(message.edit, content=None, embed=entry_embed(used, cfg), view=EntryView())
                else:
                    message = await self.api(channel.send, embed=entry_embed(used, cfg), view=EntryView(),
                        allowed_mentions=discord.AllowedMentions.none())
                    await asyncio.to_thread(store.panel, 'entry', message.id, channel_id=channel.id)
                self.entry_signature = signature
            rows = await asyncio.to_thread(store.applications, channel.guild.id)
            pending = [r for r in rows if r['status'] == 'pending' and r.get('message_id')]
            earliest = pending[0] if pending else None
            bottom_sig = (signature, tuple(r['id'] for r in pending))
            old_id = await asyncio.to_thread(store.panel, 'bottom', channel_id=channel.id)
            if old_id == channel.last_message_id and bottom_sig == self.panel_signature:
                return
            embed = discord.Embed(title='🕊️ 小蛋晋升 · 审批导航', color=0xB8C9C1,
                description=f'待审批 **{len(pending)}** 份 · 今日名额 **{max(0, 100-used)} / 100**\n'
                '点击下方按钮可直达最早未审批的申请。\n北京时间 0 点刷新名额；本导航自动更新并移至频道底部。')
            if old_id == channel.last_message_id:
                try:
                    msg = await self.api(channel.fetch_message, old_id)
                    await self.api(msg.edit, embed=embed, view=BottomView(earliest))
                    self.panel_signature = bottom_sig
                    return
                except discord.NotFound:
                    pass
            msg = await self.api(channel.send, embed=embed, view=BottomView(earliest))
            await asyncio.to_thread(store.panel, 'bottom', msg.id, channel_id=channel.id)
            self.panel_signature = bottom_sig
            if old_id:
                try:
                    await self.api(channel.get_partial_message(old_id).delete)
                except discord.NotFound:
                    pass

    @tasks.loop(seconds=30)
    async def worker(self):
        try:
            cfg = await asyncio.to_thread(store.settings)
            channel = await self.channel(cfg['channel_id'])
            guild = channel.guild
            if not self.backfilled:
                if not guild.chunked:
                    await guild.chunk(cache=True)
                count = 0
                for member in guild.members:
                    if store.auto_eligible(member):
                        count += await asyncio.to_thread(store.activate, member.id, guild.id)
                log.info('小蛋晋升：已有身份组及管理员 / 服主权益补发完成，新开通 %s 人', count)
                self.backfilled = True
            await asyncio.to_thread(store.settle_daily)
            async with self.work_lock:
                rows = await asyncio.to_thread(store.applications, guild.id)
                for row in rows:
                    try:
                        if row['status'] == 'publishing':
                            await self.publish(row)
                        elif (row['status'] == 'granting' or row.get('card_dirty') or
                              (row['status'] in ('approved', 'rejected') and
                               (row.get('log_state') != 'sent' or row.get('dm_state') == 'pending' or
                                row.get('dm_state') != row.get('logged_dm_state')))):
                            await self.process(row)
                    except Exception as error:
                        self.report(f'恢复申请 #{row["id"]}', error)
            await self.refresh_panels()
        except Exception as error:
            self.report('后台同步', error)

    @worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()
        await asyncio.to_thread(store.initialize)

    @commands.Cog.listener()
    async def on_ready(self):
        # Re-scan after reconnect as role changes may have happened while offline.
        self.backfilled = False

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        cfg = await asyncio.to_thread(store.settings)
        if payload.channel_id != cfg['channel_id']:
            return
        if payload.message_id == await asyncio.to_thread(store.panel, 'entry', channel_id=payload.channel_id):
            self.entry_signature = None
        if payload.message_id == await asyncio.to_thread(store.panel, 'bottom', channel_id=payload.channel_id):
            self.panel_signature = None

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if store.auto_eligible(after) and not store.auto_eligible(before):
            await asyncio.to_thread(store.activate, after.id, after.guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if store.auto_eligible(member):
            await asyncio.to_thread(store.activate, member.id, member.guild.id)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if before.permissions.administrator != after.permissions.administrator:
            self.backfilled = False

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        if before.owner_id != after.owner_id:
            self.backfilled = False
