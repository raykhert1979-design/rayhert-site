# -*- coding: utf-8 -*-
"""Консультант студии с памятью диалога.
Вызывается из consult-giga.yml (dispatch от Apps Script).
- Тянет последние сообщения чата (GET /messages) и передаёт их в GigaChat как контекст.
- Ветка «URL:» — аудит: отвечает шаблонно и запускает снапшот.
- Не отвечает на своё же последнее сообщение (анти-зацикливание).
"""
import os, json, urllib.request, urllib.parse, uuid, ssl, time

def ctx_no_verify():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

giga_secret = os.environ["GIGA_SECRET"]
max_token = os.environ["CONSULT_MAX_TOKEN"]
chat_id = os.environ["CHAT_ID"]
text = os.environ["TEXT"]
SELF = "569290303"  # user_id бота «Консультант студии»

KB = """СТУДИЯ АРТЁМА РАЙХЕРТА: автоматизация каналов и продуктов.

УСЛУГИ И ЦЕНЫ (ориентиры, детали в смете):
1) Ведение каналов: контент-план, публикации, ответы на комментарии, отчёт. 10-25 тыс/мес за площадку; связка 8 площадок 50-90 тыс/мес.
2) Стратегия: аудит 8-15 тыс; стратегия 30-60 тыс; с сопровождением 3 мес 90-150 тыс.
3) Автоматизация: конвейер публикаций, сбор комментариев, отчёты. Сценарий от 10 тыс; конвейер 15-40 тыс; поддержка 5-12 тыс/мес.
4) Сайты: лендинг 60-120 тыс; корпоративный 150-500 тыс; каталог/портал от 500 тыс; веб-сервис от 800 тыс.
5) Документы, презентации, аналитика. 6) Android приложения (RuStore): простое 2-4 недели, MVP от 1,5 мес.
СРОКИ: презентация/документ 2-5 дней; ведение канала старт 3-5 дней; автоматизация 1-3 недели. Смета за рабочий день.
КЕЙСЫ: радио «Деревенский шансон» в RuStore; Дзен «Митрофановна» 58 тыс подписчиков; VK группа; YouTube «Ансамбль Митрофановна» 55,9 тыс, 11,4 млн просмотров.
ПРАВИЛА: отвечай от «мы», коротко, тепло, по делу. Цены — вилки из базы, точная сумма в смете. Предлагай бесплатный аудит канала за 15 минут. Не выдумывай цены, сроки, факты. iOS не делаем, фокус Android/RuStore."""

def get_history(limit=12):
    """Последние сообщения диалога: [(роль, текст)], роль 'user'/'assistant'."""
    req = urllib.request.Request(
        "https://platform-api2.max.ru/messages?chat_id=%s&limit=%d" % (chat_id, limit),
        headers={"Authorization": max_token})
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx_no_verify()) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print("history ERR:", str(e)[:150])
        return []
    out = []
    for m in d.get("messages", []):
        t = (m.get("body") or {}).get("text") or ""
        if not t:
            continue
        s = m.get("sender") or {}     # отправитель сообщения
        uid = str(s.get("user_id") or "")
        role = "assistant" if uid == SELF else "user"
        out.append((role, t))
    out.reverse()  # от старых к новым
    return out

def giga_answer(user_text, history):
    data = urllib.parse.urlencode({"scope": "GIGACHAT_API_PERS"}).encode()
    req = urllib.request.Request("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        data=data, method="POST",
        headers={"Authorization": "Basic " + giga_secret,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json",
                 "RqUID": str(uuid.uuid4()),
                 "User-Agent": "rayhert-consult/1.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx_no_verify()) as r:
        tok = json.loads(r.read().decode())["access_token"]
    msgs = [{"role": "system", "content": "Ты — консультант студии Артёма Райхерта. Отвечай по-русски живым языком, от «мы», кратко, тепло, по делу. База знаний: " + KB}]
    # контекст диалога (до текущего сообщения)
    for role, t in history:
        if t.strip() == user_text.strip():
            continue
        msgs.append({"role": role, "content": t[:1500]})
    msgs.append({"role": "user", "content": user_text})
    payload = {"model": "GigaChat-2-Max", "messages": msgs,
               "temperature": 0.6, "max_tokens": 700}
    req2 = urllib.request.Request("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req2, timeout=90, context=ctx_no_verify()) as r:
        d = json.loads(r.read().decode())
        return d["choices"][0]["message"]["content"].strip()

def send_max(msg):
    url3 = "https://platform-api2.max.ru/messages?chat_id=" + urllib.parse.quote(str(chat_id))
    req3 = urllib.request.Request(url3, data=json.dumps({"text": msg}).encode(), method="POST",
        headers={"Authorization": max_token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req3, timeout=30, context=ctx_no_verify()) as r:
        return r.status

history = get_history()
last_role, last_text = (history[-1] if history else ("", ""))

# анти-зацикливание: не отвечаем на своё же сообщение
if last_role == "assistant" and last_text.strip() == text.strip():
    print("похоже на собственное сообщение, пропускаю")
    raise SystemExit(0)

# Ветка аудита: клиент прислал ссылку на канал
if text.strip().startswith("URL:"):
    answer = ("Спасибо! Приняли ссылку на канал — готовим бесплатный аудит за 15 минут. "
              "Пришлём сюда же краткий разбор: что сейчас с каналом и что можно улучшить. "
              "Если удобнее — можем обсудить по телефону, скажите номер.")
else:
    # Согласие на сотрудничество после аудита (был ли аудит в диалоге?)
    was_audit = any("Бесплатный аудит канала" in t for role, t in history if role == "assistant")
    agree = text.strip().lower() in ("да", "да!", "да.", "хочу", "хотим", "согласен", "согласны",
                                     "согласна", "давайте", "давай", "конечно", "готов", "готовы",
                                     "интересно", "да, интересно", "хочу сотрудничать", "хотим сотрудничать")
    if agree and was_audit:
        answer = ("Отлично! Тогда с вами свяжется наш специалист в ближайшее время, чтобы "
                  "продолжить разговор и обсудить, что можно улучшить на канале.\n\n"
                  "Что будет дальше:\n"
                  "1) Поможем получить API вашего канала для более глубокого анализа: "
                  "статистика, аудитория, источники трафика.\n"
                  "2) Расскажем про автоматизацию: регулярные публикации, сбор комментариев, "
                  "отчёты — сколько времени это сэкономит и как ускорит рост.\n\n"
                  "Пожалуйста, оставьте удобный контакт (телефон или почту), и мы вернёмся к вам "
                  "с конкретными шагами.")
    else:
        answer = giga_answer(text, history)

st = send_max(answer)
print("MAX send", st)
print("ANSWER OK" if st == 200 else "ANSWER SEND %s" % st)
