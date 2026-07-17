# Deploying the RingKeeper server to Fly.io (free)

Fly runs the server as an always-on process with a WebSocket-capable HTTP proxy and a
persistent volume for the SQLite file. This is the recommended free host — no cold starts,
no external database.

> You need a credit card on file with Fly. A single `shared-cpu-1x` 256MB machine with a
> 1GB volume sits within Fly's free allowance, but Fly requires a card to sign up.

## 1. Install flyctl

**Windows (PowerShell):**
```powershell
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```
Then restart your terminal so `fly` is on PATH.

```bash
fly version
fly auth signup   # or: fly auth login
```

## 2. Generate your shared token

Keep this — you'll paste the same value into the PC client and the phone later.
```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

## 3. Pick a unique app name + region

Edit `fly.toml`:
- set `app` to something globally unique, e.g. `ringkeeper-<yourname>`
- set `primary_region` to one near you (`fly platform regions` lists them; e.g. `iad`, `lhr`, `sin`)

Create the app (from the `server/` folder):
```bash
cd server
fly apps create ringkeeper-<yourname>
```

## 4. Create the persistent volume

The region **must match** `primary_region` in `fly.toml`:
```bash
fly volumes create ringkeeper_data --size 1 --region <your-region>
```

## 5. Set the token as a secret (not in fly.toml)

```bash
fly secrets set SHARED_TOKEN=<the token from step 2>
```

## 6. Deploy

```bash
fly deploy
```

When it finishes, your server is at:
```
https://ringkeeper-<yourname>.fly.dev
```

## 7. Verify

```bash
# Health check (no auth):
curl https://ringkeeper-<yourname>.fly.dev/health
# -> {"ok":true,"clients":0}

# Authenticated round-trip:
curl -X POST https://ringkeeper-<yourname>.fly.dev/api/calls \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"number":"+15551234567","call_type":"missed","timestamp":"2026-07-18T10:00:00Z"}'
```

Or run the smoke test against the live server:
```bash
SHARED_TOKEN=<token> BASE=https://ringkeeper-<yourname>.fly.dev npm run test:smoke
```

## 8. Point the clients at it

- **PC client** `config.json`: `"server_url": "https://ringkeeper-<yourname>.fly.dev"`
  (the client auto-derives the `wss://…/ws` WebSocket URL from that).
- **Android app** settings: same `https://…` URL + the same token. Tap **Test connection**.

Both use `https://` — the WebSocket upgrades to secure `wss://` automatically, and Fly
terminates TLS for you.

## Useful commands

```bash
fly logs                      # live server logs
fly status                    # machine + health status
fly secrets set SHARED_TOKEN=<new>   # rotate the token (also update both clients)
fly deploy                    # redeploy after code changes (DB on the volume is kept)
fly ssh console               # shell into the machine (DB is at /data/ringkeeper.db)
```

## Notes / gotchas

- **Don't scale past 1 machine.** SQLite is single-writer and the volume attaches to one
  machine. `min_machines_running = 1` + `auto_stop_machines = false` keep exactly one
  instance always on.
- **Backups:** the call history lives only on the Fly volume. `fly volumes snapshots`
  exists if you want periodic snapshots, or pull the file with `fly ssh sftp get`.
- **Cost guard:** `fly dashboard` shows usage. One small machine + 1GB volume is the free
  footprint; avoid adding more machines/volumes.
