-- RingKeeper — migration: allow WhatsApp call types.
-- Run this in an EXISTING project (Dashboard → SQL Editor) that was created
-- before WhatsApp capture was added. Fresh projects already get these types from
-- schema.sql and don't need this file.
--
-- WhatsApp calls never appear in the phone's system call log, so RingKeeper
-- captures them from WhatsApp's notifications and stores them under two new
-- call_type values. The calls table's CHECK constraint has to permit them or the
-- phone's inserts are rejected (400) and dropped.

alter table public.calls drop constraint if exists calls_call_type_check;

alter table public.calls add constraint calls_call_type_check
  check (call_type in (
    'missed','incoming','outgoing','rejected','blocked','voicemail','unknown',
    'whatsapp_missed','whatsapp_incoming'
  ));
