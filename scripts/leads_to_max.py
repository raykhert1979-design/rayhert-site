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

import datetime
import email
import imaplib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.header import decode_header

MAIL_MARKER_DEFAULT = "Заявка с сайта"
IMAP_HOST = "imap.yandex.ru"
IMAP_LOOKBACK_DAYS = 3
MAX_PER_RUN = 100
ARCHIVE_FOLDER = "Заявки"
# имя папки в modified UTF-7 — так его ждёт IMAP Яндекса
ARCHIVE_FOLDER_UTF7 = "&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"


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


def body_html_raw(msg) -> str:
    """Сырой HTML письма (FormSubmit шлёт таблицу заявки в HTML)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""
    if msg.get_content_type() == "text/html":
        payload = msg.get_payload(decode=True) or b""
        charset = msg.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    return ""


LEAD_LABELS = {
    "name": "Имя",
    "contact": "Контакт",
    "task": "Задача",
    "budget": "Бюджет",
    "comment": "Комментарий",
    "estimate": "Смета",
}


def clean_lead(subject: str, html: str) -> str:
    """Из HTML-письма FormSubmit делает краткий текст: заголовок + пары «Поле: значение»."""
    subject = subject.strip() or "Заявка с сайта"
    if not html:
        return subject
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I):
        key_m = re.search(r"<strong[^>]*>(.*?)</strong>", tr, flags=re.S | re.I)
        val_m = re.search(r"<pre[^>]*>(.*?)</pre>", tr, flags=re.S | re.I)
        key = re.sub(r"<[^>]+>", "", key_m.group(1)).strip() if key_m else ""
        val = re.sub(r"<[^>]+>", "", val_m.group(1)).strip() if val_m else ""
        if key and val:
            rows.append((key.strip(), val.strip()))
    if not rows:
        return subject
    lines = [subject, ""]
    for key, val in rows:
        label = LEAD_LABELS.get(key.lower(), key)
        lines.append(f"{label}: {val}")
    return "\n".join(lines)


def message_ids(box, folder: str, quoted: bool = False) -> set:
    """Message-ID писем в папке (для проверки «уже обработано»)."""
    ids = set()
    name = ('"' + folder + '"') if quoted else folder
    try:
        typ, _ = box.select(name)
        if typ != "OK":
            return ids
        typ, data = box.search(None, "ALL")
        if typ != "OK":
            return ids
        for num in data[0].split():
            typ, d = box.fetch(num, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            if typ != "OK" or not d or not isinstance(d[0], tuple):
                continue
            found = re.search(rb"<([^>]+)>", d[0][1])
            if found:
                ids.add(found.group(1).decode("ascii", "replace").strip().lower())
    except Exception as exc:  # noqa: BLE001
        print(f"Архив: не удалось прочитать — {exc}")
    return ids


def archive_lead(box, num) -> None:
    """Кладёт письмо в папку «Заявки», чтобы больше его не обрабатывать."""
    try:
        box.select("INBOX")
    except Exception:  # noqa: BLE001
        pass
    try:
        typ, _ = box.copy(num, '"' + ARCHIVE_FOLDER_UTF7 + '"')
        if typ != "OK":
            print(f"Архив: копирование {num} не удалось")
    except Exception as exc:  # noqa: BLE001
        print(f"Архив: копирование {num} — {exc}")


def send_to_max(text: str) -> bool:
    base = env("MAX_API_BASE", "https://platform-api2.max.ru").rstrip("/") or "https://platform-api2.max.ru"
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
        if isinstance(exc, urllib.error.URLError) and "CERTIFICATE_VERIFY_FAILED" in str(exc):
            # На части машин нет сертификата Минцифры в доверенных — повторяем без проверки
            ctx = ssl._create_unverified_context()
            try:
                with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                    return 200 <= resp.status < 300
            except urllib.error.HTTPError as exc2:
                detail = exc2.read().decode("utf-8", errors="replace")[:300]
                print(f"MAX: ошибка HTTP {exc2.code}: {detail}")
                return False
            except Exception as exc2:  # noqa: BLE001
                print(f"MAX: сеть недоступна (повтор) — {exc2}")
                return False
        print(f"MAX: сеть недоступна — {exc}")
        return False


def connect_box(login: str, password: str, attempts: int = 3):
    """Подключается к IMAP и открывает INBOX, повторяя попытку при обрыве."""
    last_error = None
    box = None
    for attempt in range(1, attempts + 1):
        try:
            box = imaplib.IMAP4_SSL(IMAP_HOST)
            box.login(login, password)
            typ, _ = box.select("INBOX")
            if typ != "OK":
                raise imaplib.IMAP4.error(f"SELECT INBOX: {typ}")
            return box
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"IMAP: попытка {attempt}/{attempts} не удалась — {exc}")
            if box is not None:
                try:
                    box.logout()
                except Exception:  # noqa: BLE001
                    pass
                box = None
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise last_error


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
        box = connect_box(login, password)
    except Exception as exc:  # noqa: BLE001
        print(f"IMAP: не удалось подключиться — {exc}")
        return 1

    sent = 0
    failed = 0
    try:
        since = (datetime.date.today() - datetime.timedelta(days=IMAP_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
        archived = message_ids(box, ARCHIVE_FOLDER_UTF7, quoted=True)
        try:
            typ, _ = box.select("INBOX")
            if typ != "OK":
                raise imaplib.IMAP4.error(f"SELECT INBOX: {typ}")
        except Exception as exc:  # noqa: BLE001
            print(f"IMAP: не удалось вернуться во Входящие — {exc}")
            box = connect_box(login, password)
        typ, data = box.search(None, f'(SENTSINCE {since})')
        if typ != "OK":
            print("IMAP: поиск писем не удался")
            return 1

        ids = data[0].split()
        if len(ids) > MAX_PER_RUN:
            ids = ids[-MAX_PER_RUN:]
        print(f"Писем к обработке (за {IMAP_LOOKBACK_DAYS} дн.): {len(ids)}, уже в архиве: {len(archived)}")

        for num in ids:
            try:
                typ, raw = box.fetch(num, "(BODY.PEEK[])")
            except Exception as exc:
                print(f"IMAP: соединение оборвалось при загрузке {num} — переподключаюсь ({exc})")
                try:
                    box.logout()
                except Exception:
                    pass
                try:
                    box = imaplib.IMAP4_SSL(IMAP_HOST)
                    box.login(login, password)
                    box.select("INBOX")
                    typ, raw = box.fetch(num, "(BODY.PEEK[])")
                except Exception as exc2:
                    print(f"IMAP: повторное подключение не удалось — {exc2}")
                    break
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue

            msg = email.message_from_bytes(raw[0][1])
            subject = decode(msg.get("Subject"))
            text = body_text(msg)

            if marker.lower() not in (subject + " " + text).lower():
                continue

            msg_id = re.sub(r"[<>]", "", (msg.get("Message-ID") or "")).strip().lower()
            if msg_id and msg_id in archived:
                continue

            payload = clean_lead(subject, body_html_raw(msg))
            if len(payload) > 3500:
                payload = payload[:3500] + "\n…сообщение обрезано"

            try:
                ok = send_to_max(payload)
            except Exception as exc:
                print(f"MAX: исключение — {exc}")
                ok = False
            if ok:
                sent += 1
                try:
                    box.store(num, "+FLAGS", "\\Seen")
                except Exception:
                    pass
                archive_lead(box, num)
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
