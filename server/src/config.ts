import 'dotenv/config';

function required(name: string): string {
  const value = process.env[name];
  if (!value || value.trim() === '') {
    throw new Error(
      `Missing required env var ${name}. Copy .env.example to .env and fill it in.`,
    );
  }
  return value.trim();
}

export const config = {
  port: Number(process.env.PORT ?? 3000),
  sharedToken: required('SHARED_TOKEN'),
  dbPath: process.env.DB_PATH?.trim() || './data/ringkeeper.db',
};

if (config.sharedToken === 'change-me-to-a-long-random-string') {
  // Don't hard-fail — but make the mistake loud.
  console.warn(
    '[config] SHARED_TOKEN is still the example value. Generate a real one before exposing the server.',
  );
}
