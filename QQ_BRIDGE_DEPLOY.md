# QQ → Discord 工单联动：Docker + PM2，同一台 VPS

两边更新到包含本功能的版本后启用。默认关闭，不开 HTTP 端口，不需要额外 Token，不直接修改 Kimibot 原来的 app_state 数据库。

## 行为

申请附言包含一个独立的6位数字即可，例如 `123456` 或 `我的编号是123456，谢谢`，无需标签。多个不同的6位编号会拒绝识别，长数字不会截取。QQ号使用平台上报的实际申请人账号。

Kimibot 完成归档索引后，每15秒核验队列；QQ端每30秒检查成员和待批准申请。

- 已过审归档工单：QQ为空或相同才同步；已有其他QQ、重复工单等冲突交给人工。
- 已过审但还在等待归档的工单：核验当前频道主题中的过审状态后可批准，归档完成后再补卡片；测试工单不通过。
- 启用联动即启用自动批准：只有近期核验通过的申请才调用QQ批准接口。未过审申请等待，不自动批准。
- 管理员先批准也能处理：成员增加事件和定期成员列表检查都会补记入群，避免重复批准。超时后先核对成员，失败最多尝试3次，之后留给人工。
- 启用后漏了成员通知可以补查；从未收到过申请则无法恢复编号。管理员可在群内发送 `关联工单 @某人 123456`，为已经入群的成员补交关联，仍需Kimibot核验工单。
- 一个工单只保留一个QQ认领，冲突不会覆盖原卡片；原“录入 / 修改 QQ”按钮保留。卡片标明申请来源及是否观察到入群。
- 不自动授予Discord身份。6位编号是申请资料，不是Discord账号所有权证明；知道他人工单号的人可能冒用。

共享数据库会保存申请标识以调用批准接口，请保持目录私有。旧版数据库自动迁移；两边都要更新。尚未处理的申请最多追踪7天。

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
2. 对应用户申请加入QQ群，附言直接写 `123456`，检查是否自动批准、归档卡片是否填入实际QQ。
3. 另一次申请由管理员抢先批准，检查卡片最终是否显示已观察到入群。
4. 测试未过审工单和已有其他QQ的卡片，应该不自动批准或覆盖。
5. 已入群但漏收申请的成员，用 `关联工单 @某人 123456` 验证补录。
6. 重启两个bot，确认状态保留、不会重复批准。

查看最近30条队列记录（在QQ项目目录）：

```bash
cd /root/qimi-bot
python3 bridge_store.py /var/lib/qimi-bridge/bridge.sqlite3
```

状态：`pending` 等待/重试；`done` 已同步；`conflict` 需要人工处理。admission字段：`waiting/running` 等待或尝试批准，`approved` 接口已确认批准，`joined` 已观察到成员，`manual` 需人工批准。尚未归档最多等待7天。人工冲突可直接用原Discord录入按钮修正；不会自动覆盖冲突记录。

## 6. 后续更新和停用

`.env`中的COMPOSE_FILE保存后，继续使用原来的Docker命令即可，挂载不会丢失：

```bash
cd /root/qimi-bot
git pull --ff-only
sudo docker compose up -d --build bot
```

停用：删除QQ `.env`的COMPOSE_FILE行后重新创建bot服务；将 `/var/lib/qimi-bridge/config.json` 重命名为 `config.disabled.json`，再重启Kimibot。保留数据库，方便追查，不影响原头衔和工单功能。

此版本只有本地模拟测试通过，尚未在你的QQ/Discord上联调。请按第5步验证NapCat是否正确上报入群附言、实际QQ号和成员增加事件。
