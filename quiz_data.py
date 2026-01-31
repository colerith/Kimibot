# quiz_data.py

QUIZ_QUESTIONS = [
    {
        "id": 1,
        "question": "SillyTavern（酒馆）是一个什么性质的软件？",
        "options": {
            "A": "一个需要付费订阅的商业聊天服务",
            "B": "一个开源、免费的本地前端界面（UI），用于连接后端AI模型",
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
            "C": "点击顶部栏的“背景”图标（通常是图片形状），上传或选择图片",
            "D": "发送指令 /change_bg 给AI"
        },
        "answer": "C"
    },
    {
        "id": 4,
        "question": "角色卡片通常支持导入的图片格式是？",
        "options": {
            "A": "仅支持 .png",
            "B": "仅支持 .webp",
            "C": "仅支持 .json 纯文本",
            "D": "PNG (含元数据) 和 WebP 均支持"
        },
        "answer": "D"
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
        "question": "如果AI开始无限重复同一句话或陷入死循环，你应该优先调高哪个参数？",
        "options": {
            "A": "Repetition Penalty (重复惩罚)",
            "B": "Context Limit (上下文限制)",
            "C": "Temperature (温度)",
            "D": "Max Response Length (最大回复长度)"
        },
        "answer": "A"
    },
    {
        "id": 9,
        "question": "“世界书”（World Info/Lorebook）的主要作用是？",
        "options": {
            "A": "用来保存所有的聊天记录",
            "B": "一个内置的浏览器，用来查百度",
            "C": "存储关键词触发的背景设定，在对话提到相关词时自动插入上下文",
            "D": "用来给角色卡片自动上色"
        },
        "answer": "C"
    },
    {
        "id": 10,
        "question": "在世界书中，为了确保像“状态栏”或“背包系统”这种需要常驻显示的内容不被遗忘，通常设置策略是？",
        "options": {
            "A": "设置极低的触发概率",
            "B": "放在世界书里设为系统d并选择深度",
            "C": "把它写在第一条消息里",
            "D": "每隔几句手动发送一遍"
        },
        "answer": "B"
    },
    {
        "id": 11,
        "question": "如果想要AI扮演你自己（用户）进行说话，或者帮AI写下一段剧情，应该使用什么功能？",
        "options": {
            "A": "Impersonate (伪装/扮演)",
            "B": "Regenerate (重新生成)",
            "C": "Continue (继续)",
            "D": "Review (审查)"
        },
        "answer": "A"
    },
    {
        "id": 12,
        "question": "“Jailbreak”（越狱/破限）在酒馆语境下指的是？",
        "options": {
            "A": "破解酒馆软件的收费版",
            "B": "一种特殊的提示词，旨在绕过AI模型的安全过滤，允许生成NSFW或受限内容",
            "C": "给酒馆安装第三方插件",
            "D": "把酒馆部署到苹果手机上"
        },
        "answer": "B"
    },
    {
        "id": 13,
        "question": "在角色卡编辑中，“Example Dialogue”（对话示例/样例）的最佳格式通常是？",
        "options": {
            "A": "写一段长篇的角色自传",
            "B": "只写关键词，如：开心，难过，生气",
            "C": "<START>\n{{char}}: 你好！\n{{user}}: 你好。\n（通过问答形式展示语气）",
            "D": "留空不填，因为没用"
        },
        "answer": "C"
    },
    {
        "id": 14,
        "question": "如果想把聊天记录导出并分享给别人，最完整的格式是？",
        "options": {
            "A": ".txt 文本文件",
            "B": ".jsonl (SillyTavern格式)",
            "C": "网页全页截图",
            "D": ".html 网页文件"
        },
        "answer": "B"
    },
    {
        "id": 15,
        "question": "在API设置中，“Context Limit”（上下文上限）设置得过高（超过模型支持范围）会导致什么？",
        "options": {
            "A": "AI变得更聪明",
            "B": "API报错，无法生成任何回复",
            "C": "生成速度变快",
            "D": "自动切换到备用模型"
        },
        "answer": "B"
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
        "question": "关于“预设”（Preset），以下说法正确的是？",
        "options": {
            "A": "预设是用来修改酒馆背景颜色的",
            "B": "预设包含了生成参数（温度等）和提示词模板，影响AI的说话风格和逻辑",
            "C": "预设就是角色卡",
            "D": "每个角色卡都自带一个锁定的预设，不能更改"
        },
        "answer": "B"
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
            "A": "在闲鱼等平台倒卖免费开源的酒馆整合包或盗版角色卡",
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
            "B": "让AI接着上一段未说完的话继续生成，或追加内容",
            "C": "切换到下一个角色",
            "D": "退出酒馆"
        },
        "answer": "B"
    },
    {
        "id": 22,
        "question": "“Author's Note”（作者注释/A注）通常用来做什么？",
        "options": {
            "A": "写作者的联系方式",
            "B": "强行插入一段高权重的指令，用来纠正AI的行为或强调当前场景",
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
            "C": "点击顶部的“群组”图标，创建新群组并添加成员",
            "D": "这是付费功能，无法开启"
        },
        "answer": "C"
    },
    {
        "id": 24,
        "question": "关于SillyTavern的“分支”（Branching）功能，描述正确的是？",
        "options": {
            "A": "它可以像树状图一样，从某条消息分叉出不同的剧情走向",
            "B": "它是指软件的更新分支（Release/Staging）",
            "C": "它是用来给文本分段的",
            "D": "A 和 B 在不同语境下都对，但在聊天功能中指 A"
        },
        "answer": "D"
    },
    {
        "id": 25,
        "question": "“Token”在AI对话中通常指的是？",
        "options": {
            "A": "一种加密货币",
            "B": "AI处理文本的最小单位（类似于词或字的一部分），用来计算长度和费用",
            "C": "API的登录密码",
            "D": "酒馆的皮肤币"
        },
        "answer": "B"
    },
    {
        "id": 26,
        "question": "如果你的世界书（Lorebook）条目很多，为了节省Token，应该开启什么功能？",
        "options": {
            "A": "Recursive Scanning (递归扫描)",
            "B": "Vector Storage (向量存储)",
            "C": "Text Translation (文本翻译)",
            "D": "Image Generation (图像生成)"
        },
        "answer": "B"
    },
    {
        "id": 27,
        "question": "在角色卡面板中，“First Message”（第一条消息/开场白）的作用是？",
        "options": {
            "A": "每次AI回复都会带上这句话",
            "B": "只有开始新聊天时，角色发出的第一句话，用于确立场景和语气",
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
            "B": "点击该消息右上角的“编辑”（笔状图标）进行修改",
            "C": "在输入框输入 /edit",
            "D": "重启酒馆"
        },
        "answer": "B"
    },
    {
        "id": 29,
        "question": "“User Persona”（用户人设）在哪里设置？",
        "options": {
            "A": "每次聊天时直接告诉AI",
            "B": "在顶部的用户设置面板中，可以设置用户的名字、头像和描述",
            "C": "必须写在每个角色卡的备注里",
            "D": "在config.yaml文件里修改"
        },
        "answer": "B"
    },
    {
        "id": 30,
        "question": "SillyTavern的“Data Bank”或“Vector Storage”主要解决了什么问题？",
        "options": {
            "A": "解决了API连接不稳定的问题",
            "B": "解决了模型不够聪明的问题",
            "C": "解决了长对话后，AI遗忘很久以前（超出上下文窗口）的记忆的问题",
            "D": "解决了图片加载慢的问题"
        },
        "answer": "C"
    },
    {
        "id": 31,
        "question": "在酒馆中，Depth（深度）这个参数在世界书或A注中通常表示？",
        "options": {
            "A": "内容的深刻程度",
            "B": "插入的内容距离最新一条消息的距离（以消息数或Token计）",
            "C": "AI思考的时间长度",
            "D": "背景图片的模糊度"
        },
        "answer": "B"
    },
    {
        "id": 32,
        "question": "如果想要在聊天中发送图片给AI看，需要？",
        "options": {
            "A": "使用的API模型本身支持视觉（Vision），并点击输入框旁的图片图标上传",
            "B": "把图片转成Base64代码发过去",
            "C": "对着屏幕大声描述图片",
            "D": "SillyTavern不支持发送图片"
        },
        "answer": "A"
    },
    {
        "id": 33,
        "question": "“System Prompt”（系统提示词）通常处于什么样的优先级？",
        "options": {
            "A": "最低，AI基本不看",
            "B": "最高或极高，它定义了AI的基本行为准则和世界观",
            "C": "中等，仅次于用户输入",
            "D": "无效，新版酒馆已移除"
        },
        "answer": "B"
    },
    {
        "id": 34,
        "question": "扩展插件“Stable Diffusion”在酒馆里主要用来？",
        "options": {
            "A": "加速文本生成",
            "B": "根据聊天内容自动生成场景图或人物图",
            "C": "优化网络连接",
            "D": "翻译英文回复"
        },
        "answer": "B"
    },
    {
        "id": 35,
        "question": "关于“Regex”（正则表达式）脚本在酒馆中的用途，错误的是？",
        "options": {
            "A": "可以用来隐藏思维链（<think>标签内容）",
            "B": "可以用来自动替换文本，比如把英文标点换成中文标点",
            "C": "可以用来格式化输出，改变字体颜色等",
            "D": "可以用来增加API的额度"
        },
        "answer": "D"
    },
    {
        "id": 36,
        "question": "如果你的酒馆界面突然无法点击，或者布局乱了，最有效的重置方法是？",
        "options": {
            "A": "重装系统",
            "B": "刷新网页（F5）",
            "C": "在用户设置里选择“Reset UI Settings”（重置UI设置）",
            "D": "更换鼠标"
        },
        "answer": "C"
    },
    {
        "id": 37,
        "question": "自动解析有什么作用？",
        "options": {
            "A": "隐藏thinking思维链",
            "B": "让AI自动生成图片",
            "C": "自动识别并执行角色指令",
            "D": "删除多余的对话内容"
        },
        "answer": "A"
    },
    {
        "id": 38,
        "question": "“Summary”（摘要）功能的作用是？",
        "options": {
            "A": "给当前聊天起个标题",
            "B": "自动总结之前的聊天剧情，以节省上下文空间",
            "C": "统计今天的聊天字数",
            "D": "评价AI的写作水平"
        },
        "answer": "B"
    },
    {
        "id": 39,
        "question": "SillyTavern支持“热修补”或“热更新”，通常通过什么方式更新到最新版？",
        "options": {
            "A": "必须删掉文件夹重新下载",
            "B": "使用 `git pull` 命令或点击界面上的“Update”按钮（如果已配置git）",
            "C": "等待作者发邮件",
            "D": "自动更新，无法关闭"
        },
        "answer": "B"
    },
    {
        "id": 40,
        "question": "在角色卡的“Advanced Definitions”（高级定义）里，通常存放？",
        "options": {
            "A": "角色的头像图片",
            "B": "大量的背景故事、对话范例、创作者元数据",
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
            "B": "OobaBooga (Text Generation WebUI)",
            "C": "NovelAI",
            "D": "Photoshop"
        },
        "answer": "D"
    },
    {
        "id": 42,
        "question": "酒馆里的“视觉小说模式”指的是什么布局模式？",
        "options": {
            "A": "把界面变成粉红色",
            "B": "一种更加二次元化的UI布局，通常强调立绘展示",
            "C": "AI只说日语的模式",
            "D": "一种省电模式"
        },
        "answer": "B"
    },
    {
        "id": 43,
        "question": "如果API连接测试显示“Valid”但无法生成消息，最可能的原因是？",
        "options": {
            "A": "网络断了",
            "B": "预设参数设置不合理或额度已用尽",
            "C": "键盘坏了",
            "D": "屏幕分辨率不支持"
        },
        "answer": "B"
    },
    {
        "id": 44,
        "question": "“Quick Reply”（快速回复）栏通常用来放什么？",
        "options": {
            "A": "常用的指令、描写片段或控制脚本，方便一键发送",
            "B": "角色的表情包",
            "C": "广告链接",
            "D": "背景音乐"
        },
        "answer": "A"
    },
    {
        "id": 45,
        "question": "对于Gemini等容易被审查的模型，社区常用的“破限”手段通常涉及？",
        "options": {
            "A": "使用“显式内容”开关",
            "B": "在预设中加入“防截断”相关逻辑",
            "C": "给模型发红包",
            "D": "不停地刷新页面"
        },
        "answer": "B"
    },
    {
        "id": 46,
        "question": "SillyTavern的数据（角色卡、聊天记录）默认保存在哪里？",
        "options": {
            "A": "云端服务器，作者能看到",
            "B": "本地的 /data 或 /public 文件夹内，完全私密",
            "C": "Windows注册表里",
            "D": "内存里，关机就没了"
        },
        "answer": "B"
    },
    {
        "id": 47,
        "question": "“Quiet”或“Thinking”模式（思维链）在近期模型中很流行，它的特征是？",
        "options": {
            "A": "AI完全不说话",
            "B": "AI在 `<think>` 标签内先进行逻辑推演，再输出最终回复",
            "C": "AI回复的声音很小",
            "D": "AI回复速度极慢但字数极少"
        },
        "answer": "B"
    },
    {
        "id": 48,
        "question": "在酒馆中，`Main Prompt`，`NSFW Prompt`，`Jailbreak Prompt` 的生效顺序通常由什么决定？",
        "options": {
            "A": "随机决定",
            "B": "由 Context Template（上下文模板/故事字符串）中的排序决定",
            "C": "总是 Jailbreak 最后",
            "D": "总是 Main Prompt 最后"
        },
        "answer": "B"
    },
    {
        "id": 49,
        "question": "如果想要备份你的整个酒馆设置和数据，最简单的办法是？",
        "options": {
            "A": "打包data-user文件夹",
            "B": "截图保存所有设置",
            "C": "无法备份",
            "D": "导出为PDF"
        },
        "answer": "A"
    },
    {
        "id": 50,
        "question": "关于“Steaming”（流式传输），描述正确的是？",
        "options": {
            "A": "看视频的功能",
            "B": "AI生成时，字会像打字机一样一个接一个蹦出来，而不需要等全部生成完",
            "C": "一种蒸汽朋克的主题皮肤",
            "D": "一种把聊天记录用水印加密的技术"
        },
        "answer": "B"
    }
]