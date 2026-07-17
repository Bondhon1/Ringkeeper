# RingKeeper — Missed Call Alert Bridge

Relays calls from an Android phone to a persistent, un-missable popup on a Windows PC,
plus a running list of every call. Single user, two devices, one shared secret token.

```
Android phone  ──HTTPS POST──▶  Server (Node + WebSocket)  ──WS push──▶  Windows PC client
   │                                    │                                      │
CallLog observer                   SQLite (all calls,                   Always-on-top popup
(captures ALL call types,          separated by type)                   for MISSED calls
 stored locally first)                                                  + tray icon + call list
```

**What it captures vs. what pops up.** The phone records **every** call — missed, incoming
(answered), outgoing, rejected, blocked, voicemail — into a **local database first** (so
nothing is lost while offline), then syncs to the server. All types are stored and appear
in the PC's list window, grouped by type. Only **missed** calls trigger the always-on-top
popup, which stays on screen until you dismiss it. (Change which types pop up via
`popup_for` in the PC client config — no rebuild needed.)

---

## Repository layout

| Folder        | What it is                                             | Language            |
|---------------|--------------------------------------------------------|---------------------|
| `server/`     | Relay server: HTTP API + WebSocket push + SQLite       | Node.js/TypeScript  |
| `pc-client/`  | Popup + call list + tray icon                          | Python 3.11+        |
| `android/`    | Call capture, local DB, network-aware sync             | Kotlin (Android)    |

---

## 0. Generate the shared token (do this first)

Both the phone and the PC authenticate with one long random token. Generate one:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

You'll paste this **same** value into all three components below.

---

## 1. Server (`server/`)

**Requirements:** Node.js **22.5+** (uses the built-in `node:sqlite` — no native build tools,
no `better-sqlite3` compile step).

```bash
cd server
npm install
cp .env.example .env          # then edit .env
```

Set in `.env`:

```
PORT=3000
SHARED_TOKEN=<the token you generated above>
DB_PATH=./data/ringkeeper.db
```

Run it:

```bash
npm run dev      # watch mode (tsx)
# or
npm run build && npm start
```

**Endpoints** (all under `/api` require `Authorization: Bearer <SHARED_TOKEN>`):

| Method | Path                    | Purpose                                                        |
|--------|-------------------------|----------------------------------------------------------------|
| POST   | `/api/calls`            | Phone submits a call `{caller_name, number, call_type, timestamp, client_uid}` |
| GET    | `/api/calls`            | List calls; filters: `?since=<iso>&type=<type>&limit=<n>`      |
| PATCH  | `/api/calls/:id/seen`   | Mark a call acknowledged                                       |
| WS     | `/ws?token=<token>`     | PC client connects; server pushes `{type:"new_call", data}`   |
| GET    | `/health`               | Unauthenticated health check                                  |

`call_type` is one of: `missed`, `incoming`, `outgoing`, `rejected`, `blocked`,
`voicemail`, `unknown`. `client_uid` makes retries idempotent — re-POSTing the same
uid returns the existing row and does not double-push.

**Smoke test** (server must be running):

```bash
SHARED_TOKEN=<token> BASE=http://localhost:3000 npm run test:smoke
```

**Deploy (free, always-on):** see **[server/DEPLOY.md](server/DEPLOY.md)** for step-by-step
Fly.io instructions — it runs the server 24/7 with WebSocket support and keeps the SQLite
file on a persistent volume (no external DB, no cold starts). The repo includes a `Dockerfile`
and `fly.toml` ready to go. Note: Vercel/Netlify/Cloudflare Workers **won't** work here —
they're serverless and can't hold the long-lived WebSocket or keep the SQLite file on disk.
Once deployed, point both clients at the `https://…fly.dev` URL (the WebSocket upgrades to
`wss://` automatically).

---

## 2. Windows PC client (`pc-client/`)

**Requirements:** Python **3.11+** (Tkinter ships with the standard python.org installer).

```bash
cd pc-client
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config.example.json config.json     # then edit config.json
```

`config.json`:

```json
{
  "server_url": "http://localhost:3000",
  "token": "<the same SHARED_TOKEN>",
  "popup_for": ["missed"]
}
```

Run it:

```bash
.venv\Scripts\pythonw.exe main.py      # pythonw = no console window
```

You get a tray icon (green = connected). Right-click → **Show calls** for the full list.
Missed calls appear as always-on-top popups in the bottom-right that only close when you
click **Dismiss** (which also marks them seen on the server).

**Headless self-test** (server must be running, `config.json` present):

```bash
.venv\Scripts\python.exe scripts\headless_test.py
```

**Auto-start at login** — run with the **same interpreter** that has the packages installed
(the venv), which the installer enforces by deriving `pythonw.exe` from the current
interpreter rather than PATH:

```bash
.venv\Scripts\python.exe install_autostart.py install     # register Task Scheduler entry
.venv\Scripts\python.exe install_autostart.py status
.venv\Scripts\python.exe install_autostart.py uninstall
```

---

## 3. Android app (`android/`)

**Requirements:** Android Studio (or the Android SDK + JDK 17). `minSdk 26`, `compileSdk 35`.

1. Open the `android/` folder in Android Studio. It creates `local.properties` with your
   SDK path automatically. (To build from the CLI, add `android/local.properties` with
   `sdk.dir=C:/Path/To/Android/Sdk` — **use forward slashes**.)
2. Build/run: `./gradlew assembleDebug` (or Run ▶ from the IDE). The debug APK lands in
   `android/app/build/outputs/apk/debug/app-debug.apk`.
3. On the phone, open **RingKeeper** and:
   - **Grant call log permission** (READ_CALL_LOG / READ_PHONE_STATE / notifications).
   - **Configure server URL + token** — the same token; the URL must be reachable from the
     phone (a public HTTPS URL when off Wi-Fi). Tap **Test connection**.
   - **Disable battery optimization** — important on Xiaomi/Samsung/Oppo, which aggressively
     kill background services.
   - Tap **Start monitoring**.

**How it works:** a foreground service ("RingKeeper is watching for calls") registers a
`ContentObserver` on the system call log. Every new call of any type is written to a local
**Room** database immediately, then a **WorkManager** job — constrained to run only when a
network is available, with exponential backoff — pushes unsynced rows to the server. If the
phone is offline, calls pile up locally and flush automatically when connectivity returns
(a network callback also nudges the queue on reconnect). A boot receiver restarts monitoring
after a reboot.

---

## End-to-end sanity check

1. Start the **server** (`npm run dev`).
2. Start the **PC client** — tray icon turns green.
3. On the **phone** (configured + monitoring), have someone call you and don't answer.
4. The missed call POSTs to the server → pushes over WebSocket → an always-on-top popup
   appears on the PC. Answered/outgoing calls won't pop up but show in **Show calls**.

Quick manual test without a phone — POST directly and watch the popup:

```bash
curl -X POST http://localhost:3000/api/calls \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"caller_name":"Test","number":"+15551234567","call_type":"missed","timestamp":"2026-07-18T10:00:00Z"}'
```

---

## Data model

```sql
CREATE TABLE calls (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  caller_name  TEXT,
  number       TEXT NOT NULL,
  call_type    TEXT NOT NULL DEFAULT 'unknown',  -- missed | incoming | outgoing | rejected | blocked | voicemail | unknown
  call_time    TEXT NOT NULL,                    -- ISO 8601, when the call happened
  received_at  TEXT NOT NULL,                    -- ISO 8601, when the server stored it
  seen         INTEGER NOT NULL DEFAULT 0,
  client_uid   TEXT                              -- phone-side dedupe key (idempotent retries)
);
```

## Security notes

- One shared secret for everything. Keep it out of source control (`server/.env`,
  `pc-client/config.json`, and the phone's EncryptedSharedPreferences are all gitignored /
  on-device). Rotate it by updating the value in all three places.
- Put the server behind **HTTPS** in production so the token and call data aren't sent in
  the clear (Railway/Render/Fly give you TLS automatically).
```
