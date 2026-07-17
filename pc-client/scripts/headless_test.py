"""Headless integration test for the non-GUI PC-client layers.

Verifies config loading, the REST ApiClient, and the auto-reconnecting WsClient
against a running server. Does NOT open any Tk windows.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from ringkeeper.api import ApiClient  # noqa: E402
from ringkeeper.config import load_config  # noqa: E402
from ringkeeper.ws_client import WsClient  # noqa: E402

failures = 0


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures += 1


cfg = load_config()
check("config loads", bool(cfg.server_url and cfg.token))
check("ws_url derived from http", cfg.ws_url == "ws://localhost:3000/ws")

api = ApiClient(cfg)
before = api.list_calls(limit=1000)
check("api.list_calls works", isinstance(before, list))

# Start the WS client and capture pushes.
received = []
connected = threading.Event()


def on_msg(msg):
    received.append(msg)


def on_status(is_conn):
    if is_conn:
        connected.set()


ws = WsClient(cfg, on_message=on_msg, on_status=on_status)
ws.start()
check("ws connects within 5s", connected.wait(timeout=5))

# POST a missed call directly to the server and expect a WS push.
uid = f"pyclient-{int(time.time()*1000)}"
resp = requests.post(
    f"{cfg.http_base}/api/calls",
    headers={"Authorization": f"Bearer {cfg.token}"},
    json={
        "caller_name": "PC Client Test",
        "number": "+15559990000",
        "call_type": "missed",
        "timestamp": "2026-07-18T10:00:00Z",
        "client_uid": uid,
    },
    timeout=10,
)
check("POST accepted", resp.status_code in (200, 201))

deadline = time.time() + 5
pushed = None
while time.time() < deadline:
    for m in received:
        if m.get("type") == "new_call" and m.get("data", {}).get("client_uid") == uid:
            pushed = m
            break
    if pushed:
        break
    time.sleep(0.1)
check("WS received the new_call push", pushed is not None)
check("pushed call is a missed call", pushed and pushed["data"]["call_type"] == "missed")

# mark_seen round-trips.
if pushed:
    cid = pushed["data"]["id"]
    seen = api.mark_seen(cid)
    check("api.mark_seen sets seen=1", seen.get("seen") == 1)

ws.stop()
time.sleep(0.3)
print("\n" + ("All headless tests passed." if failures == 0 else f"{failures} failure(s)."))
sys.exit(1 if failures else 0)
