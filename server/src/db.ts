import { DatabaseSync } from 'node:sqlite';
import { existsSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { config } from './config.js';
import type { CallRow, CallType, IncomingCall } from './types.js';

// Uses Node's built-in SQLite (node:sqlite) — no native build step, so it runs
// anywhere Node 22.5+/24 does. The API mirrors better-sqlite3 closely; swapping
// back to better-sqlite3 (for an older Node) only touches this file.

// Ensure the directory for the DB file exists before opening it.
const dir = dirname(config.dbPath);
if (dir && dir !== '.' && !existsSync(dir)) {
  mkdirSync(dir, { recursive: true });
}

const db = new DatabaseSync(config.dbPath);
db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA foreign_keys = ON');

// --- Schema / migration ---------------------------------------------------
db.exec(`
  CREATE TABLE IF NOT EXISTS calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_name  TEXT,
    number       TEXT NOT NULL,
    call_type    TEXT NOT NULL DEFAULT 'unknown',
    call_time    TEXT NOT NULL,       -- ISO 8601, when the call happened
    received_at  TEXT NOT NULL,       -- ISO 8601, when the server stored it
    seen         INTEGER NOT NULL DEFAULT 0,
    client_uid   TEXT                 -- phone-side dedupe key (nullable)
  );

  CREATE INDEX IF NOT EXISTS idx_calls_call_time ON calls (call_time);
  CREATE INDEX IF NOT EXISTS idx_calls_type ON calls (call_type);
  CREATE UNIQUE INDEX IF NOT EXISTS idx_calls_client_uid
    ON calls (client_uid) WHERE client_uid IS NOT NULL;
`);

// --- Prepared statements ---------------------------------------------------
const insertStmt = db.prepare(`
  INSERT INTO calls (caller_name, number, call_type, call_time, received_at, seen, client_uid)
  VALUES (@caller_name, @number, @call_type, @call_time, @received_at, 0, @client_uid)
`);

const findByUidStmt = db.prepare(`SELECT * FROM calls WHERE client_uid = ?`);
const getByIdStmt = db.prepare(`SELECT * FROM calls WHERE id = ?`);
const markSeenStmt = db.prepare(`UPDATE calls SET seen = 1 WHERE id = ?`);

export interface ListOptions {
  since?: string; // ISO 8601, filter call_time >= since
  type?: CallType; // filter by call_type
  limit?: number;
}

export function insertCall(call: IncomingCall): { row: CallRow; created: boolean } {
  // Idempotency: if the phone already delivered this client_uid, return existing.
  if (call.client_uid) {
    const existing = findByUidStmt.get(call.client_uid) as unknown as CallRow | undefined;
    if (existing) return { row: existing, created: false };
  }

  const receivedAt = new Date().toISOString();
  const info = insertStmt.run({
    caller_name: call.caller_name ?? null,
    number: call.number,
    call_type: call.call_type,
    call_time: call.timestamp,
    received_at: receivedAt,
    client_uid: call.client_uid ?? null,
  });

  const row = getByIdStmt.get(Number(info.lastInsertRowid)) as unknown as CallRow;
  return { row, created: true };
}

export function listCalls(opts: ListOptions = {}): CallRow[] {
  const clauses: string[] = [];
  const params: Record<string, string> = {};

  if (opts.since) {
    clauses.push('call_time >= @since');
    params.since = opts.since;
  }
  if (opts.type) {
    clauses.push('call_type = @type');
    params.type = opts.type;
  }

  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : '';
  const limit = Math.min(Math.max(opts.limit ?? 500, 1), 2000);

  const stmt = db.prepare(
    `SELECT * FROM calls ${where} ORDER BY call_time DESC LIMIT ${limit}`,
  );
  return stmt.all(params) as unknown as CallRow[];
}

export function markSeen(id: number): CallRow | undefined {
  markSeenStmt.run(id);
  return getByIdStmt.get(id) as unknown as CallRow | undefined;
}

export function getCall(id: number): CallRow | undefined {
  return getByIdStmt.get(id) as unknown as CallRow | undefined;
}

export default db;
