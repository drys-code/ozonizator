"""Install and verify the Telegram credentials used by ozon_monitor.py.

Usage (from the repository folder):

    py setup_telegram.py

The script asks for the bot token and chat id *without echoing the token*,
verifies them against the Telegram API, and saves them to
%USERPROFILE%\\.ozonizator\\secrets.env so the monitor picks them up.

Nothing is written into the repository, so the token can never be committed.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

import requests

SECRETS_FILE = Path.home() / ".ozonizator" / "secrets.env"


def main() -> int:
    print("Настройка Telegram для ozonizator")
    print("Токен создаётся у @BotFather, chat id можно узнать у @userinfobot.\n")

    token = getpass.getpass("Telegram bot token (ввод не отображается): ").strip()
    if not token:
        print("Токен не введён — отмена.")
        return 1

    chat_id = input("Telegram chat id: ").strip()
    if not chat_id:
        print("Chat id не введён — отмена.")
        return 1

    print("\nПроверяю бота...")
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", timeout=20
        )
    except requests.RequestException as exc:
        print(f"Не удалось обратиться к Telegram: {exc}")
        return 1

    payload = response.json()
    if not payload.get("ok"):
        print(f"Telegram отклонил токен: {payload.get('description')}")
        return 1
    bot = payload["result"]
    print(f"Бот найден: @{bot.get('username')} ({bot.get('first_name')})")

    print("Отправляю тестовое сообщение...")
    try:
        sent = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "✅ ozonizator подключён. Дальше цена на кофе будет приходить сюда.",
                "disable_web_page_preview": True,
            },
            timeout=20,
        ).json()
    except requests.RequestException as exc:
        print(f"Не удалось отправить сообщение: {exc}")
        return 1

    if not sent.get("ok"):
        print(
            "Сообщение не отправлено: "
            f"{sent.get('description')}\n"
            "Проверьте chat id (бот должен иметь право писать вам — нажмите Start в чате с ботом)."
        )
        return 1

    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(
        f"TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_CHAT_ID={chat_id}\n", encoding="utf-8"
    )
    print(f"\nГотово. Секреты сохранены в {SECRETS_FILE}")
    print("Тестовое сообщение отправлено — проверьте Telegram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
