# -*- coding: utf-8 -*-
import os, json, urllib.request, urllib.parse, uuid, ssl

def ctx_no_verify():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

giga_secret = os.environ["GIGA_SECRET"]
max_token = os.environ["CONSULT_MAX_TOKEN"]
chat_id = os.environ["CHAT_ID"]
text = os.environ["TEXT"]

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

def giga_answer(user_text):
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
    payload = {"model": "GigaChat-2-Max", "messages": [
        {"role": "system", "content": "Ты — консультант студии Артёма Райхерта. Отвечай по-русски живым языком, от «мы», кратко, тепло, по делу. База знаний: " + KB},
        {"role": "user", "content": user_text}],
        "temperature": 0.6, "max_tokens": 600}
    req2 = urllib.request.Request("https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req2, timeout=90, context=ctx_no_verify()) as r:
        d = json.loads(r.read().decode())
        return d["choices"][0]["message"]["content"].strip()

answer = giga_answer(text)
url3 = "https://platform-api.max.ru/messages?chat_id=" + urllib.parse.quote(str(chat_id))
req3 = urllib.request.Request(url3, data=json.dumps({"text": answer}).encode(), method="POST",
    headers={"Authorization": max_token, "Content-Type": "application/json"})
with urllib.request.urlopen(req3, timeout=30, context=ctx_no_verify()) as r:
    print("MAX send", r.status)
print("ANSWER OK")
