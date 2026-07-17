import type { NextFunction, Request, Response } from 'express';
import { timingSafeEqual } from 'node:crypto';
import { config } from './config.js';

/** Constant-time compare so token guessing can't use timing side-channels. */
export function tokenMatches(candidate: string | undefined | null): boolean {
  if (!candidate) return false;
  const a = Buffer.from(candidate);
  const b = Buffer.from(config.sharedToken);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/** Pull a bearer token out of an Authorization header. */
export function bearerFromHeader(header: string | undefined): string | null {
  if (!header) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match ? match[1] : null;
}

export function requireToken(req: Request, res: Response, next: NextFunction): void {
  const token = bearerFromHeader(req.header('authorization'));
  if (!tokenMatches(token)) {
    res.status(401).json({ error: 'unauthorized' });
    return;
  }
  next();
}
