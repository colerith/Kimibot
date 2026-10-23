"""Lottery mode selection, three-reel display, catalog and administrator controls."""
import asyncio
import math
import re

import discord

from cogs.points.storage import format_shells, get_user_points
from . import surprise_storage as store
from . import storage as roles


def symbol_for(role, entry):
    override = entry.get("symbol", "")
    if override:
        emoji = discord.PartialEmoji.from_str(override)
        return (str(emoji), str(emoji.url), f"emoji:{emoji.id}") if emoji.id else (override, None, override.replace("\ufe0f", "").replace("\ufe0e", ""))
    if role.unicode_emoji:
        return (role.unicode_emoji, None, role.unicode_emoji.replace("\ufe0f", "").replace("\ufe0e", ""))
    if role.icon:
        return ("🖼️", str(role.icon.url), f"icon:{role.icon.key.rsplit('/', 1)[-1]}")
    return ("❔", None, None)


def pool_entries(guild, cfg):
    entries = []
    for rid, entry in cfg["roles"].items():
        role = guild.get_role(int(rid))
        if role:
            entries.append((role, entry, symbol_for(role, entry)))
    return sorted(entries, key=lambda item: (item[0].position, item[0].id), reverse=True)


def playable_pool(guild, cfg):
    entries = [row for row in pool_entries(guild, cfg) if row[1]["weight"] > 0]
    symbols = set()
    for role, _, symbol in entries:
        if role.managed or role.id == guild.id or role.permissions.administrator:
            return [], "奖池包含不可作为装饰发放的身份组，请管理员调整。"
        if not symbol[2]:
            return [], f"{role.name} 尚无图标，请管理员设置显示 Emoji。"
        if symbol[2] in symbols:
            return [], "有身份组使用相同图标，请管理员设置不同 Emoji，避免中奖判定歧义。"
        symbols.add(symbol[2])
    if not entries or (len(entries) < 2 and cfg["chance"] < 100):
        return [], "请配置至少两个有不同图标的有效身份组（100% 必中时允许一个）。"
    return entries, None


def mode_embed():
    return discord.Embed(title="🎲 身份抽奖", color=0xBB8FCE, description=(
        "**🎲 普通抽奖**\n试试手气 · 五连试炼 · 十连试炼\n沿用普通奖池、保底和奖励规则。\n\n"
        "**🎰 惊喜抽奖**\n三个位置显示同一个身份组图标即可获得该身份组！\n重复身份组转换为碎片，可查询惊喜奖池和碎片余额。"))


class OwnerView(discord.ui.View):
    def __init__(self, owner_id, *, timeout=600):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("请打开自己的抽奖或管理面板。", ephemeral=True)
            return False
        return True


class LotteryModeView(OwnerView):
    @discord.ui.button(label="普通抽奖", emoji="🎲", style=discord.ButtonStyle.primary)
    async def normal(self, button, interaction):
        from .views import RoleLotteryView, build_role_lottery_embed
        await interaction.response.defer()
        data, balance = await asyncio.gather(asyncio.to_thread(roles.load_role_data),
            asyncio.to_thread(get_user_points, interaction.user.id, interaction.guild_id))
        await interaction.edit_original_response(embeds=[build_role_lottery_embed(balance, data)], view=RoleLotteryView())

    @discord.ui.button(label="惊喜抽奖", emoji="🎰", style=discord.ButtonStyle.success)
    async def surprise(self, button, interaction):
        await interaction.response.defer()
        view = SurpriseLotteryView(interaction.user.id, interaction.guild)
        await interaction.edit_original_response(embeds=[await view.prepare()], view=view)


class SurpriseLotteryView(OwnerView):
    def __init__(self, owner_id, guild):
        super().__init__(owner_id)
        self.guild = guild
        self.busy = False

    async def prepare(self):
        cfg, account, balance = await asyncio.gather(asyncio.to_thread(store.get_config, self.guild.id),
            asyncio.to_thread(store.get_account, self.owner_id, self.guild.id),
            asyncio.to_thread(get_user_points, self.owner_id, self.guild.id))
        _, error = playable_pool(self.guild, cfg)
        self.spin.disabled = not cfg["enabled"] or bool(error)
        embed = discord.Embed(title="🎰 惊喜抽奖", color=0xF4B942, description=(
            "## ❔ ┃ ❔ ┃ ❔\n三个相同身份组图标 → 获得该身份组！\n\n"
            f"每次 **{format_shells(cfg['cost'])}** 蛋壳 · 三图标一致概率 **{cfg['chance']:g}%**\n"
            f"重复转换 **{cfg['duplicate_shards']}** 碎片 · 当前碎片 **{account['shards']}**\n"
            f"蛋壳余额 **{format_shells(balance)}**\n\n"
            "中奖后按身份组权重分配；未中奖会显示不完全相同的图标。\n"
            "惊喜抽奖使用独立奖池，不计入普通抽奖保底。碎片暂只累计和查询。"))
        if not cfg["enabled"] or error:
            embed.add_field(name="当前状态", value="暂未开放" if not cfg["enabled"] else error, inline=False)
        return embed

    @discord.ui.button(label="拉动老虎机", emoji="🎰", style=discord.ButtonStyle.success)
    async def spin(self, button, interaction):
        if self.busy:
            return await interaction.response.send_message("本次正在开奖，请稍候。", ephemeral=True)
        self.busy = True
        try:
            await interaction.response.defer()
            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(embeds=[discord.Embed(title="🎰 转动中……", description="## ❔ ┃ ❔ ┃ ❔", color=0xF4B942)], view=self)
            cfg = await asyncio.to_thread(store.get_config, self.guild.id)
            entries, error = playable_pool(self.guild, cfg)
            if error:
                result = {"success": False, "reason": error}
            else:
                from .views import _LOTTERY_USER_LOCKS
                lock = _LOTTERY_USER_LOCKS.setdefault((self.guild.id, self.owner_id), asyncio.Lock())
                async with lock:
                    result = await asyncio.to_thread(store.settle_spin, self.owner_id, self.guild.id,
                        str(interaction.id), {row[0].id for row in entries},
                        {r.id for r in interaction.user.roles}, expected_config=cfg,
                        symbols={role.id: symbol for role, _, symbol in entries})
            if not result["success"]:
                embeds = [discord.Embed(title="暂时无法抽奖", description=result["reason"], color=0xED4245)]
            else:
                # The result is already durably saved; presentation never rolls again.
                await asyncio.sleep(0.6)
                embeds = self.result_embeds(result, cfg)
                winner = self.guild.get_role(result["winner"]) if result["winner"] else None
                if winner and not result["duplicate"]:
                    try:
                        await interaction.user.add_roles(winner, reason="惊喜抽奖中奖")
                    except discord.HTTPException:
                        embeds[0].add_field(name="穿戴提示", value="奖励已保存；自动穿戴失败，可稍后在小蛋换装中穿戴。", inline=False)
                if result.get("delivery_pending"):
                    embeds[0].add_field(name="衣柜同步", value="奖励已记录，重新打开惊喜抽奖即可恢复到衣柜。", inline=False)
            for child in self.children:
                child.disabled = False
            await interaction.edit_original_response(embeds=embeds, view=self, allowed_mentions=discord.AllowedMentions.none())
        except Exception as error:
            print(f"[惊喜抽奖] interaction={interaction.id}: {error!r}")
            for child in self.children:
                child.disabled = False
            try:
                await interaction.edit_original_response(embeds=[discord.Embed(title="结果显示暂时异常",
                    description="已结算结果会保存在记录中，请点击【上次结果】查看；无需再次抽取。", color=0xED4245)], view=self)
            except discord.HTTPException:
                pass
        finally:
            self.busy = False

    def result_embeds(self, result, cfg):
        rows = []
        for index, rid in enumerate(result["reels"]):
            role = self.guild.get_role(rid)
            symbol = result["symbols"][index] if result.get("symbols") else (
                symbol_for(role, cfg["roles"].get(str(rid), {})) if role else ("❔", None, None))
            rows.append((role, symbol))
        slots = "图标见下方三个位置" if any(symbol[1] for _, symbol in rows) else " ┃ ".join(symbol[0] for _, symbol in rows)
        winner = result["winner"]
        status = (f"重复身份组 <@&{winner}> → **+{result['shards_gained']} 碎片**" if result["duplicate"] else
                  f"🎉 获得 <@&{winner}>！已加入永久衣柜。") if winner else "这次图标没有完全一致，未中奖。"
        embed = discord.Embed(title="🎰 惊喜抽奖结果", description=f"## {slots}\n{status}\n\n"
            f"本次消耗 **{format_shells(result['cost'])}** 蛋壳 · 结算余额 **{format_shells(result['balance'])}**\n"
            f"结算碎片余额 **{result['shards']}**", color=0xF4B942 if winner else 0x95A5A6)
        embeds = [embed]
        for index, (role, symbol) in enumerate(rows, 1):
            reel = discord.Embed(title=f"{index} 号位", description=f"{symbol[0]} {role.mention if role else '已删除身份组'}", color=0xBB8FCE)
            if symbol[1]:
                reel.set_thumbnail(url=symbol[1])
            embeds.append(reel)
        return embeds

    @discord.ui.button(label="奖池列表 / 我的碎片", emoji="📚")
    async def catalog(self, button, interaction):
        await interaction.response.defer()
        view = SurpriseCatalogView(self.owner_id, self.guild)
        await interaction.edit_original_response(embeds=[await view.prepare()], view=view)

    @discord.ui.button(label="上次结果", emoji="📜")
    async def last_result(self, button, interaction):
        await interaction.response.defer()
        account = await asyncio.to_thread(store.get_account, self.owner_id, self.guild.id)
        if not account.get("last_result"):
            return await interaction.followup.send("还没有惊喜抽奖记录。", ephemeral=True)
        cfg = await asyncio.to_thread(store.get_config, self.guild.id)
        await interaction.edit_original_response(embeds=self.result_embeds(account["last_result"], cfg), view=self)

    @discord.ui.button(label="返回模式选择", emoji="↩️")
    async def back(self, button, interaction):
        await interaction.response.edit_message(embeds=[mode_embed()], view=LotteryModeView(self.owner_id))


class SurpriseCatalogView(OwnerView):
    def __init__(self, owner_id, guild):
        super().__init__(owner_id)
        self.guild, self.page = guild, 0

    async def prepare(self):
        cfg, account, owned = await asyncio.gather(asyncio.to_thread(store.get_config, self.guild.id),
            asyncio.to_thread(store.get_account, self.owner_id, self.guild.id),
            asyncio.to_thread(roles.get_user_collection, self.owner_id))
        owned = set(owned) | set(account["owned"])
        entries = pool_entries(self.guild, cfg)
        total_weight = sum(entry["weight"] for _, entry, _ in entries)
        pages = max(1, math.ceil(len(entries) / 10))
        self.page = max(0, min(self.page, pages - 1))
        self.prev.disabled, self.next.disabled = self.page == 0, self.page == pages - 1
        embed = discord.Embed(title="📚 惊喜抽奖奖池", description=f"我的碎片：**{account['shards']}** · 累计 **{account['draws']}** 抽\n"
            f"总中奖率 **{cfg['chance']:g}%** · 碎片暂只累计和查询。", color=0xBB8FCE)
        for role, entry, symbol in entries[self.page * 10:(self.page + 1) * 10]:
            probability = cfg["chance"] * entry["weight"] / total_weight if total_weight else 0
            icon = f"[查看图标]({symbol[1]})" if symbol[1] else symbol[0]
            embed.add_field(name=role.name[:256], value=f"{icon} {role.mention}\n"
                f"{'✅ 已拥有' if role.id in owned else '尚未拥有'} · 单次获得概率 {probability:.4g}%"
                + (" · 已暂停" if not entry["weight"] else ""), inline=False)
        if not entries:
            embed.description += "\n\n奖池暂未配置。"
        _, error = playable_pool(self.guild, cfg)
        if not cfg["enabled"] or error:
            embed.description += "\n当前暂不可抽取；显示概率为配置生效后的概率。"
        embed.set_footer(text=f"服务器身份组顺序 · 第 {self.page + 1}/{pages} 页")
        return embed

    @discord.ui.button(label="上一页", emoji="⬅️")
    async def prev(self, button, interaction):
        await interaction.response.defer()
        self.page -= 1
        await interaction.edit_original_response(embeds=[await self.prepare()], view=self)

    @discord.ui.button(label="下一页", emoji="➡️")
    async def next(self, button, interaction):
        await interaction.response.defer()
        self.page += 1
        await interaction.edit_original_response(embeds=[await self.prepare()], view=self)

    @discord.ui.button(label="返回惊喜抽奖", emoji="↩️")
    async def back(self, button, interaction):
        await interaction.response.defer()
        view = SurpriseLotteryView(self.owner_id, self.guild)
        await interaction.edit_original_response(embeds=[await view.prepare()], view=view)


class SurpriseSettingsModal(discord.ui.Modal):
    def __init__(self, panel):
        super().__init__(title="惊喜抽奖概率与费用")
        self.panel = panel
        cfg = panel.cfg
        self.cost = discord.ui.InputText(label="单次蛋壳费用（0 为免费）", value=str(cfg["cost"]))
        self.chance = discord.ui.InputText(label="三个图标一致的概率（0–100%）", value=str(cfg["chance"]))
        self.shards = discord.ui.InputText(label="重复身份组转换碎片数量", value=str(cfg["duplicate_shards"]))
        for item in (self.cost, self.chance, self.shards):
            self.add_item(item)

    async def callback(self, interaction):
        if interaction.user.id != self.panel.owner_id:
            return await interaction.response.send_message("仅原管理员可修改。", ephemeral=True)
        await interaction.response.defer()
        try:
            await asyncio.to_thread(store.update_config, interaction.guild_id, settings={
                "cost": self.cost.value, "chance": self.chance.value, "duplicate_shards": self.shards.value})
        except ValueError as error:
            return await interaction.followup.send(f"❌ {error}", ephemeral=True)
        await self.panel.refresh(interaction)
        await interaction.followup.send("✅ 概率与费用已保存。", ephemeral=True)


class SurpriseRoleModal(discord.ui.Modal):
    def __init__(self, panel, role):
        super().__init__(title="惊喜奖池身份组配置")
        self.panel, self.role = panel, role
        entry = panel.cfg["roles"].get(str(role.id), {})
        self.weight = discord.ui.InputText(label="中奖分配权重（0 暂停；默认 1）", value=str(entry.get("weight", 1)))
        self.symbol = discord.ui.InputText(label="显示 Emoji（留空使用身份组原图标）", value=entry.get("symbol", ""), required=False, max_length=100)
        self.add_item(self.weight)
        self.add_item(self.symbol)

    async def callback(self, interaction):
        if interaction.user.id != self.panel.owner_id:
            return await interaction.response.send_message("仅原管理员可修改。", ephemeral=True)
        await interaction.response.defer()
        entry = {"weight": self.weight.value, "symbol": self.symbol.value.strip()}
        symbol_text = entry["symbol"]
        if symbol_text and not re.fullmatch(r"<a?:[A-Za-z0-9_]+:[0-9]+>", symbol_text):
            # Unicode emoji may contain joiners, selectors and skin tones; reject prose/Markdown.
            has_emoji = any(0x1F000 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27FF
                            or c in "©®™‼⁉〰〽㊗㊙\u20e3" for c in symbol_text)
            if not has_emoji or any(c.isspace() for c in symbol_text) or len(symbol_text) > 32:
                return await interaction.followup.send("❌ 请填写一个 Emoji 或 Discord 自定义表情，不要填写普通文字或链接。", ephemeral=True)
        icon = symbol_for(self.role, entry)
        if not icon[2]:
            return await interaction.followup.send("❌ 该身份组没有图标，请填写一个 Emoji。", ephemeral=True)
        cfg = await asyncio.to_thread(store.get_config, interaction.guild_id)
        if any(r.id != self.role.id and symbol[2] == icon[2] for r, _, symbol in pool_entries(interaction.guild, cfg)):
            return await interaction.followup.send("❌ 该图标已被其他身份组使用，请换一个。", ephemeral=True)
        try:
            await asyncio.to_thread(store.update_config, interaction.guild_id, role_id=self.role.id, entry=entry)
        except ValueError as error:
            return await interaction.followup.send(f"❌ {error}", ephemeral=True)
        self.panel.selected_id = self.role.id
        await self.panel.refresh(interaction)
        await interaction.followup.send("✅ 身份组已保存，可继续配置其他身份组。", ephemeral=True)


class SurpriseAdminRolePicker(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="添加 / 配置身份组（可搜索）", select_type=discord.ComponentType.role_select, row=0)

    async def callback(self, interaction):
        panel = self.view
        rid = int(interaction.data["values"][0])
        role = interaction.guild.get_role(rid)
        if not role or role.managed or role.id == interaction.guild_id or role.permissions.administrator:
            return await interaction.response.send_message("请选择普通装饰身份组。", ephemeral=True)
        await interaction.response.send_modal(SurpriseRoleModal(panel, role))


class SurpriseConfiguredPicker(discord.ui.Select):
    def __init__(self, panel, entries):
        options = [discord.SelectOption(label=role.name[:100], value=str(role.id), default=role.id == panel.selected_id,
                    description=f"权重 {entry['weight']:g} · 服务器层级 {role.position}") for role, entry, _ in entries]
        super().__init__(placeholder=f"已配置奖池（第 {panel.page + 1}/{panel.pages} 页）", options=options, row=1)

    async def callback(self, interaction):
        panel = self.view
        panel.selected_id = int(self.values[0])
        await interaction.response.defer()
        await panel.refresh(interaction)


class SurpriseAdminView(OwnerView):
    def __init__(self, parent, owner_id):
        super().__init__(owner_id)
        self.parent, self.guild = parent, parent.guild
        self.page, self.pages, self.selected_id = 0, 1, None
        self.cfg = None

    async def prepare(self):
        self.cfg = await asyncio.to_thread(store.get_config, self.guild.id)
        entries = pool_entries(self.guild, self.cfg)
        self.pages = max(1, math.ceil(len(entries) / 25))
        self.page = max(0, min(self.page, self.pages - 1))
        for item in list(self.children):
            if isinstance(item, discord.ui.Select):
                self.remove_item(item)
        self.add_item(SurpriseAdminRolePicker())
        page_entries = entries[self.page * 25:(self.page + 1) * 25]
        if page_entries:
            self.add_item(SurpriseConfiguredPicker(self, page_entries))
        self.previous.disabled, self.next_page.disabled = self.page == 0, self.page == self.pages - 1
        self.edit_role.disabled = self.remove_role.disabled = self.selected_id is None
        self.toggle.label = "暂停惊喜抽奖" if self.cfg["enabled"] else "开放惊喜抽奖"
        _, error = playable_pool(self.guild, self.cfg)
        lines = [f"{symbol[0]} {role.mention} · 权重 {entry['weight']:g}" for role, entry, symbol in page_entries]
        embed = discord.Embed(title="🎰 惊喜抽奖管理", color=0xF4B942, description=(
            f"状态：**{'已开放' if self.cfg['enabled'] else '已暂停'}**\n"
            f"单抽 **{self.cfg['cost']:g}** 蛋壳 · 三图标一致概率 **{self.cfg['chance']:g}%**\n"
            f"重复转换 **{self.cfg['duplicate_shards']}** 碎片\n\n"
            "中奖时按权重分配身份组；例如中奖率 10%，两组权重 1:3，单次概率分别为 2.5% 和 7.5%。\n"
            "三图标不是独立抽取：先按总中奖率决定是否一致，再分配身份组。\n"
            "添加身份组后设置权重和独立图标；权重 0 为暂停。\n\n" + ("\n".join(lines) or "尚未配置奖池。")))
        if self.selected_id:
            embed.add_field(name="当前选择", value=f"<@&{self.selected_id}>", inline=False)
        if error:
            embed.add_field(name="配置提示", value=error, inline=False)
        embed.set_footer(text=f"服务器层级从上到下 · 第 {self.page + 1}/{self.pages} 页 · 保存后保留当前面板")
        return embed

    async def refresh(self, interaction):
        await interaction.edit_original_response(embeds=[await self.prepare()], view=self)

    @discord.ui.button(label="概率 / 费用 / 碎片", emoji="⚙️", row=2)
    async def settings(self, button, interaction):
        await interaction.response.send_modal(SurpriseSettingsModal(self))

    @discord.ui.button(label="编辑所选身份组", emoji="✏️", row=2)
    async def edit_role(self, button, interaction):
        role = interaction.guild.get_role(self.selected_id)
        if not role:
            return await interaction.response.send_message("身份组已不存在，请重新选择。", ephemeral=True)
        await interaction.response.send_modal(SurpriseRoleModal(self, role))

    @discord.ui.button(label="移除所选", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
    async def remove_role(self, button, interaction):
        await interaction.response.defer()
        await asyncio.to_thread(store.update_config, interaction.guild_id, role_id=self.selected_id, remove=True)
        self.selected_id = None
        await self.refresh(interaction)

    @discord.ui.button(label="开放惊喜抽奖", emoji="🎰", style=discord.ButtonStyle.success, row=2)
    async def toggle(self, button, interaction):
        await interaction.response.defer()
        cfg = await asyncio.to_thread(store.get_config, interaction.guild_id)
        if not cfg["enabled"]:
            _, error = playable_pool(interaction.guild, cfg)
            if error:
                return await interaction.followup.send(f"❌ {error}", ephemeral=True)
        await asyncio.to_thread(store.update_config, interaction.guild_id, settings={"enabled": not cfg["enabled"]})
        await self.refresh(interaction)

    @discord.ui.button(label="上一页", emoji="⬅️", row=3)
    async def previous(self, button, interaction):
        await interaction.response.defer()
        self.page -= 1
        await self.refresh(interaction)

    @discord.ui.button(label="下一页", emoji="➡️", row=3)
    async def next_page(self, button, interaction):
        await interaction.response.defer()
        self.page += 1
        await self.refresh(interaction)

    @discord.ui.button(label="返回奖池与图鉴配置", emoji="↩️", row=3)
    async def back(self, button, interaction):
        await self.parent.refresh_content(interaction)
