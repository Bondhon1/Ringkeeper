// End-to-end smoke test: boots nothing itself — assumes the server is running.
// Usage: SHARED_TOKEN=... BASE=http://localhost:3000 node scripts/smoke-test.mjs
import WebSocket from 'ws';

const BASE = process.env.BASE ?? 'http://localhost:3000';
const WS_BASE = BASE.replace(/^http/, 'ws');
const TOKEN = process.env.SHARED_TOKEN;

if (!TOKEN) {
  console.error('Set SHARED_TOKEN in the env to match the server.');
  process.exit(1);
}

const auth = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' };
let failures = 0;

function check(name, cond) {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}`);
  if (!cond) failures++;
}

// 1. Unauthorized without token.
{
  const r = await fetch(`${BASE}/api/calls`);
  check('GET /api/calls without token -> 401', r.status === 401);
}

// 2. Open an authed WS and wait for the pushed new_call.
const ws = new WebSocket(`${WS_BASE}/ws?token=${encodeURIComponent(TOKEN)}`);
const gotPush = new Promise((resolve) => {
  let helloSeen = false;
  ws.on('message', (raw) => {
    const msg = JSON.parse(raw.toString());
    if (msg.type === 'hello') helloSeen = true;
    if (msg.type === 'new_call') resolve({ helloSeen, call: msg.data });
  });
});
await new Promise((res, rej) => {
  ws.on('open', res);
  ws.on('error', rej);
});
check('WS connects and authenticates', true);

// 3. POST a missed call.
const uid = `smoke-${Date.now()}`;
const postRes = await fetch(`${BASE}/api/calls`, {
  method: 'POST',
  headers: auth,
  body: JSON.stringify({
    caller_name: 'Smoke Test',
    number: '+15551234567',
    call_type: 'missed',
    timestamp: new Date().toISOString(),
    client_uid: uid,
  }),
});
const posted = await postRes.json();
check('POST /api/calls -> 201 created', postRes.status === 201 && posted.created === true);

// 4. The WS should have received the push.
const pushed = await Promise.race([
  gotPush,
  new Promise((res) => setTimeout(() => res(null), 3000)),
]);
check('WS received new_call push', pushed && pushed.call?.client_uid === uid);

// 5. Idempotent re-POST returns the same row, created=false, no new push.
const rePost = await (
  await fetch(`${BASE}/api/calls`, {
    method: 'POST',
    headers: auth,
    body: JSON.stringify({
      number: '+15551234567',
      call_type: 'missed',
      timestamp: new Date().toISOString(),
      client_uid: uid,
    }),
  })
).json();
check('Duplicate client_uid is idempotent', rePost.created === false && rePost.call.id === posted.call.id);

// 6. GET filters by type.
const list = await (await fetch(`${BASE}/api/calls?type=missed&limit=10`, { headers: auth })).json();
check('GET /api/calls?type=missed returns rows', Array.isArray(list.calls) && list.calls.length > 0);

// 7. Bad call_type rejected.
const badType = await fetch(`${BASE}/api/calls`, {
  method: 'POST',
  headers: auth,
  body: JSON.stringify({ number: '123', call_type: 'banana', timestamp: new Date().toISOString() }),
});
check('Invalid call_type -> 400', badType.status === 400);

// 8. PATCH seen.
const seen = await fetch(`${BASE}/api/calls/${posted.call.id}/seen`, { method: 'PATCH', headers: auth });
const seenBody = await seen.json();
check('PATCH /:id/seen -> seen=1', seen.status === 200 && seenBody.call.seen === 1);

ws.terminate();
console.log(failures === 0 ? '\nAll smoke tests passed.' : `\n${failures} check(s) failed.`);
// Set exit code and let the event loop drain on its own — calling process.exit()
// while the WS handle is still closing trips a libuv assertion on Windows.
process.exitCode = failures === 0 ? 0 : 1;
