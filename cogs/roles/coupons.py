"""Monthly two-star vouchers with durable delivery receipts and explicit confirmation."""
import asyncio
import math
import uuid

import discord
from cogs.points import storage as points
from . import storage as roles


def recover_coupon_roles(user_id, guild_id):
    record = points.get_monthly_coupon_record(user_id, guild_id)
    ids = {int(rid) for rid in record['redemptions'].values() if rid}
    if ids:
        roles.add_many_to_collection(user_id, ids)
    return record


def initialize_monthly_coupons():
    report = points.backfill_monthly_coupons()
    with points._points_connection() as connection:
        rows = list(connection.execute('SELECT user_key, data FROM point_users'))
    for row in rows:
        rec = points._json_load(row['data'], {})
        ids = {int(rid) for rid in rec.get('monthly_coupon_redemptions', {}).values() if rid}
        if ids:
            roles.add_many_to_collection(int(row['user_key'].split(':')[-1]), ids)
    return report


def coupon_options(user_id, guild_id, server_role_ids, member_role_ids=()):
    record = recover_coupon_roles(user_id, guild_id)
    data = roles.load_role_data()
    pool = set(data.get('lottery_roles', [])) & set(server_role_ids)
    pool = {rid for rid in pool if roles.get_lottery_role_rarity(rid, data) == roles.RARITY_RARE}
    owned = set(roles.get_user_collection(user_id)) | set(roles.get_user_redeem_ownership(user_id)) | set(member_role_ids)
    return record, pool, pool - owned


def redeem_coupon(user_id, guild_id, request_id, role_id, server_role_ids, member_role_ids=()):
    # Serialize with collection writes; receipts survive interruption between debit and delivery.
    with roles._ownership_lock:
        record, pool, missing = coupon_options(user_id, guild_id, server_role_ids, member_role_ids)
        if request_id in record['redemptions']:
            return {'success': True, 'duplicate': True, 'role_id': record['redemptions'][request_id]}
        if not pool:
            return {'success': False, 'reason': 'empty_pool'}
        if role_id and role_id not in missing:
            return {'success': False, 'reason': 'unavailable'}
        if not role_id and missing:
            return {'success': False, 'reason': 'not_complete'}
        result = points.consume_monthly_coupon(user_id, guild_id, request_id, role_id)
        if result.get('success') and role_id:
            roles.add_to_collection(user_id, role_id)
        return result


class CouponSelect(discord.ui.Select):
    def __init__(self, panel):
        if panel.missing:
            options = [discord.SelectOption(label=panel.guild.get_role(rid).name[:100], value=str(rid),
                       default=panel.selected == rid) for rid in panel.missing[panel.page*25:(panel.page+1)*25]]
        else:
            options = [discord.SelectOption(label='全部二星已拥有：兑换 10 蛋壳', value='0', default=panel.selected == 0)]
        super().__init__(placeholder='① 下拉选择兑换目标', options=options, row=0)

    async def callback(self, interaction):
        panel = self.view
        panel.selected = int(self.values[0])
        panel.confirmed = None
        panel.rebuild()
        await interaction.response.edit_message(embed=panel.embed(), view=panel)


class CouponView(discord.ui.View):
    def __init__(self, guild, user_id, record, pool, missing):
        super().__init__(timeout=600)
        self.guild, self.user_id = guild, user_id
        self.balance = record['balance']
        self.pool = pool
        self.missing = sorted(missing, key=lambda rid: (guild.get_role(rid).position, rid), reverse=True)
        self.page = 0
        self.selected = self.confirmed = None
        self.request_id = uuid.uuid4().hex
        self.rebuild()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message('这不是你的二星兑换券面板。', ephemeral=True)
            return False
        return True

    def rebuild(self):
        for item in list(self.children):
            if isinstance(item, CouponSelect):
                self.remove_item(item)
        if self.pool and self.balance > 0:
            self.add_item(CouponSelect(self))
        self.confirm.disabled = self.selected is None
        self.finish.disabled = self.confirmed is None
        self.pages = max(1, math.ceil(len(self.missing)/25))
        self.previous.disabled = self.page == 0
        self.following.disabled = self.page == self.pages - 1

    def embed(self):
        target = '尚未选择' if self.selected is None else '10 蛋壳' if self.selected == 0 else f'<@&{self.selected}>'
        message = '抽奖池目前没有有效的二星身份组，兑换券保留。' if not self.pool else '只可兑换抽奖池中未拥有的二星身份组；全部拥有时可用一张券换 10 蛋壳。'
        return discord.Embed(title='🎟️ 月卡二星兑换券', color=0xF5B041, description=(
            f'剩余 **{self.balance}** 张 · 第 {self.page+1}/{self.pages} 页\n{message}\n\n'
            f'当前目标：{target}\n'
            '① 下拉选择 → ② 确认选择 → ③ 下一步，完成兑换\n'
            '前两步不会消耗兑换券；更换选择需重新确认。\n'
            + ('✅ 已确认，请核对后点击「下一步，完成兑换」。' if self.confirmed is not None else '请先选择并确认。')))

    @discord.ui.button(label='② 确认选择', style=discord.ButtonStyle.primary, row=1, disabled=True)
    async def confirm(self, button, interaction):
        if self.selected is None:
            return await interaction.response.send_message('请先选择兑换目标。', ephemeral=True)
        self.confirmed = self.selected
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label='③ 下一步，完成兑换', style=discord.ButtonStyle.success, row=1, disabled=True)
    async def finish(self, button, interaction):
        if self.confirmed is None or self.confirmed != self.selected:
            return await interaction.response.send_message('请先确认当前选择。', ephemeral=True)
        target = self.confirmed
        await interaction.response.defer()
        try:
            result = await asyncio.to_thread(redeem_coupon, self.user_id, self.guild.id, self.request_id, target,
                                             [r.id for r in self.guild.roles], [r.id for r in interaction.user.roles])
        except Exception as error:
            print(f"[月卡二星券] 兑换中断 request_id={self.request_id} error={error!r}")
            return await interaction.followup.send('兑换处理暂时中断，请再次点击下一步；已记录的兑换不会重复扣券。', ephemeral=True)
        if not result.get('success'):
            messages = {'no_coupon': '兑换券不足。', 'empty_pool': '二星池为空，兑换券已保留。',
                        'unavailable': '该身份组已拥有或不再属于二星奖池，请重新打开选择。',
                        'not_complete': '仍有未拥有的二星身份组，不能兑换蛋壳。'}
            return await interaction.followup.send(messages.get(result.get('reason'), '兑换失败，请重试。'), ephemeral=True)
        from .views import _settle_collection_rewards
        await asyncio.to_thread(_settle_collection_rewards, self.user_id, self.guild.id,
                                set(roles.get_user_collection(self.user_id)), roles.load_role_data())
        reward = f'<@&{result["role_id"]}>（已加入永久收藏，可前往换装穿戴）' if result['role_id'] else '10 蛋壳'
        await interaction.edit_original_response(embed=discord.Embed(title='✅ 兑换完成', description=f'已兑换：{reward}', color=0x57F287), view=None)

    @discord.ui.button(label='上一页', row=2)
    async def previous(self, button, interaction):
        self.page = max(0, self.page - 1)
        self.selected = self.confirmed = None
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label='下一页', row=2)
    async def following(self, button, interaction):
        self.page = min(self.pages - 1, self.page + 1)
        self.selected = self.confirmed = None
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)


class CouponShopButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='二星兑换券', emoji='🎟️', style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        record, pool, missing = await asyncio.to_thread(coupon_options, interaction.user.id, interaction.guild_id,
            [r.id for r in interaction.guild.roles], [r.id for r in interaction.user.roles])
        panel = CouponView(interaction.guild, interaction.user.id, record, pool, missing)
        await interaction.followup.send(embed=panel.embed(), view=panel, ephemeral=True)
