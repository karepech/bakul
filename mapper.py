import requests
import cloudscraper
import gzip
import xml.etree.ElementTree as ET
import re
import difflib
import concurrent.futures
from functools import lru_cache
from datetime import datetime, timedelta
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
    "https://raw.githubusercontent.com/dbghelp/StarHub-TV-EPG/refs/heads/main/starhub.xml"
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
            if not line or '=' not in line: continue
            off, ali = line.split('=', 1)
            off = off.strip().lower()
            for a in ali.split(','):
                a = a.strip().lower()
                if a: MAPPING_DICT[a] = off
        sorted_map = dict(sorted(MAPPING_DICT.items(), key=lambda x: len(x[0]), reverse=True))
        for a, o in sorted_map.items():
            COMPILED_MAPPING.append((re.compile(r'\b' + re.escape(a) + r'\b'), o))
    except: print("Gagal memuat map.txt")

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
    kamus = {
        "fudbal": "Sepakbola", "nogomet": "Sepakbola", "odbojka": "Voli", "košarka": "Basket",
        "liga prvaka": "Liga Champions", "rukomet": "Bola Tangan", "tenis": "Tenis"
    }
    for a, i in kamus.items():
        t = re.sub(r'(?i)\b' + a + r'\b', i, t)
    return t

REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

# --- FILTER KETAT CHANNEL OLAHRAGA ---
@lru_cache(maxsize=5000)
def is_target_sport_channel(name):
    n = name.lower()
    # 1. Daftar Haram Channel (Sub-channel hiburan dari provider besar)
    haram_ch = ['movie', 'cinema', 'film', 'drama', 'kids', 'news', 'music', 'entertainment', 'berita', 'kabar', 'gossip', 'sinetron', 'ria', 'warna', 'awani', 'komedi', 'tv nasional']
    if any(x in n for x in haram_ch): 
        return False
    # 2. Daftar Wajib Olahraga
    target = ['sport', 'bein', 'spotv', 'liga', 'league', 'champions', 'premier', 'arena', 'supersport', 'ssc', 'rcti', 'inews', 'mola', 'tsn', 'espn', 'fox', 'optus', 'sky', 'euro', 'vidio']
    return any(t in n for t in target)

# --- FILTER KETAT ACARA OLAHRAGA ---
@lru_cache(maxsize=5000)
def is_allowed_sport(title, durasi_menit):
    t = title.lower()
    if durasi_menit <= 30: return False
    
    # 1. Daftar Haram Acara (Tayangan ulang & Non-Olahraga)
    haram_acara = [
        "replay", "delay", "classic", "rewind", "highlights", "review", "preview", 
        "news", "berita", "kabar", "gossip", "talkshow", "studio", "magazine", 
        "sorotan", "kilas", "jurnal", "obrolan", "podcast", "movie", "bioskop", 
        "cinema", "film", "sinetron", "ftv", "dangdut", "religi", "quran", "kids", 
        "cartoon", "spongebob", "re-run", "rerun", "recorded", "history", "retro", 
        "tunda", "ulangan", "pemanasan", "warm up", "build-up", "post-match"
    ]
    if any(k in t for k in haram_acara): 
        return False
        
    # 2. Syarat Wajib Olahraga (Harus ada minimal satu kata ini)
    wajib_olahraga = [
        " vs ", " v ", "motogp", " gp ", "f1", "formula", "wsbk", "nba", "nfl", 
        "wwe", "ufc", "wimbledon", "bwf", "badminton", "tennis", "tenis", 
        "voli", "volley", "basket", "athletics", "golf", "snooker", "darts", 
        "mma", "boxing", "liga", "league", "cup", "copa", "championship", "match", "race"
    ]
    return any(k in t for k in wajib_olahraga)

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
# 3. EKSEKUSI
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
                if is_target_sport_channel(nama) or is_target_sport_channel(id_asli):
                    epg_dict[id_asli] = nama
                    kamus_rumus_epg[rumus_samakan_teks(id_asli)] = id_asli
                    kamus_rumus_epg[rumus_samakan_teks(nama)] = id_asli
            elif elem.tag == 'programme':
                cid = elem.get('channel')
                if cid in epg_dict:
                    title = elem.findtext("title") or ""
                    st, sp = parse_time(elem.get("start"), offset), parse_time(elem.get("stop"), offset)
                    dur = (sp - st).total_seconds() / 60 if st and sp else 0
                    if st and sp and sp > now_wib and st < limit_date and is_allowed_sport(title, dur):
                        if cid not in jadwal_dict: jadwal_dict[cid] = []
                        jadwal_dict[cid].append({
                            "title": terjemahkan_bahasa(title), "start": st, "stop": sp, 
                            "live": (st - timedelta(minutes=5)) <= now_wib < sp,
                            "logo": elem.find("icon").get("src") if elem.find("icon") is not None else ""
                        })
            elem.clear()
    except: continue

daftar_epg_rumus = list(kamus_rumus_epg.keys())
keranjang_match = {}

for url, content, is_e in results:
    if not content or is_e: continue
    lines = content.splitlines()
    block = []
    for ln in lines:
        ln = ln.strip()
        if not ln or "EXTM3U" in ln.upper(): continue
        if ln.startswith("#"): block.append(ln)
        else:
            if not block: continue
            raw_inf = next((b for b in block if b.upper().startswith("#EXTINF")), "")
            extra_tags = [b for b in block if not b.upper().startswith("#EXTINF") and not b.upper().startswith("#EXTGRP")]
            block = []
            if not raw_inf or ln in GLOBAL_SEEN_STREAM_URLS: continue
            
            m3u_name = raw_inf.split(",", 1)[1].strip() if "," in raw_inf else ""
            ev_m = REGEX_EVENT.search(m3u_name)
            is_sport_channel = is_target_sport_channel(m3u_name)
            
            if not ev_m and not is_sport_channel: continue
            
            GLOBAL_SEEN_STREAM_URLS.add(ln)
            orig_logo = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_inf).group(1) if "tvg-logo" in raw_inf.lower() else ""

            # Event Berjadwal dari nama channel
            if ev_m:
                ev_title_raw = re.sub(r'\[.*?\]|\(.*?\)', '', ev_m.group(3)).strip()
                if not is_allowed_sport(ev_title_raw, 60): continue # Pastikan judul event di channel juga lolos filter
                
                ev_st = now_wib.replace(hour=int(ev_m.group(1)), minute=int(ev_m.group(2)), second=0)
                if ev_st < now_wib - timedelta(hours=4): ev_st += timedelta(days=1)
                ev_sp = ev_st + timedelta(hours=2)
                if ev_sp > now_wib:
                    is_l = (ev_st - timedelta(minutes=5)) <= now_wib < ev_sp
                    k = f"{ev_title_raw}_{ev_st.timestamp()}"
                    if k not in keranjang_match: keranjang_match[k] = {"is_live": is_l, "sort": ev_st.timestamp(), "links": []}
                    jam = f"{ev_st.strftime('%H:%M')}-{ev_sp.strftime('%H:%M')}"
                    group = "🔴 SEDANG TAYANG" if is_l else "📅 JADWAL HARI INI"
                    # NAMA CHANNEL M3U DITAMBAHKAN DI SINI
                    inf = f'#EXTINF:-1 group-title="{group}" tvg-logo="{orig_logo}", 🏆 {jam} WIB - {terjemahkan_bahasa(ev_title_raw)} [{m3u_name}]'
                    keranjang_match[k]["links"].append({"prio": 0, "data": [inf] + (extra_tags if is_l else []) + [ln if is_l else f"{LINK_UPCOMING}?m={k}"]})
                continue

            # Mapping EPG ke Channel Olahraga
            id_epg = kamus_rumus_epg.get(rumus_samakan_teks(m3u_name))
            if not id_epg:
                mirip = difflib.get_close_matches(rumus_samakan_teks(m3u_name), daftar_epg_rumus, n=1, cutoff=0.80)
                id_epg = kamus_rumus_epg[mirip[0]] if mirip else None

            if id_epg and id_epg in jadwal_dict:
                for ev in jadwal_dict[id_epg]:
                    k = f"{ev['title']}_{ev['start'].timestamp()}"
                    if k not in keranjang_match: keranjang_match[k] = {"is_live": ev['live'], "sort": ev['start'].timestamp(), "links": []}
                    jam = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')}"
                    group = "🔴 SEDANG TAYANG" if ev["live"] else "📅 JADWAL HARI INI"
                    # NAMA CHANNEL M3U DITAMBAHKAN DI SINI
                    inf = f'#EXTINF:-1 group-title="{group}" tvg-id="{id_epg}" tvg-logo="{ev["logo"] or orig_logo}", 🏆 {jam} WIB - {ev["title"]} [{m3u_name}]'
                    keranjang_match[k]["links"].append({"prio": 1, "data": [inf] + (extra_tags if ev["live"] else []) + [ln if ev["live"] else f"{LINK_UPCOMING}?m={k}"]})

# Render M3U Final
hasil_m3u = []
for k, v in keranjang_match.items():
    uniq = { l["data"][-1]: l for l in v["links"] }.values()
    sorted_l = sorted(uniq, key=lambda x: x["prio"])
    for l in sorted_l[:(2 if v["is_live"] else 1)]:
        hasil_m3u.append({"order": 0 if v["is_live"] else 1, "sort": v["sort"], "data": l["data"]})
hasil_m3u.sort(key=lambda x: (x["order"], x["sort"]))

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(f'#EXTM3U name="🔴 BAKUL WIFI SPORTS"\n')
    for it in hasil_m3u: f.write("\n".join(it["data"]) + "\n")

print(f"SELESAI! {OUTPUT_FILE} diperbarui. 100% Sports dengan Nama Channel di belakang.")
