"""Editable, guild-scoped third-party service reminder."""

import asyncio

import discord

from .sqlite_store import load_json_namespace, save_json_namespace


DEFAULT_NOTICE = """# 请勿在社区寻求第三方服务、用第三方提问、暴露正在使用第三方等，一经发现会进行答题警告处理

## 为什么不建议使用第三方 API、中转或代购密钥？

第三方渠道的服务过程通常是一个无法核验的“黑箱”。你无法确认请求最终发给了哪个平台、使用了什么模型，也无法看到真实的用量、限额和上游报错。

部分商家可能存在虚标、降级或“掺水”的情况，例如：

- 标注为 Gemini，实际上可能接入豆包、其他低成本模型，甚至混用多个模型。
- 标注为高级模型，实际返回的可能是更便宜、更弱的版本。
- 根据负载或成本临时更换上游模型，却仍然使用原来的模型名称。
- 多名用户共享同一密钥、账号或额度，导致限流、上下文混乱、额度异常消耗。
- 记录、转存或分析你的对话内容、角色卡、预设和密钥，带来隐私泄露风险。
- 渠道随时失效、跑路或更换接口，付费后也未必能获得稳定服务。

仅凭回复风格，通常无法准确判断实际使用的模型。即使接口返回了某个模型名称，该名称也可能只是第三方自行填写的标签，并不能证明真实上游。

## 为什么推荐官方渠道或自己部署的反代？

- 上游来源明确，模型名称和计费规则可以核验。
- 可以查看真实的请求记录、用量、限额及错误信息。
- 出现问题时能够提供有效日志，便于复现和诊断。
- 密钥、代理规则和数据流向由自己控制，隐私风险更低。
- 自建反代只是转发自己拥有权限的官方接口，不依赖陌生商家的黑箱服务。

请注意：自己部署反代并不代表可以绕过模型方的规则，也不会让付费 API 变成免费服务。仍需遵守上游平台的使用条款与计费规则。

## 为什么社区不受理第三方 API 的相关问题？

第三方渠道的模型映射、转发逻辑、账号状态、额度分配和风控情况均由商家控制。相同的报错可能来自商家后台、共享密钥、伪造模型、上游失效或接口篡改，社区无法获取必要信息，也无法进行可靠诊断。

因此：

- 社区无法确认你实际调用的是什么模型。
- 社区无法查看第三方后台、额度和转发日志。
- 第三方渠道特有的问题无法在官方或自建环境中复现。
- 志愿答疑者没有义务充当商家的免费售后。
- 为第三方服务排错还可能变相帮助其继续销售不透明或虚标的产品。

如果你购买了第三方服务，请直接联系销售方处理。若希望获得社区帮助，请先切换到规则允许的官方渠道、正规授权平台或自己部署并可提供日志的环境，再携带完整报错信息进行提问。

**请遵守社区守则：**  
[点击查看守则](https://discord.com/channels/1397629012292931726/1417568378889175071/1417569207041785937)"""


def load_notice(guild_id: int) -> str:
    return load_json_namespace(
        f"third_party_notice:{guild_id}", legacy_file=None, default=DEFAULT_NOTICE
    )


def save_notice(guild_id: int, content: str) -> None:
    if not content.strip() or len(content) > 2000:
        raise ValueError("文案不能为空，且不能超过 2000 字。")
    save_json_namespace(f"third_party_notice:{guild_id}", content)


class ThirdPartyNoticeModal(discord.ui.Modal):
    def __init__(self, guild_id: int, owner_id: int, content: str):
        super().__init__(title="第三方违规提醒文案")
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.content_input = discord.ui.InputText(
            label="提醒正文（支持 Markdown，最多 2000 字）",
            style=discord.InputTextStyle.long,
            value=content,
            max_length=2000,
            required=True,
        )
        self.add_item(self.content_input)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id or interaction.guild_id != self.guild_id:
            return await interaction.response.send_message("❌ 仅原管理员可修改。", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await asyncio.to_thread(save_notice, self.guild_id, self.content_input.value)
        except (ValueError, OSError) as error:
            return await interaction.followup.send(f"❌ 保存失败：{error}", ephemeral=True)
        await interaction.followup.send("✅ 第三方违规提醒文案已保存，下次使用右键命令时立即生效。", ephemeral=True)


class ThirdPartyNoticeEditView(discord.ui.View):
    def __init__(self, guild_id: int, owner_id: int, content: str):
        super().__init__(timeout=600)
        self.guild_id = guild_id
        self.owner_id = owner_id
        self.content = content

    @discord.ui.button(label="编辑提醒文案", emoji="⚠️", style=discord.ButtonStyle.primary)
    async def edit_notice(self, button, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ 仅原管理员可修改。", ephemeral=True)
        await interaction.response.send_modal(
            ThirdPartyNoticeModal(self.guild_id, self.owner_id, self.content)
        )
