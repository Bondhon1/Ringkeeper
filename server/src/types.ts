// The canonical set of call types RingKeeper understands.
// The Android side maps Android's CallLog.Calls.TYPE constants onto these.
export const CALL_TYPES = [
  'missed',
  'incoming', // answered incoming
  'outgoing',
  'rejected',
  'blocked',
  'voicemail',
  'unknown',
] as const;

export type CallType = (typeof CALL_TYPES)[number];

export function isCallType(value: unknown): value is CallType {
  return typeof value === 'string' && (CALL_TYPES as readonly string[]).includes(value);
}

export interface CallRow {
  id: number;
  caller_name: string | null;
  number: string;
  call_type: CallType;
  call_time: string; // ISO 8601, when the call happened (from the phone)
  received_at: string; // ISO 8601, when the server stored it
  seen: number; // 0 | 1
  client_uid: string | null; // dedupe key from the phone (optional)
}

// What the phone POSTs. `client_uid` lets the phone retry safely without dupes.
export interface IncomingCall {
  caller_name?: string | null;
  number: string;
  call_type: CallType;
  timestamp: string; // ISO 8601 (call_time)
  client_uid?: string | null;
}

export interface WsMessage {
  type: 'new_call' | 'call_seen' | 'hello' | 'error';
  data?: unknown;
}
