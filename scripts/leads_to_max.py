#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Доставка заявок с сайта в мессенджер MAX.

Схема: форма на сайте -> приёмник форм -> письмо в Яндекс.Почту ->
этот скрипт (по расписанию GitHub Actions) -> сообщение в MAX Bot API.

Персональные данные в репозиторий не пишутся: письма остаются в почте,
обработанные помечаются прочитанными и (если папка есть) переносятся в «Заявки».

Переменные окружения:
  YANDEX_LOGIN          — адрес почты до @ (например, rajhert2018)
  YANDEX_APP_PASSWORD   — пароль приложения Яндекса (не основной пароль!)
  MAX_TOKEN             — токен бота MAX
  MAX_CHAT_ID           — id чата, куда слать заявки
  MAX_API_BASE          — необязательно, по умолчанию https://platform-api.max.ru
  MAIL_MARKER           — необязательно, подстрока темы/текста письма
"""

import email
import imaplib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from email.header import decode_header

MAIL_MARKER_DEFAULT = "Заявка с сайта"
IMAP_HOST = "imap.yandex.ru"
ARCHIVE_FOLDER = "Заявки"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def decode(value) -> str:
    if value is None:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return "".join(parts)


def body_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                html = payload.decode(charset, errors="replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def send_to_max(text: str) -> bool:
    base = env("MAX_API_BASE", "https://platform-api.max.ru").rstrip("/")
    token = env("MAX_TOKEN")
    chat_id = env("MAX_CHAT_ID")

    url = f"{base}/messages?chat_id={urllib.parse.quote(chat_id)}"
    data = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"MAX: ошибка HTTP {exc.code}: {detail}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"MAX: сеть недоступна — {exc}")
        return False


def main() -> int:
    login = env("YANDEX_LOGIN")
    password = env("YANDEX_APP_PASSWORD")
    marker = env("MAIL_MARKER", MAIL_MARKER_DEFAULT)

    missing = [n for n in ("YANDEX_LOGIN", "YANDEX_APP_PASSWORD", "MAX_TOKEN", "MAX_CHAT_ID")
               if not env(n)]
    if missing:
        print("Не заданы секреты: " + ", ".join(missing))
        print("Скрипт ничего не делает. Добавьте секреты в Settings → Secrets and variables → Actions.")
        return 0

    try:
        box = imaplib.IMAP4_SSL(IMAP_HOST)
    except Exception as exc:  # noqa: BLE001
        print(f"IMAP: не удалось подключиться — {exc}")
        return 1

    sent = 0
    failed = 0
    try:
        box.login(login, password)
        box.select("INBOX")

        typ, data = box.search(None, "UNSEEN")
        if typ != "OK":
            print("IMAP: поиск писем не удался")
            return 1

        ids = data[0].split()
        print(f"Непрочитанных писем: {len(ids)}")

        for num in ids:
            typ, raw = box.fetch(num, "(RFC822)")
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue

            msg = email.message_from_bytes(raw[0][1])
            subject = decode(msg.get("Subject"))
            text = body_text(msg)

            if marker.lower() not in (subject + " " + text).lower():
                continue

            payload = text.strip()
            if len(payload) > 3500:
                payload = payload[:3500] + "\n…сообщение обрезано"

            if send_to_max(payload):
                sent += 1
                box.store(num, "+FLAGS", "\\Seen")
                try:
                    box.copy(num, ARCHIVE_FOLDER)
                except Exception:
                    pass
            else:
                failed += 1
    finally:
        try:
            box.logout()
        except Exception:
            pass

    print(f"Отправлено в MAX: {sent}, не удалось: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
