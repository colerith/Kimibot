import asyncio
import logging
import discord
from . import makeup


class MakeupView(discord.ui.View):
    def __init__(self, owner, joined_date=None):
        super().__init__(timeout=900, disable_on_timeout=True)
        self.owner=owner
        self.joined_date=joined_date
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
        lines=[f"{v['name']}：{v['price']} 蛋壳 · 库存 {state['inventory'].get(k,0)} 张 · 已开卡余量 {state.get('remaining',{}).get(k,0)} 天" for k,v in makeup.CARDS.items()]
        try:
            dates=await asyncio.to_thread(makeup.missing_dates,self.owner,gid,self.joined_date)
            missing=f'累计漏签 **{len(dates)} 天**；最近日期：'+('、'.join(dates[:10]) or '无')+'。点击【查看漏签日期】查看全部。'
        except ValueError as error:
            missing=str(error)
        return discord.Embed(title='📅 常驻补签卡',description='\n'.join(lines)+f"\n\n{missing}\n\n当前选择：**{makeup.CARDS[self.kind]['name']}**\n钱包余额：{state['balance']:g} 蛋壳\n本月已使用：**{state['used']}/3** 次（所有卡种合计）\n最近补签日期：{history}\n\n从漏签日期列表选择 1 天至当前卡片剩余天数，可多选、不连续、跨月；选择后确认使用，剩余天数永久保留；优先用完已开卡，再使用整卡。\n按北京时间计算，仅限最近三个月且不早于 2026-08-06 上线日及入服日；不能补今天、未来或已签到日期。\n修复记录与连续天数，按当前基础签到标准补发每天奖励；不补随机事件、前十、活跃、月卡或节日加成。\n购买不计使用次数，库存不会按月清空；使用额度每月1日00:00刷新。",color=0xF4B942)
    async def refresh(self,interaction):
        await interaction.edit_original_response(embed=await self.embed(interaction.guild_id),view=self)
    @discord.ui.button(label='查看漏签日期',style=discord.ButtonStyle.secondary,row=1)
    async def missing(self,button,interaction):
        await show_missing_dates(interaction)

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
            if not makeup.available_days(state,self.kind):
                raise ValueError('该补签卡库存不足，请先购买。')
            if state['used']>=3:
                raise ValueError('本月已使用3次补签卡，请下个月再使用。')
            if not dates:
                raise ValueError('目前没有可补签日期。')
        except ValueError as error:
            await interaction.followup.send(str(error),ephemeral=True)
            return
        view=MakeupDatesView(self,self.kind,dates,joined_date,interaction.message,makeup.available_days(state,self.kind))
        await interaction.followup.send(embed=view.embed(),view=view,ephemeral=True)


class MakeupDatesView(discord.ui.View):
    def __init__(self,panel,kind,dates,joined_date,parent_message,capacity=None):
        super().__init__(timeout=900, disable_on_timeout=True)
        self.panel,self.kind=panel,kind
        self.capacity=capacity if capacity is not None else makeup.CARDS[kind]['days']
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
        return discord.Embed(title=f"📅 使用{makeup.CARDS[self.kind]['name']}",description=f"仅显示最近三个月内、2026-08-06 上线及入服后、今天之前的漏签日期。\n可跨月、不连续多选，翻页保留选择。\n请选择 **1 至 {self.capacity} 天**，确认后按实际天数扣除余量、计1次使用并补发基础奖励，未用完的天数留到下次。\n\n已选：{chosen}\n第 {self.page+1}/{max(1,(len(self.dates)+24)//25)} 页",color=0xF4B942)

    def rebuild(self):
        self.clear_items()
        page_dates=self.dates[self.page*25:(self.page+1)*25]
        if page_dates:
            select=discord.ui.Select(placeholder='选择漏签日期（可多选）',min_values=0,max_values=min(len(page_dates),self.capacity),options=[discord.SelectOption(label=day,value=day,default=day in self.selected) for day in page_dates],row=0)
            async def choose(interaction):
                async with self.lock:
                    if self.done:
                        await interaction.response.send_message('本次补签已完成。',ephemeral=True)
                        return
                    proposed=(self.selected-set(page_dates))|set(select.values)
                    if len(proposed)>self.capacity:
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
        confirm=discord.ui.Button(label='确认补签并领取奖励',style=discord.ButtonStyle.success,row=2,disabled=not 1 <= len(self.selected) <= self.capacity)
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
        view=MakeupView(interaction.user.id,member_joined_date(interaction.user))
        await interaction.followup.send(embed=await view.embed(interaction.guild_id),view=view,ephemeral=True)


def member_joined_date(member):
    joined=getattr(member,'joined_at',None)
    return joined.astimezone(makeup.p.TZ_CN).date().isoformat() if joined else None


async def show_missing_dates(interaction):
    # A visible deferred response creates a new private result, rather than
    # silently acknowledging the wallet component without showing progress.
    await interaction.response.defer(ephemeral=True, invisible=False)
    try:
        dates=await asyncio.wait_for(
            asyncio.to_thread(makeup.missing_dates,interaction.user.id,interaction.guild_id,member_joined_date(interaction.user)),
            timeout=20,
        )
        view=MissingDatesView(interaction.user.id,dates)
        await interaction.edit_original_response(content=None,embed=view.embed(),view=view)
    except ValueError as error:
        await interaction.edit_original_response(content=str(error),embed=None,view=None)
    except TimeoutError:
        logging.getLogger(__name__).warning('Missing-date query timed out: guild=%s user=%s',interaction.guild_id,interaction.user.id)
        await interaction.edit_original_response(content='漏签查询暂时繁忙，请稍后重新打开蛋壳余额再试。',embed=None,view=None)
    except Exception:
        logging.getLogger(__name__).exception('Missing-date query failed: guild=%s user=%s',interaction.guild_id,interaction.user.id)
        await interaction.edit_original_response(content='漏签查询失败，已记录错误，请稍后重新打开蛋壳余额再试。',embed=None,view=None)


class MissingDatesView(discord.ui.View):
    def __init__(self,owner,dates):
        super().__init__(timeout=900, disable_on_timeout=True)
        self.owner,self.dates,self.page=owner,dates,0
        self.update_buttons()

    async def interaction_check(self,interaction):
        if interaction.user.id==self.owner:
            return True
        await interaction.response.send_message('请打开自己的漏签查询。',ephemeral=True)
        return False

    def update_buttons(self):
        self.previous.disabled=self.page==0
        self.next_page.disabled=(self.page+1)*25>=len(self.dates)

    def embed(self):
        dates='、'.join(self.dates[self.page*25:(self.page+1)*25]) or '暂无漏签'
        return discord.Embed(title='📅 漏签日期',description=f'最近三个月内，且不早于 2026-08-06 上线日及入服日，截止昨天（北京时间），可补漏签累计 **{len(self.dates)} 天**。\n不含今天、已签到及已补签日期。\n\n{dates}\n\n第 {self.page+1}/{max(1,(len(self.dates)+24)//25)} 页',color=0xF4B942)

    @discord.ui.button(label='上一页')
    async def previous(self,button,interaction):
        self.page=max(0,self.page-1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(),view=self)

    @discord.ui.button(label='下一页')
    async def next_page(self,button,interaction):
        self.page=min(max(0,(len(self.dates)-1)//25),self.page+1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embed(),view=self)
