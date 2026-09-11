import asyncio
import os

import discord
from discord.ext import commands

from .engine import Entertainment

# Prefix-free text aliases are deliberately distinct from the existing points cog.
TEXT_COMMANDS = {'喂奇米', '摸摸奇米', '看看奇米', '今日运势', '今日奇米', '奇米运势', '娱乐帮助', '奇米帮助'}


def make_panel(text, command):
    title, _, body = text.partition('\n')
    color = 0xB49CFF if command in {'今日运势', '今日奇米', '奇米运势'} else 0xF2C879
    embed = discord.Embed(title=title, description=body, color=color)
    embed.set_footer(text='奇米游乐园 ♡ · 群宠由本服务器共同养育 · 每日签语北京时间零点刷新')
    return embed


class EntertainmentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.game = Entertainment(os.getenv('KIMI_FUN_DB', 'data/entertainment.sqlite3'), 'discord')

    async def reply(self, ctx, command):
        if not ctx.guild:
            return await ctx.respond('请在服务器里找奇米玩捏♡', ephemeral=True)
        await ctx.defer()
        text = await asyncio.to_thread(self.game.handle, ctx.guild.id, ctx.author.id, command, ctx.interaction.id)
        if text is not None:
            await ctx.followup.send(embed=make_panel(text, command), allowed_mentions=discord.AllowedMentions.none())

    kimi = discord.SlashCommandGroup('奇米', '蛋壳喂食、群宠和今日运势')

    @kimi.command(name='喂食', description='花3蛋壳喂养本服务器的奇米')
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
        if result is not None:
            await message.channel.send(embed=make_panel(result, text), allowed_mentions=discord.AllowedMentions.none())
