"""`spider-brain pair` and `spider-brain devices`. They run beside a running `spider-brain serve`
and share its data folder; neither needs the robot."""

from __future__ import annotations

import sys
import time

import httpx

from ..config import Settings
from .devices import DeviceStore, PairingCodes, data_dir

TELEGRAM_API = "https://api.telegram.org"


def _send_on_telegram(settings: Settings, text: str) -> bool:
    ok = True
    for owner in settings.telegram_owner_ids:
        try:
            resp = httpx.post(f"{TELEGRAM_API}/bot{settings.telegram_token}/sendMessage",
                              json={"chat_id": owner, "text": text}, timeout=15.0)
            ok = ok and bool(resp.json().get("ok"))
        except (httpx.HTTPError, ValueError):
            ok = False
    return ok


def pair(settings: Settings) -> int:
    codes = PairingCodes(data_dir(settings.mobile_data_dir), settings.mobile_pair_code_s)
    code = codes.issue()
    ttl = f"{settings.mobile_pair_code_s:.0f} s"
    print(f"Pairing code: {code}  (works once, for {ttl})")
    if not settings.mobile:
        print("note: SB_MOBILE is off, so the running brain will not accept this code.",
              file=sys.stderr)
    if settings.telegram_enabled:
        text = (f"Lowi app pairing code: {code}\nIt works once, for {ttl}.\n"
                "If you did not run `spider-brain pair`, ignore this and check who can reach "
                "the server.")
        if _send_on_telegram(settings, text):
            print("Also sent to the owner on Telegram.")
        else:
            print("Could not send it on Telegram.", file=sys.stderr)
    return 0


def devices(settings: Settings, action: str, name: str | None) -> int:
    store = DeviceStore(data_dir(settings.mobile_data_dir))
    if action == "list":
        listed = store.list()
        if not listed:
            print("No paired devices.")
        for d in listed:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(d.paired_at))
            print(f"{d.name}\tpaired {when}")
        return 0
    if not name:
        print("usage: spider-brain devices revoke <name>", file=sys.stderr)
        return 2
    if not store.revoke(name):
        print(f"no device named {name!r}", file=sys.stderr)
        return 1
    print(f"Revoked {name}. A running brain closes its connections within a second.")
    return 0
