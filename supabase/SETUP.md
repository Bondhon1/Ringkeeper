# Supabase setup (free, no credit card)

RingKeeper uses Supabase as its entire backend — Postgres for storage, Realtime for the
instant push to your PC, and Auth for a single login shared by your two devices. No server
to host, no card required.

## 1. Create a project

1. Sign up at <https://supabase.com> (GitHub login works, no card).
2. **New project** → name it (e.g. `ringkeeper`), pick a region near you, set a database
   password (save it somewhere; you won't need it day-to-day).
3. Wait ~2 min for it to provision.

## 2. Grab your keys

Dashboard → **Project Settings → API**:
- **Project URL** — looks like `https://abcdefgh.supabase.co`
- **anon public** key — a long JWT starting `eyJ…`

Both go into the PC client config and the phone. The anon key is safe to embed in client
apps; Row-Level Security (below) is what actually protects your data.

## 3. Create the tables + security

Dashboard → **SQL Editor** → **New query** → paste the contents of
[`schema.sql`](schema.sql) → **Run**. This creates the `calls` table, enables Row-Level
Security (each account sees only its own calls), and turns on Realtime for the table.

## 4. Create your one account

Dashboard → **Authentication → Users → Add user → Create new user**:
- enter an email + password (any email; it doesn't have to be real if you tick
  **Auto Confirm User**)
- **enable Auto Confirm User** so you can log in immediately without an email link.

This single account is what both the phone and the PC sign in as.

> Optional hardening: under **Authentication → Providers → Email**, turn **off** "Enable
> sign-ups" after creating your user, so no one else can register against your project.

## 5. Point the clients at it

You now have four values — use the **same** ones in both places:

| Value          | Where it comes from                    |
|----------------|----------------------------------------|
| `supabase_url` | Project URL (step 2)                   |
| `anon_key`     | anon public key (step 2)               |
| `email`        | the account you created (step 4)       |
| `password`     | that account's password                |

- **PC client** → `pc-client/config.json` (see `config.example.json`).
- **Android app** → the in-app settings screen.

## Good to know

- **Free projects pause after ~7 days of no activity.** The PC client holds a Realtime
  connection open continuously, which counts as activity, so in daily use it won't pause. If
  it ever does, open the dashboard and hit **Restore**.
- **Free tier limits:** 500 MB database, plenty for call history (each call is a few hundred
  bytes). 
- **Realtime not firing?** Check Dashboard → **Database → Publications → `supabase_realtime`**
  and confirm `calls` is listed. Re-run `schema.sql` if not.
- **Rotate access:** change the account password in the dashboard, then update it in the PC
  config and the phone settings.
