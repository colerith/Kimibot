import asyncio
import discord
from . import makeup


class MakeupView(discord.ui.View):
    def __init__(self, owner):
        super().__init__(timeout=300)
        self.owner=owner
        self.kind='week'
        select=discord.ui.Select(placeholder='选择补签卡类型',options=[discord.SelectOption(label=f"{v['name']} · {v['price']} 蛋壳",value=k) for k,v in makeup.CARDS.items()])
        async def select_kind(interaction):
            self.kind=select.values[0]
            await interaction.response.defer()
            await self.refresh(interaction)
        select.callback=select_kind
        self.add_item(select)
    async def interaction_check(self, interaction):
        if interaction.user.id!=self.owner:
            await interaction.response.send_message('这不是你的补签卡面板。',ephemeral=True)
            return False
        return True
    async def embed(self,gid):
        state=await asyncio.to_thread(makeup.snapshot,self.owner,gid)
        history='、'.join(sorted(state['dates'],reverse=True)[:10]) or '暂无'
        lines=[f"{v['name']}：{v['price']} 蛋壳 · 库存 {state['inventory'].get(k,0)} 张" for k,v in makeup.CARDS.items()]
        return discord.Embed(title='📅 常驻补签卡',description='\n'.join(lines)+f"\n\n当前选择：**{makeup.CARDS[self.kind]['name']}**\n钱包余额：{state['balance']:g} 蛋壳\n本月已使用：**{state['used']}/3** 次（所有卡种合计）\n最近补签日期：{history}\n\n填写起始日期，连续补签1／3／7天，允许跨月。日期段中如有已签到日期则整张不消耗，请调整日期。\n按北京时间计算，不能补今天、未来、入服前或已签到日期。\n修复记录与连续天数，按当前基础签到标准补发每天奖励；不补随机事件、前十、活跃、月卡或节日加成。\n购买不计使用次数，库存不会按月清空；使用额度每月1日00:00刷新。",color=0xF4B942)
    async def refresh(self,interaction):
        await interaction.edit_original_response(embed=await self.embed(interaction.guild_id),view=self)
    @discord.ui.button(label='确认购买所选卡 ×1',style=discord.ButtonStyle.success,row=1)
    async def buy(self,button,interaction):
        await interaction.response.defer()
        try:
            result=await asyncio.to_thread(makeup.purchase,self.owner,interaction.guild_id,self.kind,str(interaction.id))
            message=result['message']
        except ValueError as error: message=str(error)
        await self.refresh(interaction)
        await interaction.followup.send(message,ephemeral=True)
    @discord.ui.button(label='使用所选卡',style=discord.ButtonStyle.primary,row=1)
    async def apply(self,button,interaction):
        await interaction.response.send_modal(MakeupModal(self,self.kind))


class MakeupModal(discord.ui.Modal):
    def __init__(self,panel,kind):
        super().__init__(title=f"使用{makeup.CARDS[kind]['name']}")
        self.panel,self.kind=panel,kind
        self.date=discord.ui.InputText(label='起始日期（北京时间，YYYY-MM-DD）',min_length=10,max_length=10,required=True)
        self.add_item(self.date)
    async def callback(self,interaction):
        if not await self.panel.interaction_check(interaction): return
        await interaction.response.defer()
        joined=interaction.user.joined_at
        joined_date=joined.astimezone(makeup.p.TZ_CN).date().isoformat() if joined else None
        try:
            result=await asyncio.to_thread(makeup.use,self.panel.owner,interaction.guild_id,self.kind,self.date.value.strip(),str(interaction.id),joined_date)
            text=result['message']
        except ValueError as error: text=str(error)
        await self.panel.refresh(interaction)
        await interaction.followup.send(text,ephemeral=True)


class MakeupShopButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='补签卡',emoji='📅',style=discord.ButtonStyle.primary,row=2)
    async def callback(self,interaction):
        await interaction.response.defer(ephemeral=True)
        view=MakeupView(interaction.user.id)
        await interaction.followup.send(embed=await view.embed(interaction.guild_id),view=view,ephemeral=True)
