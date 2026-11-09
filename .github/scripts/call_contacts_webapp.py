#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Запись контакта клиента в Google Sheets через Apps Script Web App.
Вызывается из workflow consult-giga.yml и snapshot-audit.yml.
Контакты — закрытые данные студии, в публичный репозиторий не попадают:
все данные уходят сразу в приватную таблицу по защищённой ссылке Web App.
"""
import os, json, ssl, urllib.request

WEBAPP_URL = "https://script.google.com/macros/s/AKfycbzw5B118oSOJT9IRLrvmJROeM_v4Z9CMrNIcUF-jQnytr67Zb-qKxXUWmuY5AOOqgFxvw/exec"


def ctx_no_verify():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def detect_platform(url):
    u = (url or "").lower()
    if "rutube.ru" in u:
        return "rutube"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "vk.com" in u or "vkvideo" in u:
        return "vk"
    if "dzen.ru" in u:
        return "dzen"
    if "t.me" in u:
        return "telegram"
    if "ok.ru" in u:
        return "ok"
    return ""


def main():
    chat_id = os.environ.get("CHAT_ID", "")
    if not chat_id:
        print("нет CHAT_ID, контакт не записываю")
        return
    payload = {
        "источник": os.environ.get("CONTACT_SOURCE", "аудит"),
        "chat_id": str(chat_id),
        "имя": os.environ.get("SENDER_NAME", ""),
        "контакт": os.environ.get("CONTACT_VALUE", ""),
        "площадка": os.environ.get("PLATFORM", "") or detect_platform(os.environ.get("CHANNEL_URL", "")),
        "статус": os.environ.get("CONTACT_STATUS", "новый"),
        "следующий_шаг": os.environ.get("NEXT_STEP", ""),
        "следующее_касание": os.environ.get("NEXT_CONTACT", ""),
        "история": os.environ.get("HISTORY", "")
    }
    req = urllib.request.Request(
        WEBAPP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx_no_verify()) as r:
            resp = json.loads(r.read().decode("utf-8", "replace"))
            print("Web App ответ:", resp)
            if not resp.get("ok"):
                print("Web App вернул ошибку:", resp)
    except Exception as e:
        print("Ошибка записи контакта:", str(e)[:300])


if __name__ == "__main__":
    main()
