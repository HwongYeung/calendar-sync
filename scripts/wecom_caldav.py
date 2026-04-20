#!/usr/bin/env python3
"""WeChat Work (企业微信) CalDAV Calendar Client

Supports: list-calendars, query, create, delete operations
against the WeChat Work CalDAV server (caldav.wecom.work).

Config is stored in ~/.openclaw/extensions/wecom-caldav/config.json

Author: muskhuang
Repository: https://git.woa.com/muskhuang/wecom-caldav
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta

import caldav
from dateutil.parser import isoparse

CONFIG_PATH = os.path.expanduser("~/.openclaw/extensions/wecom-caldav/config.json")
CACHE_DIR = os.path.expanduser("~/.openclaw/extensions/wecom-caldav/cache")
CACHE_EVENTS_PATH = os.path.join(CACHE_DIR, "events.json")
CACHE_META_PATH = os.path.join(CACHE_DIR, "meta.json")
CACHE_STALE_MINUTES = 20  # warn if cache older than this


def load_cache():
    """Load cached events + meta. Returns (events, meta) or (None, None) if no cache."""
    if not os.path.exists(CACHE_EVENTS_PATH):
        return None, None
    try:
        with open(CACHE_EVENTS_PATH, "r") as f:
            events = json.load(f)
        meta = {}
        if os.path.exists(CACHE_META_PATH):
            with open(CACHE_META_PATH, "r") as f:
                meta = json.load(f)
        return events, meta
    except (json.JSONDecodeError, IOError):
        return None, None


def save_cache(events, meta_extra=None):
    """Atomically write events + meta to cache directory."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    meta = {
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "event_count": len(events),
    }
    if meta_extra:
        meta.update(meta_extra)

    # Atomic write: tmp + rename
    for path, data in [(CACHE_EVENTS_PATH, events), (CACHE_META_PATH, meta)]:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, path)


def cache_age_minutes():
    """Return cache age in minutes, or None if no cache."""
    if not os.path.exists(CACHE_META_PATH):
        return None
    try:
        with open(CACHE_META_PATH, "r") as f:
            meta = json.load(f)
        synced = datetime.fromisoformat(meta["synced_at"])
        return (datetime.now() - synced).total_seconds() / 60
    except Exception:
        return None


def load_config():
    """Load CalDAV config from disk. Returns None if not configured."""
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def save_config(config):
    """Save CalDAV config to disk."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_client(config):
    """Create and return a caldav DAVClient."""
    url = config.get("url", "https://caldav.wecom.work/calendar/")
    return caldav.DAVClient(url=url, username=config["username"], password=config["password"])


def get_principal(config):
    """Get the CalDAV principal."""
    client = get_client(config)
    return client.principal()


def cmd_setup(args):
    """Configure CalDAV credentials."""
    config = {}
    config["username"] = args.username or input("用户名 (如 yourname@company.com): ").strip()
    config["password"] = args.password or input("密码: ").strip()
    config["server"] = args.server or input("服务器 (默认 caldav.wecom.work): ").strip() or "caldav.wecom.work"
    config["url"] = f"https://{config['server']}/calendar/"

    # Test connection
    try:
        client = get_client(config)
        principal = client.principal()
        calendars = principal.calendars()
        print(f"✅ 连接成功! 发现 {len(calendars)} 个日历")
        for cal in calendars:
            try:
                name = cal.get_display_name()
            except Exception:
                name = str(cal.url)
            print(f"  - {name}")
        save_config(config)
        print(f"配置已保存到 {CONFIG_PATH}")
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        sys.exit(1)

    # === Post-setup: guide user to install the background daemon ===
    daemon_installed = CRON_TAG in _current_crontab()
    if daemon_installed:
        print("ℹ️ 检测到后台同步任务已安装，无需重复配置")
        return

    if getattr(args, 'skip_daemon', False):
        print()
        print("⚠️ 已跳过后台同步安装。查询将每次实时拉取（较慢）")
        print("   稍后可运行: wecom_caldav.py daemon-install --interval 15")
        return

    auto = getattr(args, 'auto_daemon', False)
    if not auto:
        print()
        print("📌 下一步推荐：安装后台同步任务（cron 每 15 分钟刷新缓存）")
        print("   安装后 query 响应时间从 ~40s 降到 ~0.1s")
        try:
            ans = input("现在安装？[Y/n]: ").strip().lower()
        except EOFError:
            ans = "y"
        auto = ans in ("", "y", "yes")

    if auto:
        print()
        print("🔧 正在安装后台同步任务...")
        daemon_args = argparse.Namespace(interval=15)
        cmd_daemon_install(daemon_args)
    else:
        print("⏭️ 已跳过。稍后可运行: wecom_caldav.py daemon-install --interval 15")


def cmd_install(args):
    """All-in-one: setup credentials + install background daemon."""
    setup_args = argparse.Namespace(
        username=args.username,
        password=args.password,
        server=args.server,
        auto_daemon=True,
        skip_daemon=False,
    )
    cmd_setup(setup_args)


def cmd_list_calendars(args):
    """List all available calendars."""
    config = load_config()
    if not config:
        print("❌ 未配置。请先运行: wecom_caldav.py setup")
        sys.exit(1)

    principal = get_principal(config)
    calendars = principal.calendars()
    print(f"共 {len(calendars)} 个日历:")
    for cal in calendars:
        try:
            name = cal.get_display_name()
        except Exception:
            name = str(cal.url)
        cal_id = str(cal.url).rstrip("/").split("/")[-1]
        print(f"  {cal_id}\t{name}")


def _print_event(ev):
    """Pretty-print a single event dict to stdout."""
    summary = ev.get("summary", "(无标题)")
    dtstart = ev.get("dtstart", "?")
    dtend = ev.get("dtend", "?")
    location = ev.get("location", "")
    organizer = ev.get("organizer", "")
    uid = ev.get("uid", "")
    try:
        if isinstance(dtstart, str):
            dtstart = isoparse(dtstart).strftime("%Y-%m-%d %H:%M")
        if isinstance(dtend, str):
            dtend = isoparse(dtend).strftime("%H:%M")
    except Exception:
        pass
    print(f"  📅 {summary}")
    print(f"     时间: {dtstart} ~ {dtend}")
    if location:
        print(f"     地点: {location}")
    if organizer:
        print(f"     组织人: {organizer}")
    print(f"     UID: {uid}")
    print()


def cmd_query(args):
    """Query events in a date range."""
    config = load_config()
    if not config:
        print("❌ 未配置。请先运行: wecom_caldav.py setup")
        sys.exit(1)

    # Parse date range
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d")
    else:
        now = datetime.now()
        start = now - timedelta(days=now.weekday())  # this Monday

    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d")
    else:
        end = start + timedelta(days=6)  # default: 1 week

    filter_start = start.replace(hour=0, minute=0, second=0)
    filter_end = end.replace(hour=23, minute=59, second=59)

    # === Cache-first path ===
    # Default: read from local cache (populated by `sync` or the background daemon).
    # Use --live to force a network fetch.
    if not getattr(args, 'live', False):
        cached_events, cached_meta = load_cache()
        if cached_events is not None:
            age = cache_age_minutes()
            age_str = f"{age:.1f} 分钟前" if age is not None else "未知时间"
            if age is not None and age > CACHE_STALE_MINUTES:
                print(f"⚠️ 缓存已过期（{age_str}同步），建议加 --live 或运行 sync 命令刷新", file=sys.stderr)

            # Filter cached events by date range (events are pre-expanded w/ RRULE)
            filtered = []
            for ev in cached_events:
                ev_start_str = ev.get("dtstart", "")
                if not ev_start_str:
                    continue
                try:
                    ev_dt = isoparse(ev_start_str) if isinstance(ev_start_str, str) else ev_start_str
                    ev_naive = ev_dt.replace(tzinfo=None) if hasattr(ev_dt, 'tzinfo') else ev_dt
                    if filter_start <= ev_naive <= filter_end:
                        if args.calendar and ev.get("calendar_id") != args.calendar:
                            continue
                        filtered.append(ev)
                except Exception:
                    continue
            filtered.sort(key=lambda e: str(e.get("dtstart", "")))

            # Dedupe by (summary, dtstart) across calendars/duplicate ics files
            seen = set()
            unique = []
            for e in filtered:
                k = (e.get("summary", ""), e.get("dtstart", ""))
                if k not in seen:
                    seen.add(k)
                    unique.append(e)

            if args.json:
                print(json.dumps(unique, ensure_ascii=False, indent=2, default=str))
                return
            if not unique:
                print(f"📅 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} 无日程 (缓存: {age_str})")
            else:
                print(f"📅 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} 共 {len(unique)} 个日程 (缓存: {age_str}):")
                print()
                for ev in unique:
                    _print_event(ev)
            return
        else:
            # No cache at all: fall through to live fetch, and also save cache for next time.
            print("🔄 首次使用，正在实时拉取并初始化缓存...", file=sys.stderr)
            args.full_scan = True  # force full scan to seed cache properly
            args._write_cache_on_success = True

    # If user explicitly asked for --live but didn't pass --full-scan,
    # still upgrade to full-scan (REPORT mode misses many events due to server bug)
    if getattr(args, 'live', False) and not getattr(args, 'full_scan', False):
        args.full_scan = True

    # === Live fetch path ===
    # (original code continues below, will also write cache if _write_cache_on_success is set)
    # Parse date range (legacy variables expected by old code below)

    # Store user's desired range for client-side filtering
    filter_start = start.replace(hour=0, minute=0, second=0)
    filter_end = end.replace(hour=23, minute=59, second=59)

    # WeChat Work CalDAV server has a quirk: narrow date ranges (e.g., single day)
    # return 0 results. Always use at least a 7-day query window, then filter client-side.
    query_start = min(start, start - timedelta(days=start.weekday()))  # align to Monday
    query_end = max(end, query_start + timedelta(days=6))  # ensure at least 7 days

    # For the REPORT time-range, use naive UTC (server treats TZ08 as UTC+8 internally)
    start_utc = query_start.strftime("%Y%m%dT000000Z")
    end_utc = query_end.strftime("%Y%m%dT235959Z")

    # Use curl-based approach for reliability (caldav search can timeout)
    import subprocess

    base_url = config["url"].rstrip("/")
    auth = f"{config['username']}:{config['password']}"

    # Determine which calendars to query
    principal = get_principal(config)
    calendars = principal.calendars()

    target_cal = args.calendar
    all_events = []

    for cal in calendars:
        cal_url = str(cal.url).rstrip("/")
        cal_id = cal_url.split("/")[-1]

        if target_cal and cal_id != target_cal:
            continue

        hrefs = []

        if getattr(args, 'full_scan', False):
            # Full-scan mode: PROPFIND to list ALL .ics, filter client-side
            # Use getlastmodified to only GET recently-modified events
            propfind_body = '<?xml version="1.0"?><propfind xmlns="DAV:"><prop><getetag/><getlastmodified/></prop></propfind>'
            try:
                result = subprocess.run(
                    ["curl", "-s", "-u", auth, "-X", "PROPFIND", cal_url + "/",
                     "-H", "Depth: 1", "-H", "Content-Type: application/xml",
                     "-d", propfind_body],
                    capture_output=True, text=True, timeout=30
                )
            except subprocess.TimeoutExpired:
                print(f"⚠️ 日历 {cal_id} PROPFIND 超时，跳过")
                continue

            if result.returncode != 0 or not result.stdout:
                continue

            # Parse response blocks: each response has href + lastmodified
            # Note: server uses varying namespace prefixes (d:, A:, etc.), so match prefix-agnostic
            import re
            response_blocks = re.findall(
                r'<[A-Za-z]+:response>(.*?)</[A-Za-z]+:response>',
                result.stdout, re.DOTALL
            )
            candidate_hrefs = []
            for block in response_blocks:
                href_m = re.search(r'<[A-Za-z]+:href>(/calendar/[^<]+\.ics)</[A-Za-z]+:href>', block)
                if not href_m:
                    continue
                href = href_m.group(1)
                # Parse lastmodified (may have varying prefix or even empty prefix)
                lm_m = re.search(r'<[A-Za-z]*:?getlastmodified>([^<]+)</[A-Za-z]*:?getlastmodified>', block)
                lastmod = lm_m.group(1).strip() if lm_m else None
                candidate_hrefs.append((href, lastmod))

            # Heuristic: keep events modified within last 180 days OR
            # whose URL suggests it's new (we can't know exactly, so just GET all)
            # For performance, keep only recent-ish ones based on lastmodified
            from email.utils import parsedate_to_datetime
            cutoff = datetime.now() - timedelta(days=180)
            for href, lastmod in candidate_hrefs:
                if lastmod:
                    try:
                        lm_dt = parsedate_to_datetime(lastmod).replace(tzinfo=None)
                        if lm_dt < cutoff:
                            continue
                    except Exception:
                        pass
                hrefs.append(href)
            print(f"🔍 [{cal_id}] 全量扫描: {len(candidate_hrefs)} 个文件，筛选后需 GET {len(hrefs)} 个", file=sys.stderr)
        else:
            # Default: CalDAV REPORT with time-range (fast but may miss events)
            report_body = f"""<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{start_utc}" end="{end_utc}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""

            try:
                result = subprocess.run(
                    ["curl", "-s", "-u", auth, "-X", "REPORT", cal_url + "/",
                     "-H", "Depth: 1", "-H", "Content-Type: application/xml",
                     "-d", report_body],
                    capture_output=True, text=True, timeout=15
                )
            except subprocess.TimeoutExpired:
                print(f"⚠️ 日历 {cal_id} 查询超时，跳过")
                continue

            if result.returncode != 0 or not result.stdout:
                continue

            # Parse hrefs from XML response (prefix-agnostic)
            import re
            hrefs = re.findall(r'<[A-Za-z]+:href>(/calendar/[^<]+\.ics)</[A-Za-z]+:href>', result.stdout)

        # Step 2: GET each .ics file (parallel)
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_ics(href):
            try:
                ics_result = subprocess.run(
                    ["curl", "-s", "-u", auth, f"https://{config['server']}{href}"],
                    capture_output=True, text=True, timeout=10
                )
                if ics_result.returncode != 0 or not ics_result.stdout:
                    return href, None
                return href, ics_result.stdout
            except subprocess.TimeoutExpired:
                return href, None

        with ThreadPoolExecutor(max_workers=20) as ex:
            fetched = list(ex.map(_fetch_ics, hrefs))

        for href, ics_text in fetched:
            if not ics_text:
                continue
            event = parse_ics_event(ics_text)
            if event:
                ev_start = event.get("dtstart")
                if not ev_start:
                    continue
                try:
                    ev_dt = isoparse(ev_start) if isinstance(ev_start, str) else ev_start
                    ev_start_naive = ev_dt.replace(tzinfo=None) if hasattr(ev_dt, 'tzinfo') else ev_dt
                except Exception:
                    ev_start_naive = None

                ev_end = event.get("dtend")
                ev_end_naive = None
                if ev_end:
                    try:
                        ev_end_dt = isoparse(ev_end) if isinstance(ev_end, str) else ev_end
                        ev_end_naive = ev_end_dt.replace(tzinfo=None) if hasattr(ev_end_dt, 'tzinfo') else ev_end_dt
                    except Exception:
                        pass

                rrule_str = event.get("rrule")
                exdates = event.get("exdate", [])
                if not isinstance(exdates, list):
                    exdates = [exdates] if exdates else []

                # Expand recurring events
                if rrule_str and ev_start_naive:
                    try:
                        from dateutil.rrule import rrulestr
                        # Build rrule with DTSTART anchor
                        duration = (ev_end_naive - ev_start_naive) if ev_end_naive else timedelta(minutes=30)
                        # Strip 'Z' from UNTIL to avoid tz-aware/naive conflict with naive dtstart
                        import re as _re
                        rrule_clean = _re.sub(r'(UNTIL=\d{8}T\d{6})Z', r'\1', rrule_str)
                        rule = rrulestr(rrule_clean, dtstart=ev_start_naive)
                        # Parse EXDATE values
                        excluded = set()
                        for exd in exdates:
                            try:
                                ex_dt = isoparse(exd) if isinstance(exd, str) else exd
                                excluded.add(ex_dt.replace(tzinfo=None) if hasattr(ex_dt, 'tzinfo') else ex_dt)
                            except Exception:
                                pass
                        # Generate occurrences within the user's window
                        for occ in rule.between(filter_start, filter_end, inc=True):
                            if occ in excluded:
                                continue
                            occ_event = dict(event)
                            occ_event["dtstart"] = occ.strftime("%Y-%m-%dT%H:%M:%S")
                            occ_event["dtend"] = (occ + duration).strftime("%Y-%m-%dT%H:%M:%S")
                            occ_event["calendar_id"] = cal_id
                            occ_event["ics_path"] = href
                            occ_event["recurring"] = True
                            all_events.append(occ_event)
                    except Exception as e:
                        # Fall back to single event if rrule parsing fails
                        if ev_start_naive and filter_start <= ev_start_naive <= filter_end:
                            event["calendar_id"] = cal_id
                            event["ics_path"] = href
                            all_events.append(event)
                else:
                    # Non-recurring event: apply simple range filter
                    if ev_start_naive and filter_start <= ev_start_naive <= filter_end:
                        event["calendar_id"] = cal_id
                        event["ics_path"] = href
                        all_events.append(event)

    # Sort by start time
    all_events.sort(key=lambda e: str(e.get("dtstart", "")))

    # Optionally persist cache (first-time auto seed or explicit sync)
    if getattr(args, '_write_cache_on_success', False) or getattr(args, '_sync_mode', False):
        try:
            save_cache(all_events, meta_extra={
                "mode": "sync" if getattr(args, '_sync_mode', False) else "query-seed",
                "window": f"{start.strftime('%Y-%m-%d')}~{end.strftime('%Y-%m-%d')}",
            })
            if getattr(args, '_sync_mode', False):
                print(f"✅ 已同步 {len(all_events)} 个日程到缓存 ({CACHE_EVENTS_PATH})", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ 写入缓存失败: {e}", file=sys.stderr)

    # In pure sync mode, don't print the event list to stdout
    if getattr(args, '_sync_mode', False):
        return

    # Output
    if args.json:
        print(json.dumps(all_events, ensure_ascii=False, indent=2, default=str))
    else:
        if not all_events:
            print(f"📅 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} 无日程")
        else:
            print(f"📅 {start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')} 共 {len(all_events)} 个日程:")
            print()
            for ev in all_events:
                _print_event(ev)


def parse_ics_event(ics_text):
    """Parse a VEVENT from ICS text into a dict."""
    event = {}
    in_vevent = False
    current_key = None
    current_val = None

    for line in ics_text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            in_vevent = True
            continue
        if line == "END:VEVENT":
            if current_key:
                event[current_key] = current_val
            break
        if not in_vevent:
            continue

        # Handle continuation lines (start with space/tab)
        if line.startswith(" ") or line.startswith("\t"):
            if current_key:
                current_val += line[1:]
            continue

        # Save previous key-val
        if current_key:
            event[current_key] = current_val

        # Parse new line
        if ":" not in line:
            current_key = None
            continue

        # Handle properties with params like DTSTART;TZID=TZ08:20260421T100000
        key_part, _, val = line.partition(":")
        # Normalize key (remove params after ;)
        key = key_part.split(";")[0]

        # Map interesting keys
        key_map = {
            "SUMMARY": "summary",
            "DTSTART": "dtstart",
            "DTEND": "dtend",
            "LOCATION": "location",
            "DESCRIPTION": "description",
            "UID": "uid",
            "ORGANIZER": "organizer",
            "RRULE": "rrule",
            "EXDATE": "exdate",
            "RECURRENCE-ID": "recurrence_id",
        }

        if key in key_map:
            current_key = key_map[key]
            # For ORGANIZER, extract CN if present
            if key == "ORGANIZER":
                cn_match = __import__("re").search(r'CN="([^"]+)"', key_part)
                current_val = cn_match.group(1) if cn_match else val.replace("mailto:", "")
            elif key == "EXDATE":
                # EXDATE may have multiple values comma-separated; collect as list
                existing = event.get("exdate", [])
                if not isinstance(existing, list):
                    existing = [existing]
                for v in val.split(","):
                    existing.append(parse_ics_datetime(v.strip()))
                event["exdate"] = existing
                current_key = None
                current_val = None
            elif key == "RRULE":
                current_val = val
            else:
                # Try to parse datetime values
                if key in ("DTSTART", "DTEND"):
                    # Skip VTIMEZONE dummy values (19700101)
                    if val.startswith("1970"):
                        current_key = None
                        current_val = None
                        continue
                    # Prefer TZID-prefixed values over bare values
                    has_tzid = "TZID" in key_part
                    if current_key in event and not has_tzid:
                        # Already have a TZID value, don't overwrite with bare value
                        current_key = None
                        current_val = None
                        continue
                    current_val = parse_ics_datetime(val)
                else:
                    current_val = val
        else:
            current_key = None
            current_val = None

    # Save last key-val
    if current_key:
        event[current_key] = current_val

    return event if event.get("uid") else None


def parse_ics_datetime(val):
    """Parse ICS datetime value to ISO format string."""
    # Format: 20260421T100000 or 20260421T100000Z
    try:
        clean = val.strip()
        if clean.endswith("Z"):
            dt = datetime.strptime(clean, "%Y%m%dT%H%M%SZ")
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            dt = datetime.strptime(clean, "%Y%m%dT%H%M%S")
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return val


def cmd_create(args):
    """Create a new calendar event."""
    config = load_config()
    if not config:
        print("❌ 未配置。请先运行: wecom_caldav.py setup")
        sys.exit(1)

    # Parse time arguments
    try:
        dtstart = datetime.strptime(f"{args.date} {args.start_time}", "%Y-%m-%d %H:%M")
        dtend = datetime.strptime(f"{args.date} {args.end_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        print("❌ 时间格式错误，需要: YYYY-MM-DD HH:MM")
        sys.exit(1)

    uid = f"{uuid.uuid4().hex}"
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dtstart_ics = dtstart.strftime("%Y%m%dT%H%M%S")
    dtend_ics = dtend.strftime("%Y%m%dT%H%M%S")

    # Build ICS content
    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OpenClaw//WeChat Work CalDAV//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VTIMEZONE",
        "TZID:TZ08",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        "TZOFFSETFROM:+0800",
        "TZOFFSETTO:+0800",
        "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"CREATED:{dtstamp}",
        f"DTSTART;TZID=TZ08:{dtstart_ics}",
        f"DTEND;TZID=TZ08:{dtend_ics}",
        f"SUMMARY:{args.summary}",
    ]

    if args.location:
        ics_lines.append(f"LOCATION:{args.location}")
    if args.description:
        ics_lines.append(f"DESCRIPTION:{args.description}")

    ics_lines.extend([
        "TRANSP:OPAQUE",
        "BEGIN:VALARM",
        "TRIGGER:-PT15M",
        "ACTION:DISPLAY",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ])

    ics_content = "\r\n".join(ics_lines)

    # Determine target calendar
    principal = get_principal(config)
    calendars = principal.calendars()

    target_cal = args.calendar
    cal_obj = None
    for cal in calendars:
        cal_id = str(cal.url).rstrip("/").split("/")[-1]
        if not target_cal or cal_id == target_cal:
            try:
                name = cal.get_display_name()
            except Exception:
                name = ""
            # Default to first calendar if not specified
            if not target_cal:
                cal_obj = cal
                break
            else:
                cal_obj = cal
                break

    if not cal_obj:
        print("❌ 未找到目标日历")
        sys.exit(1)

    # Upload event via PUT
    import subprocess
    cal_url = str(cal_obj.url).rstrip("/")
    event_url = f"{cal_url}/{uid}.ics"
    auth = f"{config['username']}:{config['password']}"

    # Write ICS to temp file
    tmp_path = f"/tmp/{uid}.ics"
    with open(tmp_path, "w") as f:
        f.write(ics_content)

    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-u", auth,
             "-X", "PUT", event_url,
             "-H", "Content-Type: text/calendar; charset=utf-8",
             "--data-binary", f"@{tmp_path}"],
            capture_output=True, text=True, timeout=15
        )
        http_code = result.stdout.strip()
        # CalDAV PUT returns 200, 201, 204, or 207 (Multi-Status) on success
        if http_code in ("200", "201", "204", "207"):
            print(f"✅ 日程已创建: {args.summary}")
            print(f"   时间: {dtstart.strftime('%Y-%m-%d %H:%M')} ~ {dtend.strftime('%H:%M')}")
            if args.location:
                print(f"   地点: {args.location}")
        else:
            print(f"❌ 创建失败 (HTTP {http_code})")
            print(result.stdout)
    except subprocess.TimeoutExpired:
        print("❌ 创建超时")
    finally:
        os.unlink(tmp_path)


def cmd_delete(args):
    """Delete a calendar event by UID."""
    config = load_config()
    if not config:
        print("❌ 未配置。请先运行: wecom_caldav.py setup")
        sys.exit(1)

    uid = args.uid
    if not uid:
        print("❌ 请指定要删除的日程 UID")
        sys.exit(1)

    # Search for the event across calendars
    import subprocess
    auth = f"{config['username']}:{config['password']}"
    principal = get_principal(config)
    calendars = principal.calendars()

    found = False
    for cal in calendars:
        cal_url = str(cal.url).rstrip("/")
        cal_id = cal_url.split("/")[-1]

        # Try to find the .ics file matching the UID
        # The filename might be the UID or a different name
        # We need to search - try common patterns
        possible_paths = [
            f"{cal_url}/{uid}.ics",
        ]

        # Also check via PROPFIND
        try:
            result = subprocess.run(
                ["curl", "-s", "-u", auth, "-X", "PROPFIND", cal_url + "/",
                 "-H", "Depth: 1",
                 "-H", "Content-Type: application/xml",
                 "-d", '<?xml version="1.0"?><propfind xmlns="DAV:"><prop><d:getetag/></prop></propfind>'],
                capture_output=True, text=True, timeout=15
            )
            import re
            hrefs = re.findall(r'<d:href>(/calendar/[^<]+\.ics)</d:href>', result.stdout)
            for href in hrefs:
                if uid in href:
                    possible_paths.append(f"https://{config['server']}{href}")
        except Exception:
            pass

        for path in possible_paths:
            if path.startswith("/"):
                url = f"https://{config['server']}{path}"
            else:
                url = path

            # Try DELETE
            try:
                result = subprocess.run(
                    ["curl", "-s", "-w", "\n%{http_code}", "-u", auth,
                     "-X", "DELETE", url],
                    capture_output=True, text=True, timeout=10
                )
                http_code = result.stdout.strip().split("\n")[-1]
                if http_code in ("200", "204"):
                    print(f"✅ 日程已删除 (UID: {uid})")
                    found = True
                    break
            except subprocess.TimeoutExpired:
                continue

        if found:
            break

    if not found:
        print(f"❌ 未找到日程 (UID: {uid})，请确认 UID 是否正确")
        print("💡 提示: 使用 query 命令查看日程及其 UID")
        sys.exit(1)


# ============================================================================
# Sync & background daemon
# ============================================================================

def cmd_sync(args):
    """Full-scan fetch and write to local cache. Intended for cron/daemon use."""
    # Reuse cmd_query's live-fetch path with flags to suppress stdout and write cache.
    import argparse as _ap
    from datetime import datetime as _dt, timedelta as _td
    # Default sync window: 30 days back ~ 90 days forward (covers typical query ranges)
    days_back = args.days_back if args.days_back is not None else 30
    days_forward = args.days_forward if args.days_forward is not None else 90
    today = _dt.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - _td(days=days_back)
    end = today + _td(days=days_forward)

    fake_args = _ap.Namespace(
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        calendar=None,
        json=False,
        full_scan=True,
        live=True,              # bypass cache read
        _sync_mode=True,        # suppress stdout + write cache
        _write_cache_on_success=True,
    )
    cmd_query(fake_args)


def cmd_cache_status(args):
    """Show cache status."""
    events, meta = load_cache()
    if events is None:
        print("❌ 缓存不存在")
        print(f"   路径: {CACHE_EVENTS_PATH}")
        print(f"   执行 'wecom_caldav.py sync' 初始化")
        return
    age = cache_age_minutes()
    age_str = f"{age:.1f} 分钟" if age is not None else "未知"
    print(f"📦 缓存状态")
    print(f"   路径: {CACHE_EVENTS_PATH}")
    print(f"   事件数: {len(events)}")
    print(f"   最后同步: {meta.get('synced_at', '?')} ({age_str}前)")
    print(f"   同步窗口: {meta.get('window', '?')}")
    if age is not None and age > CACHE_STALE_MINUTES:
        print(f"   ⚠️ 已过期 (>{CACHE_STALE_MINUTES} 分钟)，建议刷新")
    else:
        print(f"   ✅ 新鲜")


# --- Cross-platform scheduling via cron (Linux + macOS) ---

CRON_TAG = "# wecom-caldav-sync"  # unique marker for our cron entry


def _current_crontab():
    """Return current user's crontab content, or '' if none."""
    import subprocess as _sp
    try:
        r = _sp.run(["crontab", "-l"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""
    except FileNotFoundError:
        print("❌ 未检测到 crontab，请先安装 cron 服务", file=sys.stderr)
        sys.exit(2)


def _install_crontab(content):
    """Replace current user's crontab with new content."""
    import subprocess as _sp, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".cron", delete=False) as f:
        f.write(content if content.endswith("\n") else content + "\n")
        tmp_path = f.name
    try:
        r = _sp.run(["crontab", tmp_path], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"❌ crontab 安装失败: {r.stderr}", file=sys.stderr)
            sys.exit(2)
    finally:
        os.unlink(tmp_path)


def cmd_daemon_install(args):
    """Install a cron entry that runs `sync` every N minutes. Cross-platform (Linux+macOS)."""
    interval = args.interval or 15
    # Resolve the python interpreter and script paths actually used
    py = os.environ.get("WECOM_PY") or sys.executable or "/usr/bin/env python3"
    script = os.path.abspath(__file__)
    log_path = os.path.join(CACHE_DIR, "sync.log")
    lock_path = os.path.join(CACHE_DIR, "sync.lock")
    os.makedirs(CACHE_DIR, exist_ok=True)

    # Use flock to prevent concurrent runs; fallback to (: ) if flock absent.
    # Prefer /usr/bin/flock when available (standard on Linux); macOS may lack it.
    has_flock = os.path.exists("/usr/bin/flock") or os.path.exists("/bin/flock")
    if has_flock:
        cmd_core = f"/usr/bin/flock -n {lock_path} {py} {script} sync"
    else:
        # macOS: use a simple PID file check
        cmd_core = (
            f"(if [ -f {lock_path} ] && kill -0 $(cat {lock_path}) 2>/dev/null; then exit 0; fi; "
            f"echo $$ > {lock_path}; {py} {script} sync; rm -f {lock_path})"
        )

    cron_line = f"*/{interval} * * * * {cmd_core} >> {log_path} 2>&1 {CRON_TAG}"

    current = _current_crontab()
    # Remove old entries with the same tag
    new_lines = [ln for ln in current.splitlines() if CRON_TAG not in ln]
    new_lines.append(cron_line)
    _install_crontab("\n".join(new_lines) + "\n")

    print(f"✅ 已安装 cron 任务: 每 {interval} 分钟同步一次")
    print(f"   命令: {cron_line}")
    print(f"   日志: {log_path}")
    if not has_flock:
        print(f"   注意: 未检测到 /usr/bin/flock，已使用 PID 锁文件兜底（macOS 常见）")
    # Immediately run once to seed the cache
    print(f"🔄 立即执行首次同步...")
    cmd_sync(argparse.Namespace(days_back=None, days_forward=None))


def cmd_daemon_uninstall(args):
    """Remove the cron entry."""
    current = _current_crontab()
    if CRON_TAG not in current:
        print("ℹ️ 未找到 cron 任务（可能已卸载）")
        return
    new_lines = [ln for ln in current.splitlines() if CRON_TAG not in ln]
    _install_crontab("\n".join(new_lines) + "\n" if new_lines else "")
    print("✅ 已卸载 cron 任务")


def cmd_daemon_status(args):
    """Show cron entry status."""
    current = _current_crontab()
    lines = [ln for ln in current.splitlines() if CRON_TAG in ln]
    if not lines:
        print("❌ 未安装 cron 任务")
        print("   执行 'wecom_caldav.py daemon-install' 安装")
        return
    print("✅ cron 任务已安装:")
    for ln in lines:
        print(f"   {ln}")
    # Also show cache status
    print()
    cmd_cache_status(args)


def main():
    parser = argparse.ArgumentParser(description="企业微信 CalDAV 日程管理")
    subparsers = parser.add_subparsers(dest="command", help="操作命令")

    # setup
    p_setup = subparsers.add_parser("setup", help="配置 CalDAV 连接信息 (含 daemon 安装引导)")
    p_setup.add_argument("--username", "-u", help="用户名 (如 yourname@company.com)")
    p_setup.add_argument("--password", "-p", help="密码")
    p_setup.add_argument("--server", "-s", help="服务器地址 (默认 caldav.wecom.work)")
    p_setup.add_argument("--auto-daemon", action="store_true", help="连接成功后自动安装后台同步任务 (无交互)")
    p_setup.add_argument("--skip-daemon", action="store_true", help="跳过后台同步安装引导")

    # install (all-in-one: setup + auto daemon)
    p_install = subparsers.add_parser("install", help="一键安装: 配置凭证 + 后台同步 (推荐首次使用)")
    p_install.add_argument("--username", "-u", help="用户名")
    p_install.add_argument("--password", "-p", help="密码")
    p_install.add_argument("--server", "-s", help="服务器地址 (默认 caldav.wecom.work)")

    # list-calendars
    subparsers.add_parser("list-calendars", help="列出所有日历")

    # query
    p_query = subparsers.add_parser("query", help="查询日程 (默认读本地缓存)")
    p_query.add_argument("--start", help="开始日期 (YYYY-MM-DD，默认本周一)")
    p_query.add_argument("--end", help="结束日期 (YYYY-MM-DD，默认一周后)")
    p_query.add_argument("--calendar", "-c", help="指定日历 ID (默认查询所有)")
    p_query.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    p_query.add_argument("--full-scan", action="store_true", help="全量扫描模式（绕过服务器 time-range 过滤 bug）")
    p_query.add_argument("--live", action="store_true", help="强制实时拉取，不使用缓存")

    # sync (write cache)
    p_sync = subparsers.add_parser("sync", help="全量同步日程到本地缓存（供 cron/daemon 调用）")
    p_sync.add_argument("--days-back", type=int, default=None, help="向前同步天数 (默认 30)")
    p_sync.add_argument("--days-forward", type=int, default=None, help="向后同步天数 (默认 90)")

    # cache-status
    subparsers.add_parser("cache-status", help="查看缓存状态")

    # daemon-install / uninstall / status (cron-based, 跨 Linux+macOS)
    p_daemon_install = subparsers.add_parser("daemon-install", help="安装后台同步任务 (cron 实现)")
    p_daemon_install.add_argument("--interval", type=int, default=15, help="同步间隔 (分钟，默认 15)")
    subparsers.add_parser("daemon-uninstall", help="卸载后台同步任务")
    subparsers.add_parser("daemon-status", help="查看后台同步任务状态")

    # create
    p_create = subparsers.add_parser("create", help="创建日程")
    p_create.add_argument("--summary", "-t", required=True, help="日程标题")
    p_create.add_argument("--date", "-d", required=True, help="日期 (YYYY-MM-DD)")
    p_create.add_argument("--start-time", required=True, help="开始时间 (HH:MM)")
    p_create.add_argument("--end-time", required=True, help="结束时间 (HH:MM)")
    p_create.add_argument("--location", "-l", help="地点")
    p_create.add_argument("--description", help="描述")
    p_create.add_argument("--calendar", "-c", help="目标日历 ID")

    # delete
    p_delete = subparsers.add_parser("delete", help="删除日程")
    p_delete.add_argument("--uid", required=True, help="要删除的日程 UID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "setup": cmd_setup,
        "install": cmd_install,
        "list-calendars": cmd_list_calendars,
        "query": cmd_query,
        "sync": cmd_sync,
        "cache-status": cmd_cache_status,
        "daemon-install": cmd_daemon_install,
        "daemon-uninstall": cmd_daemon_uninstall,
        "daemon-status": cmd_daemon_status,
        "create": cmd_create,
        "delete": cmd_delete,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
