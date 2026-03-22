import requests
import cloudscraper
import gzip
import xml.etree.ElementTree as ET
import re
import difflib
import os
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
    "https://raw.githubusercontent.com/AqFad2811/epg/main/indonesia.xml",
    "https://epgshare01.online/epgshare01/epg_ripper_ID1.xml.gz",         
    "https://epgshare01.online/epgshare01/epg_ripper_MY1.xml.gz",         
    "https://epgshare01.online/epgshare01/epg_ripper_ALL_SPORTS1.xml.gz", 
    "https://epg.pw/xmltv/epg.xml.gz"                                     
]

OUTPUT_FILE = "playlist_termapping.m3u"
LINK_STANDBY = "https://bwifi.my.id/live.mp4" 
LINK_UPCOMING = "https://bwifi.my.id/5menit.mp4" 

GLOBAL_SEEN_STREAM_URLS = set()

# ========================================================
# 2. MESIN MAPPING & TRANSLATE BAHASA INDONESIA
# ========================================================
KAMUS_INDO = {
    r'\b(?:nogomet|fudbal|piłka nożna|soccer|football|futebol)\b': 'Sepak Bola',
    r'\b(?:košarka|basketball|koszykówka|básquetbol)\b': 'Bola Basket',
    r'\b(?:odbojka|volleyball|vôlei|siatkówka)\b': 'Bola Voli',
    r'\b(?:rukomet|handball|piłka ręczna)\b': 'Bola Tangan',
    r'\b(?:tenis|tennis)\b': 'Tenis',
    r'\b(?:boks|boxing|boxeo)\b': 'Tinju',
    r'\b(?:hokej|hockey)\b': 'Hoki',
    r'\b(?:atletika|athletics)\b': 'Atletik',
    r'\b(?:plivanje|swimming)\b': 'Renang',
    r'\b(?:biciklizam|cycling)\b': 'Balap Sedepa',
    r'\b(?:moto trke|motorsport|motor racing)\b': 'Balap Motor',
    r'\b(?:engleska liga|premier league|premijer liga|ingleska liga)\b': 'Liga Inggris',
    r'\b(?:španska liga|la liga|španjolska liga)\b': 'Liga Spanyol',
    r'\b(?:italijanska liga|serie a|talijanska liga)\b': 'Liga Italia',
    r'\b(?:francuska liga|ligue 1|francuske liga)\b': 'Liga Prancis',
    r'\b(?:nemačka liga|bundesliga|njemačka liga)\b': 'Liga Jerman',
    r'\b(?:liga šampiona|liga prvaka|champions league)\b': 'Liga Champions',
    r'\b(?:evropa liga|europa league|liga evrope|europska liga)\b': 'Liga Europa',
    r'\b(?:finale|final)\b': 'Final',
    r'\b(?:polufinale|semi-final|semifinal)\b': 'Semifinal',
    r'\b(?:žene|women|mulheres|kobiety|\(w\))\b': 'Wanita',
    r'\b(?:muškarci|men|homens|mężczyźni|\(m\))\b': 'Pria',
}

@lru_cache(maxsize=5000)
def translate_ke_indo(teks):
    if not teks: return ""
    teks_terjemahan = teks
    for pola, pengganti in KAMUS_INDO.items():
        teks_terjemahan = re.sub(pola, pengganti, teks_terjemahan, flags=re.IGNORECASE)
    return teks_terjemahan

@lru_cache(maxsize=10000)
def rumus_samakan_teks(teks):
    if not teks: return ""
    teks = teks.lower()
    teks = re.sub(r'\b(sports|sport|tv|hd|fhd|sd|4k|ch|channel|network|1080p|720p|50fps|60fps|hevc|raw)\b', '', teks)
    teks = re.sub(r'\[.*?\]|\(.*?\)', '', teks)
    teks = re.sub(r'[^a-z0-9]', '', teks)
    return teks

# Memuat kamus manual jika ada
kamus_manual = {}
if os.path.exists("kamus_mapping.txt"):
    with open("kamus_mapping.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                parts = line.strip().split("=")
                if len(parts) == 3:
                    kamus_manual[parts[1].strip().lower()] = {"epg": parts[0].strip(), "nama": parts[2].strip()}

CACHE_FUZZY = {}
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_VS = re.compile(r'\b(vs|v)\b')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)
REGEX_VS_EVENT = re.compile(r'(?i)\bvs\b')

@lru_cache(maxsize=2000)
def is_channel_olahraga(nama):
    kws = ['sport', 'bein', 'spotv', 'espn', 'astro', 'arena', 'ssc', 'alkass', 'premier', 'champions', 'fox', 'tsn', 'supersport', 'skysports', 'optus', 'sky', 'mola', 'vidio', 'soccer', 'football', 'nba', 'nfl', 'tennis', 'golf', 'moto', 'f1']
    return any(k in nama.lower() for k in kws)

@lru_cache(maxsize=5000)
def bersihkan_judul_event(title):
    bersih = REGEX_LIVE.sub('', title)
    bersih = re.sub(r'^[\-\:\,\|]\s*', '', re.sub(r'\s+', ' ', bersih)).strip()
    return translate_ke_indo(bersih)

def generate_event_key(title, timestamp):
    tc = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', title)
    tc = re.sub(r'\d+\]?$', '', tc.strip())
    return f"{REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', tc.lower()))}_{timestamp}"

@lru_cache(maxsize=2000)
def get_vip_score(ch_name):
    n = ch_name.lower()
    if any(k in n for k in ['bein', 'spotv', 'sportstars', 'soccer channel', 'champions tv', 'rcti sports', 'inews sports', 'mnc sports']): return 0
    return 1

@lru_cache(maxsize=5000)
def get_flag(m3u_name):
    n = m3u_name.lower()
    flags = [(' us', "🇺🇸"), (' sg', "🇸🇬"), (' my', "🇲🇾"), (' en', "🇬🇧"), (' th', "🇹🇭"), (' hk', "🇭🇰"), (' au', "🇦🇺"), (' saudi', "🇸🇦"), (' za', "🇿🇦"), (' id', "🇮🇩")]
    for k, f in flags:
        if k in n: return f
    return "📺"

@lru_cache(maxsize=5000)
def get_region_ktp(name, epg_id=""):
    n = (name + " " + epg_id).lower()
    regions = [("US",['.us','usa']), ("AU",['.au','optus']), ("UK",['.uk','sky']), ("ARAB",['arab','ssc']), ("MY",['.my','malaysia']), ("TH",['.th','true']), ("SG",['.sg','hub']), ("ZA",['.za','supersport']), ("HK",['.hk','hong']), ("PH",['.ph']), ("ID",['.id','indo'])]
    for reg, kws in regions:
        if any(x in n for x in kws): return reg
    return "UNKNOWN"

@lru_cache(maxsize=5000)
def is_allowed_sport(title, durasi_menit):
    t = title.lower()
    if re.search(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', t) or durasi_menit <= 30: return False
    haram_kata = ["replay", "delay", "classic", "rewind", "highlights", "best of", "magazine", "studio", "news", "religi", "quran", "masterchef", "cgtn", "arirang", "cnn", "history", "retro", "memories", "wwe", "ufc", "mma", "boxing", "fight", "esport", "smackdown", "one championship", "snimka", "repriza"]
    if any(k in t for k in haram_kata): return False
    target_kws = ['vs', 'liga', 'league', 'cup', 'badminton', 'bwf', 'motogp', 'f1', 'wsbk', 'nba', 'nfl', 'mls', 'basket', 'voli', 'tennis', 'tenis', 'rugby', 'afc', 'premier', 'serie a', 'bundesliga', 'la liga', 'nogomet', 'fudbal']
    return any(k in t for k in target_kws)

@lru_cache(maxsize=5000)
def is_valid_time_continent(w, title, ch_name):
    t = (title + " " + ch_name).lower()
    if any(k in t for k in [' uk', 'sky', 'la liga', 'serie a', 'bundesliga', 'epl']):
        if 5.1 <= w <= 17.9: return False
    if any(k in t for k in ['us ', 'usa', 'america', 'nba', 'nfl', 'copa']):
        if w > 14.0 or w < 5.0: return False
    if any(k in t for k in ['my', 'sg', 'th ', 'id ', 'arab', 'afc']):
        if 1.1 <= w <= 10.9: return False
    return True

def parse_time(ts):
    if not ts: return None
    try:
        match = re.search(r'^(\d{14})\s*([+-]\d{4})?', ts.strip())
        if not match: return None
        dt = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        tz_str = match.group(2)
        if tz_str:
            sign = 1 if tz_str[0] == '+' else -1
            offset = timedelta(hours=int(tz_str[1:3]), minutes=int(tz_str[3:5]))
            return dt - (sign * offset) + timedelta(hours=7)
        return dt + timedelta(hours=7)
    except: return None

def fetch_url(url, is_epg):
    try:
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        resp = scraper.get(url, timeout=45)
        if is_epg:
            content = gzip.GzipFile(fileobj=BytesIO(resp.content)).read() if url.endswith('.gz') else resp.content
            return url, content, True
        return url, resp.text, False
    except Exception as e:
        return url, None, is_epg

# ========================================================
# 3. EKSEKUSI UTAMA
# ========================================================
now_wib = datetime.utcnow() + timedelta(hours=7)
limit_date = (now_wib + timedelta(days=1)).replace(hour=3, minute=0, second=0)

epg_dict = {} 
kamus_rumus_epg = {}
jadwal_dict = {} 

with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
    futures = [executor.submit(fetch_url, url, True) for url in EPG_URLS]
    futures += [executor.submit(fetch_url, url, False) for url in M3U_URLS]
    
    epg_res = {}
    m3u_res = {}
    for future in concurrent.futures.as_completed(futures):
        u, c, is_e = future.result()
        if c:
            if is_e: epg_res[u] = c
            else: m3u_res[u] = c

for url, content in epg_res.items():
    try:
        root = ET.fromstring(content)
        for ch in root.findall('channel'):
            id_asli = ch.get('id')
            nama_epg = ch.findtext('display-name') or id_asli
            logo_ch = ch.find('icon').get('src') if ch.find('icon') is not None else ""
            if id_asli:
                epg_dict[id_asli] = {"nama": nama_epg, "logo": logo_ch}
                kamus_rumus_epg[rumus_samakan_teks(id_asli)] = id_asli
                kamus_rumus_epg[rumus_samakan_teks(nama_epg)] = id_asli
        for pg in root.findall('programme'):
            cid = pg.get('channel')
            if cid not in epg_dict: continue
            st, sp = parse_time(pg.get("start")), parse_time(pg.get("stop"))
            title = pg.findtext("title") or ""
            if not st or not sp or sp <= now_wib or st >= limit_date: continue 
            durasi = (sp - st).total_seconds() / 60
            if is_allowed_sport(title, durasi) and is_valid_time_continent(st.hour + st.minute/60, title, epg_dict[cid]["nama"]):
                if cid not in jadwal_dict: jadwal_dict[cid] = []
                jadwal_dict[cid].append({"title": bersihkan_judul_event(title), "start": st, "stop": sp, "live": (st - timedelta(minutes=5)) <= now_wib < sp, "logo": pg.find("icon").get("src") if pg.find("icon") is not None else ""})
    except: continue

daftar_teks_epg_dirumus = list(kamus_rumus_epg.keys())
keranjang_match = {}
audit_m3u = {}

for url, content in m3u_res.items():
    audit_m3u[url] = {"ada": [], "tidak": []}
    lines = content.splitlines()
    block = []
    for ln in lines:
        ln = ln.strip()
        if not ln or "EXTM3U" in ln.upper(): continue
        if ln.startswith("#"): block.append(ln)
        else:
            if not block: continue
            raw_extinf = next((b for b in block if b.upper().startswith("#EXTINF")), "")
            extra_tags = [b for b in block if not b.upper().startswith("#EXTINF") and not b.upper().startswith("#EXTGRP")]
            block = []
            if ln in GLOBAL_SEEN_STREAM_URLS: continue
            GLOBAL_SEEN_STREAM_URLS.add(ln)
            m3u_name = raw_extinf.split(",", 1)[1].strip() if "," in raw_extinf else ""
            skor_vip = get_vip_score(m3u_name)
            
            # Deteksi Event Berjadwal atau Live Dadakan
            ev_m = REGEX_EVENT.search(m3u_name)
            if ev_m or (REGEX_VS_EVENT.search(m3u_name) and not is_channel_olahraga(m3u_name)):
                ev_title = translate_ke_indo(re.sub(r'\[.*?\]|\(.*?\)', '', ev_m.group(3) if ev_m else m3u_name).strip())
                ev_start = now_wib.replace(hour=int(ev_m.group(1)), minute=int(ev_m.group(2))) if ev_m else now_wib - timedelta(minutes=5)
                if ev_start < now_wib - timedelta(hours=4): ev_start += timedelta(days=1)
                ev_stop = ev_start + timedelta(hours=2)
                is_live = (ev_start - timedelta(minutes=5)) <= now_wib < ev_stop
                key = generate_event_key(ev_title, ev_start.timestamp())
                if key not in keranjang_match: keranjang_match[key] = {"is_live": is_live, "sort": ev_start.timestamp(), "vip": skor_vip, "links": []}
                jam = f"{ev_start.strftime('%H:%M')}-{ev_stop.strftime('%H:%M')}"
                if is_live:
                    inf = f'#EXTINF:-1 group-title="🔴 SEDANG TAYANG", {get_flag(ev_title)} 🔴 {jam} WIB - {ev_title}'
                    keranjang_match[key]["links"].append({"prio": 0, "data": [inf] + extra_tags + [ln]})
                else:
                    inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI", {get_flag(ev_title)} ⏳ {jam} WIB - {ev_title}'
                    keranjang_match[key]["links"].append({"prio": 0, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
                audit_m3u[url]["ada"].append(f"{m3u_name} ➡️ [EVENT]")
                continue

            # Mapping EPG Fuzzy & Exact
            teks_m3u = rumus_samakan_teks(m3u_name)
            id_epg = kamus_rumus_epg.get(teks_m3u)
            if not id_epg:
                mirip = difflib.get_close_matches(teks_m3u, daftar_teks_epg_dirumus, n=1, cutoff=0.75)
                if mirip: id_epg = kamus_rumus_epg[mirip[0]]
            
            if id_epg and id_epg in jadwal_dict:
                for ev in jadwal_dict[id_epg]:
                    key = generate_event_key(ev['title'], ev['start'].timestamp())
                    if key not in keranjang_match: keranjang_match[key] = {"is_live": ev['live'], "sort": ev['start'].timestamp(), "vip": skor_vip, "links": []}
                    jam = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')}"
                    if ev["live"]:
                        inf = f'#EXTINF:-1 group-title="🔴 SEDANG TAYANG" tvg-id="{id_epg}", {get_flag(m3u_name)} 🔴 {jam} WIB - {ev["title"]} [{m3u_name}]'
                        keranjang_match[key]["links"].append({"prio": 1, "data": [inf] + extra_tags + [ln]})
                    else:
                        inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI", {get_flag(m3u_name)} ⏳ {jam} WIB - {ev["title"]}'
                        keranjang_match[key]["links"].append({"prio": 1, "data": [inf, f"{LINK_UPCOMING}?m={key}"]})
                audit_m3u[url]["ada"].append(f"{m3u_name} ➡️ [SINKRON]")
            else:
                if is_channel_olahraga(m3u_name): audit_m3u[url]["tidak"].append(f"{m3u_name} ➡️ [KOSONG]")

# Render M3U
hasil = []
for key, m in keranjang_match.items():
    uniq = { l["data"][-1]: l for l in m["links"] }.values()
    sorted_l = sorted(uniq, key=lambda x: x["prio"])
    for l in sorted_l[:(2 if m["is_live"] else 1)]:
        hasil.append({"order": 0 if m["is_live"] else 1, "sort": m["sort"], "vip": m["vip"], "data": l["data"]})
hasil.sort(key=lambda x: (x["order"], x["sort"], x["vip"]))

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(f'#EXTM3U name="🔴 BAKUL WIFI SPORTS"\n')
    if not hasil: f.write(f'#EXTINF:-1 group-title="INFO", BELUM ADA PERTANDINGAN\n{LINK_STANDBY}\n')
    else:
        for it in hasil: f.write("\n".join(it["data"]) + "\n")

print(f"SELESAI! File {OUTPUT_FILE} telah diperbarui secara otomatis.")
