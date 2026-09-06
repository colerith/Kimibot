"""Timed, guild-scoped role boosts within each rarity/kind bucket."""
import math
import time
import uuid
import copy
from datetime import datetime, timezone, timedelta

import discord
from .storage import load_role_data, save_role_data, _role_data_lock

BEIJING = timezone(timedelta(hours=8))


def get_up_groups(data, guild_id):
    raw = data.get("lottery_up", {}).get(str(guild_id), {})
    if not isinstance(raw, dict):
        return []
    if "groups" in raw:
        return copy.deepcopy([g for g in raw["groups"] if isinstance(g, dict) and g.get("id")])
    if raw:
        return [dict(copy.deepcopy(raw), id="legacy", name="默认 UP 组")]
    return []


def update_up_group(guild_id, group_id, *, cfg=None, delete=False, stop=False, creating=False):
    # Merge only the selected group into the latest data under the store lock.
    with _role_data_lock:
        data = load_role_data()
        groups = get_up_groups(data, guild_id)
        index = next((i for i, g in enumerate(groups) if g["id"] == group_id), None)
        if index is None and not creating:
            raise ValueError("该组别已被删除，请重新打开面板。")
        if delete:
            groups.pop(index)
        elif stop:
            groups[index]["enabled"] = False
        else:
            saved = dict(copy.deepcopy(cfg), id=group_id)
            valid = set(data.get("lottery_roles", []))
            saved["role_ids"] = [rid for rid in saved.get("role_ids", []) if rid in valid]
            if not saved["role_ids"]:
                raise ValueError("所选身份组已移出奖池，请重新选择。")
            if index is None:
                groups.append(saved)
            else:
                groups[index] = saved
        data.setdefault("lottery_up", {})[str(guild_id)] = {"groups": groups}
        save_role_data(data)


def active_up_weights(data, guild_id, now=None):
    now = time.time() if now is None else now
    valid = set(data.get("lottery_roles", []))
    result = {}
    for cfg in get_up_groups(data, guild_id):
        try:
            multiplier = float(cfg.get("multiplier", 1))
            if not cfg.get("enabled") or not math.isfinite(multiplier) or not 1 < multiplier <= 100:
                continue
            if not float(cfg["start"]) <= now < float(cfg["end"]):
                continue
            for rid in cfg.get("role_ids", []):
                rid = int(rid)
                if rid in valid:
                    result[rid] = max(result.get(rid, 1), multiplier)
        except (TypeError, ValueError, KeyError):
            continue
    return result


def parse_period(start, end, multiplier):
    start = datetime.strptime(start.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING).timestamp()
    end = datetime.strptime(end.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=BEIJING).timestamp()
    multiplier = float(multiplier)
    if end <= start or not math.isfinite(multiplier) or not 1 < multiplier <= 100:
        raise ValueError("结束时间必须晚于开始时间，倍率必须大于 1 且不超过 100。")
    return start, end, multiplier


class UpSettingsModal(discord.ui.Modal):
    def __init__(self, panel):
        super().__init__(title="UP 倍率与时间（北京时间）")
        self.panel = panel
        cfg = panel.cfg
        self.group_id = panel.group_id
        self.name_input = discord.ui.InputText(label="组别名称", value=cfg.get("name", "新 UP 组"), max_length=80)
        self.multiplier = discord.ui.InputText(label="权重倍率（大于 1，最多 100）", value=str(cfg.get("multiplier", 2)))
        def formatted(key):
            return datetime.fromtimestamp(cfg[key], BEIJING).strftime("%Y-%m-%d %H:%M") if cfg.get(key) else None
        self.start = discord.ui.InputText(label="开始时间：YYYY-MM-DD HH:MM", value=formatted("start"), placeholder="2026-09-06 18:00")
        self.end = discord.ui.InputText(label="结束时间：YYYY-MM-DD HH:MM", value=formatted("end"), placeholder="2026-09-13 18:00")
        for item in (self.name_input, self.multiplier, self.start, self.end):
            self.add_item(item)

    async def callback(self, interaction):
        if not await self.panel.interaction_check(interaction):
            return
        if self.group_id != self.panel.group_id:
            return await interaction.response.send_message("组别已切换，请重新打开编辑。", ephemeral=True)
        try:
            if not self.name_input.value.strip():
                raise ValueError("组别名称不能为空。")
            start, end, multiplier = parse_period(self.start.value, self.end.value, self.multiplier.value)
            if end <= time.time():
                raise ValueError("结束时间必须晚于现在。")
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ 时间格式应为 YYYY-MM-DD HH:MM；{exc}", ephemeral=True)
        self.panel.cfg.update(name=self.name_input.value.strip(), start=start, end=end, multiplier=multiplier)
        self.panel.rebuild()
        await interaction.response.edit_message(embed=self.panel.embed(), view=self.panel)


class UpRolesSelect(discord.ui.Select):
    def __init__(self, panel, roles):
        super().__init__(placeholder="多选本页 UP 身份组（翻页保留选择）", min_values=0, max_values=len(roles), row=0,
                         options=[discord.SelectOption(label=r.name[:100], value=str(r.id), default=r.id in panel.selected) for r in roles])
        self.page_ids = {r.id for r in roles}

    async def callback(self, interaction):
        panel = self.view
        panel.selected.difference_update(self.page_ids)
        panel.selected.update(int(v) for v in self.values)
        panel.rebuild()
        await interaction.response.edit_message(embed=panel.embed(), view=panel)


class UpGroupSelect(discord.ui.Select):
    def __init__(self, panel, groups):
        super().__init__(placeholder="选择要编辑的组别（切换前请保存）", row=3,
                         options=[discord.SelectOption(label=g.get("name", "未命名组")[:100], value=g["id"],
                                  default=g["id"] == panel.group_id) for g in groups])

    async def callback(self, interaction):
        panel = self.view
        groups = get_up_groups(load_role_data(), panel.parent.guild.id)
        target = next((g for g in groups if g["id"] == self.values[0]), None)
        if target is None:
            return await interaction.response.send_message("该组别已删除，请重新打开面板。", ephemeral=True)
        panel.load_group(target)
        panel.rebuild()
        await interaction.response.edit_message(embed=panel.embed(), view=panel)


class UpPoolView(discord.ui.View):
    def __init__(self, parent, owner_id):
        super().__init__(timeout=600)
        self.parent, self.owner_id = parent, owner_id
        groups = get_up_groups(load_role_data(), parent.guild.id)
        self.group_page = 0
        self.load_group(groups[0] if groups else None)
        self.rebuild()

    def load_group(self, group=None):
        self.is_new = group is None
        self.cfg = copy.deepcopy(group) if group else {"name": "新 UP 组", "multiplier": 2, "enabled": False}
        self.group_id = self.cfg.get("id", uuid.uuid4().hex)
        self.selected = set(self.cfg.get("role_ids", []))
        self.page = 0

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("请从自己的管理面板配置 UP 池。", ephemeral=True)
            return False
        return True

    def rebuild(self):
        for item in list(self.children):
            if isinstance(item, (UpRolesSelect, UpGroupSelect)):
                self.remove_item(item)
        groups = get_up_groups(load_role_data(), self.parent.guild.id)
        self.group_pages = max(1, math.ceil(len(groups) / 25))
        self.group_page = min(self.group_page, self.group_pages - 1)
        if groups:
            self.add_item(UpGroupSelect(self, groups[self.group_page * 25:(self.group_page + 1) * 25]))
        self.group_next.disabled = self.group_pages == 1
        self.group_next.label = f"组别翻页 {self.group_page + 1}/{self.group_pages}"
        self.delete_group.disabled = self.is_new
        self.stop.disabled = self.is_new
        ids = set(load_role_data().get("lottery_roles", []))
        roles = [r for r in self.parent.guild.roles if r.id in ids]
        self.selected.intersection_update(r.id for r in roles)
        self.pages = max(1, math.ceil(len(roles) / 25))
        self.page = min(self.page, self.pages - 1)
        current = roles[self.page * 25:(self.page + 1) * 25]
        if current:
            self.add_item(UpRolesSelect(self, current))
        self.previous.disabled = self.page == 0
        self.next_page.disabled = self.page == self.pages - 1

    def embed(self):
        cfg = self.cfg
        now = time.time()
        status = "未启用" if not cfg.get("enabled") else "未开始" if now < cfg.get("start", 0) else "已结束" if now >= cfg.get("end", 0) else "进行中"
        period = f"<t:{int(cfg['start'])}:f> → <t:{int(cfg['end'])}:f>" if cfg.get("start") and cfg.get("end") else "尚未设置"
        return discord.Embed(title="📈 限时 UP 池", color=0xF5B041, description=(
            f"当前组别：**{discord.utils.escape_markdown(cfg.get('name', '新 UP 组'))}**{'（未保存）' if self.is_new else ''}\n"
            f"状态：**{status}**（修改后须点击保存启用；切换组别前请保存）\n"
            f"权重倍率：**{cfg.get('multiplier', 2)} 倍**\n时间：{period}\n"
            f"已选 **{len(self.selected)}** 个身份组 · 第 {self.page + 1}/{self.pages} 页\n\n"
            "可配置多个独立组别；同一身份组同时命中多个活动时取最高倍率，不叠乘。\n"
            "仅提高同稀有度、同类型内的身份组权重；保底规则保持原样。\n"
            "例如同池 10 个身份组，1 个设为 2 倍，该身份组条件概率由 10% 变为 2/11 ≈ 18.18%。全选同池则相对概率不变。\n"
            "时间输入为北京时间；显示时间随 Discord 客户端时区转换。到期自动失效。\n\n"
            + ("、".join(f"<@&{rid}>" for rid in sorted(self.selected))[:1800] or "请在下方选择身份组。")))

    @discord.ui.button(label="上一页", row=1)
    async def previous(self, button, interaction):
        self.page = max(0, self.page - 1)
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="下一页", row=1)
    async def next_page(self, button, interaction):
        self.page += 1
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="清空选择", row=1)
    async def clear_selection(self, button, interaction):
        self.selected.clear()
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="编辑名称 / 倍率 / 时间", style=discord.ButtonStyle.primary, row=2)
    async def settings(self, button, interaction):
        await interaction.response.send_modal(UpSettingsModal(self))

    @discord.ui.button(label="保存启用", style=discord.ButtonStyle.success, row=2)
    async def save(self, button, interaction):
        self.rebuild()
        if not self.selected or not self.cfg.get("start") or self.cfg.get("end", 0) <= time.time():
            return await interaction.response.send_message("❌ 请选择身份组并设置有效起止时间。", ephemeral=True)
        self.cfg.update(enabled=True, role_ids=sorted(self.selected))
        try:
            update_up_group(self.parent.guild.id, self.group_id, cfg=self.cfg, creating=self.is_new)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self.is_new = False
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await interaction.followup.send("✅ UP 池已保存，按设定时间自动生效和结束。", ephemeral=True)

    @discord.ui.button(label="立即停用", style=discord.ButtonStyle.danger, row=2)
    async def stop(self, button, interaction):
        try:
            update_up_group(self.parent.guild.id, self.group_id, stop=True)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        self.cfg["enabled"] = False
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="返回管理", row=2)
    async def back(self, button, interaction):
        await self.parent.refresh_content(interaction)

    @discord.ui.button(label="新增组别", style=discord.ButtonStyle.success, row=4)
    async def add_group(self, button, interaction):
        self.load_group()
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="删除当前组别", style=discord.ButtonStyle.danger, row=4)
    async def delete_group(self, button, interaction):
        try:
            update_up_group(self.parent.guild.id, self.group_id, delete=True)
        except ValueError as exc:
            return await interaction.response.send_message(f"❌ {exc}", ephemeral=True)
        groups = get_up_groups(load_role_data(), self.parent.guild.id)
        self.load_group(groups[0] if groups else None)
        self.group_page = 0
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await interaction.followup.send("✅ 当前组别已删除，其他组别不受影响。", ephemeral=True)

    @discord.ui.button(label="组别翻页", row=4)
    async def group_next(self, button, interaction):
        self.group_page = (self.group_page + 1) % self.group_pages
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(), view=self)
