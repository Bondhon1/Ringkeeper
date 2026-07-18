-- RingKeeper — migration: shared on/off control, phone heartbeat, and ephemeral
-- WhatsApp message relay. Run this in an EXISTING project (Dashboard → SQL
-- Editor). Fresh projects get all of this from schema.sql and don't need it.

-- 1. app_state — one row per account, shared by phone + PC ---------------------
-- `monitoring_enabled` is the shared instruction: either device (or the PC
-- closing) flips it, and the other device obeys. `phone_last_seen` is the phone's
-- heartbeat so the PC can tell "intentionally off" apart from "phone went away".
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

-- 2. messages — ephemeral WhatsApp message relay ------------------------------
-- The phone inserts one row per new message; the PC shows it and DELETEs it.
-- Nothing is meant to persist here — it's a transient push channel.
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

-- 3. Realtime — stream both tables to the PC ----------------------------------
-- (add ... table is not idempotent; ignore the error if already a member.)
do $$
begin
  alter publication supabase_realtime add table public.app_state;
exception when duplicate_object then null;
end $$;

do $$
begin
  alter publication supabase_realtime add table public.messages;
exception when duplicate_object then null;
end $$;
