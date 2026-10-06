import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# -------------------------------------------------
# CONFIGURATION – change these to match your setup
# -------------------------------------------------
SEARCH_URL = (
    "https://www.ozon.ru/search/?brand=87317891&brandcertified=t&from_global=true"
    "&text=Кофе+в+зернах+Lavazza+Qualita+Oro%2C+арабика%2C+250+г"
    "&weight=250.000%3B264.000"
)

# Your city for delivery (exactly as Ozon writes it, e.g. "Москва", "Санкт-Петербург")
DELIVERY_CITY = "Владивосток"

# Where to store the persistent browser profile (cookies, local storage)
USER_DATA_DIR = Path("ozon_profile")

LOG_FILE = Path("logs/ozon_checks.txt")


def set_delivery_city(page) -> None:
    """Open the city selector and choose DELIVERY_CITY."""
    # Click the current city (usually in the top‑left corner)
    city_btn = page.locator("button:has-text('Москва'), button:has-text('Город')").first
    if city_btn.count() == 0:
        # Fallback: sometimes it's a link
        city_btn = page.locator("a:has-text('Москва'), a:has-text('Город')").first
    if city_btn.count() == 0:
        print("City selector not found – skipping city change")
        return

    city_btn.click()
    page.wait_for_timeout(1000)

    # Type the city name
    search_input = page.locator("input[placeholder*='город'], input[placeholder*='Город']").first
    if search_input.count() == 0:
        print("City search input not found")
        return

    search_input.fill(DELIVERY_CITY)
    page.wait_for_timeout(1500)

    # Click the first suggestion that matches exactly
    suggestion = page.locator(f"text={DELIVERY_CITY}").first
    if suggestion.count() > 0:
        suggestion.click()
        page.wait_for_timeout(2000)
        print(f"City set to {DELIVERY_CITY}")
    else:
        print(f"City '{DELIVERY_CITY}' not found in suggestions")


def get_first_product_url(page) -> str | None:
    """Return the URL of the first product card on the search page."""
    # Ozon product links always contain /product/
    links = page.locator("a[href*='/product/']").all()
    for link in links:
        href = link.get_attribute("href")
        if href and "/product/" in href:
            # Make absolute
            if href.startswith("/"):
                href = "https://www.ozon.ru" + href
            # Strip query parameters (they are only for analytics)
            href = href.split("?")[0]
            return href
    return None


def parse_price(page) -> str | None:
    """Extract price from the product page."""
    # Primary selector: Ozon uses this widget for the main price
    price_block = page.locator("[data-widget='webPrice']")
    if price_block.count() == 0:
        return None

    # Try the known class first
    price_el = price_block.locator("[class*='tsHeadline600Large']").first
    if price_el.count() > 0:
        text = price_el.inner_text()
    else:
        # Fallback: pick the largest number in the block
        text = price_block.inner_text()

    # Clean the string: remove spaces, non‑breaking spaces, minus signs, ₽
    cleaned = re.sub(r"[^\d.,]", "", text.replace("\u2009", "").replace("\u00A0", ""))
    cleaned = cleaned.replace(",", ".")
    # Take the first number that looks like a price
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    return match.group(0) if match else None


def get_ozon_data() -> tuple[str, str | None, str]:
    """Return (title, price, final_url) from the first product card."""
    with sync_playwright() as p:
        # Persistent context keeps cookies and avoids captcha
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=True,
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
        )
        page = context.new_page()

        # 1. Go to homepage first (natural navigation)
        page.goto("https://www.ozon.ru", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        # 2. Set delivery city
        set_delivery_city(page)

        # 3. Go to the search page
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        # 4. Find the first product link
        product_url = get_first_product_url(page)
        if not product_url:
            raise RuntimeError("No product link found on search page")

        # 5. Open the product page
        page.goto(product_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        # 6. Get title (og:title or <title>)
        title = page.title()
        og_title = page.locator("meta[property='og:title']")
        if og_title.count() > 0:
            title = og_title.get_attribute("content") or title

        # 7. Get price
        price = parse_price(page)

        final_url = page.url
        context.close()

    return title.strip(), price, final_url


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
