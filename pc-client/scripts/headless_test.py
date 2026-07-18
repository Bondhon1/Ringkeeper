"""Offline wiring test for the Supabase-native PC client.

Verifies config loading, URL derivation, and that the auth/REST/realtime layers
construct and import cleanly — no network, no Tk. A full live test needs a real
Supabase project (see supabase/SETUP.md); this catches wiring/typo regressions.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ringkeeper.api import SupabaseRest  # noqa: E402
from ringkeeper.auth import TokenManager  # noqa: E402
from ringkeeper.config import load_config  # noqa: E402
from ringkeeper.realtime import SupabaseRealtime  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures += 1


cfg = load_config()
check("config loads", bool(cfg.supabase_url and cfg.anon_key and cfg.email))
check("rest_url derived", cfg.rest_url == f"{cfg.base}/rest/v1")
check("auth_url derived", cfg.auth_url == f"{cfg.base}/auth/v1")
expected_realtime = (
    cfg.base.replace("https://", "wss://").replace("http://", "ws://") + "/realtime/v1"
)
check(
    "realtime_url is wss + /realtime/v1",
    cfg.realtime_url == expected_realtime,
)

tokens = TokenManager(cfg)
check("TokenManager constructs", tokens is not None)

api = SupabaseRest(cfg, tokens)
check("SupabaseRest constructs", api is not None)

rt = SupabaseRealtime(cfg, tokens, on_new_call=lambda r: None, on_status=lambda c: None)
check("SupabaseRealtime constructs", rt is not None)

# The INSERT payload shape from Supabase Realtime: payload["data"]["record"].
captured: list = []
states: list = []
messages: list = []
rt2 = SupabaseRealtime(
    cfg,
    tokens,
    on_new_call=captured.append,
    on_app_state=states.append,
    on_message=messages.append,
)
rt2._on_call_insert({"data": {"record": {"id": 1, "call_type": "missed", "number": "+1"}}})
check("_on_call_insert extracts record", len(captured) == 1 and captured[0]["id"] == 1)
rt2._on_call_insert({"data": {}})  # missing record → ignored, no crash
check("_on_call_insert tolerates missing record", len(captured) == 1)

rt2._on_app_state({"data": {"record": {"monitoring_enabled": False, "phone_last_seen": None}}})
check("_on_app_state extracts record", len(states) == 1 and states[0]["monitoring_enabled"] is False)

rt2._on_message({"data": {"record": {"id": 7, "sender": "Alice", "preview": "hi"}}})
check("_on_message extracts record", len(messages) == 1 and messages[0]["id"] == 7)

# api exposes the new control/message endpoints
check("api has get_app_state", hasattr(api, "get_app_state"))
check("api has set_monitoring", hasattr(api, "set_monitoring"))
check("api has delete_message", hasattr(api, "delete_message"))

# config carries the new knobs
check("config has phone_inactive_after_seconds", isinstance(cfg.phone_inactive_after_seconds, int))
check("config has set_off_on_exit", isinstance(cfg.set_off_on_exit, bool))

print("\n" + ("All offline wiring tests passed." if failures == 0 else f"{failures} failure(s)."))
sys.exit(1 if failures else 0)
