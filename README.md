# calendar-sync

> **Author**: muskhuang
> **Repository**: https://github.com/HwongYeung/calendar-sync

多源日历同步技能，通过 CalDAV 协议统一查询和管理多个日历源。**采用本地缓存 + cron 后台定时同步架构**，查询响应时间从 ~40 秒降到 ~0.1 秒。

支持的日历源：
- **企业微信**（WeCom CalDAV）— 完整支持：查询、创建、删除、后台同步
- **Apple iCloud 日历** — 镜像模式（单向）：自动将企微日程推送到 iCloud

> 企微日程查询是 `wecom_mcp schedule` 的替代方案，当 MCP 连接不可用时使用。

## 特性

- 🚀 **查询毫秒级响应**：后台 cron 每 15 分钟同步，查询直接读本地 JSON 缓存
- 🔁 **RRULE 重复事件展开**：支持 `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` 等规则的客户端展开
- 🛡️ **绕过企微 CalDAV 的 time-range 过滤 bug**：改走 PROPFIND 全量 + 客户端过滤，避免漏事件
- 🍎 **Apple iCloud 镜像**：单向推送企微日程到 iCloud 日历，自动去重、支持更新和删除
- 🌐 **跨平台**：Linux 用 `/usr/bin/flock`，macOS 用 PID 锁文件兜底
- ⚡ **一键安装**：`install` 命令一条龙配置凭证 + 首次同步 + cron 安装

## 一次性安装

### 企微日历

```bash
# 推荐：一键安装
python3 scripts/calendar_sync.py install \
  --username <企微邮箱> --password <CalDAV密码> --server caldav.wecom.work
```

**获取企微 CalDAV 密码**：企微 → 工作台 → 日程 → 右上角「三」→ 日程设置 → 同步至其他日历 → 获取密码

### iCloud 镜像配置

```bash
# 配置 iCloud 凭证（需使用 app-specific password）
python3 scripts/calendar_sync.py setup-apple \
  --username <iCloud邮箱> --password <app-specific密码>
```

> **注意**：iCloud 需要使用 [app-specific password](https://support.apple.com/zh-cn/HT204397)，不是登录密码。
> 生成方式：iCloud 设置 → 安全 → App-Specific Password → 生成

## 日常使用

### 查询日程（毫秒级，读缓存）

```bash
# 本周日程
python3 scripts/calendar_sync.py query

# 指定日期范围
python3 scripts/calendar_sync.py query --start 2026-04-20 --end 2026-04-26

# JSON 格式输出
python3 scripts/calendar_sync.py query --json
```

### 镜像到 Apple iCloud 日历

```bash
# 全量镜像：将缓存中的所有企微日程推送到 iCloud
python3 scripts/calendar_sync.py mirror-apple

# 指定日期范围
python3 scripts/calendar_sync.py mirror-apple --start 2026-04-01 --end 2026-07-01
```

镜像逻辑：
- 在 iCloud 中创建名为 `WeCom Mirror` 的专用日历（如不存在）
- 遍历本地缓存中的企微事件，使用 `wecom-mirror-<uid>` 作为 iCloud UID
- 通过 fingerprint（摘要）判断事件是否已变更，避免重复上传
- 删除 iCloud 中存在但企微侧已删除的镜像事件
- 每个事件默认设置 **提前 15 分钟**提醒

### 创建日程

```bash
python3 scripts/calendar_sync.py create \
  --summary "会议标题" --date 2026-04-21 \
  --start-time 14:00 --end-time 15:00 \
  --location "会议室A"
```

### 删除日程

```bash
python3 scripts/calendar_sync.py delete --uid <UID>
```

### 强制实时拉取（绕过缓存）

```bash
python3 scripts/calendar_sync.py query --live
```

### 缓存/后台任务管理

```bash
python3 scripts/calendar_sync.py cache-status       # 查看缓存状态
python3 scripts/calendar_sync.py daemon-status      # 查看 cron 任务状态
python3 scripts/calendar_sync.py sync              # 手动强制同步
python3 scripts/calendar_sync.py daemon-install    # 安装 cron 任务 (默认 15min)
python3 scripts/calendar_sync.py daemon-uninstall  # 卸载 cron 任务
```

## 架构

```
                 ┌─────────────────────────────────┐
cron (每15min)-->│ sync: 全量扫描 CalDAV → 本地缓存 │
                 └──────────────┬──────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │ cache/events.json   │  ← 预展开事件（含 RRULE）
                     │ cache/meta.json     │  ← 同步时间戳
                     └──────────┬──────────┘
                                │
    user query / mirror --------┴----> 毫秒级返回
```

- **缓存位置**: `~/.openclaw/extensions/calendar-sync/cache/`
- **查询默认读缓存**；缓存过期（>20 分钟）会给出警告
- **RRULE 已在 sync 阶段预展开**，缓存里就是可直接过滤的实例列表
- **`events.json` 统一格式**，每条事件含 `source` 字段（`wecom` 或 `apple`）

## 依赖

- Python 3.9+
- `caldav`
- `python-dateutil`
- 系统 `crontab`（Linux/macOS 均内置）
- （可选）`/usr/bin/flock`（Linux 常见，macOS 缺失时自动退回 PID 锁）

```bash
pip install caldav python-dateutil
```

## 文件结构

本仓库采用 **扁平结构**，既是一个 skill 包（根目录有 `SKILL.md`），也是一个 Openclaw extension 包（根目录有 `openclaw.plugin.json`）：

```
calendar-sync/
├── SKILL.md                   # 技能说明（Agent / skill installer 读取）
├── openclaw.plugin.json       # Openclaw 插件清单（skills 指向 "."）
├── README.md                  # 本文档
├── .gitignore
├── scripts/
│   └── calendar_sync.py      # 主脚本（含所有子命令）
└── references/
    └── caldav-api.md         # CalDAV API 参考
```

## 安装到 Openclaw

将仓库克隆到 Openclaw 的 extensions 目录：

```bash
cd ~/.openclaw/extensions
git clone https://github.com/HwongYeung/calendar-sync.git calendar-sync

# 首次配置企微凭证 + 安装后台同步（一条命令搞定）
python3 ~/.openclaw/extensions/calendar-sync/scripts/calendar_sync.py install \
  --username <企微邮箱> --password <CalDAV密码>

# （可选）配置 iCloud 镜像凭证
python3 ~/.openclaw/extensions/calendar-sync/scripts/calendar_sync.py setup-apple \
  --username <iCloud邮箱> --password <app-specific密码>
```

Openclaw 启动时会通过 `openclaw.plugin.json` 自动加载本 skill。

## 存储位置

- **配置文件**（凭证）：`~/.openclaw/extensions/calendar-sync/config.json`
- **缓存**：`~/.openclaw/extensions/calendar-sync/cache/events.json`
- **cron 日志**：`~/.openclaw/extensions/calendar-sync/cache/sync.log`

> 这些目录均在用户主目录下，**未纳入版本控制**。凭证、缓存等不会被提交到仓库。

## 实现要点

- **XML 命名空间前缀不固定**：企微 CalDAV 对 REPORT 用 `d:` 前缀、对 PROPFIND 用 `A:` 前缀，所有正则需 prefix-agnostic
- **RRULE UNTIL 时区陷阱**：`dateutil.rrule.rrulestr` 要求 dtstart 为 naive 而 RRULE 含 `UNTIL=...Z` 时报错，需预处理去掉 `Z`
- **VTIMEZONE 虚 DTSTART**：企微 .ics 的 VTIMEZONE 段有 `DTSTART:19700101T000000`，parse 时需跳过
- **time-range 过滤不可信**：必须 PROPFIND 全量 + 客户端过滤
- **镜像 fingerprint**：用 `(summary, dtstart, dtend, location)` 的 MD5 作为变更判据
- **iCloud CalDAV 地址**：`https://caldav.icloud.com`，使用 app-specific password 认证

详细说明见 [SKILL.md](./SKILL.md)。

## License

Internal use only.
