import asyncio
import uuid
from pathlib import Path
import discord
from discord import ui
from . import storage as store

UPLOAD_ROOT = Path('data/promotion_uploads')
BENEFITS = ('🎁 **破壳礼** · 首次开通赠送 **100 蛋壳**\n'
            '🎰 **抽奖优惠** · 普通 / 惊喜身份抽奖 **八折**，原价 10 蛋壳的十连只需 8 个\n'
            '🛍️ **衣柜优惠** · 身份组商城当前售价 **八折**\n'
            '🌅 **每日陪伴** · 北京时间每天 **+30 蛋壳**，自动到账，无需签到\n'
            '这是永久权益，无需续费；可与普通月卡的每日赠礼同时享有。')
STATUS = {'publishing': '正在投递', 'pending': '等待服主审批', 'granting': '已批准・权益发放中',
          'approved': '已通过', 'rejected': '已驳回'}


DEFAULT_COPY = {
    'title': '🐣 小蛋晋升面板｜谢谢你陪我们长大',
    'intro': '每一段认真使用的旅程，本大王都有好好珍惜惹！\n'
             f'为了感谢你的支持，我们准备了 <@&{store.ROLE_ID}> 身份组和一份长久的破壳礼。',
    'benefits': BENEFITS,
    'requirements': '使用 **日月西 / 象牙塔** 聊天 **超过 100 楼**。\n'
                    '上传 **至少两张截图**：首楼与最后一楼，能看到楼层数及日月西 / 象牙塔的相关痕迹。\n'
                    '具体聊天内容可以打码，并附上 **至少 30 字的使用感想**。',
    'notes': '申请与截图会展示在申请记录子区，请先处理好隐私。由**服主手动审批**，通过或驳回都会私信通知。\n'
             '每位成员同时只能有一份待审申请，已开通权益无需重复申请。',
}


def entry_embed(used, settings=None):
    copy = DEFAULT_COPY | {key: value for key, value in (settings or {}).items() if key in DEFAULT_COPY}
    # Remove the retired public note even when it was saved by an older admin form.
    copy['notes'] = copy['notes'].replace('管理员 / 服主自动享有权益；其申请标记为测试记录，不占名额。', '').strip()
    copy['notes'] = copy['notes'].replace('申请与截图会公开展示在本频道', '申请与截图会展示在申请记录子区')
    embed = discord.Embed(title=copy['title'], description=copy['intro'], color=0xEBCB8B)
    for name, key in [('✨ 破壳而出的专属权益', 'benefits'), ('📷 带上你的使用足迹', 'requirements'), ('🌷 申请须知', 'notes')]:
        embed.add_field(name=name, value=copy[key] or '请按申请条件提交材料。', inline=False)
    embed.add_field(name='今日申请名额', value=f'**{used} / {store.DAILY_LIMIT}** · 北京时间每日 0 点刷新。', inline=False)
    embed.set_footer(text=f'{store.today()} 批次 · 本大王在这里等你破壳！')
    return embed


def application_embed(row):
    color = {'approved': 0x9BBE9D, 'rejected': 0xCFA2A2}.get(row['status'], 0xEBCB8B)
    embed = discord.Embed(title=f'🌱 小蛋成长档案 · #{row["id"]:06d}', color=color,
                          description=f'<@{row["user_id"]}> 的破壳申请\n谢谢你把这段使用旅程分享给我们。')
    if row.get('is_test'):
        embed.description += '\n🧪 **管理员测试记录 · 不占每日名额 · 不重复发奖**'
    embed.add_field(name='申请批次', value=row['batch'])
    embed.add_field(name='申请编号', value=f'`#{row["id"]:06d}`')
    embed.add_field(name='审批状态', value=STATUS[row['status']])
    embed.add_field(name='💌 使用感想', value=row['content'][:1000], inline=False)
    if row.get('reviewer_id'):
        embed.add_field(name='审批人', value=f'<@{row["reviewer_id"]}>')
    if row.get('reason'):
        embed.add_field(name='📝 驳回理由', value=row['reason'][:1000], inline=False)
    embed.set_footer(text=f'小蛋晋升申请 #{row["id"]} · 北京时间 · 截图见附件')
    return embed


def result_embed(row):
    approved = row['status'] == 'approved'
    embed = discord.Embed(title='🐣 破壳成功，欢迎长大的你！' if approved else '🌙 小蛋的成长档案需要再补充一下',
        description=('本大王收到你的心意啦！感谢你对日月西 / 象牙塔的支持。\n'
                     f'<@&{store.ROLE_ID}> 已发放，你的永久权益也已开通。' if approved else
                     '本次申请暂未通过。别着急，按照下面的说明整理好材料后，可以重新申请。'),
        color=0x9BBE9D if approved else 0xCFA2A2)
    embed.add_field(name='申请档案', value=f'{row["batch"]} 批次 · `#{row["id"]:06d}` · {STATUS[row["status"]]}', inline=False)
    embed.add_field(name='✨ 你的破壳礼' if approved else '📝 服主的审核说明',
                    value=BENEFITS if approved else row['reason'][:1000], inline=False)
    if row.get('is_test'):
        embed.title = '🧪 小蛋晋升 · 测试审批结果'
        embed.description = '这是一份管理员 / 服主测试记录，不占每日名额。权益已自动享有，本次审批不授予身份组或重复发奖。'
    embed.set_footer(text='奇米蛋 · 认真陪伴每一颗小蛋')
    return embed


def jump_view(row):
    view = ui.View()
    if row.get('message_id'):
        view.add_item(ui.Button(label='查看申请档案', style=discord.ButtonStyle.link,
            url=f'https://discord.com/channels/{row["guild_id"]}/{row.get("channel_id", store.CHANNEL_ID)}/{row["message_id"]}'))
    return view


def owner_allowed(interaction):
    return interaction.guild is not None and interaction.user.id == interaction.guild.owner_id


class PromotionModal(ui.DesignerModal):
    def __init__(self):
        super().__init__(title='小蛋晋升 · 记录你的成长')
        self.thoughts = ui.InputText(label=None, style=discord.InputTextStyle.paragraph,
                                    min_length=30, max_length=1000, required=True)
        self.uploads = ui.FileUpload(required=True, min_values=2, max_values=6)
        self.add_item(ui.Label('使用感想（至少 30 字）', self.thoughts))
        self.add_item(ui.Label('首楼 / 末楼截图（2–6 张）', self.uploads,
            description='超过 100 楼；显示日月西 / 象牙塔痕迹，可打码。材料会公开展示。'))

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.get_cog('PromotionCog')
        cfg = await asyncio.to_thread(store.settings)
        if not cog or interaction.channel_id != cfg['channel_id']:
            return await interaction.followup.send('请从小蛋晋升频道的面板重新申请。', ephemeral=True)
        is_test = store.is_staff(interaction.user)
        if is_test:
            await asyncio.to_thread(store.activate, interaction.user.id, interaction.guild_id)
        if not is_test and any(r.id == store.ROLE_ID for r in interaction.user.roles):
            await asyncio.to_thread(store.activate, interaction.user.id, interaction.guild_id)
            return await interaction.followup.send('你已拥有破壳而出身份组，永久权益已自动开通，无需申请。', ephemeral=True)
        files = []
        committed = False
        try:
            if len(''.join(self.thoughts.value.split())) < 30:
                raise ValueError('感想至少需要 30 字，空白不计入。')
            uploads = self.uploads.values or []
            if not 2 <= len(uploads) <= 6:
                raise ValueError('请至少上传两张截图。')
            for attachment in uploads:
                if attachment.size > 8 * 1024 * 1024:
                    raise ValueError('每张截图请控制在 8 MB 以内。')
                data = await cog.api(attachment.read)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError("每张截图请控制在 8 MB 以内。")
                extension = image_extension(data)
                if not extension:
                    raise ValueError('仅支持 PNG、JPEG、GIF 或 WebP 图片。')
                path = UPLOAD_ROOT / f'{uuid.uuid4().hex}.{extension}'
                await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(path.write_bytes, data)
                files.append(str(path))
            row = await asyncio.to_thread(store.create, interaction.user.id, interaction.guild_id,
                interaction.id, self.thoughts.value, files, interaction.user.display_name, is_test=is_test)
            committed = True
            await cog.publish(row)
            await interaction.followup.send(f'🌱 已收好你的申请 `#{row["id"]:06d}`，请等待服主审批。结果会私信通知你。', ephemeral=True)
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except Exception as error:
            cog.report('提交申请', error)
            await interaction.followup.send('申请已保存，展示卡片稍后会自动补发。' if committed else '附件暂时上传失败，本次没有占用名额，请稍后重试。', ephemeral=True)
        finally:
            if not committed:
                for filename in files:
                    await asyncio.to_thread(Path(filename).unlink, missing_ok=True)


def image_extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'webp'
    return None


class EntryView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label='提交晋升申请', emoji='🌱', style=discord.ButtonStyle.success, custom_id='promotion:apply')
    async def apply(self, button, interaction):
        await interaction.response.send_modal(PromotionModal())


class RejectModal(ui.Modal):
    def __init__(self, application_id):
        super().__init__(title='驳回晋升申请 · 填写理由')
        self.application_id = application_id
        self.reason = ui.InputText(label='驳回理由（将公开记录并私信申请人）',
            style=discord.InputTextStyle.paragraph, required=True, min_length=1, max_length=1000)
        self.add_item(self.reason)

    async def callback(self, interaction):
        if not owner_allowed(interaction):
            return await interaction.response.send_message('只有服主可以审批。', ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await interaction.client.get_cog('PromotionCog').review(interaction, self.application_id, False, self.reason.value)


class ReviewView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        if not owner_allowed(interaction):
            await interaction.response.send_message('这份成长档案由服主亲自审批。', ephemeral=True)
            return False
        return True

    async def locate(self, interaction):
        rows = await asyncio.to_thread(store.applications, interaction.guild_id)
        return next((r for r in rows if r.get('message_id') == interaction.message.id), None)

    @ui.button(label='通过申请', emoji='✅', style=discord.ButtonStyle.success, custom_id='promotion:approve')
    async def approve(self, button, interaction):
        await interaction.response.defer(ephemeral=True)
        row = await self.locate(interaction)
        if not row:
            return await interaction.followup.send('未找到这份申请记录。', ephemeral=True)
        await interaction.client.get_cog('PromotionCog').review(interaction, row['id'], True)

    @ui.button(label='驳回申请', emoji='📝', style=discord.ButtonStyle.danger, custom_id='promotion:reject')
    async def reject(self, button, interaction):
        # Message ID is encoded in the embed footer; no database I/O before opening modal.
        footer = interaction.message.embeds[0].footer.text
        application_id = int(footer.split('#')[1].split(' ')[0])
        await interaction.response.send_modal(RejectModal(application_id))


class BottomView(ui.View):
    def __init__(self, earliest=None):
        super().__init__(timeout=None)
        if earliest:
            self.add_item(ui.Button(label=f'最早待审 · #{earliest["id"]:06d}', emoji='📍', style=discord.ButtonStyle.link,
                url=f'https://discord.com/channels/{earliest["guild_id"]}/{earliest.get("channel_id", store.CHANNEL_ID)}/{earliest["message_id"]}'))
        else:
            self.add_item(ui.Button(label='当前没有待审批申请', custom_id='promotion:empty', disabled=True))
