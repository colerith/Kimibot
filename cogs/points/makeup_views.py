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
        return discord.Embed(title='📅 常驻补签卡',description='\n'.join(lines)+f"\n\n当前选择：**{makeup.CARDS[self.kind]['name']}**\n钱包余额：{state['balance']:g} 蛋壳\n本月已使用：**{state['used']}/3** 次（所有卡种合计）\n最近补签日期：{history}\n\n从漏签日期列表选择1／3／7天，可多选、不连续、跨月；选择后确认使用。\n按北京时间计算，不能补今天、未来、入服前或已签到日期。\n修复记录与连续天数，按当前基础签到标准补发每天奖励；不补随机事件、前十、活跃、月卡或节日加成。\n购买不计使用次数，库存不会按月清空；使用额度每月1日00:00刷新。",color=0xF4B942)
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
        await interaction.response.defer(ephemeral=True)
        joined=getattr(interaction.user, 'joined_at', None)
        joined_date=joined.astimezone(makeup.p.TZ_CN).date().isoformat() if joined else None
        try:
            dates=await asyncio.to_thread(makeup.missing_dates,self.owner,interaction.guild_id,joined_date)
            state=await asyncio.to_thread(makeup.snapshot,self.owner,interaction.guild_id)
            if state['inventory'].get(self.kind,0)<1:
                raise ValueError('该补签卡库存不足，请先购买。')
            if state['used']>=3:
                raise ValueError('本月已使用3次补签卡，请下个月再使用。')
            if len(dates)<makeup.CARDS[self.kind]['days']:
                raise ValueError('可补签日期不足以使用这张卡，请选择天数更少的卡。')
        except ValueError as error:
            await interaction.followup.send(str(error),ephemeral=True)
            return
        view=MakeupDatesView(self,self.kind,dates,joined_date,interaction.message)
        await interaction.followup.send(embed=view.embed(),view=view,ephemeral=True)


class MakeupDatesView(discord.ui.View):
    def __init__(self,panel,kind,dates,joined_date,parent_message):
        super().__init__(timeout=300)
        self.panel,self.kind=panel,kind
        self.dates,self.joined_date,self.parent_message=dates,joined_date,parent_message
        self.page=0
        self.selected=set()
        self.lock=asyncio.Lock()
        self.done=False
        self.rebuild()

    async def interaction_check(self,interaction):
        return await self.panel.interaction_check(interaction)

    def embed(self):
        chosen='、'.join(sorted(self.selected)) or '尚未选择'
        return discord.Embed(title=f"📅 使用{makeup.CARDS[self.kind]['name']}",description=f"仅显示入服后、今天之前的漏签日期。\n可跨月、不连续多选，翻页保留选择。\n请选择恰好 **{makeup.CARDS[self.kind]['days']} 天**，确认后扣1张卡、计1次使用并补发基础奖励。\n\n已选：{chosen}\n第 {self.page+1}/{max(1,(len(self.dates)+24)//25)} 页",color=0xF4B942)

    def rebuild(self):
        self.clear_items()
        page_dates=self.dates[self.page*25:(self.page+1)*25]
        if page_dates:
            select=discord.ui.Select(placeholder='选择漏签日期（可多选）',min_values=0,max_values=min(len(page_dates),makeup.CARDS[self.kind]['days']),options=[discord.SelectOption(label=day,value=day,default=day in self.selected) for day in page_dates],row=0)
            async def choose(interaction):
                async with self.lock:
                    if self.done:
                        await interaction.response.send_message('本次补签已完成。',ephemeral=True)
                        return
                    proposed=(self.selected-set(page_dates))|set(select.values)
                    if len(proposed)>makeup.CARDS[self.kind]['days']:
                        await interaction.response.send_message('跨页选择合计超出卡片天数，请先取消部分日期。',ephemeral=True)
                        return
                    self.selected=proposed
                    self.rebuild()
                    await interaction.response.edit_message(embed=self.embed(),view=self)
            select.callback=choose
            self.add_item(select)
        for label,delta in [('上一页',-1),('下一页',1)]:
            button=discord.ui.Button(label=label,row=1,disabled=self.page+delta<0 or (self.page+delta)*25>=len(self.dates))
            async def turn(interaction,step=delta):
                async with self.lock:
                    if self.done:
                        await interaction.response.send_message('本次补签已完成。',ephemeral=True)
                        return
                    self.page=max(0,min((len(self.dates)-1)//25,self.page+step))
                    self.rebuild()
                    await interaction.response.edit_message(embed=self.embed(),view=self)
            button.callback=turn
            self.add_item(button)
        confirm=discord.ui.Button(label='确认补签并领取奖励',style=discord.ButtonStyle.success,row=2,disabled=len(self.selected)!=makeup.CARDS[self.kind]['days'])
        confirm.callback=self.confirm
        self.add_item(confirm)
        clear=discord.ui.Button(label='清空选择',row=2)
        async def clear_selection(interaction):
            async with self.lock:
                if self.done:
                    await interaction.response.send_message('本次补签已完成。',ephemeral=True)
                    return
                self.selected.clear()
                self.rebuild()
                await interaction.response.edit_message(embed=self.embed(),view=self)
        clear.callback=clear_selection
        self.add_item(clear)

    async def confirm(self,interaction):
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                await interaction.followup.send('本次补签已完成，请勿重复提交。',ephemeral=True)
                return
            try:
                result=await asyncio.to_thread(makeup.use,self.panel.owner,interaction.guild_id,self.kind,sorted(self.selected),str(interaction.id),self.joined_date)
            except ValueError as error:
                await interaction.followup.send(str(error),ephemeral=True)
                return
            self.done=True
            await interaction.edit_original_response(embed=discord.Embed(title='✅ 补签完成',description=result['message'],color=0x57F287),view=None)
            try:
                await self.parent_message.edit(embed=await self.panel.embed(interaction.guild_id),view=self.panel)
            except discord.HTTPException:
                pass  # Settlement is committed even if the old panel was deleted.


class MakeupShopButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='补签卡',emoji='📅',style=discord.ButtonStyle.primary,row=2)
    async def callback(self,interaction):
        await interaction.response.defer(ephemeral=True)
        view=MakeupView(interaction.user.id)
        await interaction.followup.send(embed=await view.embed(interaction.guild_id),view=view,ephemeral=True)
