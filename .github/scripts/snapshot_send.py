#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отправка результата снапшота канала клиенту в MAX + копия владельцу.
Вызывается из snapshot-audit.yml. Всё автоматически, без ручной отправки.
"""
import json, os, sys, ssl, urllib.request, urllib.error

def ctx_no_verify():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

def send_max(token, chat_id, text):
    req = urllib.request.Request(
        "https://platform-api2.max.ru/messages?chat_id=%s" % chat_id,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Authorization": token, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ctx_no_verify()) as r:
        return r.status

def build_text():
    try:
        with open("snapshot.json", encoding="utf-8") as f:
            data = json.load(f)
        lines = ["📊 Снапшот канала:"]
        for k, v in data.items():
            if v in (None, "", [], {}):
                continue
            if isinstance(v, (list, dict)):
                continue
            lines.append(f"• {k}: {v}")
        rv = data.get("recent_videos")
        if rv:
            lines.append("")
            lines.append("Последние видео:")
            for v in rv[:5]:
                t = (v.get("title") or "")[:50]
                lines.append(f"  - {t} (просм.: {v.get('views')})")
        return "\n".join(lines)
    except Exception as e:
        return "Не удалось снять снапшот: %s" % e

def main():
    # токен консультанта пишет клиенту; токен заявок пишет копию владельцу
    consult_token = os.environ.get("CONSULT_MAX_TOKEN", "")
    owner_token = os.environ.get("MAX_TOKEN", "")
    client_chat = os.environ.get("CHAT_ID", "")          # чат клиента
    owner_chat = os.environ.get("OWNER_CHAT_ID", "")     # чат владельца (661741347)

    if not consult_token or not client_chat:
        print("нет CONSULT_MAX_TOKEN или CHAT_ID")
        sys.exit(0)

    text = build_text()
    # приветствие, которое увидит клиент
    full = "🎁 Бесплатный аудит канала готов!\n\n" + text + \
           "\n\nЭто предварительный разбор. По всем вопросам — напишите, обсудим детали."

    # 1) клиенту (обязательно)
    try:
        st = send_max(consult_token, client_chat, full)
        print("клиенту MAX:", st)
    except urllib.error.HTTPError as e:
        print("клиенту MAX HTTP-ошибка:", e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        print("клиенту MAX ERR:", e)

    # 2) копия владельцу (если есть токен и чат)
    if owner_token and owner_chat:
        try:
            st2 = send_max(owner_token, owner_chat, full)
            print("владельцу MAX:", st2)
        except urllib.error.HTTPError as e:
            print("владельцу MAX HTTP-ошибка:", e.code, e.read().decode("utf-8", "replace")[:200])
        except Exception as e:
            print("владельцу MAX ERR:", e)

if __name__ == "__main__":
    main()
