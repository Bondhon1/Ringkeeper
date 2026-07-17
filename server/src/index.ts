import express from 'express';
import { createServer } from 'node:http';
import { config } from './config.js';
import { router } from './routes.js';
import { attachWebSocket } from './wsHub.js';

const app = express();
app.use(express.json({ limit: '256kb' }));

// Minimal request log — enough to debug the phone/PC without noise.
app.use((req, _res, next) => {
  if (req.path !== '/health') {
    console.log(`${new Date().toISOString()} ${req.method} ${req.path}`);
  }
  next();
});

app.use(router);

// Fallback error handler so a thrown route never crashes the process.
app.use(
  (err: unknown, _req: express.Request, res: express.Response, _next: express.NextFunction) => {
    console.error('[error]', err);
    if (!res.headersSent) res.status(500).json({ error: 'internal error' });
  },
);

const server = createServer(app);
attachWebSocket(server);

server.listen(config.port, () => {
  console.log(`RingKeeper server listening on http://0.0.0.0:${config.port}`);
  console.log(`  HTTP  POST   /api/calls`);
  console.log(`  HTTP  GET    /api/calls`);
  console.log(`  HTTP  PATCH  /api/calls/:id/seen`);
  console.log(`  WS           /ws`);
});

const shutdown = () => {
  console.log('\nShutting down...');
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 2000).unref();
};
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
