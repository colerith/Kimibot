# 🔮 KimiBot - 奇米大王

一个为特定 Discord 社区量身打造的多功能、高度模块化的机器人，基于最新的 `Py-cord` 框架开发。它集管理、娱乐、工具于一体，旨在提供流畅、丰富的社区交互体验。

## ✨ 主要功能

-   **强大的管理系统 (`manage`)**: 包括用户处罚、日志记录、公示等全套管理工具。
-   **自动化工单 (`tickets`)**: 成员可以通过面板创建私人化的支持频道，方便管理员进行审核或提供帮助。
-   **论坛帖子追踪 (`forum_tracker`)**: 自动监控指定论坛频道的帖子，根据关键词进行收录、统计，并生成可翻页的实时面板。
-   **丰富的社区互动**:
    -   **抽奖系统 (`lottery`)**: 管理员可以轻松发起抽奖活动。
    -   **投票系统 (`poll`)**: 成员可以创建带有截止时间的投票。
    -   **许愿池 (`wish_pool`)**: 收集成员对新功能或社区的建议。
-   **成员与激励系统**:
    -   **欢迎新成员 (`welcome`)**: 自动发送定制的欢迎语和引导。
    -   **积分系统 (`points`)**: 成员通过发言等活动自动获取积分。
    -   **身份组商店 (`roles`)**: 成员可以自助领取或兑换装饰性身份组。
-   **实用的服务器工具**:
    -   **帖子工具 (`thread_tools`)**: 提供“回到帖子顶部”等便捷功能。

## 🚀 快速开始 (开发环境搭建)

按照以下步骤，你可以在本地快速启动并开始开发 KimiBot。

### 1. 克隆仓库

```bash
git clone [你的仓库链接]
cd kimibot-project-name
```

### 2. 创建并激活虚拟环境

使用虚拟环境是管理项目依赖的最佳实践。

-   **Windows**:
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    ```
-   **macOS / Linux**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

### 3. 安装依赖

所有必需的 Python 库都记录在 `requirements.txt` 中。

```bash
pip install -r requirements.txt
```

### 4. 配置机器人

机器人需要一些关键信息才能运行。

-   **创建 `.env` 文件**:
    在项目根目录创建一个名为 `.env` 的文件，并填入你的机器人 Token。
    ```env
    DISCORD_TOKEN="你的机器人TOKEN粘贴到这里"
    ```

-   **配置 `config.py`**:
    打开 `config.py` 文件，根据你的服务器情况，修改里面的频道ID、身份组ID等常量。

-   **配置 `main.py` (用于开发)**:
    打开 `main.py` 文件，找到 `DEBUG_GUILDS` 列表，将你的测试服务器ID填入其中。这可以让你在测试服务器上**秒速更新**斜杠命令，无需等待长达一小时的全局同步。
    ```python
    # main.py
    DEBUG_GUILDS = [123456789012345678] # <- 替换成你的测试服务器ID
    ```

### 5. 运行机器人

一切就绪！现在可以启动机器人了。

```bash
python main.py
```

如果控制台显示 "本大王已经准备好萌翻全场惹！" 并且没有报错，说明你已成功启动！

## 🏗️ 项目结构

KimiBot 采用高度模块化的 `Cogs` 架构。每个核心功能都被封装在一个独立的文件夹中，使得代码逻辑清晰，易于维护和扩展。

```
KIMIBOT/
├── cogs/                      # 机器人所有功能模块（魔法书）的存放处
│   ├── shared/                # 跨模块共享的工具
│   │   └── utils.py           # (例如：is_super_egg 权限检查)
│   │
│   ├── manage/                # 核心管理功能，内部再次细分
│   │   ├── moderation_cog.py  # (例如：清空消息、慢速模式)
│   │   └── punishment_cog.py  # (例如：警告、禁言、封禁)
│   │
│   ├── forum_tracker/         # 论坛追踪模块
│   │   ├── __init__.py        # 加载入口
│   │   ├── cog.py             # 核心逻辑、命令和监听器
│   │   ├── db.py              # 数据库交互 (SQLite)
│   │   ├── utils.py           # 辅助函数 (关键词检查等)
│   │   └── views.py           # 交互界面 (翻页视图)
│   │
│   ├── lottery/               # 抽奖模块
│   │   ├── cog.py
│   │   ├── storage.py         # 数据存储 (JSON)
│   │   └── views.py
│   │
│   ├── points/                # 积分系统
│   ├── poll/                  # 投票系统
│   ├── roles/                 # 身份组系统
│   ├── thread_tools/          # 帖子工具
│   ├── tickets/               # 工单系统
│   ├── welcome/               # 欢迎新成员
│   └── wish_pool/             # 许愿池
│
├── .env                       # (需自行创建) 存放机器人Token等敏感信息
├── config.py                  # 全局配置，存放固定的ID和常量
├── main.py                    # 机器人主入口，负责加载Cogs和启动
└── requirements.txt           # 项目依赖库列表
```

**通用模块设计模式**:
-   `__init__.py`: 使文件夹成为一个 Python 包，并包含 `setup` 函数，用于被 `main.py` 加载。
-   `cog.py` / `core.py`: 模块的核心业务逻辑，包含所有斜杠命令 (`@bot.slash_command`) 和事件监听器 (`@commands.Cog.listener`)。
-   `views.py`: 存放所有与该模块相关的 UI 组件，如 `discord.ui.View`, `discord.ui.Modal` 等。
-   `storage.py` / `db.py`: 负责数据的持久化。`storage.py` 通常用于处理 JSON 文件，而 `db.py` 用于处理 SQLite 数据库。

## 🛠️ 如何新增功能

得益于模块化设计，添加新功能非常简单：

1.  在 `cogs/` 目录下创建一个新文件夹，例如 `cogs/new_feature`。
2.  在该文件夹内，创建 `__init__.py` 和 `cog.py` 文件。
3.  在 `cog.py` 中编写你的新功能代码（命令、事件等）。
4.  在 `__init__.py` 中添加标准的加载代码：
    ```python
    from .cog import NewFeatureCog

    def setup(bot):
        bot.add_cog(NewFeatureCog(bot))
    ```
5.  重新启动机器人，`main.py` 会自动扫描并加载你的新模块。