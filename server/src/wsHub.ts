import type { Server as HttpServer } from 'node:http';
import { WebSocketServer, WebSocket } from 'ws';
import { tokenMatches } from './auth.js';
import type { WsMessage } from './types.js';

/**
 * The WS hub the PC client(s) connect to. Auth happens two ways:
 *  - `?token=...` query param on the upgrade URL, or
 *  - a first message `{ "type": "auth", "token": "..." }`
 * Unauthenticated sockets are closed. Authenticated ones get pushed every
 * new_call / call_seen event via broadcast().
 */

const authed = new Set<WebSocket>();
let wss: WebSocketServer | null = null;

const HEARTBEAT_MS = 30_000;

export function attachWebSocket(server: HttpServer): void {
  wss = new WebSocketServer({ server, path: '/ws' });

  wss.on('connection', (ws, req) => {
    let isAuthed = false;

    const authorize = () => {
      isAuthed = true;
      authed.add(ws);
      send(ws, { type: 'hello', data: { ok: true } });
    };

    // Path 1: token as a query param on the upgrade URL.
    try {
      const url = new URL(req.url ?? '', 'http://localhost');
      if (tokenMatches(url.searchParams.get('token'))) authorize();
    } catch {
      /* ignore malformed URL */
    }

    // Path 2: token in the first message. Give the client a short window.
    const authTimer = setTimeout(() => {
      if (!isAuthed) {
        send(ws, { type: 'error', data: { error: 'auth timeout' } });
        ws.close(4001, 'auth timeout');
      }
    }, 5_000);

    ws.on('message', (raw) => {
      if (isAuthed) return; // authed clients don't need to send anything
      try {
        const msg = JSON.parse(raw.toString());
        if (msg?.type === 'auth' && tokenMatches(msg.token)) {
          authorize();
        } else {
          send(ws, { type: 'error', data: { error: 'bad auth' } });
          ws.close(4001, 'bad auth');
        }
      } catch {
        ws.close(4001, 'bad auth');
      }
    });

    ws.on('pong', () => {
      (ws as WebSocket & { isAlive?: boolean }).isAlive = true;
    });

    ws.on('close', () => {
      clearTimeout(authTimer);
      authed.delete(ws);
    });

    ws.on('error', () => {
      clearTimeout(authTimer);
      authed.delete(ws);
    });
  });

  // Heartbeat: drop sockets that stopped responding to pings.
  const interval = setInterval(() => {
    wss?.clients.forEach((ws) => {
      const client = ws as WebSocket & { isAlive?: boolean };
      if (client.isAlive === false) {
        authed.delete(ws);
        return ws.terminate();
      }
      client.isAlive = false;
      ws.ping();
    });
  }, HEARTBEAT_MS);

  wss.on('close', () => clearInterval(interval));
}

function send(ws: WebSocket, msg: WsMessage): void {
  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

/** Push a message to every authenticated PC client. */
export function broadcast(msg: WsMessage): void {
  const payload = JSON.stringify(msg);
  for (const ws of authed) {
    if (ws.readyState === WebSocket.OPEN) ws.send(payload);
  }
}

export function connectedClients(): number {
  return authed.size;
}
