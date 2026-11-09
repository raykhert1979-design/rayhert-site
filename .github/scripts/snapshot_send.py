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
    system = ("Ты — аналитик студии Артёма Райхерта. Составь текст бесплатного экспресс-аудита канала "
              "по данным снапшота. СТРОГО соблюдай структуру макета, без отступлений:\n"
              "1) Первая строка абзаца: «Мы проанализировали ваш канал \"<название из снапшота>\" на <площадке> "
              "и готовы поделиться результатами бесплатного экспресс-аудита.»\n"
              "2) Секция «✅ Что хорошо:» — 2 пункта с «-», только по фактам из снапшота (подписчики, "
              "объём контента, тематика). Без пустых комплиментов.\n"
              "3) Секция «❗ Над чем стоит поработать:» — 2 пункта с «-» по слабым местам из данных "
              "(регулярность публикаций, просмотры, вовлечённость). Конкретно и доброжелательно.\n"
              "4) Финальный абзац: «Если хотите узнать больше деталей об улучшении показателей своего "
              "канала, мы можем провести подробный анализ и предложить конкретные рекомендации.»\n"
              "Правила: только факты из снапшота, ничего не выдумывай, без рекламы цен, без эмодзи-заголовков "
              "вроде «Что хорошо/Что улучшить» — используй ровно «✅ Что хорошо:» и «❗ Над чем стоит поработать:». "
              "НЕ рисуй таблицы и НЕ пиши про «да» — таблица и вопрос о сотрудничестве добавляются отдельно.")
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

def send_max(token, chat_id, text, fmt="html"):
    data = {"text": text}
    if fmt:
        data["format"] = fmt
    req = urllib.request.Request(
        "https://platform-api2.max.ru/messages?chat_id=%s" % chat_id,
        data=json.dumps(data).encode("utf-8"),
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
            expl = "Объём контента, который уже размещён"
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
    """Таблица цифр ровными колонками: Показатель | Значение | Пояснение (без рамок)."""
    rows = build_metrics_rows(data)
    if not rows:
        return "Цифры по каналу не собраны."
    w1 = max(len(r[0]) for r in rows) + 2
    w2 = max(len(r[1]) for r in rows) + 2
    out = []
    for a, b, c in rows:
        out.append(f"{a:<{w1}}{b:<{w2}}{c}")
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

def build_body_plain():
    """Короткое описание канала БЕЗ таблицы (для fallback, когда GigaChat не ответил).
    Таблица добавляется отдельно в main() — ровно один раз."""
    try:
        with open("snapshot.json", encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("name") or data.get("title_meta") or data.get("og_title")
        plat = data.get("platform") or ""
        lines = []
        if name:
            lines.append("Канал: " + str(name)[:80])
        if plat:
            lines.append("Площадка: " + str(plat))
        rv = data.get("recent_videos")
        if rv:
            lines.append("")
            lines.append("Последние видео:")
            for v in rv[:3]:
                t = (v.get("title") or "")[:45]
                lines.append(f"  - {t} (просм.: {v.get('views')})")
        return "\n".join(lines)
    except Exception as e:
        return "Не удалось снять снапшот: %s" % e

def build_human_audit(snap, snap_text=""):
    """Живой экспресс-аудит: вступление, ✅ что хорошо, ❗ над чем поработать, вывод.
    Генерируется из цифр снапшота — без облака, всегда доступен."""
    name = (snap.get("name") or snap.get("title_meta") or snap.get("og_title") or "").strip()
    plat = str(snap.get("platform") or "").lower()
    plat_ru = {"rutube": "Rutube", "youtube": "YouTube", "vk": "ВКонтакте",
               "dzen": "Дзен", "telegram": "Telegram"}.get(plat, plat.upper() or "площадке")
    subs_raw = snap.get("subscribers") or snap.get("members")
    subs = str(subs_raw).strip() if subs_raw else ""

    def num(v):
        try:
            return int(str(v).replace(" ", "").replace("\u00a0", "").replace("К", "000").replace("к", "000").replace(",", "").replace(".", ""))
        except Exception:
            return None

    def parse_count(s):
        # "4 395" -> 4395 ; "58,4К" -> 58400 ; "3K" -> 3000
        if not s:
            return None
        s = str(s).strip().replace("\u00a0", " ").replace(" ", "")
        try:
            if "К" in s.upper():
                return int(float(s.upper().replace("К", "")) * 1000)
            return int(float(s.replace(",", ".")))
        except Exception:
            return None

    content_count = None
    for k in ("video_count", "video_count_meta", "posts_count"):
        if snap.get(k):
            content_count = parse_count(str(snap.get(k)))
            if content_count:
                break

    views_sum = None
    rv = snap.get("recent_videos") or []
    views_list = []
    for v in rv:
        tmp = v.get("views")
        n = num(tmp) if tmp is not None else None
        if n:
            views_list.append(n)
    if views_list:
        views_sum = sum(views_list)

    intro = f'Мы проанализировали ваш канал «{name[:60]}» на {plat_ru} и готовы поделиться результатами бесплатного экспресс-аудита.'
    good = []
    improve = []

    # аналитика по цифрам
    subs_n = parse_count(subs)
    if subs_n:
        if subs_n >= 50000:
            good.append("У вас уже сформировалась крупная аудитория — это сильный ресурс для развития канала и привлечения партнёрств.")
        elif subs_n >= 5000:
            good.append("У вас собранная база подписчиков — фундамент, на котором можно строить рост и монетизацию.")
        elif subs_n >= 500:
            good.append("У вас есть своя аудитория, которая подписана и ждёт новых публикаций — хорошая база для старта.")
        else:
            improve.append("Аудитория пока небольшая — стоит активнее привлекать подписчиков: продвижение новых роликов и перекрёстные ссылки между площадками.")
    else:
        improve.append("Прирост подписчиков стоит вывести в приоритет — это главный показатель здоровья канала.")

    if content_count:
        if content_count >= 1000:
            good.append(f"Содержательный архив — {content_count} публикаций. Такой объём контента помогает зрителям находить канал и оставаться надолго.")
        elif content_count >= 100:
            good.append(f"Уже {content_count} публикаций — регулярный контент поддерживает интерес аудитории.")
        else:
            improve.append(f"Публикаций пока немного ({content_count}) — для роста нужно наращивать регулярность и объём.")

    if views_list:
        avg = views_sum / len(views_list)
        if avg >= 1000:
            good.append("Свежие ролики стабильно собирают просмотры — контент попадает в рекомендации площадки.")
        elif avg >= 200:
            good.append(f"Свежие видео набирают в среднем {int(avg)} просмотров — это рабочая точка для роста.")
        else:
            improve.append(f"Просмотры последних роликов пока скромные (в среднем {int(avg)}) — стоит поработать над названиями, обложками и продвижением, чтобы видео чаще попадали в рекомендации.")
    else:
        improve.append("Отслеживайте просмотры каждого нового выпуска — это покажет, какой контент заходит аудитории.")

    improve.append("Регулярность публикаций — ключ к росту: чем стабильнее вы выходите, тем охотнее площадка продвигает канал и тем активнее возвращаются зрители.")

    # добиваем до равновесия
    while len(good) < 2:
        good.append("Тематика канала понятна и нишевая — есть своя аудитория и потенциал для узнаваемости.")
    while len(improve) > 3:
        improve.pop()

    parts = [intro, "\n✅ Что хорошо:"]
    parts += ["- " + g for g in good[:2]]
    parts.append("\n❗ Над чем стоит поработать:")
    parts += ["- " + p for p in improve[:2]]
    parts.append("\nЕсли хотите узнать больше деталей об улучшении показателей своего канала, "
                 "мы можем провести подробный анализ и предложить конкретные рекомендации.")
    return "\n".join(parts)

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

    # Таблица цифр — ровными колонками, из снапшота (ОДИН раз в сообщении)
    digits = ""
    try:
        with open("snapshot.json", encoding="utf-8") as f:
            snap = json.load(f)
        digits = "\n\n📈 Цифры по каналу:\n" + build_table_text(snap)
    except Exception:
        digits = ""

    # Строго по шаблону: заголовок → аудит (GigaChat или человеческий fallback) → ОДНА таблица → вопрос
    header = "🎁 Бесплатный аудит канала готов!"
    if audit:
        body = audit
    else:
        try:
            with open("snapshot.json", encoding="utf-8") as f:
                snap = json.load(f)
            body = build_human_audit(snap, text)
        except Exception:
            body = build_body_plain()
    to_client = header + "\n\n" + body + digits + COOP
    # владельцу — то же (полные данные не дублируем отдельно)
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
