import requests
import cloudscraper
import gzip
import xml.etree.ElementTree as ET
import re
import difflib
import concurrent.futures
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from io import BytesIO

# ========================================================
# 1. KONFIGURASI URL UTAMA
# ========================================================
M3U_URLS = [
    "https://aspaltvpasti.top/xxx/merah.php",
    "https://deccotech.online/tv/tvstream.html", 
    "https://freeiptv2026.tsender57.workers.dev", 
    "https://raw.githubusercontent.com/tvplaylist/T2/refs/heads/main/tv1",
    "http://sauridigital.my.id/kerbaunakal/2026TVGNS.html", 
    "https://raw.githubusercontent.com/mimipipi22/lalajo/refs/heads/main/playlist25",
    "https://semar25.short.gy",
    "https://bit.ly/TVKITKAT",
    "https://liveevent.iptvbonekoe.workers.dev",
    "https://bwifi.my.id/lokal",
    "https://bit.ly/KPL203"
]
EPG_URLS = [
    "https://bwifi.my.id/epg.xml",
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS.xml.gz",
    "https://epg.pw/xmltv/epg.xml.gz"
]

MAP_URL = "https://raw.githubusercontent.com/karepech/bakul/refs/heads/main/map.txt"
OUTPUT_FILE = "playlist_termapping.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

GLOBAL_SEEN_STREAM_URLS = set()
COMPILED_MAPPING = []

# ========================================================
# 2. MESIN MAPPING & PENERJEMAH BAHASA
# ========================================================
def load_mapping():
    try:
        r = requests.get(MAP_URL, timeout=30).text
        MAPPING_DICT = {}
        for line in r.splitlines():
            line = line.split('#')[0].strip() 
            if not line or line.startswith('['): continue
            if '=' in line:
                official, aliases = line.split('=', 1)
                official = official.strip().lower()
                for alias in aliases.split(','):
                    alias = alias.strip().lower()
                    if alias: MAPPING_DICT[alias] = official
        sorted_map = dict(sorted(MAPPING_DICT.items(), key=lambda x: len(x[0]), reverse=True))
        for alias, official in sorted_map.items():
            COMPILED_MAPPING.append((re.compile(r'\b' + re.escape(alias) + r'\b'), official))
    except: pass

@lru_cache(maxsize=10000) 
def rumus_samakan_teks(teks):
    if not teks: return ""
    res = teks.lower()
    for pattern, official in COMPILED_MAPPING:
        res = pattern.sub(official, res)
    res = re.sub(r'\b(sports|sport|tv|hd|fhd|sd|4k|ch|channel|network)\b', '', res)
    res = re.sub(r'\[.*?\]|\(.*?\)', '', res)
    res = re.sub(r'[^a-z0-9]', '', res)
    return res

@lru_cache(maxsize=5000)
def terjemahkan_bahasa(title):
    t = title
    kamus_asing = {
        "fudbal": "Sepakbola", "nogomet": "Sepakbola", "odbojka": "Voli", "košarka": "Basket",
        "italijanska liga": "Liga Italia", "engleska liga": "Liga Inggris", 
        "španska liga": "Liga Spanyol", "francuska liga": "Liga Prancis",
        "nemačka liga": "Liga Jerman", "njemačka liga": "Liga Jerman",
        "liga prvaka": "Liga Champions", "evropska liga": "Liga Europa",
        "zlatna liga": "Liga Emas", "rukomet": "Bola Tangan", "hokej": "Hoki", "tenis": "Tenis"
    }
    for asing, indo in kamus_asing.items():
        t = re.sub(r'(?i)\b' + asing + r'\b', indo, t)
    return t

# FILTERING RULES
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\blive\b|\blangsung\b)')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

@lru_cache(maxsize=5000)
def is_allowed_sport(title, durasi_menit):
    t = title.lower()
    # 1. Buang non-latin (Aksara Rusia/Cina) atau durasi terlalu pendek
    if re.search(r'[А-Яа-яЁё\u4e00-\u9fff]', t) or durasi_menit <= 30: return False
    
    # 2. Buang kata-kata non-olahraga (Bursa, Berita, Film, dll)
    sampah = ["replay", "delay", "classic", "magazine", "review", "history", "news", "movie", "drama", "kids", "talkshow", "gossip"]
    if any(k in t for k in sampah): return False
    
    # 3. Wajib ada kata kunci olahraga
    olahraga = ['vs', 'liga', 'league', 'cup', 'grand prix', 'motogp', 'f1', 'nba', 'tennis', 'bwf', 'badminton', 'afc', 'ufc', 'boxeo', 'tinju']
    return any(k in t for k in olahraga)

def parse_time(ts, offset=0):
    try:
        dt = datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
        return dt + timedelta(hours=(7 - offset))
    except: return None

def fetch_url(url, is_epg):
    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        resp = scraper.get(url, timeout=45)
        if is_epg:
            content = gzip.GzipFile(fileobj=BytesIO(resp.content)).read() if url.endswith('.gz') else resp.content
            return url, content, True
        return url, resp.text, False
    except: return url, None, is_epg

# ========================================================
# 3. EKSEKUSI UTAMA (FOKUS SPORTS)
# ========================================================
load_mapping()
now_wib = datetime.utcnow() + timedelta(hours=7)
limit_date = now_wib + timedelta(hours=24)

epg_dict, kamus_rumus_epg, jadwal_dict = {}, {}, {}

with concurrent.futures.ThreadPoolExecutor(max_workers=15) as exec:
    futures = [exec.submit(fetch_url, u, True) for u in EPG_URLS] + [exec.submit(fetch_url, u, False) for u in M3U_URLS]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

for url, content, is_e in results:
    if not content or not is_e: continue
    offset = 7 if any(x in url for x in ["AqFad2811", "indonesia.xml", "bwifi.my.id"]) else 0
    try:
        context = ET.iterparse(BytesIO(content), events=('end',))
        for _, elem in context:
            if elem.tag == 'channel':
                id_asli = elem.get('id')
                nama = elem.findtext('display-name') or id_asli
                epg_dict[id_asli] = nama
                kamus_rumus_epg[rumus_samakan_teks(id_asli)] = id_asli
                kamus_rumus_epg[rumus_samakan_teks(nama)] = id_asli
            elif elem.tag == 'programme':
                cid = elem.get('channel')
                if cid in epg_dict:
                    title = elem.findtext("title") or ""
                    st, sp = parse_time(elem.get("start"), offset), parse_time(elem.get("stop"), offset)
                    dur = (sp - st).total_seconds() / 60 if st and sp else 0
                    # FILTER HANYA SPORTS
                    if st and sp and sp > now_wib and st < limit_date and is_allowed_sport(title, dur):
                        if cid not in jadwal_dict: jadwal_dict[cid] = []
                        jadwal_dict[cid].append({"title": terjemahkan_bahasa(title), "start": st, "stop": sp, "live": (st - timedelta(minutes=5)) <= now_wib < sp, "logo": elem.find("icon").get("src") if elem.find("icon") is not None else ""})
            elem.clear()
    except: continue

keranjang_match = {}
for url, content, is_e in results:
    if not content or is_e: continue
    lines = content.splitlines()
    block = []
    for ln in lines:
        ln = ln.strip()
        if ln.startswith("#"): block.append(ln)
        elif block:
            inf = next((b for b in block if b.upper().startswith("#EXTINF")), "")
            extra = [b for b in block if not b.upper().startswith("#EXTINF") and not b.upper().startswith("#EXTGRP")]
            block = []
            if not inf or ln in GLOBAL_SEEN_STREAM_URLS: continue
            m3u_name = inf.split(",", 1)[1].strip()
            
            # 1. Jika ini Event Berjam (Otomatis Sports)
            ev_m = REGEX_EVENT.search(m3u_name)
            if ev_m and is_allowed_sport(ev_m.group(3), 60):
                ev_st = now_wib.replace(hour=int(ev_m.group(1)), minute=int(ev_m.group(2)), second=0)
                if ev_st < now_wib - timedelta(hours=4): ev_st += timedelta(days=1)
                ev_sp = ev_st + timedelta(hours=2)
                if ev_sp > now_wib:
                    is_l = (ev_st - timedelta(minutes=5)) <= now_wib < ev_sp
                    k = f"{rumus_samakan_teks(ev_m.group(3))}_{ev_st.timestamp()}"
                    if k not in keranjang_match: keranjang_match[k] = {"is_live": is_l, "sort": ev_st.timestamp(), "links": []}
                    jam = f"{ev_st.strftime('%H:%M')}-{ev_sp.strftime('%H:%M')}"
                    title = terjemahkan_bahasa(ev_m.group(3))
                    tag = "🔴 SEDANG TAYANG" if is_l else "📅 JADWAL HARI INI"
                    keranjang_match[k]["links"].append({"prio": 0, "data": [f'#EXTINF:-1 group-title="{tag}", 🏆 {jam} WIB - {title}'] + extra + [ln]})
                continue

            # 2. Jika ini Channel Regular, cari di EPG
            teks_m3u = rumus_samakan_teks(m3u_name)
            id_epg = kamus_rumus_epg.get(teks_m3u)
            if not id_epg:
                mirip = difflib.get_close_matches(teks_m3u, list(kamus_rumus_epg.keys()), n=1, cutoff=0.75)
                id_epg = kamus_rumus_epg[mirip[0]] if mirip else None

            if id_epg and id_epg in jadwal_dict:
                for ev in jadwal_dict[id_epg]:
                    k = f"{rumus_samakan_teks(ev['title'])}_{ev['start'].timestamp()}"
                    if k not in keranjang_match: keranjang_match[k] = {"is_live": ev['live'], "sort": ev['start'].timestamp(), "links": []}
                    jam = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')}"
                    tag = "🔴 SEDANG TAYANG" if ev['live'] else "📅 JADWAL HARI INI"
                    keranjang_match[k]["links"].append({"prio": 1, "data": [f'#EXTINF:-1 group-title="{tag}" tvg-id="{id_epg}" tvg-logo="{ev["logo"]}", 🏆 {jam}
