# RingKeeper — Missed Call Alert Bridge

A personal system that relays missed calls from an Android phone to a persistent, un-missable popup on a Windows PC, plus a running list of missed calls. Built by a solo developer for personal use (single user, two devices).

## Problem

The user is at their PC most of the day and misses phone calls because the phone is out of sight/hearing. RingKeeper detects a missed call on the phone, sends it to a small relay server, and the PC client shows a popup that **stays on screen until manually dismissed** (not a normal auto-dismissing OS toast), plus a persistent list of missed calls.

## Architecture

```
Android phone --(HTTPS POST)--> Server (Node/Express + WS) --(WebSocket push)--> Windows PC client
     |                                |                                              |
ContentObserver/                 SQLite/Postgres                             Always-on-top popup
BroadcastReceiver                 missed_calls table                         + tray icon + call list
on CallLog
```

Single-user system — no multi-tenant auth needed. Use one long-lived shared secret token for phone→server and PC→server auth.

## Components

### 1. Server (`/server`)
- Node.js + TypeScript + Express
- WebSocket via `ws` library for realtime push to PC client
- SQLite via `better-sqlite3` for storage (simple, file-based, no separate DB server needed for a 2-device personal tool) — keep Prisma as an option if the user wants to swap to Postgres later, but default to SQLite for zero-ops simplicity
- Endpoints:
  - `POST /api/calls` — phone submits a missed call `{ caller_name, number, timestamp }`. Requires `Authorization: Bearer <SHARED_TOKEN>`.
  - `GET /api/calls?since=<iso8601>` — fetch call history, optional filter
  - `PATCH /api/calls/:id/seen` — mark a call as acknowledged
  - `WS /ws` — PC client connects here; server pushes `{ type: "new_call", data: {...} }` on every insert. Also requires the shared token (as a query param or first message).
- On server boot, load `SHARED_TOKEN` from `.env` — never hardcode.
- Deployable to Railway/Render/Fly.io free tier, or runnable locally on a small VPS.

### 2. Android app (`/android`)
- Kotlin, minimum SDK 26+
- Permissions: `READ_CALL_LOG`, `READ_PHONE_STATE`, `RECEIVE_BOOT_COMPLETED`, `INTERNET`
- `BroadcastReceiver` on `TelephonyManager.ACTION_PHONE_STATE_CHANGED` to detect call end, cross-referenced with `CallLog.Calls` content provider to identify missed calls (type = `MISSED_TYPE`)
- Foreground service to survive background restrictions (show a persistent low-priority notification "RingKeeper is watching for missed calls")
- On missed call detected: POST to `{SERVER_URL}/api/calls` with retry-with-backoff if offline (queue locally in a small Room DB table, flush on reconnect)
- Settings screen: server URL, shared token — stored in `EncryptedSharedPreferences`
- On first run, prompt user to disable battery optimization for the app (needed on most OEMs — Xiaomi/Samsung/Oppo are aggressive about killing background services)

### 3. Windows PC client (`/pc-client`)
- Python 3.11+
- `websockets` library for the WS connection to the server, with auto-reconnect on drop
- `pystray` for a system tray icon (right-click: show list, quit)
- `tkinter` for the popup window:
  - `overrideredirect` + `-topmost True`, positioned bottom-right
  - Shows caller name/number + time, stacks multiple popups if several calls come in
  - Only closes on explicit user click (X button) — never auto-dismisses or times out
- Separate `tkinter` (or simple local web view) window for the full missed-call list, fetched from `GET /api/calls`
- Config file (`config.json` or `.env`) for server URL + token
- Auto-start: install a shortcut in `shell:startup` or register a Task Scheduler entry that runs `pythonw.exe main.py` (use `pythonw`, not `python`, to avoid a console window — note: this is the same pyw.exe/python environment mismatch class of bug from the brightness-tool project, so make sure the Task Scheduler action uses the **same interpreter path** that has the required packages installed, not just whatever `pythonw` resolves to on PATH)

## Data model

```sql
CREATE TABLE missed_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  caller_name TEXT,
  number TEXT NOT NULL,
  call_time TEXT NOT NULL,      -- ISO 8601
  received_at TEXT NOT NULL,    -- when server got it
  seen INTEGER NOT NULL DEFAULT 0
);
```

## Build order (do in this sequence)

1. **Server skeleton**: Express app, SQLite schema + migration, `POST /api/calls`, `GET /api/calls`, `PATCH /api/calls/:id/seen`, token middleware. Test with `curl`.
2. **WebSocket layer**: add `/ws`, broadcast on insert. Test with a simple `wscat` client.
3. **PC client MVP**: connect to WS, print incoming calls to console. Then add the always-on-top popup. Then add the list window. Then add tray icon.
4. **Android app**: permissions + manifest, ContentObserver/BroadcastReceiver, POST on missed call. Test by calling the phone from another number and watching server logs.
5. **Foreground service + offline queue** on Android.
6. **Autostart** on both PC client (Task Scheduler) and Android (boot receiver).
7. **Polish**: retry/reconnect logic, mark-as-seen sync between list view and popups, basic error logging on all three components.

## Non-goals (skip unless asked)
- No multi-user auth system — one shared token is sufficient.
- No push notifications via FCM — direct WebSocket is simpler for a single always-on PC.
- No mobile UI polish beyond a basic settings screen — this app has one job.

## Environment variables (server `.env`)

```
PORT=3000
SHARED_TOKEN=<generate a long random string>
DB_PATH=./data/ringkeeper.db
```

## Deliverable checklist for Claude Code
- [ ] `/server` — Express + WS server with SQLite, all three endpoints, token auth
- [ ] `/android` — Kotlin app that detects missed calls and POSTs them, with foreground service
- [ ] `/pc-client` — Python client with popup, list view, tray icon, autostart script
- [ ] Root `README.md` explaining how to run all three parts and how to generate/set the shared token
