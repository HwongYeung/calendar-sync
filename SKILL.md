---
name: wecom-caldav
description: 企业微信日历管理技能，通过 CalDAV 协议查询、创建、删除企微日程。采用本地缓存 + 后台定时同步架构，查询毫秒级响应。当用户需要查看企微日程、创建日程、删除日程、查询本周/今日/下周日程、同步企微日历时触发。首次使用需配置 CalDAV 凭证并安装后台同步任务（setup + daemon-install）。替代不可用的 wecom_mcp 日程接口。支持 RRULE 重复事件展开、EXDATE 排除日期、全量扫描模式（绕过企微 CalDAV 服务器的 time-range 过滤 bug）。
---

# 企业微信 CalDAV 日程管理

通过 CalDAV 协议直连企业微信日历服务器，**采用本地缓存 + cron 后台定时同步架构**，查询响应时间从网络方案的 ~40 秒降到 ~0.1 秒。

> ⚠️ 本技能是 `wecom_mcp schedule` 的替代方案，当 MCP 连接不可用时使用。

## 架构

```
                 ┌─────────────────────────────────┐
cron (每15min)-->│ sync: 全量扫描 CalDAV → 本地缓存 │
                 └──────────────┬──────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │ cache/events.json   │  ← 234 个预展开事件（含 RRULE）
                     │ cache/meta.json     │  ← 同步时间戳
                     └──────────┬──────────┘
                                │
    user query -----------------┴----> 毫秒级返回
```

- **缓存位置**: `~/.openclaw/extensions/wecom-caldav/cache/`
- **查询默认读缓存**；缓存过期（>20 分钟）会给出警告
- **RRULE 已在 sync 阶段预展开**，缓存里就是可直接过滤的实例列表

## 前置条件

- Python 依赖: `caldav`, `python-dateutil`（建议放到脚本同级 `.venv` 中）
- 跨平台（Linux / macOS），使用系统 `crontab` 做后台调度
- 首次使用需运行 `setup` 命令配置凭证

## 一次性安装（首次使用）

**推荐：一键安装**（配置凭证 + 自动装后台同步）

```bash
python3 scripts/wecom_caldav.py install \
  --username <邮箱> --password <密码> --server caldav.wecom.work
```

这一条命令完成全部首次配置：
1. 保存 CalDAV 凭证到 `~/.openclaw/extensions/wecom-caldav/config.json`
2. 测试连接并列出可用日历
3. 立即全量同步一次日程到本地缓存
4. 安装 cron 后台任务（默认每 15 分钟同步一次）

**分步安装**（需要交互确认时）：

```bash
# setup 命令会在凭证保存后提示是否安装 daemon（回车即装）
python3 scripts/wecom_caldav.py setup --username <邮箱> --password <密码>
```

如果只想配置凭证、不装 daemon（不推荐，查询会很慢）：

```bash
python3 scripts/wecom_caldav.py setup --username <邮箱> --password <密码> --skip-daemon
```

**获取企微 CalDAV 密码**: 企微 → 工作台 → 日程 → 右上角「三」→ 日程设置 → 同步至其他日历 → 获取密码

### ⚠️ Agent 首次使用检查清单

Agent 触发本技能后，在调用 `query` 前应先检查：

1. **config 是否存在** → 不存在则调用 `install` 或 `setup`（向用户索要凭证）
2. **cron daemon 是否已装** → 通过 `daemon-status` 检查；未装则提示用户执行 `daemon-install`（或直接用 `install` 一键搞定）
3. **缓存是否新鲜** → `cache-status` 看是否 ≤15 分钟；过期则 `sync`

## 日常使用

### 查询日程（毫秒级，推荐）

```bash
# 本周日程
python3 scripts/wecom_caldav.py query

# 指定日期范围
python3 scripts/wecom_caldav.py query --start 2026-04-20 --end 2026-04-26

# JSON 格式输出
python3 scripts/wecom_caldav.py query --json

# 指定日历
python3 scripts/wecom_caldav.py query --calendar F23qk~xwUsIUJTFdFg7AAAP
```

`query` 默认从本地缓存读取，通常 < 100ms 返回。

### 强制实时拉取（绕过缓存）

```bash
python3 scripts/wecom_caldav.py query --live --start 2026-04-20 --end 2026-04-26
```

`--live` 会触发全量扫描（约 40s），用于：
- 刚创建/删除了日程需要立即看到最新状态
- 缓存明显异常时的调试

### 查看缓存状态

```bash
python3 scripts/wecom_caldav.py cache-status
```

### 手动强制同步

```bash
python3 scripts/wecom_caldav.py sync
python3 scripts/wecom_caldav.py sync --days-back 30 --days-forward 90  # 自定义同步窗口
```

### 后台任务管理

```bash
python3 scripts/wecom_caldav.py daemon-status      # 查看 cron 任务是否安装
python3 scripts/wecom_caldav.py daemon-install     # 安装 cron 任务 (默认 15min)
python3 scripts/wecom_caldav.py daemon-uninstall   # 卸载 cron 任务
```

### 创建日程

```bash
python3 scripts/wecom_caldav.py create \
  --summary "会议标题" \
  --date 2026-04-21 \
  --start-time 14:00 \
  --end-time 15:00 \
  --location "会议室A" \
  --description "会议描述"
```

创建成功后建议手动 `sync` 一次刷新缓存，否则缓存里要等下一个 15 分钟周期才能看到。

### 删除日程

```bash
python3 scripts/wecom_caldav.py delete --uid <日程UID>
```

先用 `query` 获取 UID，再用 `delete` 删除。

## 典型 Agent 工作流

### 查询日程

1. 直接调用 `query --start X --end Y`（读缓存，毫秒级）
2. 如果输出提示"缓存已过期" → 再跑一次 `sync`，或者直接改用 `--live`
3. 格式化输出：标题、时间、地点、组织人
4. 对重复事件（同 UID 不同 dtstart）可合并展示为"🔁 工作日每天"等模式

### 创建日程

1. 解析用户意图：标题、日期、开始/结束时间、地点
2. 向用户确认日程信息
3. 运行 `create` 命令
4. **提示用户**：已创建，下次 query 最多延迟 15 分钟看到，如需立即确认请加 `--live`

### 删除日程

1. 先 `query` 定位目标日程（读缓存），获取 UID
2. 向用户确认删除（标题、时间）
3. 运行 `delete --uid <UID>`

## 实现要点（开发者参考）

- **XML 命名空间前缀**：企微 CalDAV 服务器对 REPORT 用 `d:` 前缀，对 PROPFIND 却用 `A:` 前缀。所有 XML 解析正则必须使用 prefix-agnostic 写法：`<[A-Za-z]+:href>...</[A-Za-z]+:href>`
- **RRULE UNTIL 时区陷阱**：`dateutil.rrule.rrulestr` 若 dtstart 为 naive 而 RRULE 含 `UNTIL=...Z`，会报 `UNTIL must be UTC when DTSTART is tz-aware`。预处理去掉 Z：`re.sub(r'(UNTIL=\d{8}T\d{6})Z', r'\1', rrule_str)`
- **VTIMEZONE 虚 DTSTART**：企微的 .ics 里 VTIMEZONE 段有 `DTSTART:19700101T000000`，parse 时需跳过，仅采纳 VEVENT 内带 `TZID=TZ08` 的 DTSTART
- **time-range 过滤不可信**：企微 CalDAV 的 time-range REPORT 会漏事件（特别是你作为参会人而非组织人的事件），`--full-scan` 改走 PROPFIND 全量 + `getlastmodified` 过滤 + 20 线程并发 GET
- **跨平台调度**：使用系统 `crontab` (`*/15 * * * *`)，Linux 用 `/usr/bin/flock` 防并发，macOS 用 PID 锁文件兜底
- **原子写缓存**：`tmp file + os.replace`，避免读到半写入的 JSON

## 注意事项

- 时间格式统一使用 `YYYY-MM-DD` 和 `HH:MM`
- 默认时区为 `Asia/Shanghai` (UTC+8)
- 创建日程默认设置提前 15 分钟提醒
- 同步窗口默认 `[今日-30 天, 今日+90 天]`，长尾历史会议查询需手动 `sync --days-back <更大值>`
- 企微 CalDAV 密码可能定期更新，如遇 401 错误需重新 setup
- 配置文件路径：`~/.openclaw/extensions/wecom-caldav/config.json`
- 缓存路径：`~/.openclaw/extensions/wecom-caldav/cache/`
- cron 日志：`~/.openclaw/extensions/wecom-caldav/cache/sync.log`

## API 参考

详细的 CalDAV 接口说明见 [references/caldav-api.md](references/caldav-api.md)。
