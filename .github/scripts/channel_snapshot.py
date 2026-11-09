# -*- coding: utf-8 -*-
"""
Снапшот канала по публичной ссылке (без API и токенов клиента).
Вход: URL канала (YouTube/Rutube/VK/Дзен).
Выход: JSON с публичными метриками, которые видны на странице.

Используется облачным раннером (GitHub Actions) для бесплатного аудита за 15 минут.
Здесь: обычные HTTP-запросы, без Selenium (Selenium оставляем для сложных случаев).
"""
import json, re, sys, datetime, urllib.request, urllib.parse, ssl, html

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

def ctx_ssl():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c

UA_BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

def fetch(url, timeout=30, accept=None, bot=False):
    headers = {"User-Agent": UA_BOT if bot else UA, "Accept-Language": "ru,en;q=0.8"}
    if accept:
        headers["Accept"] = accept
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx_ssl()) as r:
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
        if "charset=windows-1251" in ctype.lower() or "charset=cp1251" in ctype.lower():
            return raw.decode("windows-1251", "replace")
        return raw.decode("utf-8", "replace")

def og_meta(h, prop):
    # VK и другие вставляют атрибуты перед property: <meta data-rh="true" property="og:title" content="...">
    m = re.search(r'<meta[^>]*property="%s"[^>]*content="([^"]*)"' % re.escape(prop), h)
    return clean(m.group(1)) if m else None

def clean(s):
    if not s: return s
    return html.unescape(s).strip()

def detect(url):
    u = url.lower()
    if "youtube.com" in u or "youtu.be" in u: return "youtube"
    if "rutube.ru" in u: return "rutube"
    if "vk.com" in u or "vk.ru" in u or "m.vk.com" in u: return "vk"
    if "dzen.ru" in u: return "dzen"
    if "t.me" in u: return "telegram"
    return "other"

# ---------- RU/YT/Дзен через эмбед/меты ----------
def parse_youtube(url, html_page=""):
    # пробуем страницу канала; на раннере есть yt-dlp, здесь — попытка без него
    data = {"url": url, "platform": "youtube"}
    try:
        if not html_page:
            html_page = fetch(url)
        # заголовок
        m = re.search(r'<title>([^<]*)</title>', html_page)
        if m: data["title_meta"] = clean(m.group(1))
        # og:title / og:description
        for og in ("title", "description", "image"):
            v = og_meta(html_page, "og:" + og)
            if v: data["og_" + og] = v
        # подписчики из мета (частая метка)
        for pat in (r'"subscriberCountText"[^}]*?"content"\s*:\s*"([^"]+)"',
                    r'subscriberCountText[^}]*?"content"\s*:\s*"([^"]+)"'):
            m = re.search(pat, html_page)
            if m:
                data["subscribers"] = clean(m.group(1))
                break
        if "subscribers" not in data:
            m = re.search(r'([\d.,\s]+[КкМм]?)\s+подписчик', html_page)
            if m: data["subscribers"] = m.group(1).strip()
        # количество видео из канала (og:description часто содержит)
        m = re.search(r'([\d.,\s]+)\s+(?:видео|video)', html_page)
        if m: data["video_count_meta"] = m.group(1).strip()
        return data
    except Exception as e:
        data["error"] = str(e)[:150]
        return data

def parse_rutube(url):
    data = {"url": url, "platform": "rutube"}
    try:
        m = re.search(r'rutube\.ru/channel/(\d+)', url)
        channel_id = m.group(1) if m else None
        if not channel_id:
            data["error"] = "no channel id"
            return data
        data["channel_id"] = channel_id
        # HTML-страница канала: название, описание, подписчики
        try:
            h = fetch("https://rutube.ru/channel/%s/" % channel_id)
            name = og_meta(h, "og:title")
            if name: data["name"] = name
            m = re.search(r'<meta name="description" content="([^"]*)"', h)
            if m: data["description"] = clean(m.group(1))[:300]
            # подписчики: цифра рядом со словом "подписчи..."
            for mm in re.finditer(r'([\d.,\s\u00a0]+)\s*подписчи', h):
                v = mm.group(1).strip()
                if v:
                    data["subscribers"] = v
                    break
            m = re.search(r'([\d.,\s\u00a0]+)\s*(?:видео|видеоролик)', h)
            if m: data["video_count"] = m.group(1).strip()
        except Exception as e:
            data["html_err"] = str(e)[:120]
        # Последние видео + сумма просмотров (поле hits) через API
        try:
            api = "https://rutube.ru/api/channel/%s/?format=json&page=1&per_page=20" % channel_id
            j = json.loads(fetch(api, accept="application/json"))
            items = (j.get("results") or []) if isinstance(j, dict) else []
            total_views = 0
            vids = []
            for v in items[:6]:
                vids.append({
                    "title": v.get("title"),
                    "views": v.get("hits"),
                    "published": v.get("created_ts"),
                })
                total_views += (v.get("hits") or 0)
            data["recent_videos"] = vids
            data["page_views_sum"] = total_views
        except Exception as e:
            data["api_video_err"] = str(e)[:120]
    except Exception as e:
        data["error"] = str(e)[:150]
    return data

def parse_vk(url):
    data = {"url": url, "platform": "vk"}
    try:
        # VK для обычных UA отдаёт заглушку «Ваш браузер устарел»; googlebot получает полную страницу,
        # но иногда (второй запрос подряд) отдаёт усечённый вариант без статистики — ретраим до 3 раз.
        data["note"] = "получено через googlebot-UA (VK скрывает данные от обычных браузеров)"
        for attempt in range(3):
            h = fetch(url, accept=None, bot=True)
            name = og_meta(h, "og:title")
            if name: data["name"] = name
            m = re.search(r'<title>([^<]*)</title>', h)
            if m and "name" not in data: data["title_meta"] = clean(m.group(1))
            svod = og_meta(h, "og:description")
            if svod:
                data["summary"] = svod[:600]
            # Статистика: "| 3K подписчика. 2,2K записей." в og:description и <b>3K</b> подписчиков в HTML
            for pat, key in ((r'([\d.,\s]+[КкМм]?)\s+подписчик', "subscribers"),
                             (r'([\d.,\s]+[КкМм]?)\s+фотограф', "photos"),
                             (r'([\d.,\s]+[КкМм]?)\s+запис', "posts_count"),
                             (r'([\d.,\s]+[КкМм]?)\s+обсужден', "discussions")):
                mm = re.search(pat, svod or "")
                if mm and mm.group(1).strip():
                    data[key] = mm.group(1).strip()
            for pat, key in ((r'<b>\s*([\d.,\s]+[КкМм]?)\s*</b>\s*(?:подписчик|участник)', "subscribers"),
                             (r'<b>\s*([\d.,\s]+[КкМм]?)\s*</b>\s*фотограф', "photos"),
                             (r'<b>\s*([\d.,\s]+[КкМм]?)\s*</b>\s*запис', "posts_count"),
                             (r'<b>\s*([\d.,\s]+[КкМм]?)\s*</b>\s*обсужден', "discussions")):
                mm = re.search(pat, h)
                if mm and key not in data:
                    data[key] = mm.group(1).strip()
            if "subscribers" in data or "posts_count" in data:
                break
        return data
    except Exception as e:
        data["error"] = str(e)[:150]
        return data

def parse_dzen(url):
    data = {"url": url, "platform": "dzen"}
    try:
        html_page = fetch(url)
        m = re.search(r'<title>([^<]*)</title>', html_page)
        if m: data["title_meta"] = clean(m.group(1))
        # подписчики: "подписчик" / "подписчиков"
        m = re.search(r'([\d.,\s]+[КкМм]?)\s+подписчик', html_page)
        if m: data["subscribers"] = m.group(1).strip()
        # og:title
        v = og_meta(html_page, "og:title")
        if v: data["og_title"] = v
        # количество публикаций
        m = re.search(r'([\d.,\s]+[КкМм]?)\s+публикац', html_page)
        if m: data["publications"] = m.group(1).strip()
        return data
    except Exception as e:
        data["error"] = str(e)[:150]
        return data

def parse_telegram(url):
    data = {"url": url, "platform": "telegram"}
    try:
        html_page = fetch(url)
        m = re.search(r'<title>([^<]*)</title>', html_page)
        if m: data["title_meta"] = clean(m.group(1))
        # подписчиков в телеграфе видно в data-post / переводе страницы
        m = re.search(r'([\d.,\s]+[КкМм]?)\s+subscriber', html_page)
        if m: data["subscribers"] = m.group(1).strip()
        m = re.search(r'([\d.,\s]+[КкМм]?)\s+подписчик', html_page)
        if m: data["subscribers"] = m.group(1).strip()
        return data
    except Exception as e:
        data["error"] = str(e)[:150]
        return data

def main():
    if len(sys.argv) < 2:
        print("usage: python channel_snapshot.py <url>"); sys.exit(1)
    url = sys.argv[1]
    plat = detect(url)
    if plat == "youtube":
        out = parse_youtube(url)
    elif plat == "rutube":
        out = parse_rutube(url)
    elif plat == "vk":
        out = parse_vk(url)
    elif plat == "dzen":
        out = parse_dzen(url)
    elif plat == "telegram":
        out = parse_telegram(url)
    else:
        out = {"url": url, "platform": "other", "note": "неизвестная площадка"}
    out["fetched_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
