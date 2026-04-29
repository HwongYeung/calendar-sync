---
name: calendar-sync
author: muskhuang
repository: https://github.com/HwongYeung/calendar-sync
description: 多源日历同步技能，支持企业微信（WeCom CalDAV）和 Apple iCloud 日历，两源均通过 CalDAV 直接从云端读取。采用本地缓存 + cron 后台定时同步架构，查询毫秒级响应。支持企微日程的查询/创建/删除，Apple 日历云端直取，以及企微→Apple iCloud 单向镜像同步。当用户需要查看日程、管理日历、或同步到 Apple 日历时触发。
---

# Calendar Sync — 多源日历同步

支持多个日历源，统一查询和管理：

- **企业微信**（WeCom CalDAV）— 完整支持：查询、创建、删除、后台同步
- **Apple iCloud 日历** — 云端直取（通过 `caldav.icloud.com` 官方 CalDAV 读取所有日历事件），同时也可作为企微镜像目标

采用 **本地缓存 + cron 后台定时同步** 架构，查询响应时间从网络方案的 ~40 秒降到 ~0.1 秒。

## 架构

```
                     ┌──────────────────────────────────────────────┐
 cron (每 15min) --> │  sync: 企微 CalDAV + iCloud CalDAV  → 本地缓存 │
                     └───────────────────────┬──────────────────────┘
                                             │
                                 ┌───────────▼───────────┐
                                 │ cache/events.json     │  ← 预展开事件
                                 │  [{source:"wecom",…}, │    (含 RRULE、
                                 │   {source:"apple",…}] │     source 标签)
                                 │ cache/meta.json       │  ← 同步时间戳
                                 └───────────┬───────────┘
                                             │
      user query / mirror ------------------┴--------> 毫秒级返回
```

- **缓存位置**: `~/.openclaw/extensions/calendar-sync/cache/`
- **查询默认读缓存**；缓存过期（>20 分钟）会给出警告
- **RRULE 已在 sync 阶段预展开**，缓存里就是可直接过滤的实例列表
- **每条事件都带 `source` 字段**（`wecom` / `apple`），可用 `--source` 过滤
- **镜像功能**: `mirror-apple` 命令将企微日程单向推送到 iCloud「WeCom Mirror」日历

## 前置条件

- Python 依赖: `caldav`, `python-dateutil`（建议放到脚本同级 `.venv` 中）
- 跨平台（Linux / macOS），使用系统 `crontab` 做后台调度
- 首次使用需运行 `setup` 命令配置企微凭证；iCloud 镜像需额外配置 iCloud 凭证

## 一次性安装（企微）

**推荐：一键安装**（配置凭证 + 自动装后台同步）

```bash
python3 scripts/calendar_sync.py install \
  --username <邮箱> --password <密码> --server caldav.wecom.work
```

这一条命令完成全部首次配置：
1. 保存 CalDAV 凭证到 `~/.openclaw/extensions/calendar-sync/config.json`
2. 测试连接并列出可用日历
3. 立即全量同步一次日程到本地缓存
4. 安装 cron 后台任务（默认每 15 分钟同步一次）

**获取企微 CalDAV 密码**: 企微 → 工作台 → 日程 → 右上角「三」→ 日程设置 → 同步至其他日历 → 获取密码

## Apple iCloud 日历配置（云端直取 + 镜像）

```bash
# 推荐：一键安装（配置凭证 + 立即全量同步）
python3 scripts/calendar_sync.py install-apple \
  --username <iCloud邮箱> --password <app-specific密码>

# 或仅保存凭证
python3 scripts/calendar_sync.py setup-apple \
  --username <iCloud邮箱> --password <app-specific密码>
```

- iCloud 凭证保存在同一 `config.json` 的 `apple` 字段下
- 需要生成 **app-specific password**（[appleid.apple.com](https://appleid.apple.com) → 登录与安全 → App 专属密码）
- 一旦配置，后台 cron 会**同时同步企微 + Apple**，两边事件都进本地缓存
- 写入镜像的目标日历仍叫 `WeCom Mirror`，读取时会自动跳过该日历避免循环

## 日常使用

### 查询日程（毫秒级，推荐）

```bash
# 本周所有来源
python3 scripts/calendar_sync.py query

# 指定日期范围
python3 scripts/calendar_sync.py query --start 2026-04-20 --end 2026-04-26

# 只看企微 / 只看 Apple
python3 scripts/calendar_sync.py query --source wecom
python3 scripts/calendar_sync.py query --source apple

# JSON 格式输出
python3 scripts/calendar_sync.py query --json
```

`query` 默认从本地缓存读取，通常 < 100ms 返回。结果会在标题前打上 `[💼 企微]` / `[🍎 Apple]` 标签，Apple 事件还会显示来源日历名称。

### 同步到 Apple iCloud 日历（镜像）

```bash
# 全量镜像：将缓存中的所有企微日程推送到 iCloud
python3 scripts/calendar_sync.py mirror-apple

# 指定日期范围
python3 scripts/calendar_sync.py mirror-apple --start 2026-04-01 --end 2026-07-01
```

镜像逻辑：
- 在 iCloud 中创建名为 `WeCom Mirror` 的专用日历（如不存在）
- 遍历本地缓存中的企微事件，生成 `wecom-mirror-<uid>` 格式的 iCloud UID
- 通过 fingerprint（摘要）判断事件是否已变更，避免重复上传
- 删除 iCloud 中存在但企微侧已删除的镜像事件
- 每个事件默认设置 **提前 15 分钟**提醒

### 手动强制同步

```bash
python3 scripts/calendar_sync.py sync
python3 scripts/calendar_sync.py sync --days-back 30 --days-forward 90
```

### 后台任务管理

```bash
python3 scripts/calendar_sync.py daemon-status      # 查看 cron 任务是否安装
python3 scripts/calendar_sync.py daemon-install     # 安装 cron 任务 (默认 15min)
python3 scripts/calendar_sync.py daemon-uninstall   # 卸载 cron 任务
```

### 创建日程

```bash
python3 scripts/calendar_sync.py create \
  --summary "会议标题" \
  --date 2026-04-21 \
  --start-time 14:00 \
  --end-time 15:00 \
  --location "会议室A" \
  --description "会议描述"
```

### 删除日程

```bash
python3 scripts/calendar_sync.py delete --uid <日程UID>
```

## Agent 工作流

### 查询日程
1. 直接调用 `query --start X --end Y`（读缓存，毫秒级）
2. 如果输出提示"缓存已过期" → 再跑一次 `sync`，或者直接改用 `--live`
3. 格式化输出：标题、时间、地点、组织人

### 镜像到 Apple 日历
1. 确保企微凭证和 iCloud 凭证均已配置
2. 先 `sync` 确保缓存最新
3. 运行 `mirror-apple` 推送变更

## 实现要点（开发者参考）

- **XML 命名空间前缀**：企微 CalDAV 服务器对 REPORT 用 `d:` 前缀，对 PROPFIND 却用 `A:` 前缀。所有 XML 解析正则必须使用 prefix-agnostic 写法
- **RRULE UNTIL 时区陷阱**：`dateutil.rrule.rrulestr` 若 dtstart 为 naive 而 RRULE 含 `UNTIL=...Z`，会报 `UNTIL must be UTC when DTSTART is tz-aware`。预处理去掉 Z
- **VTIMEZONE 虚 DTSTART**：企微的 .ics 里 VTIMEZONE 段有 `DTSTART:19700101T000000`，parse 时需跳过
- **time-range 过滤不可信**：企微 CalDAV 的 time-range REPORT 会漏事件，改用 PROPFIND 全量 + 客户端过滤
- **跨平台调度**：使用系统 `crontab`，Linux 用 `/usr/bin/flock` 防并发，macOS 用 PID 锁文件兜底
- **原子写缓存**：`tmp file + os.replace`，避免读到半写入的 JSON
- **镜像 fingerprint**：用 `(summary, dtstart, dtend, location)` 的 MD5 作为变更判据，避免重复 PUT

## 注意事项

- 时间格式统一使用 `YYYY-MM-DD` 和 `HH:MM`
- 默认时区为 `Asia/Shanghai` (UTC+8)
- 创建日程默认设置提前 15 分钟提醒
- iCloud 镜像使用 app-specific password，不是 iCloud 登录密码
- 配置文件路径：`~/.openclaw/extensions/calendar-sync/config.json`（不含凭证，已加入 .gitignore）
- 缓存路径：`~/.openclaw/extensions/calendar-sync/cache/`

## API 参考

详细的 CalDAV 接口说明见 [references/caldav-api.md](references/caldav-api.md)。
