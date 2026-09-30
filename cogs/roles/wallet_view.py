import asyncio
from datetime import timedelta

import discord

from cogs.points.storage import format_shells
from cogs.points.wallet import get_report, totals, festival_bonus

FORTUNE_CHANNEL = 'https://discord.com/channels/1397629012292931726/1439091267773530152'
PAGE_SIZE = 8
SOURCE_NAMES = {
    'sign_in': '每日签到', 'kimi_praise': '关键词打卡',
    'daily_forum_post': '社区发帖', 'forum_post': '社区发帖',
    'daily_task_bonus': '每日任务奖励', 'daily_task_bonus_revoke': '任务奖励扣回',
    'kimi_fortune_event': '运势奇遇', 'kimi_status_event': '群宠奇遇',
    'kimi_feed': '喂养奇米', 'monthly_card_daily': '月卡每日领取',
    'monthly_card_purchase': '购买月卡', 'monthly_coupon_exchange': '月卡券兑换',
    'role_lottery': '身份组抽奖', 'role_lottery_refund': '抽奖退款',
    'role_lottery_shell_reward': '抽奖蛋壳奖励', 'role_redeem': '身份组兑换',
    'role_redeem_refund': '兑换退款', 'role_collection_reward': '图鉴奖励',
    'acceleration_card': '加速卡', 'egg_qa_reply': '问答回复', 'egg_qa_self_reply': '问答自答',
    'submission_recommendation': '安利投稿', 'submission_repo': 'Repo 投稿',
    'submission_delete_penalty': '删除投稿扣回', 'submission_useful_tier': '投稿有用奖励',
}


def source_name(source):
    if source in SOURCE_NAMES:
        return SOURCE_NAMES[source]
    if source.startswith('submission_comment_'):
        return '投稿评论'
    if source.startswith('submission_reply_'):
        return '投稿回复'
    return '其他收支'


def summary_line(values):
    return (f"收入 **+{format_shells(values['income'])}**　支出 **−{format_shells(values['expense'])}**\n"
            f"净变化 **{values['net']:+.1f}** 蛋壳")


def build_wallet_embed(user, report, mode='overview', page=0):
    today = report['today']
    embed = discord.Embed(title='🥚 小蛋的钱包', color=0xF2C879,
                          description=f"### {format_shells(report['balance'])} 蛋壳\n"
                                      f"连续签到 **{report['streak']}** 天 · 今日有效发言 **{report['messages']}** 条")
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)
    monthly = report['monthly']
    if monthly.get('active'):
        embed.description += f"\n📅 月卡收益 **×{monthly['reward_multiplier']:g}** · 剩余 **{monthly['remaining_days']:g}** 天"
    else:
        embed.description += '\n📅 月卡未启用'
    if report.get('festival'):
        festival = report['festival']
        embed.description += f"\n🎉 {discord.utils.escape_markdown(festival['name'])} · 活动收益 **×{festival['multiplier']:g}**"
    if mode in {'overview', 'fortune'}:
        embed.add_field(name='🔮 今日签文', value=report['fortune'] or
                        f'今天还没有签文，去[奇米游乐频道]({FORTUNE_CHANNEL})发送 **/奇米 运势**，找奇米抽一签吧！', inline=False)
    if mode != 'fortune':
        selected_day = today.isoformat() if mode in {'overview', 'today'} else mode
        rows = report['rows'] if mode == 'seven' else [row for row in report['rows'] if row['day'] == selected_day]
        label = '近七天' if mode == 'seven' else ('今日' if selected_day == today.isoformat() else selected_day)
        values = totals(rows)
        embed.add_field(name=f'🧾 {label}收支', value=summary_line(values), inline=False)
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(0, page), pages-1)
        lines = []
        for row in rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE]:
            stamp = row['moment'].strftime('%m/%d %H:%M' if mode == 'seven' else '%H:%M')
            bonus = festival_bonus(row)
            detail = f" · 含节日 +{format_shells(bonus)}" if bonus else ''
            lines.append(f"`{stamp}` {source_name(row['source'])} **{row['amount']:+.1f}**{detail}")
        embed.add_field(name=f'收支明细 · {page+1}/{pages} 页', value='\n'.join(lines) or '这段时间还没有蛋壳收支，口袋安安静静的。', inline=False)
        if values['festival_bonus']:
            embed.add_field(name='🎉 节日福利已入账', value=f"本次筛选含节日额外奖励 **+{format_shells(values['festival_bonus'])}** 蛋壳，已计入余额和上方收支。", inline=False)
    # Period summaries always remain the last fields, including in fortune-only mode.
    embed.add_field(name='📊 本周 · 周一至今', value=summary_line(report['week']), inline=True)
    embed.add_field(name='🗓️ 本月 · 月初至今', value=summary_line(report['month']), inline=True)
    embed.set_footer(text=f'{today:%Y-%m-%d} · 北京时间 · 收支按实际入账统计（已含加成）· 下方筛选近七天')
    return embed


class WalletFilter(discord.ui.Select):
    def __init__(self, today, selected):
        choices = [('overview', '今日总览 · 签文与收支'), ('fortune', '只看今日签文'),
                   ('today', '今日蛋壳收支'), ('seven', '近七天全部收支')]
        choices += [((today-timedelta(days=offset)).isoformat(), (today-timedelta(days=offset)).strftime('%m月%d日收支')) for offset in range(1, 7)]
        super().__init__(placeholder='筛选签文或近七天收支', row=0,
                         options=[discord.SelectOption(label=label, value=value, default=value == selected) for value, label in choices])

    async def callback(self, interaction):
        await interaction.response.defer()
        await self.view.render(interaction, mode=self.values[0], page=0)


class WalletView(discord.ui.View):
    def __init__(self, user, guild_id):
        super().__init__(timeout=600)
        self.user, self.guild_id = user, guild_id
        self.mode, self.page = 'overview', 0
        self.lock = asyncio.Lock()

    async def interaction_check(self, interaction):
        if interaction.user.id == self.user.id:
            return True
        await interaction.response.send_message('请打开自己的蛋壳余额面板。', ephemeral=True)
        return False

    async def prepare(self):
        report = await asyncio.to_thread(get_report, self.user.id, self.guild_id)
        valid_days = {(report['today']-timedelta(days=offset)).isoformat() for offset in range(7)}
        if self.mode not in {'overview', 'fortune', 'today', 'seven'} and self.mode not in valid_days:
            self.mode, self.page = 'today', 0
        selected_day = report['today'].isoformat() if self.mode in {'overview', 'today'} else self.mode
        rows = report['rows'] if self.mode == 'seven' else [row for row in report['rows'] if row['day'] == selected_day]
        pages = max(1, (len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
        self.page = min(max(0, self.page), pages-1)
        self.previous.disabled = self.mode == 'fortune' or self.page == 0
        self.next_page.disabled = self.mode == 'fortune' or self.page == pages-1
        for item in list(self.children):
            if isinstance(item, WalletFilter):
                self.remove_item(item)
        self.add_item(WalletFilter(report['today'], self.mode))
        return build_wallet_embed(self.user, report, self.mode, self.page)

    async def render(self, interaction, *, mode=None, page=None, step=0):
        async with self.lock:
            if mode is not None:
                self.mode = mode
            self.page = page if page is not None else self.page + step
            embed = await self.prepare()
            await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label='上一页', style=discord.ButtonStyle.secondary, row=1)
    async def previous(self, button, interaction):
        await interaction.response.defer()
        await self.render(interaction, step=-1)

    @discord.ui.button(label='下一页', style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, button, interaction):
        await interaction.response.defer()
        await self.render(interaction, step=1)

    @discord.ui.button(label='刷新', emoji='🔄', style=discord.ButtonStyle.primary, row=1)
    async def refresh(self, button, interaction):
        await interaction.response.defer()
        await self.render(interaction)
