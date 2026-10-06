#!/usr/bin/env python3
"""Ozon price monitor for Lavazza coffee beans (250 g).

Checks the Ozon product page with a real browser, extracts the current card
price, appends the result to logs/ozon_checks.txt and sends a Telegram message
containing the price and a link to the product.

Designed to run from a Russian IP address: Ozon blocks requests coming from
foreign/VPN/datacenter IP addresses, so GitHub-hosted runners cannot read
prices. See README.md.

Environment / configuration
---------------------------
TELEGRAM_BOT_TOKEN   Telegram bot token (required)
TELEGRAM_CHAT_ID     Telegram chat id (required)
OZON_HEADLESS        "0" to watch the browser, default "1"
OZON_CITY            Delivery city to request, default "Владивосток"

Exit codes: 0 = price obtained (or deliberately skipped), 1 = failure.
"""
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# The console and redirected output on Windows default to cp1251, which cannot
# encode "₽" or some Cyrillic text. Force UTF-8 before anything is printed.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

import requests
from playwright.sync_api import sync_playwright

# --- Product under watch -----------------------------------------------------
# Lavazza Qualita Oro, coffee beans, 250 g
PRODUCT_ID = "32933704"
PRODUCT_URL = (
    "https://www.ozon.ru/product/"
    "kofe-v-zernah-lavazza-qualita-oro-250-g-32933704/"
)
PRODUCT_NAME = "Кофе в зёрнах Lavazza Qualita Oro, 250 г"

# --- Settings ---------------------------------------------------------------
DEFAULT_CITY = "Владивосток"
LOG_FILE = Path("logs/ozon_checks.txt")
STATE_FILE = Path("logs/last_price.txt")

# Vladivostok is UTC+10; fall back to the machine's local time.
VLADIVOSTOK = timezone(timedelta(hours=10))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def now_vladivostok() -> str:
    return datetime.now(VLADIVOSTOK).strftime("%Y-%m-%d %H:%M:%S +10")


def log(line: str) -> None:
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def parse_price(block_text: str | None) -> int | None:
    """Extract the card price from the Ozon `webPrice` widget text.

    Real widget text looks like:
      "744 ₽ | С банками | 759 ₽ | 829 ₽ | С другими банками | 298 ₽ за 100 гр"
    The first "<number> ₽" that is not part of a per-unit comparison
    ("... за 100 гр") is the price of the card.
    """
    if not block_text:
        return None
    text = block_text.replace("\u2009", " ").replace("\u00a0", " ")
    for match in re.finditer(r"(\d[\d\s]*)\s*₽", text):
        prefix = text[max(0, match.start() - 12):match.start()].lower()
        tail = text[match.end():match.end() + 12].lower()
        per_unit = ("гр", "кг", "мл", " л")
        if ("за" in prefix and any(u in prefix for u in per_unit)) or (
            "за" in tail and any(u in tail for u in per_unit)
        ):
            continue
        value = int(re.sub(r"\D", "", match.group(1)) or 0)
        if value > 0:
            return value
    return None


class PriceUnavailable(RuntimeError):
    """Raised when Ozon serves a page without a usable price."""


# Ozon sometimes answers with an "Antibot Challenge Page" instead of the
# product page. Waiting a little and retrying usually succeeds.
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 25


def _fetch_once(city: str) -> tuple[int, str, str]:
    """Single attempt: return (price, city_reported_by_ozon, product_title)."""
    headless = os.environ.get("OZON_HEADLESS", "1") != "0"

    with sync_playwright() as play:
        browser = play.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            locale="ru-RU",
            timezone_id="Asia/Vladivostok",
            viewport={"width": 1440, "height": 1000},
            user_agent=USER_AGENT,
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9"},
        )
        page = context.new_page()
        try:
            response = page.goto(
                PRODUCT_URL, wait_until="domcontentloaded", timeout=90_000
            )
            status = response.status if response else None
            page.wait_for_timeout(6000)

            title = page.title()
            lowered = title.lower()
            if "antibot" in lowered or "challenge" in lowered:
                raise PriceUnavailable(
                    f"Ozon показал антибот-страницу (HTTP {status}). "
                    "Обычно помогает повторная попытка."
                )
            if "нет соединения" in lowered:
                raise PriceUnavailable(
                    "Ozon вернул страницу «Похоже, нет соединения» "
                    f"(HTTP {status}). Обычно это блокировка по IP: "
                    "нужен российский IP-адрес."
                )

            bar = page.locator("[data-widget='addressBookBarWeb']")
            reported_city = (
                bar.first.inner_text().replace("\n", " ").strip()
                if bar.count()
                else ""
            )

            heading = page.locator("[data-widget='webProductHeading']")
            if heading.count():
                title = heading.first.inner_text().replace("\n", " ").strip() or title

            price_widget = page.locator("[data-widget='webPrice']")
            if price_widget.count() == 0:
                raise PriceUnavailable(
                    f"Блок с ценой не найден (HTTP {status}, title={title!r})"
                )

            price = parse_price(price_widget.first.inner_text())
            if price is None:
                raise PriceUnavailable("Цена на странице не распознана")
            return price, reported_city, title
        finally:
            context.close()
            browser.close()


def fetch_price(city: str) -> tuple[int, str, str]:
    """Fetch the price, retrying transient anti-bot responses."""
    last_error: Exception | None = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return _fetch_once(city)
        except Exception as exc:  # noqa: BLE001 - retried below
            last_error = exc
            if attempt < ATTEMPTS:
                wait = RETRY_DELAY_SECONDS * attempt
                log(
                    f"attempt {attempt}/{ATTEMPTS} failed "
                    f"({type(exc).__name__}: {exc}); retrying in {wait}s"
                )
                time.sleep(wait)
    raise PriceUnavailable(f"не удалось за {ATTEMPTS} попытки: {last_error}")


SECRETS_FILE = Path.home() / ".ozonizator" / "secrets.env"


def load_local_secrets() -> None:
    """Load TELEGRAM_* from %USERPROFILE%\\.ozonizator\\secrets.env if present.

    Keeps credentials out of the repository. Variables already present in the
    environment take priority.
    """
    if not SECRETS_FILE.is_file():
        return
    for raw in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def send_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "Не заданы TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
            "(запустите py setup_telegram.py)"
        )
    # Overridable so test_telegram_message.py can capture the outgoing message.
    api_base = os.environ.get("OZON_TELEGRAM_API", "https://api.telegram.org")
    response = requests.post(
        f"{api_base}/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Telegram API {response.status_code}: {response.text[:300]}")


def previous_price() -> int | None:
    try:
        return int(STATE_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def build_message(price: int | None, city: str, error: str | None) -> str:
    stamp = now_vladivostok()
    if error:
        return (
            "⚠️ Не удалось проверить цену\n\n"
            f"Товар: {PRODUCT_NAME}\n"
            f"Время: {stamp}\n"
            f"Причина: {error}\n\n"
            f"{PRODUCT_URL}"
        )

    was = previous_price()
    trend = ""
    if was is not None and was != price:
        diff = price - was
        arrow = "📉" if diff < 0 else "📈"
        trend = f"\n{arrow} Изменение: {diff:+d} ₽ (было {was} ₽)"

    return (
        "☕️ Ozon: цена на кофе\n\n"
        f"Товар: {PRODUCT_NAME}\n"
        f"Цена: {price} ₽{trend}\n"
        f"Город доставки: {city or 'не определён'}\n"
        f"Время: {stamp}\n\n"
        f"{PRODUCT_URL}"
    )


def main() -> int:
    load_local_secrets()
    city = os.environ.get("OZON_CITY", DEFAULT_CITY)
    stamp = now_vladivostok()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    ok = True
    try:
        price, reported_city, title = fetch_price(city)
        log(f"{stamp} | OK | price={price} ₽ | ozon_city={reported_city} | {title}")
        STATE_FILE.write_text(str(price), encoding="utf-8")
        message = build_message(price, reported_city, None)
    except Exception as exc:  # noqa: BLE001 - report any failure to the user
        ok = False
        reason = f"{type(exc).__name__}: {exc}"
        log(f"{stamp} | ERROR | {reason}")
        message = build_message(None, "", reason)

    try:
        send_telegram(message)
        log(f"{stamp} | telegram=sent")
    except Exception as exc:  # noqa: BLE001
        ok = False
        log(f"{stamp} | telegram=FAILED | {type(exc).__name__}: {exc}")

    log(f"{stamp} | RESULT | {'ok' if ok else 'failed'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
