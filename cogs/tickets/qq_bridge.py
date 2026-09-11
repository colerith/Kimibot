"""Optional same-host QQ mailbox consumer. Enable with config.json; no HTTP server."""
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

import discord
from discord.ext import commands, tasks

from .bridge_store import Mailbox
from .utils import ApprovedTicketArchiveView, archive_edit_lock

log = logging.getLogger(__name__)


def archive_info(message, bot_id):
    if message.author.id != bot_id or not message.embeds:
        return None
    embed = message.embeds[0]
    title = embed.title or ''
    if not title.startswith(('✅ 已过审工单 · #', '🚫 未过审工单 · #', '⏰ 超时工单 · #')):
        return None
    fields = {f.name: str(f.value).strip('` ') for f in embed.fields}
    ticket = fields.get('🧾 工单编号', '')
    if not re.fullmatch(r'[1-9][0-9]{5}', ticket):
        return None
    return ticket, title.startswith('✅ 已过审工单 · #'), fields


def update_embed(embed, row):
    fields = {f.name: str(f.value).strip('` ') for f in embed.fields}
    current = fields.get('🐧 QQ 号码', '')
    if current not in ('', '尚未录入', str(row['qq'])):
        raise ValueError('归档已有其他QQ，保留人工记录')
    result = embed.copy()
    changes = {
        '🐧 QQ 号码': f"`{row['qq']}`",
        '🔗 QQ 同步来源': f"QQ群 `{row['gid']}` 的入群申请；工单号由申请人填写",
    }
    if row['joined']:
        changes['💬 加群状态'] = f"已观察到入群 · <t:{int(row['joined'])}:f>"
    elif not fields.get('💬 加群状态', '').startswith('已观察到入群'):
        changes['💬 加群状态'] = '已收到入群申请，尚未核实入群'
    for name, value in changes.items():
        for index, field in enumerate(result.fields):
            if field.name == name:
                result.set_field_at(index, name=name, value=value, inline=False)
                break
        else:
            result.add_field(name=name, value=value, inline=False)
    return result


class QQBridge(commands.Cog):
    def __init__(self, bot, config_path):
        self.bot = bot
        path = Path(config_path)
        config = json.loads(path.read_text(encoding='utf-8'))
        self.guild_id = int(config['discord_guild_id'])
        self.channel_id = int(config['archive_channel_id'])
        self.group_ids = {int(v) for v in config['qq_group_ids']}
        if not self.group_ids or self.guild_id <= 0 or self.channel_id <= 0:
            raise ValueError('QQ bridge configuration is incomplete')
        self.box = Mailbox(path.parent / 'bridge.sqlite3')
        self.initialized = False
        self.cursor = 0

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.work.is_running():
            self.work.start()

    def cog_unload(self):
        self.work.cancel()

    async def scan(self, channel):
        if not self.initialized:
            # Rebuild fully before accepting a numeric ticket match (detect historical collisions).
            with self.box.connect() as db:
                db.execute('DELETE FROM archives')
            self.cursor = 0
        after = discord.Object(id=self.cursor) if self.cursor else None
        async for message in channel.history(limit=None, oldest_first=True, after=after):
            info = archive_info(message, self.bot.user.id)
            if info:
                self.box.index(message.id, info[0], info[1])
            self.cursor = message.id
            await asyncio.sleep(0)
        if not self.initialized:
            log.info('QQ bridge archive index ready')
        self.initialized = True

    async def process(self, channel, row):
        if row['gid'] not in self.group_ids:
            return 'conflict', 'QQ群不在接收白名单中'
        if time.time() - row['requested'] > 7 * 86400:
            return 'conflict', '请求已超过7天，请人工核对'
        matches = self.box.matches(row['ticket'])
        if len(matches) > 1:
            return 'conflict', '工单编号重复，请人工核对Discord用户'
        active_matches = [active for active in channel.guild.text_channels if re.search(
            r'(?:^|\|)\s*工单ID:\s*' + re.escape(row['ticket']) + r'\s*(?:\||$)', active.topic or '')]
        if len(active_matches) > 1:
            return 'conflict', '多个现存工单使用相同编号'
        if active_matches:
            if matches:
                return 'pending', '同编号原工单仍存在，等待归档清理后再核对'
            active = await self.bot.fetch_channel(active_matches[0].id)
            info = dict(part.strip().split(': ', 1) for part in (active.topic or '').split('|') if ': ' in part.strip())
            if info.get('工单ID') != row['ticket'] or info.get('审核状态') != '已过审' or info.get('测试模式') == '是':
                return 'pending', '工单尚未过审或为测试工单，不自动批准'
            if not self.box.reserve(row['ticket'], row['qq']):
                return 'conflict', '该工单已被其他QQ申请占用，请人工核对'
            return 'ready', '现存工单已过审，可批准入群；等待归档后同步卡片'
        if not matches:
            if time.time() - row['requested'] > 7 * 86400:
                return 'conflict', '7天内未找到归档，请人工核对'
            return 'pending', '等待工单归档或核对编号'
        match = matches[0]
        if not match['approved']:
            return 'conflict', '不是已过审工单'
        async with archive_edit_lock(match['message']):
            try:
                message = await channel.fetch_message(match['message'])
            except discord.NotFound:
                return 'conflict', '归档消息已删除，请人工处理'
            info = archive_info(message, self.bot.user.id)
            if not info or info[0] != row['ticket'] or not info[1]:
                return 'conflict', '归档消息内容已改变'
            try:
                embed = update_embed(message.embeds[0], row)
            except ValueError as exc:
                return 'conflict', str(exc)
            if not self.box.reserve(row['ticket'], row['qq']):
                return 'conflict', '该工单已被其他QQ申请占用，请人工核对'
            if embed.to_dict() != message.embeds[0].to_dict():
                await message.edit(embed=embed, view=ApprovedTicketArchiveView(), allowed_mentions=discord.AllowedMentions.none())
        return 'done', '已同步归档QQ' + ('及入群通知' if row['joined'] else '；等待入群通知')

    @tasks.loop(seconds=15)
    async def work(self):
        try:
            channel = self.bot.get_channel(self.channel_id) or await self.bot.fetch_channel(self.channel_id)
            if not isinstance(channel, discord.TextChannel) or channel.guild.id != self.guild_id:
                raise ValueError('归档频道类型或服务器ID不匹配')
            await self.scan(channel)
            for row in self.box.pending():
                try:
                    state, note = await self.process(channel, row)
                except Exception:
                    log.exception('QQ bridge request failed; will retry')
                    state, note = 'pending', 'Discord或存储暂时失败，等待重试'
                self.box.result(row, state, note)
                if state == 'conflict':
                    log.warning('QQ bridge manual review: ticket=%s reason=%s', row['ticket'], note)
                elif state == 'done':
                    log.info('QQ bridge synced: ticket=%s', row['ticket'])
                await asyncio.sleep(1)
        except Exception:
            log.exception('QQ bridge unavailable; next cycle will retry')


def setup_bridge(bot):
    path = os.getenv('QIMI_BRIDGE_CONFIG', '/var/lib/qimi-bridge/config.json')
    if Path(path).is_file():
        bot.add_cog(QQBridge(bot, path))
    else:
        log.info('QQ bridge disabled (no config file)')
