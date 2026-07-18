-- RingKeeper — Supabase schema.
-- Run this in your Supabase project: Dashboard → SQL Editor → paste → Run.
-- It creates the calls table, locks it down with Row-Level Security so each
-- account only sees its own calls, and enables Realtime so the PC client gets
-- an instant push on every insert.

-- 1. Table -------------------------------------------------------------------
create table if not exists public.calls (
  id           bigint generated always as identity primary key,
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  caller_name  text,
  number       text not null,
  call_type    text not null default 'unknown'
               check (call_type in ('missed','incoming','outgoing','rejected','blocked','voicemail','unknown','whatsapp_missed','whatsapp_incoming')),
  call_time    timestamptz not null,
  received_at  timestamptz not null default now(),
  seen         boolean not null default false,
  client_uid   text
);

-- Idempotent inserts from the phone: re-POSTing the same client_uid is ignored.
-- Must be a NON-partial unique index: PostgREST's `on_conflict=client_uid` upsert
-- can only infer a plain unique index/constraint, not a partial one (a partial
-- index triggers Postgres error 42P10). NULL client_uids are still allowed
-- multiple times because Postgres treats NULLs as distinct in a unique index.
create unique index if not exists calls_client_uid_key
  on public.calls (client_uid);

create index if not exists calls_user_time_idx on public.calls (user_id, call_time desc);
create index if not exists calls_type_idx on public.calls (call_type);

-- 2. Row-Level Security ------------------------------------------------------
alter table public.calls enable row level security;

-- Each policy scopes rows to the signed-in account (auth.uid()). Realtime
-- delivery to the PC also respects the SELECT policy, so only your own calls
-- are ever pushed.
drop policy if exists "own calls: select" on public.calls;
create policy "own calls: select" on public.calls
  for select using (user_id = auth.uid());

drop policy if exists "own calls: insert" on public.calls;
create policy "own calls: insert" on public.calls
  for insert with check (user_id = auth.uid());

drop policy if exists "own calls: update" on public.calls;
create policy "own calls: update" on public.calls
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());

-- 3. Realtime ----------------------------------------------------------------
-- Add the table to the realtime publication so INSERT/UPDATE events are streamed.
alter publication supabase_realtime add table public.calls;

-- 4. app_state — shared on/off control + phone heartbeat ----------------------
-- One row per account, shared by the phone and PC. `monitoring_enabled` is the
-- shared instruction: either device (or the PC closing) can flip it and the
-- other obeys. `phone_last_seen` is the phone's heartbeat, so the PC can tell
-- "intentionally off" apart from "the phone went away".
create table if not exists public.app_state (
  user_id             uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  monitoring_enabled  boolean not null default true,
  control_source      text,                    -- 'phone' | 'pc' | 'pc_closed'
  control_updated_at  timestamptz not null default now(),
  phone_last_seen     timestamptz
);

alter table public.app_state enable row level security;

drop policy if exists "own state: select" on public.app_state;
create policy "own state: select" on public.app_state
  for select using (user_id = auth.uid());

drop policy if exists "own state: insert" on public.app_state;
create policy "own state: insert" on public.app_state
  for insert with check (user_id = auth.uid());

drop policy if exists "own state: update" on public.app_state;
create policy "own state: update" on public.app_state
  for update using (user_id = auth.uid()) with check (user_id = auth.uid());

alter publication supabase_realtime add table public.app_state;

-- 5. messages — ephemeral WhatsApp message relay ------------------------------
-- The phone inserts one row per new WhatsApp message; the PC shows it and then
-- DELETEs it. Nothing is meant to persist — it's a transient push channel.
create table if not exists public.messages (
  id           bigint generated always as identity primary key,
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  sender       text not null,
  preview      text,
  received_at  timestamptz not null default now(),
  client_uid   text
);

create unique index if not exists messages_client_uid_key on public.messages (client_uid);
create index if not exists messages_user_time_idx on public.messages (user_id, received_at desc);

alter table public.messages enable row level security;

drop policy if exists "own messages: select" on public.messages;
create policy "own messages: select" on public.messages
  for select using (user_id = auth.uid());

drop policy if exists "own messages: insert" on public.messages;
create policy "own messages: insert" on public.messages
  for insert with check (user_id = auth.uid());

drop policy if exists "own messages: delete" on public.messages;
create policy "own messages: delete" on public.messages
  for delete using (user_id = auth.uid());

alter publication supabase_realtime add table public.messages;
