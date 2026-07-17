import { Router, type Request, type Response } from 'express';
import { requireToken } from './auth.js';
import { getCall, insertCall, listCalls, markSeen } from './db.js';
import { isCallType, type IncomingCall } from './types.js';
import { broadcast, connectedClients } from './wsHub.js';

export const router = Router();

// Health check — unauthenticated, handy for uptime pings / deploy checks.
router.get('/health', (_req: Request, res: Response) => {
  res.json({ ok: true, clients: connectedClients() });
});

// Everything below requires the shared token.
router.use('/api', requireToken);

// POST /api/calls — the phone submits a call of any type.
router.post('/api/calls', (req: Request, res: Response) => {
  const body = req.body as Partial<IncomingCall>;

  if (!body || typeof body.number !== 'string' || body.number.trim() === '') {
    res.status(400).json({ error: 'number is required' });
    return;
  }
  const callType = body.call_type ?? 'unknown';
  if (!isCallType(callType)) {
    res.status(400).json({ error: `invalid call_type: ${String(body.call_type)}` });
    return;
  }
  const timestamp = body.timestamp ?? new Date().toISOString();
  if (Number.isNaN(Date.parse(timestamp))) {
    res.status(400).json({ error: 'timestamp must be ISO 8601' });
    return;
  }

  const { row, created } = insertCall({
    caller_name: body.caller_name ?? null,
    number: body.number.trim(),
    call_type: callType,
    timestamp,
    client_uid: body.client_uid ?? null,
  });

  // Only push to PC clients for genuinely new rows (retries stay quiet).
  if (created) {
    broadcast({ type: 'new_call', data: row });
  }

  res.status(created ? 201 : 200).json({ call: row, created });
});

// GET /api/calls?since=<iso>&type=<type>&limit=<n>
router.get('/api/calls', (req: Request, res: Response) => {
  const since = typeof req.query.since === 'string' ? req.query.since : undefined;
  if (since && Number.isNaN(Date.parse(since))) {
    res.status(400).json({ error: 'since must be ISO 8601' });
    return;
  }
  const typeParam = typeof req.query.type === 'string' ? req.query.type : undefined;
  if (typeParam !== undefined && !isCallType(typeParam)) {
    res.status(400).json({ error: `invalid type: ${typeParam}` });
    return;
  }
  const limit = typeof req.query.limit === 'string' ? Number(req.query.limit) : undefined;

  const calls = listCalls({
    since,
    type: typeParam,
    limit: Number.isFinite(limit) ? limit : undefined,
  });
  res.json({ calls });
});

// PATCH /api/calls/:id/seen — acknowledge a call.
router.patch('/api/calls/:id/seen', (req: Request, res: Response) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id) || id <= 0) {
    res.status(400).json({ error: 'invalid id' });
    return;
  }
  if (!getCall(id)) {
    res.status(404).json({ error: 'not found' });
    return;
  }
  const row = markSeen(id);
  // Let other connected clients (e.g. the popup) know it was acknowledged.
  broadcast({ type: 'call_seen', data: row });
  res.json({ call: row });
});
