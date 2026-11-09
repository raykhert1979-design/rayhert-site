#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отправка результата снапшота канала в MAX (вызывается из snapshot-audit.yml)."""
import json, os, sys, ssl, urllib.request, urllib.error

def main():
    token = os.environ.get("MAX_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "")
    if not token or not chat_id:
        print("нет MAX_TOKEN или CHAT_ID")
        sys.exit(0)
    text = None
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
        text = "\n".join(lines)
    except Exception as e:
        text = "Не удалось снять снапшот: %s" % e
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        "https://platform-api2.max.ru/messages?chat_id=%s" % chat_id,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Authorization": token, "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            print("MAX ответ:", r.status)
    except urllib.error.HTTPError as e:
        print("MAX HTTP-ошибка:", e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        print("MAX ERR:", e)

if __name__ == "__main__":
    main()
