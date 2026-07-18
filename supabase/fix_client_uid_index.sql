-- RingKeeper fix — run once in Supabase → SQL Editor if you created the DB from
-- an earlier version of schema.sql.
--
-- Why: the original schema created a *partial* unique index on client_uid
-- (`where client_uid is not null`). PostgREST's upsert (`on_conflict=client_uid`,
-- used by the Android sync) cannot infer a partial index and fails with
-- Postgres error 42P10, so every synced call is rejected. Replacing it with a
-- plain unique index makes the upsert work. NULL client_uids are still allowed
-- multiple times (Postgres treats NULLs as distinct in a unique index).

drop index if exists public.calls_client_uid_key;

create unique index if not exists calls_client_uid_key
  on public.calls (client_uid);

-- Remove the connectivity test row inserted while verifying the fix (harmless if absent).
delete from public.calls where client_uid = 'plain-test-001';
