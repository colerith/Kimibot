# QQ → Discord 工单联动：Docker + PM2，同一台 VPS

两边更新到包含本功能的版本后启用。默认关闭，不开 HTTP 端口，不需要额外 Token，不直接修改 Kimibot 原来的 app_state 数据库。

## 行为

申请人必须在 QQ 入群附言写 `工单号：123456`（真实6位工单号）。也接受 `#123456`。可附带QQ，但程序只使用QQ平台上报的实际申请人账号；不识别没有标签的纯数字，以免误把QQ号当工单号。群问题中可写“请在答案中完整填写：工单号：你的六位编号”。

Kimibot 启动后扫描指定归档频道中自己发送的工单卡片，建立索引；完成首次扫描后才处理队列。后续每15秒检查新归档与待同步记录；失败通常60秒后重试。卡片量大时首次扫描会较慢。

- 已归档且已过审、QQ为空：自动填入申请人的QQ。
- 尚未归档：队列等待归档完成再更新，不改变现有30分钟归档流程。
- 已填同QQ：幂等处理；已有其他QQ：保留原值，标记人工处理。
- 同号多工单、未过审、配置群不符或删除的卡片：人工处理。
- 申请与真正入群分开，只有收到成员增加事件才写“已观察到入群”；不会自动批准入群或授予Discord身份。
- 不发送群内确认消息，不额外私信申请人。通过日志与本地状态查看结果。
- 新功能只能处理启用后收到的申请。漏收的历史申请不能凭空恢复；请人工录入。
- 原管理员“录入 / 修改 QQ”按钮保留；同步每次读取卡片当前值，手动值不会被旧缓存覆盖。

**身份边界：** 六位工单编号由申请人填写，不构成对Discord账号所有权的验证。这版同步的是申请资料，卡片会标记来源；不要据此自动发身份。尚未实现一次性绑定码。

## 1. 更新两个项目

如果改动是通过PR交付，先在GitHub合并两个PR，再执行以下命令。

QQ项目：

```bash
cd /root/qimi-bot
git pull --ff-only
```

Kimibot项目（替换为你实际目录）：

```bash
cd /你的Kimibot目录
git pull --ff-only
pm2 list
```

记下Kimibot的PM2进程名。不要新开第二个Kimibot实例。

## 2. 建立共享目录和配置

下面按两个程序由 root 管理写。如果PM2实际由其他Linux用户运行，请将 `-o root -g root` 改为该用户及其主组；不要用777。`2770`使容器创建的数据库继承目录组，Docker启动命令已设置组可写权限。

```bash
sudo install -d -m 2770 -o root -g root /var/lib/qimi-bridge
sudo nano /var/lib/qimi-bridge/config.json
```

填入实际ID（值不要带注释）：

```json
{
  "discord_guild_id": 你的Discord服务器ID,
  "archive_channel_id": 存放已过审归档卡片的文字频道ID,
  "qq_group_ids": [你的QQ群号]
}
```

上面的中文占位符必须替换成数字。Discord设置开启开发者模式，然后右键服务器/频道复制ID。归档频道是存放卡片的日志文字频道，不是旧工单分类。

保存后验证JSON，并限制配置权限：

```bash
python3 -m json.tool /var/lib/qimi-bridge/config.json
sudo chmod 640 /var/lib/qimi-bridge/config.json
```

非root的PM2用户还需要拥有该配置文件或属于文件所属组。目录中的数据库包含QQ与工单资料，不要公开分享。

## 3. 启用 QQ 端

```bash
cd /root/qimi-bot
nano .env
```

确认 `ALLOWED_GROUPS` 包含配置中的QQ群。增加一行（已有COMPOSE_FILE时编辑原行，不要重复添加）：

```dotenv
COMPOSE_FILE=compose.yaml:compose.bridge.yaml
```

然后启动：

```bash
sudo docker compose up -d --build bot
sudo docker compose logs --tail=80 bot
```

应看到 `qimi_bridge` 插件加载成功。原头衔功能保持启用。

## 4. 重启 PM2 中的 Kimibot

以原来运行PM2的同一个Linux用户执行，替换进程名：

```bash
pm2 restart 你的Kimibot进程名
pm2 logs 你的Kimibot进程名 --lines 100
```

不需要 `pm2 start`，也不需要新的保活进程。初始化后日志会提示归档索引就绪；索引期间不编辑卡片。确保Kimibot能查看该频道、读取历史消息和编辑自己的消息。

## 5. 小范围验收

1. 找一张已过审、QQ尚未录入的工单，记下编号。
2. 对应用户申请加入测试/目标QQ群，附言 `工单号：123456`。
3. 看归档卡片是否自动填QQ，并显示“已收到入群申请，尚未核实入群”。
4. 管理员正常同意申请后，检查是否更新为“已观察到入群”。
5. 测试已有其他QQ的卡片，应该保留原值，日志提示人工处理。
6. 重启两个bot，确认不会重复修改同一份记录。

查看最近30条队列记录（在QQ项目目录）：

```bash
cd /root/qimi-bot
python3 bridge_store.py /var/lib/qimi-bridge/bridge.sqlite3
```

状态：`pending` 等待/重试；`done` 已同步；`conflict` 需要人工处理。尚未归档最多等待7天。人工冲突可直接用原Discord录入按钮修正；不会自动覆盖冲突记录。

## 6. 后续更新和停用

`.env`中的COMPOSE_FILE保存后，继续使用原来的Docker命令即可，挂载不会丢失：

```bash
cd /root/qimi-bot
git pull --ff-only
sudo docker compose up -d --build bot
```

停用：删除QQ `.env`的COMPOSE_FILE行后重新创建bot服务；将 `/var/lib/qimi-bridge/config.json` 重命名为 `config.disabled.json`，再重启Kimibot。保留数据库，方便追查，不影响原头衔和工单功能。

此版本只有本地模拟测试通过，尚未在你的QQ/Discord上联调。请按第5步验证NapCat是否正确上报入群附言、实际QQ号和成员增加事件。
