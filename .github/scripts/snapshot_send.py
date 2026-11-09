#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отправка результата снапшота канала клиенту в MAX + копия владельцу.
GigaChat сам пишет текст аудита по снапшоту. Вызывается из snapshot-audit.yml.
Всё автоматически, без ручной отправки.
"""
import json, os, sys, ssl, urllib.request, urllib.error, urllib.parse, uuid

def ctx_no_verify():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

def giga_audit(snapshot_text):
    """Формирует текст бесплатного аудита по снапшоту через GigaChat."""
    secret = os.environ.get("GIGA_SECRET", "")
    if not secret:
        return None
    data = urllib.parse.urlencode({"scope": "GIGACHAT_API_PERS"}).encode()
    req = urllib.request.Request("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data=data, method="POST",
        headers={"Authorization": "Basic " + secret,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json",
                 "RqUID": str(uuid.uuid4()),
                 "User-Agent": "rayhert-audit/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx_no_verify()) as r:
        tok = json.loads(r.read().decode())["access_token"]
    system = ("Ты — аналитик студии Артёма Райхерта. По данным снапшота канала составь "
              "бесплатный аудит за 15 минут. Пиши по-русски, от «мы», тепло, по делу, без воды и без "
              "рекламы цен. Строго: разбери ТОЛЬКО те цифры и факты, которые есть в снапшоте — подписчики, "
              "активность, просмотры, регулярность публикаций, названия канала. Ничего не выдумывай и не "
              "обобщай сверх данных. Избегай шаблонных комплиментов («отличный канал», «хорошая работа»), "
              "говори конкретно и честно, но доброжелательно. НЕ проси вводить «да» и НЕ предлагай "
              "выбрать опцию — после аудита клиент сам увидит вопрос о сотрудничестве.")
    payload = {"model": "GigaChat-2-Max", "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": "Снапшот канала:\n" + snapshot_text}],
        "temperature": 0.55, "max_tokens": 900}
    req2 = urllib.request.Request("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req2, timeout=90, context=ctx_no_verify()) as r:
        d = json.loads(r.read().decode())
        return d["choices"][0]["message"]["content"].strip()

def send_max(token, chat_id, text):
    req = urllib.request.Request(
        "https://platform-api2.max.ru/messages?chat_id=%s" % chat_id,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Authorization": token, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30, context=ctx_no_verify()) as r:
        return r.status

LABELS = {
    "url": "Канал",
    "platform": "Площадка",
    "name": "Название канала",
    "subscribers": "Подписчики",
    "members": "Участники",
    "video_count": "Видео в канале",
    "video_count_meta": "Видео в канале",
    "posts_count": "Записей на стене",
    "page_views_sum": "Просмотры (последняя страница)",
    "views_sum": "Сумма просмотров",
    "photos": "Фотографии",
    "description": "Описание",
    "summary": "Описание",
}

def _fmt(v):
    return str(v).strip()

def build_metrics_rows(data):
    """Программный блок цифр: строки «показатель — значение — пояснение»."""
    rows = []
    plat = _fmt(data.get("platform") or "").lower()
    rows.append(("Площадка", plat.upper() if plat else "—",
                 "С этой платформы собран аудит"))
    for k, label in LABELS.items():
        if k in ("url", "platform", "description", "summary"):
            continue
        v = data.get(k)
        if v is None or v == "" or v == [] or v == {}:
            continue
        val = _fmt(v)
        if len(val) > 60:
            val = val[:60] + "…"
        expl = ""
        if k in ("subscribers", "members"):
            expl = "Аудитория, которая подписана на канал"
        elif k in ("video_count", "video_count_meta", "posts_count"):
            expl = "Объём контента, который уже на канале"
        elif k == "page_views_sum":
            expl = "Просмотры последних видео — реакция аудитории на новый контент"
        elif k == "views_sum":
            expl = "Общая сумма просмотров канала"
        rows.append((label, val, expl))
    rv = data.get("recent_videos") or []
    if rv:
        total = 0
        for v in rv:
            try:
                total += int(v.get("views") or 0)
            except (TypeError, ValueError):
                pass
        if total:
            rows.append(("Просмотры последних видео", str(total),
                         "Считаются из списка свежих роликов"))
        rows.append(("Свежих роликов показано", str(len(rv)),
                     "Первые из ленты канала"))
    return rows

def build_table_text(data):
    """Таблица цифр: показатели и объяснения."""
    rows = build_metrics_rows(data)
    if not rows:
        return "Цифры по каналу не собраны."
    w1 = max(len(r[0]) for r in rows) + 1
    w2 = max(len(r[1]) for r in rows) + 1
    out = []
    for a, b, c in rows:
        out.append(f"{a:<{w1}} {b:<{w2}} {c}")
    return "\n".join(out)

def build_text():
    try:
        with open("snapshot.json", encoding="utf-8") as f:
            data = json.load(f)
        header = []
        name = data.get("name") or data.get("title_meta") or data.get("og_title")
        if name:
            header.append("Канал: " + str(name)[:80])
        plat = data.get("platform")
        if plat:
            header.append("Площадка: " + str(plat))
        table = build_table_text(data)
        rv = data.get("recent_videos")
        if rv:
            header.append("")
            header.append("Последние видео:")
            for v in rv[:5]:
                t = (v.get("title") or "")[:45]
                header.append(f"  - {t} (просм.: {v.get('views')})")
        parts = ["📊 Снапшот канала:"]
        if header:
            parts.append("\n".join(header))
        parts.append("\n📈 Цифры по каналу:")
        parts.append(table)
        return "\n\n".join(parts)
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

    text = build_text()  # сырые данные снапшота
    # GigaChat составляет текст аудита; если не вышло — шлём сырые данные
    audit = None
    try:
        audit = giga_audit(text)
        print("GigaChat аудит:", "OK" if audit else "нет")
    except Exception as e:
        print("GigaChat ERR:", str(e)[:200])

    # Вопрос о дальнейшем сотрудничестве — вместо «напишите да» в прошлом промпте
    COOP = ("\n\nЕсли хотите, чтобы мы помогли с каналом — ответьте «да», "
            "и с вами свяжутся наши специалисты: обсудим, что даст автоматизация "
            "и как получить API канала для более глубокого анализа.")

    if audit:
        to_client = "🎁 Бесплатный аудит канала готов!\n\n" + audit + COOP
        to_owner = "🎁 Бесплатный аудит канала!\n\n" + audit + "\n\n---\nСырые данные снапшота:\n" + text
    else:
        to_client = "🎁 Бесплатный аудит канала готов!\n\n" + text + COOP
        to_owner = to_client

    # 1) клиенту (обязательно)
    try:
        st = send_max(consult_token, client_chat, to_client)
        print("клиенту MAX:", st)
    except urllib.error.HTTPError as e:
        print("клиенту MAX HTTP-ошибка:", e.code, e.read().decode("utf-8", "replace")[:200])
    except Exception as e:
        print("клиенту MAX ERR:", e)

    # 2) копия владельцу (если есть токен и чат)
    if owner_token and owner_chat:
        try:
            st2 = send_max(owner_token, owner_chat, to_owner)
            print("владельцу MAX:", st2)
        except urllib.error.HTTPError as e:
            print("владельцу MAX HTTP-ошибка:", e.code, e.read().decode("utf-8", "replace")[:200])
        except Exception as e:
            print("владельцу MAX ERR:", e)

if __name__ == "__main__":
    main()
