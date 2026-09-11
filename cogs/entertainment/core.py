import asyncio
import os

import discord
from discord.ext import commands

from .engine import ALIASES, Entertainment

# Prefix-free text aliases are deliberately distinct from the existing points cog.
TEXT_COMMANDS = {'奇米签到', '奇米我来惹', '我的饭粒', '奇米饭粒', '喂奇米', '摸摸奇米', '看看奇米', '今日运势', '今日奇米', '奇米运势', '娱乐帮助', '奇米帮助'}


class EntertainmentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game = Entertainment(os.getenv('KIMI_FUN_DB', 'data/entertainment.sqlite3'), 'discord')

    async def reply(self, ctx, command):
        if not ctx.guild:
            return await ctx.respond('请在服务器里找奇米玩捏♡', ephemeral=True)
        await ctx.defer()
        text = await asyncio.to_thread(self.game.handle, ctx.guild.id, ctx.author.id, command, ctx.interaction.id)
        await ctx.followup.send(text, allowed_mentions=discord.AllowedMentions.none())

    kimi = discord.SlashCommandGroup('奇米', '签到、饭粒、群宠和今日运势')

    @kimi.command(name='签到', description='每天来领饭粒捏♡')
    async def checkin(self, ctx):
        await self.reply(ctx, '奇米签到')

    @kimi.command(name='饭粒', description='看看你的小口袋')
    async def balance(self, ctx):
        await self.reply(ctx, '我的饭粒')

    @kimi.command(name='喂食', description='花3粒米喂养本服务器的奇米')
    async def feed(self, ctx):
        await self.reply(ctx, '喂奇米')

    @kimi.command(name='摸摸', description='摸摸本服务器的奇米')
    async def pet(self, ctx):
        await self.reply(ctx, '摸摸奇米')

    @kimi.command(name='群宠', description='看看大家一起养的奇米')
    async def status(self, ctx):
        await self.reply(ctx, '看看奇米')

    @kimi.command(name='运势', description='每天固定一签，纯属娱乐')
    async def fortune(self, ctx):
        await self.reply(ctx, '今日运势')

    @kimi.command(name='帮助', description='查看奇米游乐园玩法')
    async def help(self, ctx):
        await self.reply(ctx, '娱乐帮助')

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.author.bot or message.webhook_id:
            return
        text = message.content.strip()
        if text not in TEXT_COMMANDS:
            return
        result = await asyncio.to_thread(self.game.handle, message.guild.id, message.author.id, text, message.id)
        await message.channel.send(result, allowed_mentions=discord.AllowedMentions.none())
