# Garmin 中国区活动同步到国际区

这是一个运行在本地 Linux 环境中的轻量同步工具，用于把 Garmin 中国区账号中的运动活动同步到 Garmin 国际区账号。

项目使用 Garmin 登录 Token，避免在日常同步任务中保存或重复输入账号密码；同步状态保存在本地 SQLite 数据库中，并通过文件锁防止定时任务重复运行。

## 解决的问题

- 支持 Garmin 中国区和国际区的 MFA 登录初始化。
- 从中国区下载活动的原始 FIT 文件，并上传到国际区。
- 已成功同步的活动会记录到本地数据库，后续运行自动跳过。
- 国际区返回活动重复冲突时，会把活动标记为已完成。
- 支持指定开始同步时间，并自动分页读取该时间之后的活动。
- 上传顺序为从旧到新，尽量保持活动顺序稳定。
- 使用文件锁避免多个同步任务同时执行。
- 支持 dry-run，只检查活动而不下载和上传。
- 支持每天凌晨 1 点自动同步最近 24 小时的活动。

## 当前范围

当前只支持：

```text
Garmin 中国区 -> Garmin 国际区
```

同步内容仅包括运动活动及其原始 FIT 文件，不包括步数、睡眠、身体电量、HRV 等健康数据。

## 文件说明

| 文件或目录 | 用途 |
| --- | --- |
| `sync.py` | 活动同步主程序 |
| `garmin_cn_login.py` | 中国区首次登录和 MFA 验证 |
| `test_cn.py` | 检查中国区 Token 是否仍然有效 |
| `run_daily_sync.sh` | 定时任务入口，工作目录需按实际部署位置设置，并自动计算当前时间减一天 |
| `cn_tokens/` | 中国区登录 Token，不应提交到 Git |
| `global_tokens/` | 国际区登录 Token，不应提交到 Git |
| `sync_state.db` | 已同步活动记录 |
| `sync.lock` | 防止同步任务重叠运行的文件锁 |
| `sync-cron.log` | 定时任务日志，首次定时执行后生成 |

## 环境要求

- Linux
- Python 3.10 或更高版本
- 可以访问 Garmin 中国区和国际区服务
- Python 包 `garminconnect`
- 如需自动执行，需要 cron

Python 脚本会以脚本自身所在目录作为项目目录，因此可以部署到任意位置。Token、数据库和锁文件都会保存在项目目录下，无需修改 Python 源码。

`run_daily_sync.sh` 中的 `cd` 命令仍需按照实际部署位置设置；配置 cron 时，脚本路径和日志路径也需要使用实际路径。下面以 `/opt/garmin-auth` 为例。

## 安装

进入项目目录：

```bash
cd /opt/garmin-auth
```

如果还没有虚拟环境，可以创建并安装依赖：

```bash
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install garminconnect
```

检查命令行是否可用：

```bash
./venv/bin/python sync.py --help
```

## 首次初始化

首次使用需要分别初始化中国区和国际区登录。登录成功后，Token 会保存在本地目录中；日常同步不再需要输入账号密码。

### 1. 初始化中国区

```bash
cd /opt/garmin-auth
./venv/bin/python garmin_cn_login.py
```

按提示输入中国区邮箱、密码和 MFA 验证码。成功后 Token 会保存到项目目录下的：

```text
cn_tokens/
```

不要连续反复尝试登录，否则 Garmin 可能返回 429 限流。

### 2. 检查中国区登录

```bash
./venv/bin/python test_cn.py
```

成功时会输出：

```text
Garmin CN session OK
User: 用户名称
```

### 3. 初始化国际区

```bash
./venv/bin/python sync.py --init-global
```

按提示输入国际区邮箱、密码和 MFA 验证码。成功后 Token 会保存到项目目录下的：

```text
global_tokens/
```

## 手动同步

首次建议先使用 dry-run：

```bash
./venv/bin/python sync.py --dry-run
```

该命令会登录两端账号并检查活动，但不会下载 FIT 或上传活动。

确认范围无误后正式同步：

```bash
./venv/bin/python sync.py
```

未指定开始时间时，默认检查最近 20 条活动。可以通过环境变量调整每次请求的条数：

```bash
GARMIN_SYNC_LIMIT=50 ./venv/bin/python sync.py
```

## 指定开始同步时间

`--start-time` 表示只处理该本地时间（包含该时刻）之后的活动。

按日期同步：

```bash
./venv/bin/python sync.py --start-time 2026-09-01
```

按具体时间同步：

```bash
./venv/bin/python sync.py --start-time "2026-09-01 08:30:00"
```

也支持 ISO 格式和环境变量：

```bash
./venv/bin/python sync.py --start-time "2026-09-01T08:30:00"

export GARMIN_SYNC_START_TIME="2026-09-01 08:30:00"
./venv/bin/python sync.py
```

设置开始时间后，程序会按页读取中国区活动，直到越过时间边界，不再只检查最近 20 条。

建议先组合 dry-run 检查范围：

```bash
./venv/bin/python sync.py \
  --dry-run \
  --start-time "2026-09-01 00:00:00"
```

## 查看同步状态

查看最近 30 条同步记录：

```bash
./venv/bin/python sync.py --state
```

状态记录保存在 `sync_state.db`。常见状态：

- `ok`：上传成功。
- `duplicate`：国际区已经存在该活动，按同步完成处理。

## 每日定时同步

先确认 `run_daily_sync.sh` 中的工作目录与实际部署位置一致：

```bash
# 请根据项目的实际部署位置设置工作目录。
cd /opt/garmin-auth
```

然后配置 cron。以下以项目部署在 `/opt/garmin-auth`、使用 root 用户的 cron 为例：

```cron
0 1 * * * /opt/garmin-auth/run_daily_sync.sh >> /opt/garmin-auth/sync-cron.log 2>&1
```

它会在每天服务器本地时间凌晨 1 点运行。`run_daily_sync.sh` 会计算“当前时间减一天”并传给 `--start-time`。

如果项目部署在其他位置，需要同时替换 cron 中的脚本路径、日志路径，以及 `run_daily_sync.sh` 中的工作目录。

例如任务在 `2026-09-14 01:00:00` 运行，实际传入：

```text
--start-time "2026-09-13 01:00:00"
```

检查定时任务和 cron 服务：

```bash
crontab -l
service cron status
pgrep -a cron
```

查看日志：

```bash
tail -n 100 /opt/garmin-auth/sync-cron.log
tail -f /opt/garmin-auth/sync-cron.log
```

检查定时入口语法：

```bash
bash -n /opt/garmin-auth/run_daily_sync.sh
```

手动执行以下命令会进行真实同步：

```bash
/opt/garmin-auth/run_daily_sync.sh
```

## 同步流程

1. 获取文件锁，防止 cron 和手动任务重叠。
2. 使用本地 Token 登录中国区和国际区。
3. 读取符合时间范围的中国区活动。
4. 将活动调整为从旧到新的上传顺序。
5. 查询本地数据库，跳过已经同步的活动。
6. 从中国区下载原始文件并提取 FIT。
7. 把 FIT 上传到国际区。
8. 将成功或重复状态写入 SQLite。

如果部分活动失败，程序会继续处理其他活动，结束时返回退出码 `2`。失败活动不会写入完成状态，下次执行时可以重试。

## 常见问题

### 找不到中国区 Token

重新初始化并检查：

```bash
./venv/bin/python garmin_cn_login.py
./venv/bin/python test_cn.py
```

### 国际区尚未初始化

```bash
./venv/bin/python sync.py --init-global
```

### Garmin 返回 429

表示登录请求过于频繁。停止反复重试，等待一段时间后再运行，并检查是否一直在重复初始化登录。

### 上传返回 409 或 Conflict

通常表示国际区已经存在同一个活动。程序会记录为 `duplicate`，后续不再重复上传。

### 定时任务没有运行

```bash
service cron status
crontab -l
ls -l /opt/garmin-auth/run_daily_sync.sh
tail -n 100 /opt/garmin-auth/sync-cron.log
date
```

cron 使用服务器本地时间，需要确认服务器时区符合预期，例如 `Asia/Shanghai`。

### 查看程序退出码

```bash
./venv/bin/python sync.py --dry-run
echo $?
```

- `0`：本次执行正常结束。
- `2`：至少有一个活动同步失败，或参数校验失败。

## 数据和安全

`.gitignore` 已排除：

```gitignore
cn_tokens/
global_tokens/
venv/
*.db
*.lock
*.log
```

`cn_tokens/` 和 `global_tokens/` 包含登录凭据，不能上传到 Git、发送给他人或写入公开日志。

提交代码前建议检查：

```bash
git status --short --ignored
```

确认 Token、数据库、锁文件、日志和虚拟环境都显示为已忽略。

## 参考项目

本项目在需求设计和同步流程上参考了：

- [gooin/dailysync-rev](https://github.com/gooin/dailysync-rev)

主要参考了中国区与国际区之间的活动同步思路、分页读取、从旧到新上传、增量处理和重复活动规避方式。

当前项目是针对本机环境整理的轻量 Python 实现，只提供中国区到国际区的活动同步，并不覆盖参考项目中的反向同步、Wellness 健康数据同步、Docker、GitHub Actions 等完整功能。
