import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = "https://www.ozon.ru/product/kofe-v-zernah-lavazza-qualita-oro-arabika-250-g-926443964/?at=1nmn1NevvUpRsmF_g9WbNI1Gp2TDTAI7&sh=SXLvNfQ7fA&__rr=1"
LOG_FILE = Path("logs/ozon_checks.txt")


def find_price(text: str) -> str | None:
    patterns = [
        r'"price"\s*:\s*"?(?P<price>\d+(?:[.,]\d+)?)"?',
        r'"finalPrice"\s*:\s*"?(?P<price>\d+(?:[.,]\d+)?)"?',
        r'"discountPrice"\s*:\s*"?(?P<price>\d+(?:[.,]\d+)?)"?',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group("price").replace(",", ".")

    return None


def get_ozon_data() -> tuple[str, str | None, str]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
        )

        page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        title = page.title()

        og_title = page.locator("meta[property='og:title']")
        if og_title.count() > 0:
            title = og_title.get_attribute("content") or title
        html = page.content()
        current_url = page.url

        browser.close()

    return title.strip(), find_price(html), current_url


def send_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    response.raise_for_status()


def main() -> None:
    checked_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        title, price, final_url = get_ozon_data()

        price_text = f"{price} ₽" if price else "не определена"
        log_line = f"{checked_at} | OK | price={price_text} | title={title} | url={final_url}\n"

        message = (
            "🛒 Проверка Ozon\n"
            f"Товар: {title}\n"
            f"Цена: {price_text}\n"
            f"Время: {checked_at}\n"
            f"{final_url}"
        )

    except Exception as error:
        log_line = f"{checked_at} | ERROR | {type(error).__name__}: {error}\n"
        message = (
            "⚠️ Ошибка проверки Ozon\n"
            f"Время: {checked_at}\n"
            f"Ошибка: {type(error).__name__}: {error}"
        )

    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(log_line)

    send_telegram(message)


if __name__ == "__main__":
    main()
