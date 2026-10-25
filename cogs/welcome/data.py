# 酒馆准入题库：114 道单选、36 道多选。来源与解析见各题。
# Wiki 作者：贝露凛倾；修订说明见 docs/quiz-wiki-update.md。

QUIZ_QUESTIONS = [
    {
        "id": 1,
        "question": "酒馆是一个什么性质的软件？",
        "options": {
            "A": "一个需要付费订阅的商业聊天服务",
            "B": "一个开源、免费的本地前端界面",
            "C": "一个自带AI模型的云端APP",
            "D": "一个专注二次元画图的生成器"
        },
        "answer": "B"
    },
    {
        "id": 2,
        "question": "在运行SillyTavern之前，你的电脑/手机通常必须安装哪个环境？",
        "options": {
            "A": "Java Runtime Environment",
            "B": "Node.js",
            "C": "Python 3.10",
            "D": "C++ Redistributable"
        },
        "answer": "B"
    },
    {
        "id": 3,
        "question": "如果你想更换当前聊天的背景图片，应该在哪里操作？",
        "options": {
            "A": "必须修改酒馆的源代码文件",
            "B": "只能在API连接设置里修改",
            "C": "点击顶部栏的“背景”图标上传或选择图片",
            "D": "发送指令 /change_bg 给AI"
        },
        "answer": "C"
    },
    {
        "id": 4,
        "question": "以下哪组文件可作为常见的角色卡导入格式？",
        "options": {
            "A": "任意 JPG 截图",
            "B": "带角色数据的 PNG 或角色卡 JSON",
            "C": "任意改名为 PNG 的图片",
            "D": "只有纯文本 TXT"
        },
        "answer": "B",
        "explanation": "图片须保留角色数据；格式名称本身不能保证可导入。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 5,
        "question": "在提示词中，`{{user}}` 和 `{{char}}` 这两个宏（占位符）分别代表什么？",
        "options": {
            "A": "服务器管理员 和 机器人",
            "B": "用户名字 和 当前角色名字",
            "C": "用户名 和 角色描述",
            "D": "第一人称 和 第三人称"
        },
        "answer": "B"
    },
    {
        "id": 6,
        "question": "当你对AI生成的回复不满意时，最常用的操作是“Swipe”（刷回复），它的图标通常是？",
        "options": {
            "A": "一个垃圾桶图标",
            "B": "消息框右下角的左/右箭头",
            "C": "顶部的刷新按钮",
            "D": "发送框旁边的飞机图标"
        },
        "answer": "B"
    },
    {
        "id": 7,
        "question": "API设置中的“Temperature”（温度）参数主要影响AI输出的什么特性？",
        "options": {
            "A": "回复的生成速度",
            "B": "回复的长度",
            "C": "回复的随机性和创造性",
            "D": "回复的逻辑严密性"
        },
        "answer": "C"
    },
    {
        "id": 8,
        "question": "模型反复重复同一句话时，哪种排查方式更合理？",
        "options": {
            "A": "把所有惩罚参数直接拉满",
            "B": "删掉全部聊天记录",
            "C": "先检查提示词与重复上下文，再按模型支持范围调整参数",
            "D": "更换头像即可解决"
        },
        "answer": "C",
        "explanation": "避免把某一个采样参数当作适用于所有模型的修复方法。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 9,
        "question": "“世界书”（World Info/Lorebook）的主要作用是？",
        "options": {
            "A": "用来保存所有的聊天记录",
            "B": "一个内置的浏览器，用来查百度",
            "C": "存储背景设定、要求等",
            "D": "用来给角色卡片自动上色"
        },
        "answer": "C"
    },
    {
        "id": 10,
        "question": "世界书内容没有进入请求，应优先检查什么？",
        "options": {
            "A": "角色头像大小",
            "B": "浏览器壁纸",
            "C": "API 密钥长度",
            "D": "世界书关联、条目启用、触发条件与预算"
        },
        "answer": "D",
        "explanation": "条目的插入位置不等于触发条件，也不保证模型遵循。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 11,
        "question": "Impersonate（代写用户发言）主要用于什么？",
        "options": {
            "A": "生成一段用户角色的发言草稿",
            "B": "让模型接着最后一条 AI 消息继续写",
            "C": "切换 API 供应商",
            "D": "永久修改角色卡作者"
        },
        "answer": "A",
        "explanation": "用户角色与 AI 角色是不同的发言身份。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/personas/",
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 12,
        "question": "关于提示词中的“破限”说法，哪项更准确？",
        "options": {
            "A": "启用后必定取消模型限制",
            "B": "是一类尝试影响模型回应的提示词，效果并不保证",
            "C": "会自动增加 API 额度",
            "D": "等于替换了上游模型权重"
        },
        "answer": "B",
        "explanation": "提示词会影响请求，但不能保证模型输出或改变供应商规则。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 13,
        "question": "在角色卡编辑中，“Example Dialogue”（对话示例/样例）的最佳格式通常是？",
        "options": {
            "A": "写一段长篇的角色自传",
            "B": "只写关键词，如：开心，难过，生气",
            "C": "通过问答形式展示语气",
            "D": "留空不填，因为没用"
        },
        "answer": "C"
    },
    {
        "id": 14,
        "question": "如果想把聊天记录导出并分享给别人，最完整的格式是？",
        "options": {
            "A": ".txt 文本文件",
            "B": ".jsonl 文件",
            "C": "网页全页截图",
            "D": ".html 网页文件"
        },
        "answer": "B"
    },
    {
        "id": 15,
        "question": "请求报错提示超过模型上下文上限时，应怎样处理？",
        "options": {
            "A": "只修改界面上显示的上限数字",
            "B": "反复发送原请求",
            "C": "按实际模型限制减少输入并合理预留输出空间",
            "D": "提高显示的历史消息数量"
        },
        "answer": "C",
        "explanation": "设置值不能扩大模型实际支持的容量。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 16,
        "question": "SillyTavern的扩展功能“TTS”指的是什么？",
        "options": {
            "A": "Text To Speech（文本转语音），让角色读出回复",
            "B": "Time To Sleep（睡眠模式）",
            "C": "Total Token Size（总Token量）",
            "D": "Text Translation System（文本翻译系统）"
        },
        "answer": "A"
    },
    {
        "id": 17,
        "question": "社区常说的“哈基米”通常是指哪家公司的模型API？",
        "options": {
            "A": "OpenAI (GPT)",
            "B": "Anthropic (Claude)",
            "C": "Google (Gemini)",
            "D": "Mistral"
        },
        "answer": "C"
    },
    {
        "id": 18,
        "question": "聊天补全预设通常用于配置什么？",
        "options": {
            "A": "只保存人物头像",
            "B": "把模型安装到浏览器",
            "C": "替代所有角色卡",
            "D": "提示词条目及相关生成参数"
        },
        "answer": "D",
        "explanation": "预设属于请求配置，角色卡和模型仍有各自作用。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 19,
        "question": "如果你想让角色根据不同的情绪（如开心、生气）自动切换立绘表情，需要使用哪个功能？",
        "options": {
            "A": "Group Chat (群聊)",
            "B": "Expressions (表情/立绘扩展)",
            "C": "Vector Storage (向量存储)",
            "D": "Author's Note (作者注释)"
        },
        "answer": "B"
    },
    {
        "id": 20,
        "question": "以下哪种行为是被社区明令禁止的商业化行为？",
        "options": {
            "A": "在闲鱼倒卖免费角色卡",
            "B": "无偿分享自己的提示词",
            "C": "撰写免费的酒馆使用教程",
            "D": "自己搭建免费的公益API供群友使用"
        },
        "answer": "A"
    },
    {
        "id": 21,
        "question": "在输入框上方通常有一个“Continue”（继续）按钮，它的作用是？",
        "options": {
            "A": "保存当前对话",
            "B": "让AI接着上一段继续生成",
            "C": "切换到下一个角色",
            "D": "退出酒馆"
        },
        "answer": "B"
    },
    {
        "id": 22,
        "question": "“Author's Note”（作者注释）通常用来做什么？",
        "options": {
            "A": "写作者的联系方式",
            "B": "可以给AI提供额外要求",
            "C": "用来给对话存档",
            "D": "用来测试API延迟"
        },
        "answer": "B"
    },
    {
        "id": 23,
        "question": "若要开启“群聊模式”（Group Chat），你应该？",
        "options": {
            "A": "在API设置里选择“Multi-User”",
            "B": "手动把两个角色的名字写在一个卡里",
            "C": "点击顶部的“群组”图标创建新群组并添加成员",
            "D": "这是付费功能，无法开启"
        },
        "answer": "C"
    },
    {
        "id": 24,
        "question": "在聊天记录某一层创建剧情分支，通常意味着什么？",
        "options": {
            "A": "从该处建立另一份聊天走向，保留原分支",
            "B": "删除此前所有对话",
            "C": "自动修改模型版本",
            "D": "将角色卡上传给所有用户"
        },
        "answer": "A",
        "explanation": "聊天分支用于探索不同后续，不是 Git 分支。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 25,
        "question": "关于 Token 的说法，哪项正确？",
        "options": {
            "A": "一个 Token 永远等于一个汉字",
            "B": "它是分词器划分的文本单位，不固定等于字数",
            "C": "只用于统计图片数量",
            "D": "与输入和输出长度无关"
        },
        "answer": "B",
        "explanation": "不同文本与分词器的计数可能不同。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/advancedformatting/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 26,
        "question": "希望世界书更节省上下文，首先应考虑什么？",
        "options": {
            "A": "把每条内容都设为常驻",
            "B": "重复导入同一本世界书",
            "C": "精简内容并检查触发条件、扫描范围与预算",
            "D": "必须安装向量扩展才能使用世界书"
        },
        "answer": "C",
        "explanation": "向量检索并非普通世界书运行的必要条件。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 27,
        "question": "在角色卡面板中，“First Message”（第一条消息/开场白）的作用是？",
        "options": {
            "A": "每次AI回复都会带上这句话",
            "B": "开始新聊天时角色发出的第一句话",
            "C": "它是角色的自我介绍，不会发出来",
            "D": "它是给用户的欢迎语"
        },
        "answer": "B"
    },
    {
        "id": 28,
        "question": "当你想修改AI刚刚发送的内容（例如改错别字），应该？",
        "options": {
            "A": "无法修改，只能撤回重发",
            "B": "点击该消息右上角的“编辑”",
            "C": "在输入框输入 /edit",
            "D": "重启酒馆"
        },
        "answer": "B"
    },
    {
        "id": 29,
        "question": "要修改自己参与聊天时的名字、头像与人设，应使用什么？",
        "options": {
            "A": "模型采样配置",
            "B": "角色卡作者元数据",
            "C": "背景图片设置",
            "D": "用户角色管理（Persona Management）"
        },
        "answer": "D",
        "explanation": "用户角色管理用于设置用户在聊天中扮演的身份。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/personas/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 30,
        "question": "Data Bank 配合检索增强生成，主要做什么？",
        "options": {
            "A": "为请求提供相关文档内容",
            "B": "保证模型永久记住全部历史",
            "C": "自动训练上游模型",
            "D": "把 API 变成离线服务"
        },
        "answer": "A",
        "explanation": "检索提供额外上下文，不等于无限记忆。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/data-bank/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 31,
        "question": "在酒馆中，Depth（深度）这个参数在世界书或A注中通常表示？",
        "options": {
            "A": "内容的深刻程度",
            "B": "插入的内容距离最新一条消息的距离",
            "C": "AI思考的时间长度",
            "D": "背景图片的模糊度"
        },
        "answer": "B"
    },
    {
        "id": 32,
        "question": "想让模型理解图片内容，需要满足什么条件？",
        "options": {
            "A": "只需把文件改成 PNG",
            "B": "当前模型与连接方式支持图像输入，并正确发送图片",
            "C": "只需安装一个 UI 主题",
            "D": "任意文本模型都天然支持"
        },
        "answer": "B",
        "explanation": "图片附件的显示与模型接收图像是两回事。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 33,
        "question": "系统提示词设置好后，是否能保证模型完全遵循？",
        "options": {
            "A": "可以，所有模型都无条件遵循",
            "B": "只有提高输出长度才可保证",
            "C": "不能，还受模型能力、接口和其他上下文影响",
            "D": "只要全用大写就能保证"
        },
        "answer": "C",
        "explanation": "应检查实际发出的提示词，并测试模型表现。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 34,
        "question": "扩展插件“Stable Diffusion”在酒馆里主要用来？",
        "options": {
            "A": "加速文本生成",
            "B": "根据聊天生图",
            "C": "优化网络连接",
            "D": "翻译英文回复"
        },
        "answer": "B"
    },
    {
        "id": 35,
        "question": "关于“Regex”（正则表达式）脚本在酒馆中的用途，错误的是？",
        "options": {
            "A": "可以用来隐藏思维链",
            "B": "可以用来自动替换文本",
            "C": "可以让AI变得更聪明",
            "D": "可以用来增加API的额度"
        },
        "answer": "D"
    },
    {
        "id": 36,
        "question": "更换 UI 主题后界面异常，较合理的第一步是什么？",
        "options": {
            "A": "立即删除整个 data 目录",
            "B": "重新申请 API 密钥",
            "C": "清空所有角色卡",
            "D": "先回退该主题并排查相关美化设置"
        },
        "answer": "D",
        "explanation": "先隔离最近的界面改动，避免无关的数据损失。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 37,
        "question": "酒馆的推理内容解析功能主要用于什么？",
        "options": {
            "A": "识别接口或格式支持的推理内容并单独呈现",
            "B": "提高 API 每日额度",
            "C": "保证模型回答正确",
            "D": "为所有模型开启隐藏能力"
        },
        "answer": "A",
        "explanation": "推理的返回形式因模型和接口而异，不一定都是同一标签。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 38,
        "question": "“Summary”（摘要）功能的作用是？",
        "options": {
            "A": "给当前聊天起个标题",
            "B": "自动总结之前的聊天剧情",
            "C": "统计今天的聊天字数",
            "D": "评价AI的写作水平"
        },
        "answer": "B"
    },
    {
        "id": 39,
        "question": "通过 Git 安装的酒馆准备更新时，哪种做法更稳妥？",
        "options": {
            "A": "不备份并强制覆盖所有文件",
            "B": "备份实际数据目录、检查本地修改，再使用对应更新流程",
            "C": "只替换浏览器缓存",
            "D": "删除角色卡来加快更新"
        },
        "answer": "B",
        "explanation": "更新方式取决于安装方式，不能把 git pull 当成所有安装的通用步骤。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 40,
        "question": "在角色卡的“Advanced Definitions”（高级定义）里，通常存放？",
        "options": {
            "A": "角色的头像图片",
            "B": "背景故事、对话范例、创作者元数据",
            "C": "API密钥",
            "D": "用户的个人信息"
        },
        "answer": "B"
    },
    {
        "id": 41,
        "question": "以下哪个不是SillyTavern支持的后端API来源？",
        "options": {
            "A": "KoboldCPP",
            "B": "OobaBooga",
            "C": "NovelAI",
            "D": "Photoshop"
        },
        "answer": "D"
    },
    {
        "id": 42,
        "question": "酒馆里的“视觉小说模式”指的是什么布局模式？",
        "options": {
            "A": "让酒馆能够看小说的模式",
            "B": "一种强调立绘展示的UI布局",
            "C": "AI只说日语的模式",
            "D": "一种省电模式"
        },
        "answer": "B"
    },
    {
        "id": 43,
        "question": "连接测试成功但正式请求失败，下一步应怎么做？",
        "options": {
            "A": "认定所有参数都一定正确",
            "B": "立即购买第三方密钥",
            "C": "查看完整错误和日志，核对模型、额度及请求参数",
            "D": "只更换聊天背景"
        },
        "answer": "C",
        "explanation": "连接测试成功不能证明完整生成请求一定成功。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 44,
        "question": "“Quick Reply”（快速回复）栏通常用来放什么？",
        "options": {
            "A": "常用的指令、描写片段或控制脚本",
            "B": "角色的表情包",
            "C": "广告链接",
            "D": "背景音乐"
        },
        "answer": "A"
    },
    {
        "id": 45,
        "question": "预设要求配置特定的推理标签或配套正则时，应如何处理？",
        "options": {
            "A": "同时启用所有历史正则",
            "B": "随意复制别的模型标签",
            "C": "认为配置后模型一定不会拒答",
            "D": "按作者说明核对适用模型与配套设置，再测试"
        },
        "answer": "D",
        "explanation": "配套设置主要解决兼容与展示问题，不保证改变模型限制。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 46,
        "question": "SillyTavern的数据（角色卡、聊天记录）默认保存在哪里？",
        "options": {
            "A": "云端服务器，作者能看到",
            "B": "本地的 /data 文件夹内",
            "C": "Windows注册表里",
            "D": "内存里，关机就没了"
        },
        "answer": "B"
    },
    {
        "id": 47,
        "question": "关于模型推理内容，哪项说法更准确？",
        "options": {
            "A": "不同模型和接口可能用不同形式返回，也可能不提供",
            "B": "所有模型都必定返回 think 标签",
            "C": "看不到推理就说明没有消耗 Token",
            "D": "解析推理会改变 API 余额"
        },
        "answer": "A",
        "explanation": "不能以某一种标签代表所有模型的返回形式。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 48,
        "question": "在酒馆中，`Main Prompt`，`NSFW Prompt`，`Jailbreak Prompt` 的生效顺序通常由什么决定？",
        "options": {
            "A": "随机决定",
            "B": "由预设条目排序决定",
            "C": "总是 Jailbreak 最后",
            "D": "总是 Main Prompt 最后"
        },
        "answer": "B"
    },
    {
        "id": 49,
        "question": "备份酒馆用户资料时，应优先确认并备份哪里？",
        "options": {
            "A": "浏览器下载目录即可",
            "B": "当前实例实际使用的数据目录，默认通常是 data",
            "C": "只保存桌面快捷方式",
            "D": "只保存程序图标"
        },
        "answer": "B",
        "explanation": "还应记录扩展来源与自定义配置；远程部署的数据在服务器上。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 50,
        "question": "Streaming（流式传输）的基本含义是什么？",
        "options": {
            "A": "每次请求都免费",
            "B": "只能输出一个字符",
            "C": "生成过程中分块返回内容",
            "D": "保证一定比非流式生成更多内容"
        },
        "answer": "C",
        "explanation": "分块不是严格逐字，也不代表改变模型权限。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 51,
        "question": "根据社区《核心宗旨》，本社区的主要定位和接纳对象是？",
        "options": {
            "A": "全年龄向的二次元绘画交流群",
            "B": "面向全性别的通用人工智能技术讨论组",
            "C": "【女性酒馆交流群】，仅限女性，且以酒馆平台为主",
            "D": "商业化的第三方API倒卖中转站"
        },
        "answer": "C"
    },
    {
        "id": 52,
        "question": "关于“非酒馆平台”的使用规定，以下哪项行为是严格禁止的？",
        "options": {
            "A": "在自己的电脑上本地部署SillyTavern",
            "B": "使用自己搭建的云端酒馆（且不涉及商业化）",
            "C": "未经允许将群内资源导入第三方小手机、Omate、Tavo等非酒馆平台",
            "D": "在群内讨论如何优化前端CSS"
        },
        "answer": "C"
    },
    {
        "id": 53,
        "question": "为什么社区坚决反对使用“商业化的第三方云酒馆”？",
        "options": {
            "A": "因为它们界面太丑",
            "B": "因为它们收费太贵",
            "C": "因为数据都在贩子手中，容易泄露隐私",
            "D": "因为它们不支持中文"
        },
        "answer": "C"
    },
    {
        "id": 54,
        "question": "在社区内遭遇“贩子”（第三方API商家）相关话题时，正确的做法是？",
        "options": {
            "A": "询问哪家店的模型更便宜",
            "B": "分享自己购买的渠道链接给群友",
            "C": "不提及、不推荐、不分享，且社区不负责解答相关问题",
            "D": "公开挂出商家的名字进行宣传"
        },
        "answer": "C"
    },
    {
        "id": 55,
        "question": "关于“二传”（二次传播）的规则，若作品无额外声明，默认为？",
        "options": {
            "A": "可以随意转载到Github",
            "B": "只要注明出处就可以转载",
            "C": "禁止二传",
            "D": "可以转载到其他全女性社区"
        },
        "answer": "C"
    },
    {
        "id": 56,
        "question": "以下哪项内容属于社区的“绝对红线”，严禁出现？",
        "options": {
            "A": "关于GB（女攻男受）的讨论",
            "B": "代孕、毒品严重违反公序良俗的内容",
            "C": "关于AI模型参数的争论",
            "D": "对于角色卡设定的吐槽"
        },
        "answer": "B"
    },
    {
        "id": 57,
        "question": "如果某位成员在公屏聊起了“过激XP”或“G向”内容，这违反了哪条守则？",
        "options": {
            "A": "反商业化守则",
            "B": "尊重原创守则",
            "C": "聊天守则中的禁止敏感话题",
            "D": "反二传守则"
        },
        "answer": "C"
    },
    {
        "id": 58,
        "question": "社区对于“融梗”（过度借鉴他人创意）的判定标准和处理态度是？",
        "options": {
            "A": "只要改了名字就不算融梗",
            "B": "禁止任何未经允许的过度借鉴、抄袭",
            "C": "同人创作不存在融梗说法",
            "D": "只要不商用就可以随意融梗"
        },
        "answer": "B"
    },
    {
        "id": 59,
        "question": "对于严重违规行为（如倒卖、恶意引战），社区将采取的处罚是？",
        "options": {
            "A": "口头警告一次",
            "B": "罚抄群规100遍",
            "C": "踢群、DC频道封禁，公示，并要求提供删除产出的录屏",
            "D": "仅禁言1小时"
        },
        "answer": "C"
    },
    {
        "id": 60,
        "question": "规则最后提到的社区“每日仪式感”活动是？",
        "options": {
            "A": "集体向管理员问好",
            "B": "准时唱奇米蛋之歌",
            "C": "分享今日的早餐照片",
            "D": "打卡签到领取积分"
        },
        "answer": "B"
    },
    {
        "id": 61,
        "question": "高级格式设置中的 Context Template 主要适用于哪类连接？",
        "options": {
            "A": "所有连接都必须依靠它",
            "B": "只用于图片生成",
            "C": "只用于语音合成",
            "D": "文本补全；聊天补全主要使用提示词管理器"
        },
        "answer": "D",
        "explanation": "不要把文本补全模板的配置方式直接套到聊天补全。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/advancedformatting/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 62,
        "question": "当你想在世界书（World Info）中实现“只有当条目A触发时，条目B才有可能被触发”的逻辑，应如何设置？",
        "options": {
            "A": "将条目B设为常驻（Constant）",
            "B": "在条目B的“Secondary Keys”中填入条目A的关键词",
            "C": "利用递归扫描机制，条目A的内容包含条目B的关键词，且条目B非常驻、未排除递归",
            "D": "把条目A和B写在同一个卡片里"
        },
        "answer": "C"
    },
    {
        "id": 63,
        "question": "世界书的附加关键词逻辑应如何理解？",
        "options": {
            "A": "结合主关键词、附加关键词及选定逻辑共同判断",
            "B": "任何感叹号都会自动禁止条目",
            "C": "只由条目标题决定",
            "D": "设置后完全不受启用状态影响"
        },
        "answer": "A",
        "explanation": "不能把简单符号写法当作所有版本统一的触发规则。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 64,
        "question": "在采样参数中，`Top P` (Nucleus Sampling) 的含义是？",
        "options": {
            "A": "从概率最高的词中截取总概率达到P的集合进行随机选择",
            "B": "强制模型选择概率最高的P个词",
            "C": "惩罚重复的词汇",
            "D": "控制输出的Token数量上限"
        },
        "answer": "A"
    },
    {
        "id": 65,
        "question": "若你在使用正则脚本（Regex）时勾选了“Run on Edit”（在编辑时运行），会发生什么？",
        "options": {
            "A": "脚本会被永久删除",
            "B": "当你手动修改了聊天记录并保存时，该脚本会再次处理这段文本",
            "C": "编辑功能会被禁用",
            "D": "会自动把你的修改内容发送给开发者"
        },
        "answer": "B"
    },
    {
        "id": 66,
        "question": "想确认某段历史或设定是否实际发给模型，应该怎么做？",
        "options": {
            "A": "只看聊天窗口是否能滚动到它",
            "B": "查看实际请求或提示词明细",
            "C": "只看头像是否加载",
            "D": "只看最后一条回复长度"
        },
        "answer": "B",
        "explanation": "界面可见内容不一定等于请求上下文。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 67,
        "question": "STScript（SillyTavern内置脚本语言,如隐藏上下文）通常以什么符号开头来执行命令？",
        "options": {
            "A": "#",
            "B": "/",
            "C": "!",
            "D": ">"
        },
        "answer": "B"
    },
    {
        "id": 68,
        "question": "想查看一次回复实际使用了哪些提示词内容，可以优先使用什么？",
        "options": {
            "A": "删除预设",
            "B": "修改用户头像",
            "C": "回复的提示词明细或请求检查工具",
            "D": "换一个背景"
        },
        "answer": "C",
        "explanation": "检查实际请求比猜测条目是否生效更可靠。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 69,
        "question": "系统提示词占用了大量上下文预算，会有什么直接影响？",
        "options": {
            "A": "永久降低模型参数量",
            "B": "自动增加余额",
            "C": "保证生成更长回复",
            "D": "留给其他输入内容和输出的空间可能减少"
        },
        "answer": "D",
        "explanation": "上下文预算有限，不宜用“必定降智”代替具体解释。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 70,
        "question": "世界书中的`preventRecursion`（防止递归）选项如果被勾选，意味着？",
        "options": {
            "A": "该条目永远不会被触发",
            "B": "该条目触发后，其内容**不会**再被用来扫描触发其他世界书条目",
            "C": "该条目不能包含递归函数",
            "D": "该条目只能在最后被触发"
        },
        "answer": "B"
    },
    {
        "id": 71,
        "question": "在酒馆中使用“TTS”（语音合成）时，`Provider` 指的是？",
        "options": {
            "A": "提供语音合成服务的引擎来源",
            "B": "网络提供商",
            "C": "角色的配音演员",
            "D": "音箱的品牌"
        },
        "answer": "A"
    },
    {
        "id": 72,
        "question": "回复到达最大输出长度而被截断时，应优先检查什么？",
        "options": {
            "A": "停止原因、输出上限与模型限制",
            "B": "角色卡头像颜色",
            "C": "Discord 昵称",
            "D": "浏览器收藏夹数量"
        },
        "answer": "A",
        "explanation": "不能仅凭截断判断模型为何继续生成。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 73,
        "question": "如果你的模型反代出现了“429 Too Many Requests”错误，最可能的原因是？",
        "options": {
            "A": "网络链接不佳",
            "B": "API的额度已用尽或请求频率过高",
            "C": "该模型不支持酒馆内使用",
            "D": "上下文超出最大长度"
        },
        "answer": "B"
    },
    {
        "id": 75,
        "question": "在群聊模式（Group Chat）中，如果想让某个角色暂时“闭嘴”不参与自动发言，可以？",
        "options": {
            "A": "把它踢出群",
            "B": "在群聊侧边栏勾选该角色的“Mute”（静音）选项",
            "C": "把它的角色卡删了",
            "D": "把它的名字改成“System”"
        },
        "answer": "B"
    },
    {
        "id": 76,
        "question": "前端角色卡显示不正常时，首先应如何排查？",
        "options": {
            "A": "所有角色卡都必须安装相同扩展",
            "B": "查看作者依赖说明，核对扩展、版本与相关正则",
            "C": "关闭全部安全设置即可",
            "D": "把 PNG 改名为 JPG"
        },
        "answer": "B",
        "explanation": "依赖取决于卡的实现，不存在适用于所有前端卡的唯一插件。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 77,
        "question": "当正则脚本的放置位置（Placement）选择为“World Info”时，脚本会对哪些内容生效？",
        "options": {
            "A": "所有聊天记录",
            "B": "仅针对被激活插在上下文中的世界书内容",
            "C": "仅针对世界书的标题",
            "D": "仅针对未激活的条目"
        },
        "answer": "B"
    },
    {
        "id": 78,
        "question": "社区规则中提到，对于“代孕、毒品、虐待儿童”等红线内容，社区的态度是？",
        "options": {
            "A": "可以在私下讨论",
            "B": "只要是虚构的就没关系",
            "C": "坚决反对，严禁出现，这是底线",
            "D": "视剧情需要而定"
        },
        "answer": "C"
    },
    {
        "id": 79,
        "question": "在高级格式设置中，“Tokenizer”（分词器）的选择应该依据？",
        "options": {
            "A": "选择名字最好听的",
            "B": "必须选择“Best”",
            "C": "应选择与当前连接的模型架构相匹配的分词器",
            "D": "随便选，不影响"
        },
        "answer": "C"
    },
    {
        "id": 80,
        "question": "世界书有主关键词和附加关键词时，排查未触发应检查什么？",
        "options": {
            "A": "只看文件大小",
            "B": "把所有关键词删除",
            "C": "两组关键词、选定逻辑及扫描范围是否满足条件",
            "D": "只看角色名字长短"
        },
        "answer": "C",
        "explanation": "附加关键词逻辑与扫描范围共同影响触发。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 81,
        "question": "关于社区内作品的“二改”要求，正确的态度是？",
        "options": {
            "A": "既然下载了就是我的，想怎么改怎么改",
            "B": "必须在获得原作者授权或遵守原作者明确的二改规定的前提下进行",
            "C": "只要不商用，可以随意二改并发布",
            "D": "二改后必须说是自己原创的"
        },
        "answer": "B"
    },
    {
        "id": 82,
        "question": "“Presence Penalty”（存在惩罚）和“Frequency Penalty”（频率惩罚）的区别在于？",
        "options": {
            "A": "没有区别",
            "B": "前者确实存在就罚，后者根据出现频率累加惩罚；前者抑制话题重复，后者抑制逐字重复",
            "C": "前者针对名词，后者针对动词",
            "D": "前者针对输入，后者针对输出"
        },
        "answer": "B"
    },
    {
        "id": 83,
        "question": "Moving UI 的主要作用是什么？",
        "options": {
            "A": "修改模型采样温度",
            "B": "自动翻译角色卡",
            "C": "为 API 增加调用额度",
            "D": "调整界面面板的位置布局"
        },
        "answer": "D",
        "explanation": "它是界面布局功能，不只指某一种设备。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 84,
        "question": "使用不受信任的他人反向代理时，应重点考虑什么？",
        "options": {
            "A": "请求内容与密钥可能经过对方系统",
            "B": "必然提升所有模型质量",
            "C": "必然免费且稳定",
            "D": "会自动获得官方授权"
        },
        "answer": "A",
        "explanation": "自建且受控的反代与陌生商家服务不应混为一谈。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f1b6f"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 85,
        "question": "在写Prompt时，`{{char}}` 和 `{{user}}` 这类变量在发送给模型前会发生什么？",
        "options": {
            "A": "会被原样发送",
            "B": "会被自动替换为当前实际的角色名和用户名",
            "C": "会被删掉",
            "D": "会变成星号"
        },
        "answer": "B"
    },
    {
        "id": 86,
        "question": "SillyTavern的“Web Search”（联网搜索）扩展通常依赖于？",
        "options": {
            "A": "直接读取你的浏览器历史",
            "B": "连接搜索引擎来获取实时信息",
            "C": "模型自带的知识库",
            "D": "无法联网"
        },
        "answer": "B"
    },
    {
        "id": 87,
        "question": "如果你的世界书条目设置了“Sticky”（粘性），意味着？",
        "options": {
            "A": "它很难被删除",
            "B": "一旦触发，它会在后续的 `N` 轮对话中强制保持激活状态",
            "C": "它会粘在屏幕最上方",
            "D": "它会复制很多份"
        },
        "answer": "B"
    },
    {
        "id": 88,
        "question": "社区规则中提到“我们谁也不比谁高贵”是为了强调？",
        "options": {
            "A": "大家都很穷",
            "B": "不管是大佬还是小白，不管是哪种性向或XP，大家都应平等尊重",
            "C": "禁止使用付费模型",
            "D": "禁止发表情包"
        },
        "answer": "B"
    },
    {
        "id": 89,
        "question": "如果AI生成的回复中包含不需要的代码块或特殊符号，最好使用什么工具去除？",
        "options": {
            "A": "每次手动删",
            "B": "利用正则脚本来自动清洗",
            "C": "骂AI一顿",
            "D": "重新安装系统"
        },
        "answer": "B"
    },
    {
        "id": 90,
        "question": "关于“Prompt Injection”（提示词注入）攻击，在酒馆语境下通常指？",
        "options": {
            "A": "黑客攻击你的电脑",
            "B": "一种利用特殊指令让模型无视已有设定的行为",
            "C": "给模型打针",
            "D": "输入的内容太长了"
        },
        "answer": "B"
    },
    {
        "id": 91,
        "question": "如果群友分享了一个很好的预设，但你用起来效果很差，最可能的原因不包括？",
        "options": {
            "A": "你们使用的模型不同",
            "B": "你们的采样参数不同",
            "C": "你的电脑颜色设置不同",
            "D": "你的角色卡写法与该预设不兼容"
        },
        "answer": "C"
    },
    {
        "id": 92,
        "question": "关于“第三方API/中转平台”，以下哪种描述符合社区对违规行为的认定？",
        "options": {
            "A": "非模型官方提供、以中转聚合形式收费提供调用服务",
            "B": "分享公益免费的API",
            "C": "模型官方提供的付费API(如DeepSeek)",
            "D": "自行搭建的模型反代"
        },
        "answer": "A"
    },
    {
        "id": 93,
        "question": "以下哪一项行为在社区内是被严格禁止的？",
        "options": {
            "A": "在闲聊频道分享自己的作品",
            "B": "推荐某中转API平台计费的模型调用服务",
            "C": "询问预设的配置问题",
            "D": "发布自己制作的作品并保留署名"
        },
        "answer": "B"
    },
    {
        "id": 94,
        "question": "对于“付费酒馆美化服务”，社区的态度是？",
        "options": {
            "A": "只要质量好可以适当推荐",
            "B": "不购买、不推荐、不教学、不协助",
            "C": "允许作者接单但需给社区分成",
            "D": "默许私下交易"
        },
        "answer": "B"
    },
    {
        "id": 95,
        "question": "如果社区成员被查实使用了第三方付费内容，管理组可能采取的措施是？",
        "options": {
            "A": "立即永久封禁",
            "B": "提醒一次后不再处理",
            "C": "暂时移除浏览权限并送回答题区重新学习",
            "D": "忽略该行为"
        },
        "answer": "C"
    },
    {
        "id": 96,
        "question": "成员执意使用第三方付费服务时遇到报错，正确做法是？",
        "options": {
            "A": "在社区公共频道发帖要求大家帮忙排查",
            "B": "自行解决",
            "C": "私信管理要求提供技术支持",
            "D": "在社区内公开声讨该服务商"
        },
        "answer": "B"
    },
    {
        "id": 97,
        "question": "加入社区即代表你已声明以下哪项？",
        "options": {
            "A": "会继续从事AIRP商业化行为",
            "B": "已年满18岁，并承诺不进行商业化或网暴行为",
            "C": "将提供至少一份创作内容",
            "D": "同意管理员可以随时编辑你的作品"
        },
        "answer": "B"
    },
    {
        "id": 98,
        "question": "以下哪种行为直接触碰社区红线？",
        "options": {
            "A": "在频道发表不成熟的观点",
            "B": "忘记一次署名并立即补上",
            "C": "查实存在商业化行为",
            "D": "向管理求助"
        },
        "answer": "C"
    },
    {
        "id": 99,
        "question": "当你在社区内遇到无法解决的争议或问题时，最恰当的做法是？",
        "options": {
            "A": "在公共频道与对方持续争论",
            "B": "叫朋友来加入争吵",
            "C": "@超级小蛋 或私信超级小蛋求助",
            "D": "发到墙内平台曝光"
        },
        "answer": "C"
    },
    {
        "id": 100,
        "question": "如果作者在作品说明中声明“禁止二改”，其他成员应当？",
        "options": {
            "A": "可以进行二改但仅限私下使用",
            "B": "尊重作者意愿，不进行二改",
            "C": "无视声明，共享精神就是可以随意改",
            "D": "向管理组申请解除限制"
        },
        "answer": "B"
    },
    {
        "id": 101,
        "question": "未经作品权利人许可，将社区作品转载至非SillyTavern平台属于什么行为？",
        "options": {
            "A": "正常分享",
            "B": "违规二传",
            "C": "促进交流",
            "D": "作者应当感到荣幸"
        },
        "answer": "B"
    },
    {
        "id": 102,
        "question": "预设、正则和世界书都可能是 JSON，导入时应怎么区分？",
        "options": {
            "A": "按文件大小猜测",
            "B": "依据资源说明与内容，进入对应功能导入",
            "C": "全部放入角色卡导入框",
            "D": "统一改成 PNG"
        },
        "answer": "B",
        "explanation": "相同后缀不代表相同资源类型。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 103,
        "question": "下载的角色图片丢失了角色数据，改后缀能修复吗？",
        "options": {
            "A": "改成 PNG 就能恢复",
            "B": "重命名作者即可",
            "C": "不能，应重新获取保留元数据的原文件",
            "D": "修改头像尺寸即可"
        },
        "answer": "C",
        "explanation": "文件改名不会补回已丢失的元数据。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 104,
        "question": "切换预设后显示异常，发现旧全局正则仍开启，应怎么做？",
        "options": {
            "A": "把全部正则再导入一次",
            "B": "删除全部世界书",
            "C": "更换服务器昵称",
            "D": "核对作用范围并关闭不匹配的旧规则"
        },
        "answer": "D",
        "explanation": "全局规则可能影响新的预设或角色。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7",
            "https://docs.sillytavern.app/extensions/regex/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 105,
        "question": "只在编辑器里打开一本世界书，能否据此确认它已对当前聊天生效？",
        "options": {
            "A": "不能，还要确认关联、启用和触发条件",
            "B": "可以，编辑就等于启用",
            "C": "可以，文件名不为空即可",
            "D": "可以，与任何条件无关"
        },
        "answer": "A",
        "explanation": "编辑对象与实际激活来源不是同一个概念。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861",
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 106,
        "question": "想只给当前角色使用某本世界书，应该怎么做？",
        "options": {
            "A": "开启所有全局世界书",
            "B": "关联到该角色并核对条目条件",
            "C": "只改世界书文件名",
            "D": "把书名写进浏览器标签"
        },
        "answer": "B",
        "explanation": "全局关联与角色关联的作用范围不同。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7",
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 107,
        "question": "正则设置为仅修改显示时，应如何理解？",
        "options": {
            "A": "已经修改上游模型权重",
            "B": "会增加上下文上限",
            "C": "显示变化不等于发给模型的提示词也变化",
            "D": "一定删除磁盘里的原始记录"
        },
        "answer": "C",
        "explanation": "显示处理和提示词处理的作用对象不同。",
        "sources": [
            "https://docs.sillytavern.app/extensions/regex/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 108,
        "question": "排查一条正则替换错误时，适合先用什么方式？",
        "options": {
            "A": "删除全部聊天记录",
            "B": "关闭 API 账户",
            "C": "反复上传同一角色卡",
            "D": "在正则测试模式中输入样本文本比较结果"
        },
        "answer": "D",
        "explanation": "先用小样本定位匹配与替换问题。",
        "sources": [
            "https://docs.sillytavern.app/extensions/regex/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 109,
        "question": "快速回复集导入后没有看到按钮，应检查什么？",
        "options": {
            "A": "是否启用并加入合适的快速回复范围",
            "B": "世界书标题是否全大写",
            "C": "角色头像是否透明",
            "D": "API 密钥是否以固定字母开头"
        },
        "answer": "A",
        "explanation": "仅导入不一定完成启用或关联。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 110,
        "question": "更换预设后 API 连接也改变了，应该优先核对什么？",
        "options": {
            "A": "背景透明度",
            "B": "预设是否绑定了连接配置",
            "C": "聊天气泡颜色",
            "D": "角色图片宽度"
        },
        "answer": "B",
        "explanation": "预设与连接的关联可能导致切换时连接一起改变。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f1b6f"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 111,
        "question": "主角色世界书与额外关联的世界书在导出角色卡时有什么区别？",
        "options": {
            "A": "所有关联内容都必定自动打包",
            "B": "所有世界书都无法导出",
            "C": "主世界书可嵌入角色卡，额外关联不应假定自动随卡导出",
            "D": "只由角色头像大小决定"
        },
        "answer": "C",
        "explanation": "分享前需核对导出内容与依赖。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 112,
        "question": "Persona 的标题和人设描述有什么区别？",
        "options": {
            "A": "标题一定比系统提示词优先",
            "B": "标题是 API 密钥",
            "C": "描述只影响头像",
            "D": "标题用于管理展示，描述可参与提示词构建"
        },
        "answer": "D",
        "explanation": "不要把管理用标题误当成模型收到的人设正文。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/personas/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 113,
        "question": "角色专属 Data Bank 附件是否会随角色卡自动导出？",
        "options": {
            "A": "不应假定会，官方文档说明这些附件不随卡导出",
            "B": "一定会全部导出",
            "C": "只要头像为 PNG 就会",
            "D": "与文件数量奇偶有关"
        },
        "answer": "A",
        "explanation": "角色可用附件与角色卡导出数据不同。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/data-bank/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 114,
        "question": "导入别人分享的预设前，先阅读什么最有帮助？",
        "options": {
            "A": "只看下载次数",
            "B": "适用模型、版本、配套资源与启用说明",
            "C": "只看作者头像",
            "D": "只看文件名长短"
        },
        "answer": "B",
        "explanation": "先确认适用环境，减少导入后的兼容问题。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 115,
        "question": "正则脚本被禁用后，应如何理解？",
        "options": {
            "A": "仍会始终处理全部文本",
            "B": "仅对某一种语言失效",
            "C": "不会按正常启用流程执行，需先检查开关",
            "D": "会自动删除所有历史消息"
        },
        "answer": "C",
        "explanation": "排查时先确认规则是否启用及其作用范围。",
        "sources": [
            "https://docs.sillytavern.app/extensions/regex/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 116,
        "type": "multiple",
        "question": "资源导入前应检查哪些事项？",
        "options": {
            "A": "作者要求的配套扩展或正则",
            "B": "只要后缀是 JSON 就能混用",
            "C": "资源类型及对应导入入口",
            "D": "适用版本与模型"
        },
        "answers": [
            "A",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/f73b7"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 117,
        "type": "multiple",
        "question": "世界书没有进入请求时，哪些检查有帮助？",
        "options": {
            "A": "角色头像颜色",
            "B": "预算是否足够",
            "C": "是否关联到当前上下文",
            "D": "条目是否启用且满足触发条件"
        },
        "answers": [
            "B",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/worldinfo/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 118,
        "type": "multiple",
        "question": "以下哪些属于合理的正则排错步骤？",
        "options": {
            "A": "区分显示处理和提示词处理",
            "B": "检查启用状态和作用范围",
            "C": "把所有全局规则一起打开",
            "D": "在测试模式里验证样本文本"
        },
        "answers": [
            "A",
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://docs.sillytavern.app/extensions/regex/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 119,
        "type": "multiple",
        "question": "用户角色管理（Persona）可以涉及哪些设置？",
        "options": {
            "A": "更改上游模型权重",
            "B": "人设描述",
            "C": "名字与头像",
            "D": "将人设绑定到聊天"
        },
        "answers": [
            "B",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/personas/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 120,
        "type": "multiple",
        "question": "以下关于请求上下文的说法哪些正确？",
        "options": {
            "A": "可能包含历史消息",
            "B": "只包含最后一条输入",
            "C": "可能包含角色描述和用户人设",
            "D": "可能包含激活的世界书内容"
        },
        "answers": [
            "A",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://docs.sillytavern.app/usage/prompts/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 121,
        "type": "multiple",
        "question": "关于 Data Bank 的说法哪些正确？",
        "options": {
            "A": "保证无限记忆",
            "B": "附件可有不同可用范围",
            "C": "角色附件一定随卡导出",
            "D": "可管理用于检索的文档"
        },
        "answers": [
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://docs.sillytavern.app/usage/core-concepts/data-bank/"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 122,
        "type": "multiple",
        "question": "哪些操作有助于保留可用的角色卡文件？",
        "options": {
            "A": "获取作者提供的原文件",
            "B": "把 JPG 改名成 PNG",
            "C": "只保存聊天截图",
            "D": "确认文件保留角色数据"
        },
        "answers": [
            "A",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 123,
        "type": "multiple",
        "question": "哪些资源可能采用 JSON 格式，但需要分别导入？",
        "options": {
            "A": "正则规则",
            "B": "任何视频文件",
            "C": "世界书",
            "D": "预设"
        },
        "answers": [
            "A",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 124,
        "type": "multiple",
        "question": "哪些做法能减少切换预设后的正则冲突？",
        "options": {
            "A": "停用不匹配的旧全局正则",
            "B": "核对作者配套说明",
            "C": "无条件启用全部历史规则",
            "D": "检查规则作用范围"
        },
        "answers": [
            "A",
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 125,
        "type": "multiple",
        "question": "以下哪些信息有助于排查资源导入问题？",
        "options": {
            "A": "具体错误提示",
            "B": "电脑外壳颜色",
            "C": "资源类型",
            "D": "实际文件格式"
        },
        "answers": [
            "A",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 126,
        "type": "multiple",
        "question": "关于备份，哪些做法合理？",
        "options": {
            "A": "把删除原数据当作备份",
            "B": "保留独立备份副本",
            "C": "记录自定义配置与扩展来源",
            "D": "确认实际数据目录"
        },
        "answers": [
            "B",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 127,
        "type": "multiple",
        "question": "更新酒馆之前，哪些准备较合理？",
        "options": {
            "A": "备份数据",
            "B": "直接强制覆盖所有文件",
            "C": "检查本地修改",
            "D": "检查安装方式"
        },
        "answers": [
            "A",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 128,
        "type": "multiple",
        "question": "关于流式返回，哪些说法正确？",
        "options": {
            "A": "生成过程中可分块收到内容",
            "B": "保证不再受输出上限影响",
            "C": "等于免费调用接口",
            "D": "每一块不一定恰好一个字"
        },
        "answers": [
            "A",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 129,
        "type": "multiple",
        "question": "关于上下文长度，哪些理解正确？",
        "options": {
            "A": "拉满就保证永不遗忘",
            "B": "设置数字不能扩大模型容量",
            "C": "要考虑模型实际限制",
            "D": "长设定会占用输入空间"
        },
        "answers": [
            "B",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 130,
        "type": "multiple",
        "question": "遇到上下文超限，哪些处理方向合理？",
        "options": {
            "A": "核对模型限制",
            "B": "合理预留输出空间",
            "C": "精简发送的输入",
            "D": "只更改角色头像"
        },
        "answers": [
            "A",
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 131,
        "type": "multiple",
        "question": "以下哪些不属于预设能保证做到的事？",
        "options": {
            "A": "配置提示词条目",
            "B": "无限增加 API 额度",
            "C": "改变上游模型权重",
            "D": "永久取消供应商规则"
        },
        "answers": [
            "B",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 132,
        "type": "multiple",
        "question": "关于聊天分支，哪些说法合理？",
        "options": {
            "A": "必定删除原聊天",
            "B": "不等于更换 Git 分支",
            "C": "可以探索不同的后续走向",
            "D": "自动升级模型"
        },
        "answers": [
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 133,
        "type": "multiple",
        "question": "关于角色与用户人设，哪些说法正确？",
        "options": {
            "A": "用户人设描述自己扮演的身份",
            "B": "两者都可能影响请求内容",
            "C": "AI 角色卡描述对方角色",
            "D": "两者只能共用同一份头像"
        },
        "answers": [
            "A",
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 134,
        "type": "multiple",
        "question": "关于 Persona 绑定，哪些说法正确？",
        "options": {
            "A": "可以绑定到角色",
            "B": "可以绑定到聊天",
            "C": "绑定就是训练模型",
            "D": "绑定会自动分享账号密码"
        },
        "answers": [
            "A",
            "B"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 135,
        "type": "multiple",
        "question": "哪些内容可能在提示词中占用空间？",
        "options": {
            "A": "角色设定",
            "B": "历史对话",
            "C": "未被发送的本地壁纸文件",
            "D": "世界书正文"
        },
        "answers": [
            "A",
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 136,
        "type": "multiple",
        "question": "检查实际提示词有助于确认哪些问题？",
        "options": {
            "A": "历史消息是否包含在请求中",
            "B": "设定是否进入请求",
            "C": "相关条目是否被插入",
            "D": "模型是否绝对保证遵循全部内容"
        },
        "answers": [
            "A",
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 137,
        "type": "multiple",
        "question": "关于提示词效果，哪些理解合理？",
        "options": {
            "A": "需检查实际请求并测试",
            "B": "不同接口可能需要不同配置",
            "C": "写成系统消息就百分百服从",
            "D": "模型能力会影响效果"
        },
        "answers": [
            "A",
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 138,
        "type": "multiple",
        "question": "关于世界书关联，哪些说法正确？",
        "options": {
            "A": "可以存在全局来源",
            "B": "在编辑器打开就一定生效",
            "C": "关联后无需考虑任何触发条件",
            "D": "可以存在角色专属来源"
        },
        "answers": [
            "A",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 139,
        "type": "multiple",
        "question": "世界书编辑时，哪些做法更合理？",
        "options": {
            "A": "假定条目标题一定发送给模型",
            "B": "检查关键词和触发逻辑",
            "C": "控制不必要的长内容",
            "D": "正文写清楚要提供的信息"
        },
        "answers": [
            "B",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 140,
        "type": "multiple",
        "question": "世界书内容缺失时，哪些因素值得核对？",
        "options": {
            "A": "可用预算",
            "B": "是否满足触发条件",
            "C": "昵称是否含表情",
            "D": "条目是否被禁用"
        },
        "answers": [
            "A",
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 141,
        "type": "multiple",
        "question": "分享带世界书的角色时，哪些做法合理？",
        "options": {
            "A": "只检查头像好不好看",
            "B": "单独检查额外关联的依赖",
            "C": "假定所有外部文件都会自动打包",
            "D": "核对主世界书是否嵌入"
        },
        "answers": [
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 142,
        "type": "multiple",
        "question": "正则可以用于哪些操作？",
        "options": {
            "A": "调整文本显示格式",
            "B": "替换匹配内容",
            "C": "查找匹配文本",
            "D": "增加供应商余额"
        },
        "answers": [
            "A",
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 143,
        "type": "multiple",
        "question": "调试正则时，哪些信息值得检查？",
        "options": {
            "A": "角色生日是否为今天",
            "B": "启用状态",
            "C": "匹配表达式",
            "D": "替换内容"
        },
        "answers": [
            "B",
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 144,
        "type": "multiple",
        "question": "关于正则作用范围，哪些理解正确？",
        "options": {
            "A": "任意规则都只影响当前一条消息",
            "B": "角色专属规则限定于对应角色",
            "C": "全局规则可能影响多个角色",
            "D": "显示变化一定意味着原始存档被删除"
        },
        "answers": [
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 145,
        "type": "multiple",
        "question": "正则测试模式可以帮助完成哪些工作？",
        "options": {
            "A": "对比替换后的输出",
            "B": "输入样本文本",
            "C": "核对匹配是否符合预期",
            "D": "提高模型的上下文上限"
        },
        "answers": [
            "A",
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 146,
        "type": "multiple",
        "question": "关于 Data Bank 文档，哪些说法正确？",
        "options": {
            "A": "所有附件都自动随角色卡导出",
            "B": "等于修改模型训练数据",
            "C": "可以有全局范围",
            "D": "可以有聊天范围"
        },
        "answers": [
            "C",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 147,
        "type": "multiple",
        "question": "检索增强生成与永久记忆有哪些区别？",
        "options": {
            "A": "检索为当前请求提供相关材料",
            "B": "开启后就不再需要上下文预算",
            "C": "等于无限保存到模型权重",
            "D": "并不保证永远记住全部聊天"
        },
        "answers": [
            "A",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 148,
        "type": "multiple",
        "question": "遇到前端角色卡显示异常，哪些检查合理？",
        "options": {
            "A": "相关扩展版本",
            "B": "作者要求的依赖",
            "C": "配套正则是否启用",
            "D": "先删除整个酒馆数据目录"
        },
        "answers": [
            "A",
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 149,
        "type": "multiple",
        "question": "快速回复按钮没有出现，哪些检查合理？",
        "options": {
            "A": "是否正确导入回复集",
            "B": "回复集是否关联到合适范围",
            "C": "API 密钥是否包含角色名",
            "D": "是否启用了快速回复"
        },
        "answers": [
            "A",
            "B",
            "D"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 150,
        "type": "multiple",
        "question": "关于文本补全与聊天补全，哪些说法正确？",
        "options": {
            "A": "可以无条件照搬另一种连接的配置",
            "B": "两者的提示词配置方式可能不同",
            "C": "聊天补全主要使用提示词管理器",
            "D": "所有高级格式设置都适用于全部连接"
        },
        "answers": [
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    },
    {
        "id": 151,
        "type": "multiple",
        "question": "哪类信息适合写进资源的使用说明？",
        "options": {
            "A": "所需扩展或配套文件",
            "B": "适用模型和版本",
            "C": "导入和启用步骤",
            "D": "承诺所有环境都绝不报错"
        },
        "answers": [
            "A",
            "B",
            "C"
        ],
        "explanation": "需选择全部正确项；答案依据所列教程知识点。",
        "sources": [
            "https://wiki.opizontas.org/books/642e9/page/9b861"
        ],
        "reviewed_at": "2026-10-25"
    }
]
