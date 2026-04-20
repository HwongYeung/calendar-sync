# CalDAV API Reference

## Server Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `https://caldav.wecom.work/.well-known/caldav` | GET | Discovery, 301 → `/calendar/` |
| `https://caldav.wecom.work/calendar/` | PROPFIND | Principal discovery |
| `https://caldav.wecom.work/calendar/{user}` | PROPFIND | User's calendar home |
| `https://caldav.wecom.work/calendar/{cal_id}/` | PROPFIND/REPORT | Calendar collection |
| `https://caldav.wecom.work/calendar/{cal_id}/{event}.ics` | GET/PUT/DELETE | Event resource |

## Authentication

Basic Auth with username (email) and password obtained from:
- 企业微信 → 工作台 → 日程 → 右上角"三" → 日程设置 → 同步至其他日历

## Common CalDAV Operations

### 1. Discover Principal

```http
PROPFIND /calendar/ HTTP/2
Depth: 0
Content-Type: application/xml

<?xml version="1.0"?>
<propfind xmlns="DAV:">
  <prop><current-user-principal/></prop>
</propfind>
```

Response: `/calendar/muskhuang%40tencent.com`

### 2. List Calendars

```http
PROPFIND /calendar/muskhuang%40tencent.com/ HTTP/2
Depth: 1
Content-Type: application/xml

<?xml version="1.0"?>
<propfind xmlns="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <prop>
    <d:displayname/>
    <c:supported-calendar-component-set/>
    <resourcetype/>
  </prop>
</propfind>
```

### 3. Query Events by Time Range

```http
REPORT /calendar/{cal_id}/ HTTP/2
Depth: 1
Content-Type: application/xml

<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="20260420T000000Z" end="20260426T155959Z"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>
```

**Important**: The server returns `calendar-data` as 404 in REPORT responses. Must GET each `.ics` file individually.

### 4. GET Event ICS

```http
GET /calendar/{cal_id}/{event_id}.ics HTTP/2
Authorization: Basic {creds}
```

Returns full VCALENDAR with VEVENT.

### 5. Create Event (PUT)

```http
PUT /calendar/{cal_id}/{new_uid}.ics HTTP/2
Content-Type: text/calendar; charset=utf-8

BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//OpenClaw//WeChat Work CalDAV//EN
CALSCALE:GREGORIAN
BEGIN:VTIMEZONE
TZID:TZ08
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:+0800
TZOFFSETTO:+0800
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{timestamp}
DTSTART;TZID=TZ08:{start}
DTEND;TZID=TZ08:{end}
SUMMARY:{title}
LOCATION:{location}
TRANSP:OPAQUE
BEGIN:VALARM
TRIGGER:-PT15M
ACTION:DISPLAY
END:VALARM
END:VEVENT
END:VCALENDAR
```

### 6. Delete Event

```http
DELETE /calendar/{cal_id}/{event_id}.ics HTTP/2
```

Returns 200 or 204 on success.

## ICS Event Field Mapping

| ICS Field | Output Key | Notes |
|-----------|-----------|-------|
| UID | uid | Unique identifier |
| SUMMARY | summary | Event title |
| DTSTART;TZID=TZ08 | dtstart | Start time, timezone +08:00 |
| DTEND;TZID=TZ08 | dtend | End time, timezone +08:00 |
| LOCATION | location | May contain meeting link or room |
| DESCRIPTION | description | May contain meeting details, links |
| ORGANIZER;CN="name" | organizer | Organizer display name |
| ATTENDEE;CN="name" | attendees | Participant names |
| RRULE | rrule | Recurrence rule |

## Datetime Format

- ICS format: `20260421T100000` (local) or `20260421T020000Z` (UTC)
- Timezone parameter: `TZID=TZ08` represents UTC+8
- API time-range filter uses UTC: `start="20260420T000000Z"`

## Known Quirks

1. **REPORT calendar-data returns 404**: Must use GET for each .ics file separately
2. **Python caldav search() timeout**: Use curl subprocess for reliability
3. **Event filenames may not match UID**: Some events use generated filenames (e.g., `d1vkuf815nn3giq5huo0.ics`) while the UID inside may differ
4. **Recurring events**: RRULE is included in the ICS; expansion handled client-side
