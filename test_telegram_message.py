#!/usr/bin/env python3
"""Verify the Telegram messages ozon_monitor.py produces.

Two layers:
  1. build_message() is checked directly for both the success and the failure
     wording, so no network access is involved.
  2. send_telegram() is checked against a local stand-in for the Telegram API,
     proving the HTTP call and payload are correct.

Usage: py test_telegram_message.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ozon_monitor as monitor  # noqa: E402

captured: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        captured.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true,"result":{"message_id":1}}')

    def log_message(self, *args):
        return


def check(name: str, ok: bool) -> bool:
    print(f"{'PASS' if ok else 'FAIL'} | {name}")
    return ok


def main() -> int:
    results: list[bool] = []

    # ---------- 1. success message ----------
    success = monitor.build_message(744, "Владивосток", None)
    print("--- success message ---")
    print(success)
    print()
    results += [
        check("success: contains price", "744 ₽" in success),
        check("success: contains product link", monitor.PRODUCT_URL in success),
        check("success: contains product name", "Lavazza" in success),
        check("success: contains city", "Владивосток" in success),
        check("success: contains time", "Время:" in success),
        check("success: not an error", "Не удалось" not in success),
    ]

    # ---------- 2. failure message ----------
    failure = monitor.build_message(None, "", "PriceUnavailable: тест")
    print("\n--- failure message ---")
    print(failure)
    print()
    results += [
        check("failure: states the problem", "Не удалось проверить цену" in failure),
        check("failure: keeps product link", monitor.PRODUCT_URL in failure),
        check("failure: includes reason", "PriceUnavailable: тест" in failure),
    ]

    # ---------- 3. trend line ----------
    state_before = monitor.STATE_FILE.read_text(encoding="utf-8") if monitor.STATE_FILE.exists() else None
    try:
        monitor.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        monitor.STATE_FILE.write_text("800", encoding="utf-8")
        trend = monitor.build_message(744, "Владивосток", None)
        results.append(check("trend: shows drop vs previous price", "📉" in trend and "-56" in trend))
    finally:
        if state_before is None:
            monitor.STATE_FILE.unlink(missing_ok=True)
        else:
            monitor.STATE_FILE.write_text(state_before, encoding="utf-8")

    # ---------- 4. real HTTP send against a stub API ----------
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TESTTOKEN"
    os.environ["TELEGRAM_CHAT_ID"] = "99999"
    os.environ["OZON_TELEGRAM_API"] = f"http://127.0.0.1:{port}"
    try:
        monitor.send_telegram(success)
    except Exception as exc:  # noqa: BLE001
        print(f"send_telegram raised: {exc}")
        results.append(False)
    finally:
        server.shutdown()

    print(f"\n--- captured {len(captured)} telegram request(s) ---")
    if captured:
        print(json.dumps(captured[0], ensure_ascii=False, indent=2))
        results += [
            check("send: called the Telegram API", True),
            check("send: used the configured chat id", captured[0].get("chat_id") == "99999"),
            check("send: carried the price", "744 ₽" in captured[0].get("text", "")),
            check("send: carried the product link", monitor.PRODUCT_URL in captured[0].get("text", "")),
        ]
    else:
        results.append(check("send: called the Telegram API", False))

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
