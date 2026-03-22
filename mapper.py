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
    print("Mendownload kamus mapping...")
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
    except Exception as e:
        print(f"❌ Gagal memuat map.txt: {e}")

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
        "liga prvaka": "Liga Champions", "liga prvakov": "Liga Champions",
        "evropska liga": "Liga Europa", "europska liga": "Liga Europa",
        "zlatna liga": "Liga Emas", "rukomet": "Bola Tangan", "hokej": "Hoki",
        "tenis": "Tenis", "piłka nożna": "Sepakbola"
    }
    for asing, indo in kamus_asing.items():
        t = re.sub(r'(?i)\b' + asing + r'\b', indo, t)
    t = re.sub(r'^([A-Za-z0-9\s]+)\s+-\s+([A-Za-z0-9\s]+)([\.,]|$)', r'\1 vs \2\3', t)
    return t

# Filter live/sport rules
REGEX_LIVE = re.compile(r'(?i)(\(l\)|\[l\]|\(d\)|\[d\]|\(r\)|\[r\]|\blive\b|\blangsung\b|\blive on\b)')
REGEX_VS = re.compile(r'\b(vs|v)\b')
REGEX_NON_ALPHANUM = re.compile(r'[^a-z0-9]')
REGEX_EVENT = re.compile(r'(?:^|[^0-9])(\d{2})[:\.](\d{2})\s*(?:WIB)?\s*[\-\|]?\s*(.+)', re.IGNORECASE)

@lru_cache(maxsize=5000)
def bersihkan_judul_event(title):
    bersih = REGEX_LIVE.sub('', title)
    bersih = re.sub(r'^[\-\:\,\|]\s*', '', re.sub(r'\s+', ' ', bersih)).strip()
    return terjemahkan_bahasa(bersih)

def generate_event_key(title, timestamp):
    tc = re.sub(r'(?i)\#\s*\d+|\[.*?\]|\(.*?\)', '', title)
    tc = re.sub(r'\d+\]?$', '', tc.strip())
    return f"{REGEX_NON_ALPHANUM.sub('', REGEX_VS.sub('', tc.lower()))}_{timestamp}"

@lru_cache(maxsize=2000)
def get_vip_score(ch_name):
    n = ch_name.lower()
    if any(k in n for k in ['bein', 'spotv', 'sportstars', 'soccer channel', 'champions tv', 'rcti sports']): return 0
    return 1

@lru_cache(maxsize=5000)
def get_flag(m3u_name):
    n = m3u_name.lower()
    flags = [(' us', "🇺🇸"), (' sg', "🇸🇬"), (' my', "🇲🇾"), (' uk', "🇬🇧"), (' th', "🇹🇭"), (' hk', "🇭🇰"), (' au', "🇦🇺"), (' arab', "🇸🇦"), (' za', "🇿🇦"), (' id', "🇮🇩")]
    for k, f in flags:
        if k in n: return f
    return "📺"

@lru_cache(maxsize=5000)
def is_target_sport_channel(name):
    n = name.lower()
    if any(x in n for x in ['movie', 'cinema', 'film', 'drama', 'kids', 'news']): return False
    target = ['sport', 'bein', 'spotv', 'liga', 'league', 'champions', 'premier', 'serie a', 'motogp', 'f1', 'nba', 'tenis', 'rugby', 'afc', 'ssc', 'rcti', 'mnc', 'vidio']
    return any(t in n for t in target)

@lru_cache(maxsize=5000)
def is_allowed_sport(title, durasi_menit):
    t = title.lower()
    if re.search(r'[А-Яа-яЁё\u4e00-\u9fff\u3040-\u30ff\u0600-\u06ff]', t) or durasi_menit <= 30: return False
    haram = ["replay", "delay", "classic", "rewind", "highlights", "magazine", "review", "history", "retro"]
    if any(k in t for k in haram): return False
    return any(k in t for k in ['vs', 'liga', 'league', 'cup', 'copa', 'bwf', 'motogp', 'f1', 'nba', 'tennis', 'afc'])

@lru_cache(maxsize=5000)
def is_valid_time_continent(w, title, ch_name):
    t = (title + " " + ch_name).lower()
    if any(k in t for k in [' uk', 'sky', 'euro', 'la liga', 'serie a', 'bundesliga']):
        if 5.1 <= w <= 17.9: return False
    if any(k in t for k in ['us ', 'usa', 'nba', 'copa']):
        if w > 14.0 or w < 5.0: return False
    return True

def parse_time(ts, default_offset_hours=0):
    if not ts: return None
    try:
        dt_naive = datetime.strptime(ts[:14], "%Y%m%d%H%M%S")
        return dt_naive + timedelta(hours=(7 - default_offset_hours))
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
# 3. EKSEKUSI UTAMA
# ========================================================
load_mapping() 
now_wib = datetime.utcnow() + timedelta(hours=7)
limit_date = now_wib + timedelta(hours=24) 
limit_past = now_wib - timedelta(days=2) 

epg_dict, kamus_rumus_epg, jadwal_dict, buku_sejarah_replay = {}, {}, {}, set()

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
                    if st and sp and is_allowed_sport(title, dur):
                        jb = bersihkan_judul_event(title).lower()
                        if limit_past <= sp < now_wib: buku_sejarah_replay.add(jb)
                        elif sp > now_wib and st < limit_date and jb not in buku_sejarah_replay:
                            if is_valid_time_continent(st.hour + st.minute/60, title, epg_dict[cid]):
                                if cid not in jadwal_dict: jadwal_dict[cid] = []
                                jadwal_dict[cid].append({"title": bersihkan_judul_event(title), "start": st, "stop": sp, "live": (st - timedelta(minutes=5)) <= now_wib < sp, "logo": elem.find("icon").get("src") if elem.find("icon") is not None else ""})
            elem.clear()
    except: continue

daftar_epg_rumus = list(kamus_rumus_epg.keys())
keranjang_match, audit_laporan = {}, {}

for url, content, is_e in results:
    if not content or is_e: continue
    p_name = url.split('/')[-1].upper()
    audit_laporan[p_name] = []
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
            if not raw_inf or "," not in raw_inf: continue
            stream_url = ln
            raw_attrs, m3u_name = raw_inf.split(",", 1)
            m3u_name = m3u_name.strip()
            
            ev_m = REGEX_EVENT.search(m3u_name)
            if not ev_m and not is_target_sport_channel(m3u_name): continue
            if stream_url in GLOBAL_SEEN_STREAM_URLS: continue
            GLOBAL_SEEN_STREAM_URLS.add(stream_url)

            skor_vip = get_vip_score(m3u_name)
            logo_m = re.search(r'(?i)tvg-logo=["\']([^"\']*)["\']', raw_attrs)
            orig_logo = logo_m.group(1) if logo_m else ""

            if ev_m:
                ev_title = re.sub(r'\[.*?\]|\(.*?\)', '', ev_m.group(3)).strip()
                ev_st = now_wib.replace(hour=int(ev_m.group(1)), minute=int(ev_m.group(2)), second=0)
                if ev_st < now_wib - timedelta(hours=4): ev_st += timedelta(days=1)
                ev_sp = ev_st + timedelta(hours=2)
                if ev_sp > now_wib and ev_st < limit_date:
                    is_l = (ev_st - timedelta(minutes=5)) <= now_wib < ev_sp
                    k = generate_event_key(ev_title, ev_st.timestamp())
                    if k not in keranjang_match: keranjang_match[k] = {"is_live": is_l, "sort": ev_st.timestamp(), "vip": skor_vip, "links": []}
                    jam = f"{ev_st.strftime('%H:%M')}-{ev_sp.strftime('%H:%M')}"
                    title_indo = terjemahkan_bahasa(ev_title)
                    if is_l:
                        inf = f'#EXTINF:-1 group-title="🔴 SEDANG TAYANG" tvg-logo="{orig_logo}", {get_flag(ev_title)} 🔴 {jam} WIB - {title_indo}'
                        keranjang_match[k]["links"].append({"prio": 0, "data": [inf] + extra_tags + [stream_url]})
                    else:
                        inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{orig_logo}", {get_flag(ev_title)} ⏳ {jam} WIB - {title_indo}'
                        keranjang_match[k]["links"].append({"prio": 0, "data": [inf, f"{LINK_UPCOMING}?m={k}"]})
                continue

            # Fuzzy Match Mapping
            teks_m3u = rumus_samakan_teks(m3u_name)
            id_epg = kamus_rumus_epg.get(teks_m3u)
            if not id_epg:
                mirip = difflib.get_close_matches(teks_m3u, daftar_epg_rumus, n=1, cutoff=0.75)
                id_epg = kamus_rumus_epg[mirip[0]] if mirip else None

            if id_epg and id_epg in jadwal_dict:
                for ev in jadwal_dict[id_epg]:
                    k = generate_event_key(ev['title'], ev['start'].timestamp())
                    if k not in keranjang_match: keranjang_match[k] = {"is_live": ev['live'], "sort": ev['start'].timestamp(), "vip": skor_vip, "links": []}
                    jam = f"{ev['start'].strftime('%H:%M')}-{ev['stop'].strftime('%H:%M')}"
                    if ev["live"]:
                        inf = f'#EXTINF:-1 group-title="🔴 SEDANG TAYANG" tvg-id="{id_epg}" tvg-logo="{ev["logo"] or orig_logo}", {get_flag(m3u_name)} 🔴 {jam} WIB - {ev["title"]} [{m3u_name}]'
                        keranjang_match[k]["links"].append({"prio": 1, "data": [inf] + extra_tags + [stream_url]})
                    else:
                        inf = f'#EXTINF:-1 group-title="📅 JADWAL HARI INI" tvg-logo="{ev["logo"] or orig_logo}", {get_flag(m3u_name)} ⏳ {jam} WIB - {ev["title"]}'
                        keranjang_match[k]["links"].append({"prio": 1, "data": [inf, f"{LINK_UPCOMING}?m={k}"]})
                audit_laporan[p_name].append(f"✅ {m3u_name} -> {epg_dict[id_epg]}")
            else:
                audit_laporan[p_name].append(f"❌ {m3u_name} (KOSONG)")

# Final Render
hasil_m3u = []
for k, v in keranjang_match.items():
    uniq = { l["data"][-1]: l for l in v["links"] }.values()
    sorted_l = sorted(uniq, key=lambda x: x["prio"])
    for l in sorted_l[:(2 if v["is_live"] else 1)]:
        hasil_m3u.append({"order": 0 if v["is_live"] else 1, "sort": v["sort"], "vip": v["vip"], "data": l["data"]})
hasil_m3u.sort(key=lambda x: (x["order"], x["sort"], x["vip"]))

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(f'#EXTM3U name="🔴 BAKUL WIFI SPORTS"\n')
    if not hasil_m3u: f.write(f'#EXTINF:-1 group-title="INFO", BELUM ADA JADWAL\n{LINK_STANDBY}\n')
    else:
        for it in hasil_m3u: f.write("\n".join(it["data"]) + "\n")

with open("laporan_rumus.txt", "w", encoding="utf-8") as f:
    for p, logs in audit_laporan.items():
        f.write(f"=== {p} ===\n" + "\n".join(logs) + "\n\n")

print(f"SELESAI! File {OUTPUT_FILE} telah diperbarui.")
