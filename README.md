# RingKeeper — Missed Call Alert Bridge

Relays calls from an Android phone to a persistent, un-missable popup on a Windows PC,
plus a running list of every call. Single user, two devices — with **Supabase** as the
entire backend (no server to host, no credit card).

```
Android phone ──REST insert──▶  Supabase  ──Realtime (WebSocket)──▶  Windows PC client
   │                         (Postgres + Realtime + Auth)                    │
CallLog observer                     │                              Always-on-top popup
(captures ALL call types,        calls table                        for MISSED calls
 stored locally first)           (RLS per account)                  + tray icon + call list
```

**What it captures vs. what pops up.** The phone records **every** call — missed, incoming
(answered), outgoing, rejected, blocked, voicemail — into a **local database first** (so
nothing is lost while offline), then syncs each to Supabase. All types are stored and appear
in the PC's list window, grouped by type. Only **missed** calls trigger the always-on-top
popup, which stays on screen until you dismiss it. (Change which types pop up via `popup_for`
in the PC client config — no rebuild needed.)

**WhatsApp calls too.** WhatsApp calls never appear in the Android system call log, so they're
captured separately by reading WhatsApp's **call notifications** (via a
`NotificationListenerService`) — you grant a one-time "Notification access" like you do battery
optimization. They're stored as their own types, `whatsapp_missed` and `whatsapp_incoming`, and
`whatsapp_missed` pops up by default alongside regular missed calls. This needs the Android app
plus the extra grant; nothing else is required. (Detection reads the notification text, which
WhatsApp localizes — English is handled out of the box; see
[`WhatsAppCallListener`](android/app/src/main/java/com/ringkeeper/app/service/WhatsAppCallListener.kt)
to add other languages.)

**Shared on/off switch.** A single instruction, stored in Supabase (`app_state`), pauses/resumes
**both** devices at once. Turn it off from the phone (**Turn off** button) or the PC (tray →
**Turn off**); either stops the phone capturing/syncing and the PC popping up. **Closing the PC
client also flips it off** (set `set_off_on_exit: false` in the PC config to opt out). The phone
keeps a lightweight loop running while off, so it obeys a **Turn on** from either side within
~30s.

**Phone-inactive alerts.** The phone sends a heartbeat every ~30s. If the PC stops hearing it
(phone powered off, offline, or the app was killed) it raises a "phone inactive" popup and turns
the tray icon amber — so you know the bridge is down rather than assuming "no calls." Turning
monitoring *off* does **not** trigger this (that's intentional and the heartbeat keeps flowing);
only an actually-absent phone does.

**WhatsApp messages (ephemeral).** New WhatsApp messages are relayed to the PC as a one-time
popup (sender + preview) and **never stored** — the phone inserts a row into `messages`, the PC
shows it and immediately deletes it. Requires the same Notification access as WhatsApp calls.

**Why Supabase (and not Vercel/Render/Fly).** The un-missable alert needs a live push to the
PC and persistent storage. Supabase gives all three pieces free with no card: Postgres
(storage), **Realtime** (a managed WebSocket that pushes each new row to the PC instantly),
and **Auth** (one account shared by your two devices, with Row-Level Security so only you can
see your calls). There's no long-running server to deploy — the phone and PC talk to Supabase
directly. Serverless hosts like Vercel can't hold the WebSocket or keep a database, and a
custom always-on server would need a paid host.

---

## Repository layout

| Folder        | What it is                                            | Language           |
|---------------|-------------------------------------------------------|--------------------|
| `supabase/`   | `schema.sql` (table + RLS + realtime) and setup guide | SQL                |
| `pc-client/`  | Popup + call list + tray icon                         | Python 3.11+       |
| `android/`    | Call capture, local DB, network-aware sync            | Kotlin (Android)   |

---

## 1. Set up Supabase (do this first)

Follow **[supabase/SETUP.md](supabase/SETUP.md)**. In short:

1. Create a free Supabase project (GitHub login, no card).
2. Copy your **Project URL** and **anon public key** (Project Settings → API).
3. Run **[supabase/schema.sql](supabase/schema.sql)** in the SQL Editor (creates the `calls`
   table, Row-Level Security, and enables Realtime).
4. Create one account (Authentication → Users → Add user, **Auto Confirm** on).

You'll end up with four values used by **both** clients: `supabase_url`, `anon_key`,
`email`, `password`.

---

## 2. Windows PC client (`pc-client/`)

**Requirements:** Python **3.11+** (Tkinter ships with the python.org installer;
tick **"Add Python to PATH"** during install).

### Easy way (recommended — no terminal, no admin)

Double-click **`pc-client\setup.bat`**. It creates the virtual environment, installs
dependencies, creates `config.json` from the example, and registers RingKeeper to start
at every login — all **without administrator rights**. It then offers to start the app
immediately. The only thing you must do by hand is open **`config.json`** and fill in your
four Supabase values (below).

Two companion double-click helpers sit next to it:

| File            | What it does                                                        |
|-----------------|--------------------------------------------------------------------|
| `setup.bat`     | One-click first-time setup (venv + deps + config + autostart).     |
| `start.bat`     | Start RingKeeper now (tray icon), without logging out.             |
| `uninstall.bat` | Remove the autostart entry. Deletes no files.                      |

### Manual way

```bash
cd pc-client
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config.example.json config.json     # then edit config.json
```

`config.json`:

```json
{
  "supabase_url": "https://your-ref.supabase.co",
  "anon_key": "eyJhbGci…",
  "email": "your-ringkeeper-account@example.com",
  "password": "your-account-password",
  "popup_for": ["missed", "whatsapp_missed"],
  "phone_inactive_after_seconds": 180,
  "set_off_on_exit": true
}
```

Run it:

```bash
.venv\Scripts\pythonw.exe main.py      # pythonw = no console window
```

The client signs in to Supabase, subscribes to Realtime, and shows a tray icon (green =
connected). Right-click → **Show calls** for the full list. Missed calls appear as
always-on-top popups in the bottom-right that only close when you click **Dismiss** (which
also marks them seen in Supabase).

**Offline wiring self-test** (no network needed, `config.json` present):
```bash
.venv\Scripts\python.exe scripts\headless_test.py
```

**Auto-start at login** — `setup.bat` already does this for you. To do it by hand, run with
the **same interpreter** that has the packages installed (the venv); the installer derives
`pythonw.exe` from the current interpreter to avoid the classic pyw/python environment
mismatch. It writes a **per-user** `HKCU\...\Run` entry, so **no administrator rights are
needed**:
```bash
.venv\Scripts\python.exe install_autostart.py install     # register per-user autostart
.venv\Scripts\python.exe install_autostart.py status
.venv\Scripts\python.exe install_autostart.py uninstall
```

---

## 3. Android app (`android/`)

**Requirements:** Android Studio (or Android SDK + JDK 17). `minSdk 26`, `compileSdk 35`.

1. Open the `android/` folder in Android Studio (it writes `local.properties` with your SDK
   path automatically; for CLI builds add `android/local.properties` with
   `sdk.dir=C:/Path/To/Android/Sdk` — **use forward slashes**).
2. Build/run: `./gradlew assembleDebug` (or Run ▶). APK →
   `android/app/build/outputs/apk/debug/app-debug.apk`.
3. On the phone, open **RingKeeper** and:
   - **Grant call log permission** (READ_CALL_LOG / READ_PHONE_STATE / notifications).
   - **Configure Supabase connection** — paste the same `supabase_url`, `anon_key`, `email`,
     `password`. Tap **Test connection** (it signs in and checks access).
   - **Disable battery optimization** — important on Xiaomi/Samsung/Oppo, which aggressively
     kill background services.
   - **(Optional) Enable WhatsApp call capture** — tap it and toggle **RingKeeper** on in the
     system "Notification access" screen. This lets RingKeeper read WhatsApp's call
     notifications (the only way to see WhatsApp calls, which never reach the call log).
   - Tap **Start monitoring**.

**How it works:** a foreground service ("RingKeeper is watching for calls") registers a
`ContentObserver` on the system call log. Every new call of any type is written to a local
**Room** database immediately, then a **WorkManager** job — constrained to run only when a
network is available, with exponential backoff — signs in to Supabase (JWT cached, refreshed
automatically) and inserts unsynced rows via PostgREST, upserting on `client_uid` so retries
never duplicate. If the phone is offline, calls pile up locally and flush automatically when
connectivity returns (a network callback also nudges the queue). A boot receiver restarts
monitoring after a reboot.

WhatsApp calls take a parallel path: a `NotificationListenerService` (active once you grant
Notification access) reads WhatsApp's call notifications, writes them to the same local Room DB
(with `callLogId` null and `source = "whatsapp"`), and feeds the same sync queue. WhatsApp
re-posts a notification several times per call, so a per-call `client_uid` (caller + second +
type) plus a unique index collapse the repeats to one row.

> **Existing Supabase project?** If you created your database before these features, run these
> once in the SQL Editor (fresh projects get everything from `schema.sql` automatically):
> - [supabase/add_whatsapp_call_types.sql](supabase/add_whatsapp_call_types.sql) — the two new
>   `call_type` values (otherwise WhatsApp call inserts are rejected).
> - [supabase/add_control_and_messages.sql](supabase/add_control_and_messages.sql) — the
>   `app_state` (shared on/off + heartbeat) and `messages` (ephemeral) tables.

---

## End-to-end sanity check

1. Start the **PC client** — tray icon turns green once it's subscribed.
2. On the **phone** (configured + monitoring), have someone call you and don't answer.
3. The missed call is stored locally, synced to Supabase, and Supabase Realtime pushes it to
   the PC → an always-on-top popup appears. Answered/outgoing calls won't pop up but show in
   **Show calls**.

Quick manual test without a phone — insert a row straight into Supabase and watch the popup
(replace URL / anon key / a valid access token, or just use the SQL Editor):

```sql
insert into public.calls (user_id, number, caller_name, call_type, call_time)
values (auth.uid(), '+15551234567', 'Test', 'missed', now());
```
(Run it while signed in via the dashboard SQL editor as your user, or use the REST API with
your account's JWT.)

---

## Data model

See **[supabase/schema.sql](supabase/schema.sql)** for the full definition. The `calls` table:

| column        | type          | notes                                             |
|---------------|---------------|---------------------------------------------------|
| `id`          | bigint (PK)   | identity                                          |
| `user_id`     | uuid          | `default auth.uid()`, FK → auth.users, RLS key    |
| `caller_name` | text          | nullable                                          |
| `number`      | text          | not null                                          |
| `call_type`   | text          | missed / incoming / outgoing / rejected / blocked / voicemail / unknown / whatsapp_missed / whatsapp_incoming |
| `call_time`   | timestamptz   | when the call happened                            |
| `received_at` | timestamptz   | `default now()`                                   |
| `seen`        | boolean       | `default false`                                   |
| `client_uid`  | text (unique) | phone-side dedupe key (idempotent inserts)        |

Two more tables back the control/messaging features (see `schema.sql`):

- **`app_state`** — one row per account: `monitoring_enabled` (the shared on/off instruction,
  flipped by either device), `control_source`, `control_updated_at`, and `phone_last_seen` (the
  phone's heartbeat). Realtime-streamed so the PC reacts to both flag flips and heartbeats.
- **`messages`** — ephemeral WhatsApp message relay: the phone inserts `sender` + `preview`, the
  PC shows a popup and immediately deletes the row. Nothing persists.

## Security notes

- **Row-Level Security** scopes every row to your account (`user_id = auth.uid()`), and
  Realtime respects it — only your own calls are ever pushed to the PC.
- The **anon key** is meant to live in client apps; it's not the sensitive part. Your account
  password is — it's stored in the phone's EncryptedSharedPreferences and the PC's local
  `config.json` (gitignored). Optionally disable new sign-ups in Supabase after creating your
  account so no one else can register.
- Rotate access by changing the account password in the Supabase dashboard, then updating it
  in the PC config and the phone settings.
