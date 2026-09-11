# 奇米娱乐功能

无需AI API，数据保存在SQLite，重启保留。QQ只响应ALLOWED_GROUPS中的群；Discord按服务器独立统计，不响应私信。

| 玩法 | QQ文字 | Discord斜杠 | Discord文字 |
| --- | --- | --- | --- |
| 签到 | 签到 | /奇米 签到 | 奇米签到 |
| 余额 | 我的饭粒 | /奇米 饭粒 | 我的饭粒 |
| 喂宠物 | 喂奇米 | /奇米 喂食 | 喂奇米 |
| 摸宠物 | 摸摸奇米 | /奇米 摸摸 | 摸摸奇米 |
| 状态 | 看看奇米 | /奇米 群宠 | 看看奇米 |
| 运势 | 今日运势 | /奇米 运势 | 今日运势 |
| 帮助 | 娱乐帮助 | /奇米 帮助 | 娱乐帮助 |

- 北京时间每天签到一次，随机5–15饭粒，连续签到每满7天额外5粒。
- 喂食花3粒米，加饱食、心情和经验；摸摸免费加心情、经验。两种操作各有每人60秒冷却，饱食满时不扣米。
- 同群/服务器大家共养一只奇米，饱食和心情随时间下降，不会死亡，经验每100点升一级。
- 今日运势当天固定，只作娱乐。重复消息不会重复扣米或领奖。
- 每个平台、每个群/服务器的钱包独立；QQ与Discord不互通，也不兑换Kimibot已有蛋壳。

## 更新与保活

合并对应PR后，QQ项目目录执行：

```bash
git pull --ff-only
docker compose up -d --build bot
docker compose logs --tail=80 bot
```

Kimibot项目目录执行（替换实际PM2进程名）：

```bash
git pull --ff-only
pm2 restart 你的Kimibot进程名
pm2 logs 你的Kimibot进程名 --lines 80
```

Kimibot启动器会自动加载新的 `cogs/entertainment` 文件夹，无需新增进程或安装额外依赖。若斜杠指令暂未刷新，可先使用文字指令，并查看启动同步日志。

QQ默认数据文件 `/data/entertainment.sqlite3` 位于现有Docker数据卷；Discord默认 `data/entertainment.sqlite3` 相对PM2工作目录。可用 `QIMI_FUN_DB` / `KIMI_FUN_DB` 指定路径。不要删除数据卷或改变PM2工作目录，否则可能看起来像余额清空。备份SQLite时建议先停止对应bot。

上线验收：签到两次确认只发一次米，喂食确认扣3米，另一成员查看同一只宠物；重启后余额保留。
