import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# -------------------------------------------------
# НАСТРОЙКИ
# -------------------------------------------------
SEARCH_URL = (
    "https://www.ozon.ru/search/?brand=87317891&brandcertified=t&from_global=true"
    "&text=Кофе+в+зернах+Lavazza+Qualita+Oro%2C+арабика%2C+250+г"
    "&weight=250.000%3B264.000"
)

# Ваш город доставки
DELIVERY_CITY = "Москва"

USER_DATA_DIR = Path("ozon_profile")
LOG_FILE = Path("logs/ozon_checks.txt")


def set_delivery_city(page) -> None:
    """Открывает выбор города и устанавливает DELIVERY_CITY."""
    city_btn = page.locator("button:has-text('Москва'), button:has-text('Город')").first
    if city_btn.count() == 0:
        city_btn = page.locator("a:has-text('Москва'), a:has-text('Город')").first
    if city_btn.count() == 0:
        print("Не найден выбор города – пропускаем смену города")
        return

    city_btn.click()
    page.wait_for_timeout(1000)

    search_input = page.locator("input[placeholder*='город'], input[placeholder*='Город']").first
    if search_input.count() == 0:
        print("Не найдено поле поиска города")
        return

    search_input.fill(DELIVERY_CITY)
    page.wait_for_timeout(1500)

    suggestion = page.locator(f"text={DELIVERY_CITY}").first
    if suggestion.count() > 0:
        suggestion.click()
        page.wait_for_timeout(2000)
        print(f"Город установлен: {DELIVERY_CITY}")
    else:
        print(f"Город '{DELIVERY_CITY}' не найден в подсказках")


def get_first_product_url(page) -> str | None:
    """Возвращает URL первой карточки товара на странице поиска."""
    links = page.locator("a[href*='/product/']").all()
    for link in links:
        href = link.get_attribute("href")
        if href and "/product/" in href:
            if href.startswith("/"):
                href = "https://www.ozon.ru" + href
            href = href.split("?")[0]
            return href
    return None


def parse_price(page) -> str | None:
    """Извлекает цену со страницы товара."""
    price_block = page.locator("[data-widget='webPrice']")
    if price_block.count() == 0:
        return None

    price_el = price_block.locator("[class*='tsHeadline600Large']").first
    if price_el.count() > 0:
        text = price_el.inner_text()
    else:
        text = price_block.inner_text()

    cleaned = re.sub(r"[^\d.,]", "", text.replace("\u2009", "").replace("\u00A0", ""))
    cleaned = cleaned.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    return match.group(0) if match else None


def get_ozon_data() -> tuple[str, str | None, str]:
    """Возвращает (название, цена, итоговый URL) для первой карточки товара."""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=True,
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
        )
        page = context.new_page()

        page.goto("https://www.ozon.ru", wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(3000)

        set_delivery_city(page)

        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        product_url = get_first_product_url(page)
        if not product_url:
            raise RuntimeError("Не найдена ссылка на товар на странице поиска")

        page.goto(product_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)

        title = page.title()
        og_title = page.locator("meta[property='og:title']")
        if og_title.count() > 0:
            title = og_title.get_attribute("content") or title

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
