# wecom-caldav

> **Author**: muskhuang
> **Repository**: https://git.woa.com/muskhuang/wecom-caldav

企业微信 CalDAV 日程管理 skill，通过 CalDAV 协议直连企业微信日历服务器，采用 **本地缓存 + cron 后台定时同步** 架构，查询响应时间从 ~40 秒降到 ~0.1 秒。

> 本 skill 是 `wecom_mcp schedule` 的替代方案，当 MCP 连接不可用时使用。

## 特性

- 🚀 **查询毫秒级响应**：后台 cron 每 15 分钟同步，查询直接读本地 JSON 缓存
- 🔁 **RRULE 重复事件展开**：支持 `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` 等规则的客户端展开
- 🛡️ **绕过企微 CalDAV 的 time-range 过滤 bug**：改走 PROPFIND 全量 + 客户端过滤，避免漏事件
- 🌐 **跨平台**：Linux 用 `/usr/bin/flock`，macOS 用 PID 锁文件兜底
- ⚡ **一键安装**：`install` 命令一条龙配置凭证 + 首次同步 + cron 装载

## 一次性安装

```bash
# 推荐：一键安装
python3 scripts/wecom_caldav.py install \
  --username <邮箱> --password <CalDAV密码> --server caldav.wecom.work
```

**获取企微 CalDAV 密码**：企微 → 工作台 → 日程 → 右上角「三」→ 日程设置 → 同步至其他日历 → 获取密码

## 日常使用

```bash
# 查询日程（毫秒级，读缓存）
python3 scripts/wecom_caldav.py query
python3 scripts/wecom_caldav.py query --start 2026-04-20 --end 2026-04-26

# 创建日程
python3 scripts/wecom_caldav.py create \
  --summary "会议标题" --date 2026-04-21 \
  --start-time 14:00 --end-time 15:00 \
  --location "会议室A"

# 删除日程
python3 scripts/wecom_caldav.py delete --uid <UID>

# 强制实时拉取（绕过缓存）
python3 scripts/wecom_caldav.py query --live

# 缓存/后台任务管理
python3 scripts/wecom_caldav.py cache-status
python3 scripts/wecom_caldav.py daemon-status
python3 scripts/wecom_caldav.py sync          # 手动强制同步
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
    user query -----------------┴----> 毫秒级返回
```

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

本仓库是一个符合 **Openclaw extension 规范** 的插件包：

```
wecom-caldav/                       # Openclaw extension 包根目录
├── openclaw.plugin.json            # 插件清单（声明 id/skills 等）
├── README.md                       # 本文档
├── .gitignore
└── skills/
    └── wecom-caldav/               # 内含一个 skill: wecom-caldav
        ├── SKILL.md                # 技能说明（Agent 读取）
        ├── scripts/
        │   └── wecom_caldav.py     # 主脚本（含所有子命令）
        └── references/
            └── caldav-api.md       # CalDAV API 参考
```

## 安装到 Openclaw

将仓库克隆到 Openclaw 的 extensions 目录：

```bash
cd ~/.openclaw/extensions
git clone git@git.woa.com:muskhuang/wecom-caldav.git

# 首次配置凭证 + 安装后台同步（一条命令搞定）
python3 ~/.openclaw/extensions/wecom-caldav/skills/wecom-caldav/scripts/wecom_caldav.py install \
  --username <邮箱> --password <CalDAV密码>
```

Openclaw 启动时会自动发现并加载本 extension 包下的所有 skill。

## 存储位置

- **配置文件**（凭证）：`~/.openclaw/extensions/wecom-caldav/config.json`
- **缓存**：`~/.openclaw/extensions/wecom-caldav/cache/events.json`
- **cron 日志**：`~/.openclaw/extensions/wecom-caldav/cache/sync.log`

> 这些目录均在用户主目录下，**未纳入版本控制**。凭证、缓存等不会被提交到仓库。

## 实现要点

- **XML 命名空间前缀不固定**：企微 CalDAV 对 REPORT 用 `d:` 前缀、对 PROPFIND 用 `A:` 前缀，所有正则需 prefix-agnostic
- **RRULE UNTIL 时区陷阱**：`dateutil.rrule.rrulestr` 要求 dtstart 为 naive 而 RRULE 含 `UNTIL=...Z` 时报错，需预处理去掉 `Z`
- **VTIMEZONE 虚 DTSTART**：企微 .ics 的 VTIMEZONE 段有 `DTSTART:19700101T000000`，parse 时需跳过
- **time-range 过滤不可信**：必须 PROPFIND 全量 + 客户端过滤

详细说明见 [SKILL.md](./SKILL.md)。

## License

Internal use only.
