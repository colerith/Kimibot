import asyncio
import logging
import time
from datetime import datetime
import discord
from discord.ext import commands, tasks
from . import storage as store

log = logging.getLogger(__name__)
PANEL_FOOTER = '定期邀请面板 · 每周一 00:00 开放 · 周六 00:00 失效 · 北京时间'


def public_panel(state):
    invite = store.active_invite(state)
    embed = discord.Embed(title=state['title'], description=state['copy'], color=0xB8C9C1)
    view = discord.ui.View(timeout=None)
    if invite:
        expiry = datetime.fromisoformat(invite['expires']).strftime('%Y-%m-%d %H:%M')
        embed.add_field(name='本周邀请', value=f"{invite['url']}\n**截止：{expiry} 北京时间**", inline=False)
        view.add_item(discord.ui.Button(label='加入社区', style=discord.ButtonStyle.link, url=invite['url']))
    else:
        embed.add_field(name='当前状态', value='暂未开放，开放时会自动更新本面板。', inline=False)
    embed.set_footer(text=PANEL_FOOTER)
    return embed, view


class WeeklyInviteCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.api_lock = asyncio.Lock()
        self.next_request = 0.0
        self.signature = None

    async def api(self, operation, *args, **kwargs):
        async with self.api_lock:
            await asyncio.sleep(max(0, self.next_request-time.monotonic()))
            try:
                return await operation(*args, **kwargs)
            except discord.HTTPException as error:
                if error.status == 429:
                    self.next_request = time.monotonic() + max(30, float(getattr(error.response, 'headers', {}).get('Retry-After', 30)))
                raise
            finally:
                self.next_request = max(self.next_request, time.monotonic()+1)

    async def channel(self):
        return self.bot.get_channel(store.CHANNEL_ID) or await self.api(self.bot.fetch_channel, store.CHANNEL_ID)

    async def recover_attempt(self, channel, state):
        attempt = state.get('attempt')
        if not attempt:
            return
        # Discover a successful request whose response/DB commit was interrupted.
        # If invite listing fails, do not create a second unknown link.
        invites = await self.api(channel.invites)
        for invite in invites:
            expires = getattr(invite, 'expires_at', None)
            if (getattr(invite.inviter, 'id', None) == self.bot.user.id and invite.created_at and expires and
                invite.created_at >= datetime.fromisoformat(attempt['started']) and
                abs((expires-datetime.fromisoformat(attempt['expires'])).total_seconds()) < 5):
                state['invite'] = dict(code=invite.code, url=invite.url, expires=attempt['expires'], week=attempt['week'])
                break
        state['attempt'] = None
        await asyncio.to_thread(store.save, state)

    async def sync_locked(self, state, *, force=False):
        channel = await self.channel()
        await self.recover_attempt(channel, state)
        await self.recover_panel(channel, state)
        if store.creation_allowed(state) and not store.active_invite(state):
            async def create():
                at = store.now()
                monday, end = store.window(at)
                if not store.creation_allowed(state, at):
                    return None
                age = int((end-at).total_seconds())
                if age < 1:
                    return None
                state['attempt'] = dict(started=at.isoformat(), expires=end.isoformat(), week=monday.date().isoformat())
                await asyncio.to_thread(store.save, state)
                return await channel.create_invite(max_age=age, max_uses=0, temporary=False, unique=True,
                    reason=f'weekly-invite:{monday.date().isoformat()}')
            invite = await self.api(create)
            if invite:
                attempt = state['attempt']
                state['invite'] = dict(code=invite.code, url=invite.url, expires=attempt['expires'], week=attempt['week'])
                state['attempt'] = None
                await asyncio.to_thread(store.save, state)
        if not state['enabled']:
            return
        embed, view = public_panel(state)
        signature = str(embed.to_dict())
        if not force and self.signature == signature and state.get('message_id'):
            return
        message = None
        if state.get('message_id'):
            try:
                message = await self.api(channel.fetch_message, state['message_id'])
            except discord.NotFound:
                pass
        if message:
            await self.api(message.edit, embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        else:
            state['panel_attempt'] = store.now().isoformat()
            await asyncio.to_thread(store.save, state)
            message = await self.api(channel.send, embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            state['message_id'] = message.id
            state['panel_attempt'] = None
            await asyncio.to_thread(store.save, state)
        self.signature = signature

    async def recover_panel(self, channel, state):
        if not state.get('panel_attempt'):
            return
        async def find():
            async for message in channel.history(limit=None, after=datetime.fromisoformat(state['panel_attempt'])):
                if message.author.id == self.bot.user.id and any(e.footer.text == PANEL_FOOTER for e in message.embeds):
                    return message
        message = await self.api(find)
        if message:
            state['message_id'] = message.id
        state['panel_attempt'] = None
        await asyncio.to_thread(store.save, state)

    async def manage(self, *, changes=None, send=False, revoke=False):
        async with self.lock:
            state = await asyncio.to_thread(store.load)
            if changes:
                state.update(changes)
                await asyncio.to_thread(store.save, state)
            if revoke:
                state['enabled'] = False
                await asyncio.to_thread(store.save, state)
                await self.revoke_locked(state)
            else:
                if send:
                    state['enabled'] = True
                    await asyncio.to_thread(store.save, state)
                await self.sync_locked(state, force=True)

    async def revoke_locked(self, state):
        channel = await self.channel()
        await self.recover_attempt(channel, state)
        await self.recover_panel(channel, state)
        invite = store.active_invite(state)
        if invite:
            try:
                remote = await self.api(self.bot.fetch_invite, invite['code'])
                await self.api(remote.delete, reason='管理员撤销每周邀请')
            except discord.NotFound:
                pass
        state['invite'] = None
        await asyncio.to_thread(store.save, state)
        if state.get('message_id'):
            try:
                await self.api(channel.get_partial_message(state['message_id']).delete)
            except discord.NotFound:
                pass
            state['message_id'] = None
            await asyncio.to_thread(store.save, state)
        self.signature = None

    @tasks.loop(seconds=30)
    async def worker(self):
        try:
            async with self.lock:
                state = await asyncio.to_thread(store.load)
                if not state['enabled']:
                    if state.get('invite') or state.get('attempt') or state.get('message_id') or state.get('panel_attempt'):
                        await self.revoke_locked(state)
                else:
                    await self.sync_locked(state)
        except Exception:
            log.exception('每周邀请同步失败，将在下一轮重试')

    @worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.worker.is_running():
            self.worker.start()

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.channel_id == store.CHANNEL_ID:
            self.signature = None

    def cog_unload(self):
        self.worker.cancel()
