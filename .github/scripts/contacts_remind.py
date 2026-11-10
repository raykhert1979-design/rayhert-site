#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ежедневная сводка контактов-действий владельцу студии в MAX.
Читает таблицу контактов через Apps Script Web App (doGet?action=summarize),
выбирает контакты, по которым есть «следующий шаг» или «следующее касание»,
и шлёт компактную сводку с напоминаниями. Вызывается из contacts-remind.yml.
"""
import os, json, ssl, urllib.request, urllib.parse

WEBAPP_URL = "https://script.google.com/macros/s/AKfycbzw5B118oSOJT9IRLrvmJROeM_v4Z9CMrNIcUF-jQnytr67Zb-qKxXUWmuY5AOOqgFxvw/exec"
ACCESS_KEY = os.environ.get("CONTACTS_KEY", "")  # секрет из GitHub Secrets, не хранить в репо
MAX_API = "https://platform-api2.max.ru/messages"


def ctx_no_verify():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def fetch_rows():
    url = WEBAPP_URL + "?action=summarize&key=" + urllib.parse.quote(ACCESS_KEY)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30, context=ctx_no_verify()) as r:
        return json.loads(r.read().decode("utf-8", "replace")).get("rows", [])


def send_max(token, chat_id, text):
    req = urllib.request.Request(
        MAX_API + "?chat_id=%s" % urllib.parse.quote(str(chat_id)),
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Authorization": token, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ctx_no_verify()) as r:
        return r.status


def main():
    token = os.environ.get("MAX_TOKEN", "")
    chat_id = os.environ.get("MAX_CHAT_ID", "")
    if not token or not chat_id:
        print("нет MAX_TOKEN или MAX_CHAT_ID")
        return
    try:
        rows = fetch_rows()
    except Exception as e:
        print("сводка: ошибка чтения таблицы:", str(e)[:200])
        # не падаем молча: уведомим хозяина
        try:
            send_max(token, chat_id, "⚠️ Не удалось прочитать таблицу контактов для сводки: " + str(e)[:200])
        except Exception as e2:
            print("и уведомить не вышло:", str(e2)[:150])
        return

    if not rows:
        print("контактов нет")
        return

    # «Действия» — контакты, у которых задан следующий шаг или касание
    actions = []
    for r in rows:
        step = (r.get("следующий_шаг") or "").strip()
        when = (r.get("следующее_касание") or "").strip()
        status = (r.get("статус") or "").strip()
        if step or when:
            actions.append({
                "имя": (r.get("имя") or "").strip() or ("чат " + str(r.get("chat_id") or "")),
                "статус": status or "—",
                "шаг": step or "—",
                "касание": when or "—",
                "источник": (r.get("источник") or "").strip()
            })

    if not actions:
        print("активных действий нет")
        return

    lines = ["📋 Сводка контактов за сегодня:"]
    for a in actions:
        lines.append("• " + a["имя"] + (" (" + a["источник"] + ")" if a["источник"] and a["источник"] != "аудит" else ""))
        if a["шаг"] and a["шаг"] != "—":
            lines.append("  Шаг: " + a["шаг"])
        if a["касание"] and a["касание"] != "—":
            lines.append("  Касание: " + a["касание"])
    text = "\n".join(lines)
    try:
        st = send_max(token, chat_id, text)
        print("сводка отправлена:", st)
    except Exception as e:
        print("ошибка отправки сводки:", str(e)[:200])


if __name__ == "__main__":
    main()
